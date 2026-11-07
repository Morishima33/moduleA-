"""显式单请求证据范围：原代码等值、不可变JSON及返回前全SHA，不写真实研究。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import json,os,unittest
import subprocess
from contracts import ContractError
from storage import file_record
from contextvars import copy_context


class ReadEvidenceScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.sid='study_'+'a'*32;self.home=self.root/'studies'/self.sid;self.home.mkdir(parents=True)
        self.manifest=self.home/'manifest.json';self.manifest.write_text('{"current":1}',encoding='utf-8')
        self.path=self.home/'sample.json';self.path.write_text('{"value":"original"}',encoding='utf-8')
        self.ref=file_record(self.home,self.path,'source')

    def scope(self):
        from modulea.core.read_evidence import read_evidence_scope
        return read_evidence_scope(self.root,self.sid)

    def test_duplicate_refs_first_and_exit_are_full_sha_checked(self):
        with self.scope() as evidence:
            evidence.verify_all(self.home,[self.ref]*80)
            self.assertEqual(evidence.read_json(evidence.verified_file(self.home,self.ref)),{'value':'original'})
            self.assertEqual(evidence.stats['first_sha_checks'],1)
        self.assertEqual(evidence.stats['exit_sha_checks'],1)
        self.assertEqual(evidence.stats['first_bytes_hashed'],self.ref['bytes'])
        self.assertEqual(evidence.stats['exit_bytes_hashed'],self.ref['bytes'])

    def test_same_mtime_tamper_cannot_publish_and_json_uses_verified_immutable_bytes(self):
        with self.assertRaises(ContractError):
            with self.scope() as evidence:
                path=evidence.verified_file(self.home,self.ref);stamp=path.stat()
                path.write_text('{"value":"tampered"}',encoding='utf-8');os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                self.assertEqual(evidence.read_json(path),{'value':'original'})

    def test_manifest_change_and_next_independent_request_reject(self):
        with self.scope() as evidence:evidence.verified_file(self.home,self.ref)
        self.path.write_text('{"value":"tampered"}',encoding='utf-8')
        with self.assertRaises(ContractError):
            with self.scope() as fresh:fresh.verified_file(self.home,self.ref)
        with self.assertRaises(ContractError):
            with self.scope():self.manifest.write_text('{"current":2}',encoding='utf-8')

    def test_other_thread_and_root_never_share_proof(self):
        with self.scope() as evidence:
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(evidence.verified_file,self.home,self.ref).result()
            self.assertEqual(evidence.stats['first_sha_checks'],0)
            other=self.root.parent/'other_scope.json';other.write_text('{}',encoding='utf-8');self.addCleanup(other.unlink)
            record=file_record(other.parent,other,'other');evidence.verified_file(other.parent,record)
            self.assertEqual(evidence.stats['first_sha_checks'],0)

    def test_bound_original_code_and_globals_stay_unchanged(self):
        from modulea.core import plan_reports
        source=plan_reports.read_receipt;original=source.__globals__['verified_file']
        with self.scope() as evidence:
            bound=evidence.bind(source)
            self.assertIs(bound.__code__,source.__code__)
            self.assertIs(bound.__closure__,source.__closure__)
            self.assertIs(bound.__defaults__,source.__defaults__)
            self.assertIs(source.__globals__['verified_file'],original)
            self.assertIsNot(bound.__globals__['verified_file'],original)
            self.assertIs(evidence.bind(plan_reports.publish),plan_reports.publish)
        self.assertIs(source.__globals__['verified_file'],original)

    def test_second_report_protocol_keeps_its_own_namespace_and_original_class_closure(self):
        from modulea.core import plan_reports,plan_reports_v2
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        with self.scope() as evidence:
            old=evidence.bind(plan_reports.read_receipt);new=evidence.bind(plan_reports_v2.read_receipt)
            self.assertEqual(old.__globals__['VERSION'],plan_reports.VERSION)
            self.assertEqual(new.__globals__['VERSION'],plan_reports_v2.VERSION)
            self.assertEqual(evidence.bind(plan_reports_v2._info_base).__globals__['CONFIG'],plan_reports_v2.CONFIG)
            self.assertIs(evidence.bind(AnalysisPlanWorkflow._active).__closure__,AnalysisPlanWorkflow._active.__closure__)

    def test_local_identity_bridge_keeps_original_code_and_bound_read_dependencies(self):
        from modulea.core import identity_exceptions,system_execution
        with self.scope() as evidence:
            bound=evidence.bind(system_execution.require_batch)
            module=bound.__builtins__['__import__']('identity_exceptions',bound.__globals__,None,('for_batch',),1)
            bridge=module.for_batch
            self.assertIs(bridge.__code__,identity_exceptions.for_batch.__code__)
            self.assertIs(bridge.__globals__['read_record'],evidence.bind(identity_exceptions.read_record))
            self.assertIs(bridge.__globals__['guard'],evidence.bind(identity_exceptions.guard))
            self.assertIs(evidence.bind(identity_exceptions.register),identity_exceptions.register)

    def test_same_path_changed_dependency_hash_is_not_reused(self):
        with self.assertRaises(ContractError):
            with self.scope() as evidence:
                evidence.verified_file(self.home,self.ref)
                evidence.verified_file(self.home,dict(self.ref,sha256='0'*64))

    def test_copied_thread_context_and_explicit_other_study_do_not_merge(self):
        from modulea.core.read_evidence import read_evidence_scope,current_evidence
        with self.scope() as evidence:
            copied=copy_context()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertIsNone(pool.submit(copied.run,current_evidence).result())
            other=self.root/'studies'/'study_other';other.mkdir();(other/'manifest.json').write_text('{}',encoding='utf-8')
            with read_evidence_scope(self.root,'study_other') as different:
                self.assertIsNot(different,evidence)
            self.assertIs(current_evidence(),evidence)

    def test_same_scope_nested_context_shares_evidence_and_does_not_clear_parent(self):
        with self.scope() as evidence:
            evidence.verified_file(self.home,self.ref)
            with self.scope() as nested:
                self.assertIs(nested,evidence)
                self.assertEqual(nested.stats['exit_sha_checks'],0)
                nested.verified_file(self.home,self.ref)
            self.assertEqual(evidence.stats['exit_sha_checks'],0)
        self.assertEqual(evidence.stats['exit_sha_checks'],1)

    def test_cloned_local_imports_are_private_and_unindexed_json_is_guarded(self):
        import builtins,sys
        from modulea.api import plan_reports
        from storage import verified_file
        module=sys.modules['storage'];original_import=builtins.__import__
        with self.scope() as evidence:
            bound=evidence.bind(plan_reports.info)
            private_import=bound.__globals__['__builtins__']['__import__']
            self.assertIs(bound.__builtins__['__import__'],private_import)
            proxy=private_import('storage',{},None,('verified_file',),0)
            self.assertIsNot(proxy.verified_file,verified_file)
            self.assertIs(sys.modules['storage'],module)
            self.assertIs(builtins.__import__,original_import)
            self.assertEqual(evidence.read_json(self.manifest),{'current':1})
            returned=evidence.read_json(self.path);returned['value']='caller mutation'
            self.assertEqual(evidence.read_json(self.path),{'value':'original'})

    def test_missing_study_remains_original_http_not_found(self):
        from modulea.config import Settings
        from modulea.api.server import App
        from modulea.api.errors import ApiError
        from modulea.core.read_evidence import read_evidence_scope
        app=App(Settings(data_root=self.root,runtime_dir=self.root/'runtime'))
        with read_evidence_scope(self.root,'study_'+'d'*32) as evidence:
            with self.assertRaises(ApiError) as failure:evidence.call(app.views.module,'study_'+'d'*32,'A07')
            self.assertEqual(failure.exception.status,404)

    def junction(self, link, target):
        """Windows目录联接无需符号链接权限；仅创建本测试临时目录内的联接。"""
        if os.name!='nt':self.skipTest('此项核对Windows目录联接')
        run=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True)
        if run.returncode:self.skipTest('当前环境无法创建目录联接：'+repr(run.stderr))
        self.assertTrue(link.is_junction())

    def test_same_byte_manifest_junction_replacement_is_rejected(self):
        from modulea.core.read_evidence import read_evidence_scope
        first=self.root/'studies'/'first';second=self.root/'studies'/'second'
        for home in (first,second):home.mkdir();(home/'manifest.json').write_text('{}',encoding='utf-8')
        link=self.root/'studies'/'study_link';self.junction(link,first)
        try:
            with self.assertRaises(ContractError):
                with read_evidence_scope(self.root,'study_link'):
                    link.rmdir();self.junction(link,second)
            self.assertTrue((first/'manifest.json').is_file());self.assertTrue((second/'manifest.json').is_file())
        finally:
            if link.is_junction():link.rmdir()

    def test_cached_home_junction_replacement_is_rejected(self):
        first=self.root/'first';second=self.root/'second'
        for home in (first,second):home.mkdir();(home/'sample').write_bytes(b'evidence')
        link=self.root/'inputs';self.junction(link,first);ref=file_record(first,first/'sample','source')
        try:
            with self.assertRaises(ContractError):
                with self.scope() as evidence:
                    evidence.verified_file(link,ref)
                    link.rmdir();self.junction(link,second)
        finally:
            if link.is_junction():link.rmdir()

    def test_location_reuse_calls_original_again_on_exit_and_default_remains_fresh(self):
        from modulea.config import Settings
        from modulea.core.kernel import Kernel
        reader=Kernel(Settings(data_root=self.root)).read_workflow()
        with self.scope() as evidence:
            for _ in range(20):self.assertEqual(reader.location(self.sid),self.home.resolve())
            self.assertEqual(evidence.stats['location_resolutions'],1)
            self.assertEqual(evidence.stats['location_cache_hits'],19)
        self.assertEqual(reader.location(self.sid),self.home.resolve())

    def test_other_root_bound_method_remains_original_and_write_factory_keeps_validators(self):
        from modulea.config import Settings
        from modulea.core.kernel import Kernel
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from modulea.core.read_archive import ReadResultMixin
        reader=Kernel(Settings(data_root=self.root/'another')).read_workflow()
        validators={'A03':lambda *a:None}
        with self.scope() as evidence:
            method=reader._active;self.assertIs(evidence.bind(method),method)
            original=AnalysisPlanWorkflow(self.root,validators)
            self.assertNotIsInstance(original,ReadResultMixin)
            self.assertIs(original.validators,validators)

    def test_json_pages_equal_without_global_patching(self):
        from modulea.devtools.demo_data import build
        from modulea.config import Settings
        from modulea.api.server import App
        sid=build(self.root/'demo');app=App(Settings(data_root=self.root/'demo',runtime_dir=self.root/'runtime'))
        old=app.views.module(sid,'A07')
        from modulea.core.read_evidence import read_evidence_scope
        with read_evidence_scope(app.settings.data_root,sid) as evidence:new=evidence.call(app.views.module,sid,'A07')
        self.assertEqual(new,old)
        self.assertGreater(evidence.stats['exit_sha_checks'],0)

    def test_http_never_sends_normal_json_when_file_changes_before_scope_exit(self):
        import threading
        from urllib.request import urlopen
        from urllib.error import HTTPError
        from modulea.devtools.demo_data import build
        from modulea.config import Settings
        from modulea.api.server import create_server
        from modulea.core.read_evidence import read_evidence_scope
        data=self.root/'http_demo';sid=build(data);server,app=create_server(Settings(data_root=data,runtime_dir=self.root/'http_runtime'),0)
        manifest=app.kernel.read_workflow().load(sid);home=data/'studies'/sid
        rid=manifest['current']['A07'];result=json.loads((home/manifest['runs'][rid]['result_file']['path']).read_text('utf-8'))
        target=home/result['files'][-1]['path'];tamper=[]
        def checked(req,study,module):
            with read_evidence_scope(data,study) as evidence:
                value=evidence.call(app.views.module,study,module)
                if tamper:
                    saved=target.stat();raw=target.read_bytes();target.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                    os.utime(target,ns=(saved.st_atime_ns,saved.st_mtime_ns))
                return value
        app.compiled=[(method,pattern,checked if getattr(handler,'__name__','')=='get_module' else handler)
                      for method,pattern,handler in app.compiled]
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}/api/v1/studies/{sid}/modules/A07'
        try:
            with urlopen(url) as response:self.assertEqual(json.load(response)['run']['run_id'],rid)
            tamper.append(True)
            with self.assertRaises(HTTPError) as failure:urlopen(url)
            self.assertEqual(failure.exception.code,503)
            self.assertNotIn('run',json.loads(failure.exception.read()))
            tamper.clear()
            with self.assertRaises(HTTPError) as failure:urlopen(url)
            self.assertEqual(failure.exception.code,503)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_two_concurrent_requests_each_own_complete_first_and_exit_proofs(self):
        import threading
        from modulea.devtools.demo_data import build
        from modulea.config import Settings
        from modulea.api.server import App
        from modulea.core.read_evidence import read_evidence_scope
        data=self.root/'concurrent';sid=build(data);app=App(Settings(data_root=data,runtime_dir=self.root/'concurrent_runtime'))
        start=threading.Barrier(2)
        def request():
            start.wait(timeout=10)
            with read_evidence_scope(data,sid) as evidence:
                value=evidence.call(app.views.module,sid,'A07')
                proofs={(str(home),ref['path'],ref['bytes'],ref['sha256']) for home,ref,path in evidence.proofs.values()}
            return value,proofs,evidence.stats
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(request);second=pool.submit(request)
            left,right=first.result(timeout=90),second.result(timeout=90)
        self.assertEqual(left[0],right[0]);self.assertTrue(left[1]);self.assertEqual(left[1],right[1])
        for result in (left,right):
            self.assertEqual(result[2]['first_sha_checks'],len(result[1]))
            self.assertEqual(result[2]['exit_sha_checks'],len(result[1]))

    def test_original_view_cache_capture_is_same_request_only_and_default_clears_it(self):
        from modulea.devtools.demo_data import build
        from modulea.config import Settings
        from modulea.core.kernel import Kernel
        from modulea.core.read_evidence import read_evidence_scope
        data=self.root/'cache_demo';sid=build(data);reader=Kernel(Settings(data_root=data)).read_workflow()
        with read_evidence_scope(data,sid) as first:
            reader.view(sid);cache=reader._request_view_cache
            self.assertIs(reader._request_view_cache_scope,first)
            self.assertTrue(cache['active']);self.assertIsNone(reader._view_cache)
            cache['request_only_sentinel']=True
        with read_evidence_scope(data,sid) as second:
            reader.view(sid)
            self.assertIs(reader._request_view_cache_scope,second)
            self.assertIsNot(reader._request_view_cache,cache)
            self.assertNotIn('request_only_sentinel',reader._request_view_cache)
        reader.view(sid)
        self.assertFalse(hasattr(reader,'_request_view_cache'))
        self.assertFalse(hasattr(reader,'_request_view_cache_scope'))


if __name__=='__main__':unittest.main()
