"""HTTP读取结束立即释放缓存，失败仍拒绝响应；仅合成原件。"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from contracts import ContractError
from storage import file_record
from modulea.api.server import App
from modulea.core.read_evidence import current_evidence


class HttpBoundedReadTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.sid='study_'+'e'*32
        self.home=self.root/'studies'/self.sid;self.home.mkdir(parents=True)
        (self.home/'manifest.json').write_text('{"revision":1}')
        self.app=SimpleNamespace(settings=SimpleNamespace(data_root=self.root))
        self.refs=[]
        for index in range(12):
            path=self.home/f'{index}.json'
            path.write_text(json.dumps({'data':'x'*4096,'nested':[1,2]}))
            self.refs.append(file_record(self.home,path,'test'))

    def read(self):
        self.evidence=current_evidence(self.root)
        for ref in self.refs:self.evidence.reader.read(self.home,ref)
        # 私有函数外观也形成引用环，结束不能仅等循环GC才释放内容。
        from modulea.core.system_receptor_rescue_v2 import partial_recovery
        self.evidence.bind(partial_recovery)
        return {'value':[1,2]}

    def assert_closed(self):
        e=self.evidence
        self.assertFalse(e.active)
        for name in ('json_bytes','parsed','preparation_records','proofs','functions','namespaces'):
            self.assertFalse(bool(getattr(e,name)),'请求结束仍保留 '+name)
        self.assertIsNone(current_evidence())

    def test_production_json_entry_releases_content_without_waiting_for_gc(self):
        self.assertEqual(App._json_read(self.app,self.sid,self.read),{'value':[1,2]})
        self.assertEqual(self.evidence.stats['first_sha_checks'],self.evidence.stats['exit_sha_checks'])
        self.assert_closed()

    def test_large_response_revalidates_all_files_through_batch_reader(self):
        from unittest.mock import patch
        from modulea.core.http_read_evidence import json_evidence_scope
        from modulea.core.read_archive import ReadArchive

        refs = []
        for index in range(75):
            path = self.home / f'attachment-{index}.txt'
            path.write_bytes(b'original')
            refs.append(file_record(self.home, path, 'test'))

        original_bulk = ReadArchive.verify_all
        with patch.object(ReadArchive, 'verify_all', autospec=True, side_effect=original_bulk) as bulk:
            with json_evidence_scope(self.root, self.sid) as scope:
                for ref in refs:
                    scope.reader.verify(self.home, ref)
            bulk.assert_called_once_with(scope.raw_reader, self.home.resolve(), refs)
            self.assertEqual(scope.stats['exit_sha_checks'], len(refs))

        with self.assertRaises(ContractError):
            with json_evidence_scope(self.root, self.sid) as scope:
                for ref in refs:
                    scope.reader.verify(self.home, ref)
                target = self.home / refs[-1]['path']
                stamp = target.stat()
                target.write_bytes(b'tampered')
                os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def test_callback_error_releases_buffers_and_preserves_error(self):
        def fail():
            self.read();raise ValueError('原始错误')
        with self.assertRaisesRegex(ValueError,'原始错误'):App._json_read(self.app,self.sid,fail)
        self.assert_closed()

    def test_exit_sha_failure_still_blocks_and_releases_buffers(self):
        def mutate():
            value=self.read();path=self.home/self.refs[0]['path'];stamp=path.stat()
            path.write_bytes(path.read_bytes().replace(b'xx',b'zz',1))
            os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return value
        with self.assertRaises(ContractError):App._json_read(self.app,self.sid,mutate)
        self.assert_closed()

    def test_json_budget_eviction_reloads_verified_bytes_and_isolates_return_values(self):
        from modulea.core.http_read_evidence import json_evidence_scope
        with json_evidence_scope(self.root,self.sid,cache_bytes=8192) as e:
            self.evidence=e
            first=e.reader.read(self.home,self.refs[0]);first['nested'].append(9)
            for ref in self.refs:
                self.assertEqual(e.reader.read(self.home,ref)['nested'],[1,2])
                self.assertLessEqual(e.cache_size,8192)
            self.assertLessEqual(e.cache_peak,8192)
            self.assertFalse(e.json_bytes);self.assertFalse(e.parsed)
            self.assertEqual(e.reader.read(self.home,self.refs[0])['nested'],[1,2])
        self.assert_closed()

    def test_large_rescue_packet_reuses_bounded_cache_and_rechecks_sha_at_exit(self):
        from unittest.mock import patch
        from modulea.core import http_read_evidence as http

        path=self.home/'rescue.json'
        raw=json.dumps({'schema_version':'A06.system_rescue.2','data':'x'*24000,'nested':[1,2]}).encode()
        path.write_bytes(raw);ref=file_record(self.home,path,'rescue_scoring_packet')
        with patch.object(http,'JSON_CACHE_BYTES',8192), self.assertRaises(ContractError):
            with http.json_evidence_scope(self.root,self.sid,cache_bytes=8192) as e:
                self.evidence=e
                e.reader.read(self.home,ref)['nested'].append(3)
                self.assertEqual(e.reader.read(self.home,ref)['nested'],[1,2])
                self.assertEqual(e.stats['json_parses'],1)
                self.assertEqual(e.stats['json_cache_hits'],1)
                self.assertLessEqual(e.cache_peak,8192)
                stamp=path.stat();path.write_bytes(raw.replace(b'xx',b'zz',1))
                os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assert_closed()

    def test_reparse_after_verification_rejects_changed_bytes_without_ttl(self):
        from modulea.core.http_read_evidence import json_evidence_scope
        with self.assertRaises(ContractError):
            with json_evidence_scope(self.root,self.sid,cache_bytes=0) as e:
                self.evidence=e;e.reader.verify(self.home,self.refs[0])
                path=self.home/self.refs[0]['path'];path.write_bytes(b'changed')
                e.reader.read(self.home,self.refs[0])
        self.assert_closed()

    def test_nested_scope_reuses_only_same_study_and_restores_outer_scope(self):
        from modulea.core.http_read_evidence import json_evidence_scope
        other='study_'+'a'*32;home=self.root/'studies'/other;home.mkdir()
        (home/'manifest.json').write_text('{}')
        with json_evidence_scope(self.root,self.sid) as first:
            with json_evidence_scope(self.root,self.sid) as shared:self.assertIs(shared,first)
            self.assertTrue(first.active)
            with json_evidence_scope(self.root,other) as second:
                self.assertIsNot(second,first);self.assertIs(current_evidence(),second)
            self.assertFalse(second.active);self.assertIs(current_evidence(),first)
        self.assertIsNone(current_evidence())

    def test_scope_references_cannot_reuse_proofs_in_another_thread(self):
        from concurrent.futures import ThreadPoolExecutor
        from modulea.core.http_read_evidence import json_evidence_scope
        from contextvars import copy_context
        with json_evidence_scope(self.root,self.sid) as e:
            e.reader.verify(self.home,self.refs[0]);before=len(e.proofs)
            context=copy_context()
            def other():
                self.assertIsNone(current_evidence())
                self.assertFalse(e._owned())
                self.assertEqual(e.reader.read(self.home,self.refs[1])['nested'],[1,2])
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(context.run,other).result()
            self.assertEqual(len(e.proofs),before)

    def test_manifest_change_rejects_response_then_restores_scope(self):
        def mutate_manifest():
            self.read();(self.home/'manifest.json').write_text('{"revision":2}')
        with self.assertRaisesRegex(ContractError,'研究登记已改变'):
            App._json_read(self.app,self.sid,mutate_manifest)
        self.assert_closed()

    def test_foreign_root_and_saved_reader_after_exit_use_original_strict_read(self):
        from modulea.core.http_read_evidence import json_evidence_scope
        foreign=TemporaryDirectory();self.addCleanup(foreign.cleanup)
        other=Path(foreign.name);path=other/'test.json';path.write_text('{"nested":[3]}')
        ref=file_record(other,path,'test')
        with json_evidence_scope(self.root,self.sid) as e:
            e.reader.read(self.home,self.refs[0]);before=len(e.proofs)
            self.assertEqual(e.reader.read(other,ref),{'nested':[3]})
            self.assertEqual(len(e.proofs),before)
            saved=e.read_json
        target=self.home/self.refs[0]['path'];target.write_text('{"new":true}')
        self.assertEqual(saved(target),{'new':True})

    def test_card_entry_also_closes_http_buffers(self):
        from unittest.mock import patch
        from modulea.api.views import Views
        from modulea.core.http_read_evidence import HttpReadEvidence
        from modulea.devtools.demo_data import build
        from modulea.config import Settings
        from modulea.core.kernel import Kernel
        data=self.root/'cards';sid=build(data)
        tasks=SimpleNamespace(list=lambda *a,**k:[],active_for=lambda *a:None)
        views=Views(Kernel(Settings(data_root=data,runtime_dir=self.root/'runtime')),tasks)
        seen=[];close=HttpReadEvidence.close
        def observe(e):
            seen.append(e);return close(e)
        with patch.object(HttpReadEvidence,'close',observe):
            cards=views.study_cards();self.assertEqual(cards[0]['study']['study_id'],sid)
        self.assertTrue(seen)
        for e in seen:
            self.assertFalse(e.active);self.assertFalse(e.proofs);self.assertFalse(e.cache)

    def test_list_rereads_conflicting_study_once_using_new_evidence(self):
        from unittest.mock import patch
        from modulea.api.views import Views
        from modulea.core.http_read_evidence import HttpReadEvidence
        from contracts import ContractError

        manifest = self.home / 'manifest.json'
        original = manifest.read_bytes()
        kernel = SimpleNamespace(settings=SimpleNamespace(data_root=self.root))
        for changes, moved in ((1, False), (2, False), (1, True)):
            with self.subTest(changes=changes, moved=moved):
                manifest.write_bytes(original)
                seen = []
                views = Views(kernel, None)
                first_finish = HttpReadEvidence.finish

                def read(study_id, *, with_states):
                    self.assertTrue(with_states)
                    self.assertEqual(study_id, self.sid)
                    scope = current_evidence(self.root)
                    scope.reader.verify(self.home, self.refs[0])
                    seen.append(scope)
                    return {'study': {'trashed': moved and len(seen) == 2}, 'version': scope.manifest_bytes}

                def finish(scope):
                    if len(seen) <= changes:
                        manifest.write_bytes(manifest.read_bytes() + b' ')
                    return first_finish(scope)

                with patch.object(views, 'study_card', side_effect=read), patch.object(HttpReadEvidence, 'finish', finish):
                    if changes == 1 and not moved:
                        result = views._build_cards([{'study_id': self.sid}])
                        self.assertEqual(result[0]['version'], original + b' ')
                        self.assertEqual(seen[-1].stats['exit_sha_checks'], 1)
                    else:
                        with self.assertRaisesRegex(ContractError, '研究登记已改变'):
                            views._build_cards([{'study_id': self.sid}])
                self.assertEqual(len(seen), 2)
                self.assertIsNot(seen[0], seen[1])
                self.assertTrue(all(not evidence.active for evidence in seen))

    def test_http_keeps_original_strict_utf8_json_encoding_contract(self):
        from modulea.core.http_read_evidence import json_evidence_scope
        # 独立索引随合成原件正确登记，验证的是内容契约，不是SHA损坏。
        for encoding in ('utf-16','utf-32','utf-8-sig'):
            with self.subTest(encoding=encoding):
                path=self.home/'encoding.json';path.write_bytes('{"value":1}'.encode(encoding))
                ref=file_record(self.home,path,'test')
                with self.assertRaises(ContractError):
                    with json_evidence_scope(self.root,self.sid) as e:e.reader.read(self.home,ref)

    def _rescue_scope_fixture(self):
        """沿生产JSON入口调用共享加载器，不让测试reader替代HTTP证据收集。"""
        from tests.modulea.test_rescue_evidence_http import RescueEvidenceHttpTests
        seed=RescueEvidenceHttpTests('test_inherited_score_has_exact_model_one_source_context_and_no_invented_regions')
        seed.setUp();self.addCleanup(seed.doCleanups)
        app=SimpleNamespace(settings=SimpleNamespace(data_root=seed.root),kernel=seed.app.kernel)
        return seed,app

    def test_shared_rescue_loader_collects_packet_and_fixed_input_for_exit_proof(self):
        from unittest.mock import patch
        from modulea.api import rescue_evidence
        from modulea.core.http_read_evidence import HttpReadEvidence
        seed,app=self._rescue_scope_fixture();seen=set();finish=HttpReadEvidence.finish
        def observe(e):
            seen.update(ref['path'] for home,ref,path in e.proofs.values())
            return finish(e)
        with patch.object(HttpReadEvidence,'finish',observe):
            value=App._json_read(app,seed.sid,rescue_evidence.load_bundle,app,seed.sid,seed.rid)
        expected={seed.run['inputs']['system_input_ref']['path'],
                  value[4]['tables']['scoring_packet'][0]['path']}
        self.assertTrue(expected<=seen,(expected,seen))

    def test_shared_rescue_loader_rejects_input_changed_before_response_with_same_mtime(self):
        from unittest.mock import patch
        from modulea.api import rescue_evidence
        from modulea.core.http_read_evidence import HttpReadEvidence
        seed,app=self._rescue_scope_fixture();finish=HttpReadEvidence.finish
        target=seed.case.home/seed.run['inputs']['system_input_ref']['path']
        raw=target.read_bytes();stamp=target.stat()
        def mutate(e):
            changed=raw.replace(b'original',b'changed!',1)
            self.assertNotEqual(changed,raw)
            self.assertEqual(len(changed),len(raw))
            target.write_bytes(changed)
            os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return finish(e)
        try:
            with patch.object(HttpReadEvidence,'finish',mutate):
                with self.assertRaises(ContractError):
                    App._json_read(app,seed.sid,rescue_evidence.load_bundle,app,seed.sid,seed.rid)
        finally:
            target.write_bytes(raw)
