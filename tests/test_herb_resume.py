"""HERB临时网关失败、断点恢复和研究版本边界；只使用虚构网络和目录。"""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import Mock
from urllib.error import HTTPError

from contracts import ContractError
from science_modules.a01.acquisition import Fetcher, HERB_API
from science_modules.a01.collection_flow import herb_resume_folders
from storage import write_json


class AutomaticPackageTests(unittest.TestCase):
    """后台本机构建包的容量与浏览器上传隔离，原ZIP安全检查仍生效。"""
    def test_large_herb_package_only_accepted_on_explicit_backend_path(self):
        from science_modules.a01.uploads import unpack
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_STORED) as z:
            z.writestr('original_requests/fixture.bin', b'x' * (17 * 1024 * 1024))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ContractError):unpack(data.getvalue(),Path(d)/'browser')
            target=Path(d)/'automatic';target.mkdir()
            unpack(data.getvalue(),target,max_compressed=64*1024*1024)
            self.assertEqual((target/'original_requests/fixture.bin').stat().st_size,17*1024*1024)
            with self.assertRaises(ContractError):unpack(data.getvalue(),target,max_compressed=1024*1024*1024)

    def test_large_backend_mode_does_not_disable_zip_path_check(self):
        from science_modules.a01.uploads import unpack
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w')as z:z.writestr('../outside',b'x')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ContractError):unpack(data.getvalue(),Path(d),max_compressed=64*1024*1024)

    def test_large_package_goes_through_original_stage_and_keeps_a02(self):
        from science_modules.a01.uploads import stage
        from test_source_uploads import fixture, package
        original = package('HERB')
        stream=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED) as dst:
            for name in src.namelist():dst.writestr(name,src.read(name))
            dst.writestr('original_requests/padding.bin',b'x'*(17*1024*1024))
        source={'database':'HERB','format':'source_zip','name':'HERB_official.zip','data':stream.getvalue(),
                'source_url':HERB_API,'version':'A01.acquisition.1；以原响应固定','automatic_herb':True}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);w,sid,a00=fixture(root);before=w.load(sid)
            # 来源字段不能启用后端容量，网页默认仍被拒绝。
            with self.assertRaises(ContractError):stage(w,sid,a00,'','',source,root/'runtime')
            self.assertEqual(w.load(sid),before)
            stage(w,sid,a00,'','',source,root/'runtime',automatic_herb=True)
            after=w.load(sid)
            self.assertEqual(after['current'],before['current'])
            self.assertEqual(after['reviews'],before['reviews'])
            self.assertIn('current_component_uploads',after)

    def test_other_database_cannot_enable_herb_capacity(self):
        from science_modules.a01.uploads import stage
        with self.assertRaises(ContractError):
            stage(None,'test','','','',{'database':'BATMAN','format':'source_zip','data':b''},Path('.'),automatic_herb=True)


class Response(io.BytesIO):
    """虚构官方响应，保留字节与长度语义。"""
    status = 200
    def __init__(self, raw):
        super().__init__(raw)
        self.headers = {"Content-Length": str(len(raw))}
    def geturl(self):
        return HERB_API


class HerbRetryTests(unittest.TestCase):
    """瞬时错误有界退避，永久错误不反复请求，错误页不进入成功缓存。"""
    def test_gateway_retry_backs_off_and_preserves_failures(self):
        with tempfile.TemporaryDirectory() as d:
            sleeps, progress = [], []
            opener = Mock(side_effect=[HTTPError(HERB_API, 502, "Bad Gateway", {}, io.BytesIO(b"gateway")) for _ in range(3)] + [Response(b'{"ok":true}')])
            fetch = Fetcher(Path(d), opener, sleeps.append, progress=progress.append)
            self.assertEqual(fetch.herb("detail_api", label="Ingredient", v="HBIN1"), {"ok": True})
            self.assertEqual(opener.call_count, 4)
            self.assertTrue(all(delay in sleeps for delay in (2, 4, 8)))
            self.assertEqual(len(list(Path(d).glob('*failure*.json'))), 3)
            self.assertTrue(any("502" in text for text in progress))

    def test_404_is_not_retried_and_retry_after_is_honoured_with_cap(self):
        with tempfile.TemporaryDirectory() as d:
            opener = Mock(side_effect=HTTPError(HERB_API, 404, "not found", {}, io.BytesIO()))
            fetch = Fetcher(Path(d)/"404", opener, lambda _: None)
            with self.assertRaises(HTTPError):fetch.herb("detail_api", v="missing")
            self.assertEqual(opener.call_count, 1)
            sleeps = []
            opener = Mock(side_effect=[HTTPError(HERB_API, 429, "busy", {"Retry-After": "120"}, io.BytesIO()), Response(b'{"ok":true}')])
            Fetcher(Path(d)/"429", opener, sleeps.append).herb("detail_api", v="limited")
            self.assertIn(60, sleeps)

    def test_successful_http_error_page_is_not_cached_as_json(self):
        with tempfile.TemporaryDirectory() as d:
            opener = Mock(side_effect=[Response(b'<html>Bad Gateway</html>'), Response(b'{"ok":true}')])
            fetch = Fetcher(Path(d), opener, lambda _: None)
            self.assertEqual(fetch.herb("detail_api", v="HBIN1"), {"ok": True})
            self.assertEqual(opener.call_count, 2)
            successful = [p for p in Path(d).glob('*.bin') if 'failure' not in p.name]
            self.assertEqual(len(successful), 1)
            self.assertEqual(json.loads(successful[0].read_bytes()), {"ok": True})

    def test_retry_limit_stops_without_false_success(self):
        with tempfile.TemporaryDirectory() as d:
            def offline(*args, **kwargs):raise HTTPError(HERB_API, 503, "busy", {}, io.BytesIO())
            opener = Mock(side_effect=offline)
            with self.assertRaises(HTTPError):Fetcher(Path(d), opener, lambda _: None).herb("detail_api", v="HBIN1")
            self.assertEqual(opener.call_count, 5)
            self.assertFalse(any('failure' not in p.name for p in Path(d).glob('*.bin')))


class ResumeTests(unittest.TestCase):
    """只选同研究同上游的归档原件，逐请求内容校验后恢复。"""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)/"study"
        self.root = self.home/"raw/A01_acquisition"
        self.prior = self.root/"fetch_old"
        self.prior.mkdir(parents=True)
        self.folder = self.root/"fetch_new"
        self.folder.mkdir()
        self.binding = {"study_id":"study_test","bound_a00":"run_a00","bound_a01":"","herbs":["测试药"]}

    def legacy(self, **changes):
        write_json(self.prior/'acquisition_result_attempt_test.json', dict(self.binding, **changes))

    def test_legacy_matching_binding_can_resume_without_redownload(self):
        self.legacy()
        old = Fetcher(self.prior/"HERB/original_requests", lambda *a, **k:Response(b'{"ok":true}'), lambda _:None)
        old.herb("detail_api", v="HBIN1")
        candidates = herb_resume_folders(self.home, self.folder, self.binding)
        self.assertEqual(candidates, [self.prior/"HERB/original_requests"])
        opener = Mock(side_effect=AssertionError("不应重复下载"))
        fresh = Fetcher(self.folder/"HERB/original_requests", opener, lambda _:None, resume_folders=candidates)
        self.assertEqual(fresh.herb("detail_api", v="HBIN1"), {"ok":True})
        self.assertEqual(fresh.reused_requests, 1)
        opener.assert_not_called()
        self.assertEqual(len(list(fresh.folder.glob('*.json'))),1)

    def test_other_study_or_upstream_and_outside_directory_not_reused(self):
        for change in ({"study_id":"other"},{"bound_a00":"changed"},{"bound_a01":"changed"},{"herbs":["另一药"]}):
            with self.subTest(change=change):
                marker = self.prior/'acquisition_binding.json'
                if marker.exists():marker.unlink()
                write_json(marker,dict(self.binding,**change))
                self.assertEqual(herb_resume_folders(self.home,self.folder,self.binding),[])
        with self.assertRaises(ContractError):herb_resume_folders(self.home,Path(self.tmp.name)/'outside',self.binding)

    def test_legacy_binding_without_herbs_is_accepted_only_for_same_a00(self):
        self.legacy()
        marker=self.prior/'acquisition_result_attempt_test.json'
        value=json.loads(marker.read_bytes());value.pop('herbs');marker.write_text(json.dumps(value),'utf-8')
        self.assertEqual(herb_resume_folders(self.home,self.folder,self.binding),[self.prior/"HERB/original_requests"])
        self.assertEqual(herb_resume_folders(self.home,self.folder,dict(self.binding,bound_a00='different')),[])

    def test_tampered_cache_is_rejected_instead_of_silently_adopted(self):
        old = Fetcher(self.prior/"HERB/original_requests", lambda *a,**k:Response(b'{"ok":true}'), lambda _:None)
        old.herb("detail_api", v="HBIN1")
        next(old.folder.glob('*.bin')).write_bytes(b'tampered')
        fresh = Fetcher(self.folder/"HERB/original_requests", Mock(), lambda _:None, resume_folders=[old.folder])
        with self.assertRaises(ContractError):fresh.herb("detail_api", v="HBIN1")


if __name__ == '__main__':unittest.main()
