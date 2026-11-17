"""只读super链应保留原状态判定且纳入原件完整证明，不能落回未适配的读取。"""
import sys
from unittest import TestCase
from unittest.mock import patch

import storage
from storage import file_record,read_json,verified_file
from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core.kernel import _ReadWorkflow
from modulea.core.inherited_read_evidence import json_evidence_scope
from tests.modulea import test_system_receptor_rescue_v2_core as fixture
from tests.modulea import test_read_evidence_scope as guard_fixture


class InheritedReadEvidenceTests(TestCase):
    def setUp(self):
        self.seed=fixture.ReceptorRescueV2CoreTests('test_original_paths_baseline_publishes_normal_v2_without_changing_preparation_or_reviews')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        value=self.seed.execute(self.seed.body());self.sid=self.seed.sid;self.rid=value['run_id']
        self.w=_ReadWorkflow(self.seed.w.root,self.seed.w.validators)
        self.manifest=self.w.load(self.sid);self.home=self.w.location(self.sid)
        path=self.home/'readonly_parent_fact.json';path.write_text('{"value":1}',encoding='utf-8')
        self.reference=file_record(self.home,path,'readonly_parent_fact')

    def test_super_delegation_captures_parent_file_reads_without_raw_storage_fallback(self):
        original=AnalysisPlanWorkflow._active;reference=self.reference
        # 在受信父方法增加合成只读证据，再执行原方法；不替换原有状态判断的结果。
        def observed_parent(workflow,manifest,run_id):
            value=read_json(verified_file(workflow.location(manifest['study_id']),reference))
            assert value=={'value':1}
            return original(workflow,manifest,run_id)
        raw=[];previous=sys.getprofile();code=storage.verified_file.__code__
        def profile(frame,event,arg):
            if event=='call' and frame.f_code is code and str(frame.f_locals.get('root'))==str(self.home):
                raw.append(1)
        with patch.object(AnalysisPlanWorkflow,'_active',observed_parent),json_evidence_scope(self.w.root,self.sid) as evidence:
            sys.setprofile(profile)
            try:self.assertTrue(self.w.active(self.manifest,self.rid))
            finally:sys.setprofile(previous)
            self.assertEqual(raw,[],'super父方法应进入原证据范围，不能重复从原storage读取')
        self.assertGreater(evidence.stats['exit_sha_checks'],0)

    def test_unknown_function_is_not_bound(self):
        def unrelated(value):return value
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            self.assertIs(evidence.bind(unrelated),unrelated)

    def test_http_json_entry_uses_inherited_scope(self):
        """生产JSON入口也必须覆盖父方法，不在测试外另套成功的范围。"""
        from types import SimpleNamespace
        from modulea.api.server import App
        original=AnalysisPlanWorkflow._active;reference=self.reference
        def observed_parent(workflow,manifest,run_id):
            read_json(verified_file(workflow.location(manifest['study_id']),reference))
            return original(workflow,manifest,run_id)
        raw=[];previous=sys.getprofile();code=storage.verified_file.__code__
        def profile(frame,event,arg):
            if event=='call' and frame.f_code is code and str(frame.f_locals.get('root'))==str(self.home):
                raw.append(1)
        app=SimpleNamespace(settings=SimpleNamespace(data_root=self.w.root))
        with patch.object(AnalysisPlanWorkflow,'_active',observed_parent):
            sys.setprofile(profile)
            try:self.assertTrue(App._json_read(app,self.sid,self.w.active,self.manifest,self.rid))
            finally:sys.setprofile(previous)
        self.assertEqual(raw,[],'生产JSON入口应使用完整继承只读范围')

    def test_home_and_inbox_card_assembly_also_keeps_inherited_read_proofs(self):
        """首页与待办共用卡片组装也须穿过同一父方法证据链，不能继续走旧范围。"""
        from types import SimpleNamespace
        from modulea.api.views import Views
        original=AnalysisPlanWorkflow._active;reference=self.reference;workflow=self.w
        def observed_parent(reader,manifest,run_id):
            read_json(verified_file(reader.location(manifest['study_id']),reference))
            return original(reader,manifest,run_id)
        manifest=self.manifest;rid=self.rid
        def card(views,study_id,with_states=False):
            return {'active':workflow.active(manifest,rid)}
        views=Views(SimpleNamespace(settings=SimpleNamespace(data_root=self.w.root)),None)
        raw=[];previous=sys.getprofile();code=storage.verified_file.__code__
        def profile(frame,event,arg):
            if event=='call' and frame.f_code is code and str(frame.f_locals.get('root'))==str(self.home):
                raw.append(1)
        with patch.object(AnalysisPlanWorkflow,'_active',observed_parent),patch.object(Views,'study_card',card):
            sys.setprofile(profile)
            try:self.assertEqual(views._build_cards([manifest]),[{'active':True}])
            finally:sys.setprofile(previous)
        self.assertEqual(raw,[],'首页/待办卡片不能绕过已知继承读取证据')


class InheritedReadGuardTests(TestCase):
    """对新范围重复必要边界；不以旧范围通过推断新范围同样安全。"""
    setUp=guard_fixture.ReadEvidenceScopeTests.setUp

    def scope(self):
        return json_evidence_scope(self.root,self.sid)

    test_duplicate_refs_first_and_exit_are_full_sha_checked=guard_fixture.ReadEvidenceScopeTests.test_duplicate_refs_first_and_exit_are_full_sha_checked
    test_same_mtime_tamper_cannot_publish_and_json_uses_verified_immutable_bytes=guard_fixture.ReadEvidenceScopeTests.test_same_mtime_tamper_cannot_publish_and_json_uses_verified_immutable_bytes
    test_manifest_change_and_next_independent_request_reject=guard_fixture.ReadEvidenceScopeTests.test_manifest_change_and_next_independent_request_reject
    test_other_thread_and_root_never_share_proof=guard_fixture.ReadEvidenceScopeTests.test_other_thread_and_root_never_share_proof
    test_same_path_changed_dependency_hash_is_not_reused=guard_fixture.ReadEvidenceScopeTests.test_same_path_changed_dependency_hash_is_not_reused
    test_same_scope_nested_context_shares_evidence_and_does_not_clear_parent=guard_fixture.ReadEvidenceScopeTests.test_same_scope_nested_context_shares_evidence_and_does_not_clear_parent

    def test_exact_method_clone_preserves_code_and_globals_without_binding_writes(self):
        """实际父方法原code执行于私有globals；未知/写方法保持原对象。"""
        from modulea.core.native_execution import NativeWorkflow
        original=AnalysisPlanWorkflow._active
        original_reader=original.__globals__['verified_file']
        reader=_ReadWorkflow(self.root,{})
        calls=[];previous=sys.getprofile()
        # 空研究不调用状态机，直接测试签名相同的受信父方法及其默认参数/闭包。
        marker=object()
        def diagnostic(workflow,manifest,run_id=marker):
            return read_json(verified_file(workflow.location(self.sid),self.ref)),run_id
        def profile(frame,event,arg):
            if event=='call' and frame.f_code is diagnostic.__code__:
                calls.append(frame.f_globals)
        with patch.object(AnalysisPlanWorkflow,'_active',diagnostic),self.scope() as evidence:
            bound=evidence.bind(diagnostic)
            self.assertIs(evidence.bind(NativeWorkflow._begin),NativeWorkflow._begin)
            self.assertIs(evidence.bind(reader.review).__func__,reader.review.__func__)
            sys.setprofile(profile)
            try:value,default=bound(reader,{})
            finally:sys.setprofile(previous)
            self.assertEqual(value,{'value':'original'});self.assertIs(default,marker)
            self.assertEqual(len(calls),1);self.assertIsNot(calls[0],diagnostic.__globals__)
            self.assertIs(diagnostic.__globals__['verified_file'],verified_file)
            self.assertEqual(evidence.stats['first_sha_checks'],1)
        self.assertIs(original.__globals__['verified_file'],original_reader)
        self.assertEqual(evidence.stats['exit_sha_checks'],1)
        # 退出后保存的包装器必须回到原严格读取，不得继续复用旧证明。
        self.path.write_text('{"value":"tampered"}',encoding='utf-8')
        from contracts import ContractError
        with self.assertRaises(ContractError):bound(reader,{})

    def test_copied_thread_context_does_not_bind_inherited_methods(self):
        """被复制的ContextVar也不能让其他线程使用本线程私有super链。"""
        from contextvars import copy_context
        from concurrent.futures import ThreadPoolExecutor
        with self.scope() as evidence:
            copied=copy_context()
            with ThreadPoolExecutor(max_workers=1) as pool:
                returned=pool.submit(copied.run,evidence.bind,AnalysisPlanWorkflow._active).result()
            self.assertIs(returned,AnalysisPlanWorkflow._active)

    def test_actual_http_uses_new_scope_and_blocks_tampering_before_sending_json(self):
        """沿生产HTTP分派检查完整页面等值，并核新scope退出前损坏不能发正常JSON。"""
        import json,os,threading
        from urllib.request import urlopen
        from urllib.error import HTTPError
        from modulea.devtools.demo_data import build
        from modulea.config import Settings
        from modulea.api.server import create_server
        from modulea.core.inherited_read_evidence import InheritedReadEvidence
        data=self.root/'http_demo';sid=build(data)
        server,app=create_server(Settings(data_root=data,runtime_dir=self.root/'http_runtime'),0)
        expected=app.views.module(sid,'A07')
        manifest=app.kernel.read_workflow().load(sid);home=data/'studies'/sid
        rid=manifest['current']['A07']
        result=json.loads((home/manifest['runs'][rid]['result_file']['path']).read_text('utf-8'))
        target=home/result['files'][-1]['path'];original=InheritedReadEvidence.finish;tamper=[];scopes=[]
        def finish(evidence):
            scopes.append(evidence)
            if tamper:
                stamp=target.stat();raw=target.read_bytes()
                target.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return original(evidence)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_address[1]}/api/v1/studies/{sid}/modules/A07'
            with patch.object(InheritedReadEvidence,'finish',finish):
                with urlopen(url,timeout=30) as response:self.assertEqual(json.load(response),expected)
                self.assertEqual(len(scopes),1)
                self.assertGreater(scopes[0].stats['exit_sha_checks'],0)
                tamper.append(True)
                with self.assertRaises(HTTPError) as failure:urlopen(url,timeout=30)
                self.assertEqual(failure.exception.code,503)
                self.assertNotIn('run',json.load(failure.exception))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_parallel_home_cards_own_separate_scopes_and_any_exit_failure_blocks_batch(self):
        """两个实际卡片线程各自建范围，任一首尾SHA不一致不能返回整批卡片。"""
        import threading
        from types import SimpleNamespace
        from contracts import ContractError
        from modulea.api.views import Views
        from modulea.core.read_evidence import current_evidence
        from modulea.core.inherited_read_evidence import InheritedReadEvidence
        second='study_'+'b'*32;other=self.root/'studies'/second;other.mkdir()
        (other/'manifest.json').write_text('{}',encoding='utf-8')
        path=other/'sample.json';path.write_bytes(self.path.read_bytes())
        references={self.sid:self.ref,second:file_record(other,path,'source')}
        views=Views(SimpleNamespace(settings=SimpleNamespace(data_root=self.root)),None)
        for tamper in (False,True):
            with self.subTest(tamper= tamper):
                barrier=threading.Barrier(2);owners=[]
                root=self.root
                def card(view,study_id,with_states=False):
                    evidence=current_evidence(root)
                    self.assertIsInstance(evidence,InheritedReadEvidence)
                    self.assertEqual(evidence.owner,threading.get_ident())
                    evidence.verified_file(root/'studies'/study_id,references[study_id])
                    owners.append(evidence)
                    barrier.wait(timeout=5)
                    if tamper and study_id==second:path.write_text('broken',encoding='utf-8')
                    return {'study_id':study_id}
                with patch.object(Views,'study_card',card):
                    if tamper:
                        with self.assertRaises(ContractError):views._build_cards([{'study_id':s} for s in (self.sid,second)])
                    else:
                        self.assertEqual(views._build_cards([{'study_id':s} for s in (self.sid,second)]),
                            [{'study_id':s} for s in (self.sid,second)])
                self.assertEqual(len(owners),2);self.assertIsNot(owners[0],owners[1])
                self.assertTrue(all(not evidence.active for evidence in owners))
                self.assertIsNone(current_evidence(root))
