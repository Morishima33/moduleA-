"""验收包只整理同批既有图件与构象；缺译、损坏或跨批附件明确阻断。"""
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import zipfile

from modulea.api import acceptance_bundle
from modulea.api.errors import ApiError
from tests.modulea.test_rescue_evidence_http import RescueEvidenceHttpTests


class AcceptanceBundleTests(unittest.TestCase):
    def setUp(self):
        self.seed=RescueEvidenceHttpTests('test_actual_http_download_sha_and_read_only_manifest')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        font=os.environ.get('MODULEA_TEST_FONT')
        if not font:
            candidates=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc',
                        Path('/System/Library/Fonts/Supplemental/Songti.ttc')]
            font=next((str(path) for path in candidates if path.is_file()),None)
        if not font:raise unittest.SkipTest('实际PNG/SVG核验需要明确可用的中文字体')
        from science_modules.a06.system_rescue_display_v2 import export
        s=self.seed
        s.packet['summary']['message_zh']='合成同批验收包测试'
        folder=s.case.home/f'runs/A06/{s.rid}/rescue/display'/('display_'+'f'*32)
        figures,attachments=export(s.case.home,s.packet,folder,font_path=font)
        s.files.extend(figures+attachments);s.save()
        self.empty=SimpleNamespace(query={},query1=lambda _:None)
        self.req=SimpleNamespace(query={'expected_input_key':['original']},query1=lambda _:'original')

    def test_zip_member_fingerprints_and_original_top1_without_new_study_files(self):
        s=self.seed
        before={p.relative_to(s.case.home).as_posix():p.read_bytes() for p in s.case.home.rglob('*') if p.is_file()}
        value=acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertTrue(value['enabled'],value)
        answer=acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        with zipfile.ZipFile(io.BytesIO(answer[1])) as archive:
            manifest=json.loads(archive.read('验收目录与指纹.json'))
            self.assertEqual(manifest['run_id'],s.rid)
            for row in manifest['files']:
                raw=archive.read(row['path'])
                self.assertEqual(len(raw),row['bytes'])
                self.assertEqual(sha256(raw).hexdigest(),row['sha256'])
            top=archive.read('poses/pair_000001/top1.pdbqt')
            self.assertIn(b'MODEL 1',top);self.assertNotIn(b'MODEL 2',top)
            self.assertFalse(any(name.endswith('.docx') for name in archive.namelist()))
        after={p.relative_to(s.case.home).as_posix():p.read_bytes() for p in s.case.home.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_missing_translation_blocks_final_delivery(self):
        s=self.seed
        # 只测试门控函数，原科学包和已登记展示不改写；缺译必须独立列明。
        bundle=list(acceptance_bundle.load_bundle(s.app,s.sid,s.rid))
        bundle[5]=deepcopy(bundle[5]);bundle[5]['source_fixed']['compounds'][0]['name']='Untranslated identity'
        bundle[4]=deepcopy(bundle[4]);bundle[4]['files']=[ref for ref in bundle[4]['files'] if not
            ref.get('role','').startswith('plot_a06_rescue_') and ref.get('role') not in
            ('a06_rescue_matrix_csv','a06_rescue_display_view')]
        value=acceptance_bundle.assess(bundle)
        self.assertFalse(value['enabled'])
        self.assertEqual(value['translation_missing_ids'],['C1'])
        self.assertTrue(any('核译' in note for note in value['blockers_zh']))

    def test_missing_current_figure_is_blocked_without_generating_it(self):
        s=self.seed
        s.files=[r for r in s.files if r.get('role')!='plot_a06_rescue_focus_png'];s.save()
        value=acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertFalse(value['enabled'])
        with self.assertRaises(ApiError) as caught:acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        self.assertEqual(caught.exception.status,409)

    def test_corrupt_registered_csv_is_not_regenerated(self):
        s=self.seed
        ref=next(r for r in s.files if r.get('role')=='a06_rescue_matrix_csv')
        path=s.case.home/ref['path'];path.write_bytes(b'wrong')
        with self.assertRaises(ApiError) as caught:acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertEqual(caught.exception.status,503)
        self.assertEqual(path.read_bytes(),b'wrong')

    def test_producer_role_aliases_export_one_member_and_keep_every_registration(self):
        """真实producer目录证据与语义附件并列登记，同路径同SHA应只存一次字节。"""
        s=self.seed
        semantic=deepcopy(s.files)
        s.files=[dict(ref,role='rescue_evidence') for ref in semantic]+semantic
        s.save()
        before=(s.case.home/'manifest.json').read_bytes()
        value=acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertTrue(value['enabled'])
        answer=acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        with zipfile.ZipFile(io.BytesIO(answer[1])) as archive:
            names=archive.namelist();self.assertEqual(len(names),len(set(names)))
            index=json.loads(archive.read('验收目录与指纹.json'))
            self.assertEqual(index['registered_reference_count'],len(s.files)+1)
            registrations=[]
            for item in index['files']:
                if item['path'].startswith('registered/'):
                    registrations.extend(item['registrations'])
                    raw=archive.read(item['path']);self.assertEqual(sha256(raw).hexdigest(),item['sha256'])
            result=s.app.kernel.read_workflow().result(s.manifest,s.rid)
            registrations.sort(key=lambda row:row['index'])
            self.assertEqual([row['record'] for row in registrations],result['files'])
        self.assertEqual((s.case.home/'manifest.json').read_bytes(),before)

    def test_identical_plot_role_registration_is_not_a_conflicting_figure(self):
        s=self.seed;picture=next(r for r in s.files if r.get('role')=='plot_a06_rescue_full_png')
        s.files.append(deepcopy(picture));s.save()
        self.assertTrue(acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)['enabled'])
        self.assertEqual(acceptance_bundle.download(s.app,self.req,s.sid,s.rid)[0],'verified_download')

    def test_conflicting_same_path_identity_is_rejected_in_both_orders(self):
        s=self.seed;original=deepcopy(s.files);ref=original[0]
        for change in ({'sha256':'0'*64},{'bytes':ref['bytes']+1}):
            for first in (False,True):
                with self.subTest(change=change,conflict_first=first):
                    bad=dict(ref,**change)
                    s.files=([bad]+deepcopy(original)) if first else (deepcopy(original)+[bad])
                    s.save()
                    with self.assertRaises(ApiError) as caught:acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
                    self.assertEqual(caught.exception.status,503)
                    with self.assertRaises(ApiError):acceptance_bundle.download(s.app,self.req,s.sid,s.rid)

    def test_different_registered_paths_with_same_bytes_remain_distinct_members(self):
        from storage import file_record
        s=self.seed;original=s.files[0];raw=(s.case.home/original['path']).read_bytes()
        path=s.case.home/'different_registered_original.bin';path.write_bytes(raw)
        other=file_record(s.case.home,path,'different_source_relation');s.files.append(other);s.save()
        answer=acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        with zipfile.ZipFile(io.BytesIO(answer[1])) as archive:
            self.assertEqual(archive.read('registered/'+original['path']),raw)
            self.assertEqual(archive.read('registered/'+other['path']),raw)

    def test_same_plot_role_different_path_is_still_a_conflict(self):
        from storage import file_record
        s=self.seed;ref=next(r for r in s.files if r.get('role')=='plot_a06_rescue_full_png')
        path=s.case.home/ref['path'];copy=path.with_name('other_full.png');copy.write_bytes(path.read_bytes())
        s.files.append(file_record(s.case.home,copy,ref['role']));s.save()
        with self.assertRaises(ApiError) as caught:acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertEqual(caught.exception.status,503)

    def test_actual_http_alias_zip_sha_manifest_and_original_files_are_preserved(self):
        import threading
        from urllib.request import urlopen
        from modulea.api.server import create_server
        from modulea.config import Settings
        s=self.seed;s.files=[dict(r,role='rescue_evidence') for r in s.files]+deepcopy(s.files);s.save()
        before={p.relative_to(s.case.home).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in s.case.home.rglob('*') if p.is_file()}
        server,app=create_server(Settings(data_root=s.root,runtime_dir=s.root/'acceptance_runtime'),0)
        app.kernel.read_workflow=s.app.kernel.read_workflow
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/api/v1/studies/{s.sid}/runs/{s.rid}/acceptance.zip?expected_input_key=original'
            with urlopen(url,timeout=30) as response:
                raw=response.read();self.assertEqual(response.headers['X-Content-SHA256'],sha256(raw).hexdigest())
                self.assertEqual(response.headers.get_content_type(),'application/zip')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                index=json.loads(archive.read('验收目录与指纹.json'))
                self.assertEqual(index['registered_reference_count'],len(s.files)+1)
                self.assertNotIn(b'MODEL 2',archive.read('poses/pair_000001/top1.pdbqt'))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
        self.assertEqual(before,{p.relative_to(s.case.home).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in s.case.home.rglob('*') if p.is_file()})

    def test_budget_counts_unique_bytes_and_still_rejects_above_limit(self):
        from unittest.mock import patch
        s=self.seed;s.files=[dict(r,role='rescue_evidence') for r in s.files]+deepcopy(s.files);s.save()
        result=s.app.kernel.read_workflow().result(s.manifest,s.rid)
        unique={ref['path']:ref for ref in result['files']};total=sum(r['bytes'] for r in unique.values())
        self.assertGreater(sum(r['bytes'] for r in result['files']),total)
        with patch.object(acceptance_bundle,'MAX_REGISTERED_BYTES',total,create=True):
            self.assertEqual(acceptance_bundle.download(s.app,self.req,s.sid,s.rid)[0],'verified_download')
        with patch.object(acceptance_bundle,'MAX_REGISTERED_BYTES',total-1,create=True):
            with self.assertRaises(ApiError) as caught:acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
            self.assertEqual(caught.exception.status,503)

    def test_manifest_change_after_packaging_rejects_zip_response(self):
        from unittest.mock import patch
        s=self.seed;reader=s.app.kernel.read_workflow();original=reader.load;calls=[]
        def load(sid):
            manifest=original(sid);calls.append(sid)
            if len(calls)>1:manifest['synthetic_version_change']=True
            return manifest
        with patch.object(reader,'load',side_effect=load):
            with self.assertRaises(ApiError) as caught:acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        self.assertEqual(caught.exception.status,503)
        self.assertIn('研究登记已改变',caught.exception.message_zh)


if __name__=='__main__':unittest.main()
