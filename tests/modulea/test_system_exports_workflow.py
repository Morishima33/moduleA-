"""真实公开工作流导出、检查点恢复及HTTP下载；所有研究、来源和几何明确为合成。"""
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from storage import verified_file
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from modulea.core import system_exports_v2 as registry
from modulea.core.trace_export import build_trace
from science_modules.a06 import system_exports_v2 as science
from tests.modulea import test_system_scoring as upstream


class SystemExportsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 合成来源沿原生产准备/资格规范，Vina只在隔离基线实际评分一次。
        upstream.SystemScoringTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base)
        cls.scored=w.score_analysis_plan_system_preparation(cls.sid,{
            'batch_id':cls.batch_id,'expected_preparation_run_id':cls.qualified['run_id'],
            'expected_scoring_run_id':None},tools=cls.tools)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_exports_workflow_');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.root=self.folder/'data';shutil.copytree(self.base,self.root)
        self.w=full_workflow(self.root);self.before=self.w.load(self.sid)
        info=self.w.analysis_plan_system_exports_info(self.sid)
        self.body={key:info[key] for key in ('expected_module','expected_run_id','expected_input_hash')}|{
            'request_id':'sysexportreq_'+uuid4().hex,'author':'明确隔离导出测试',
            'note':'合成结果原字节导出，不是人工复核', 'confirmed':True}

    def execute(self):return self.w.export_analysis_plan_system_results(self.sid,self.body)

    def stable_science(self):
        """只允许追加派生档案，科学原件与人工记录逐项保持。"""
        after=self.w.load(self.sid)
        for key in ('current','runs','reviews'):
            self.assertEqual(after.get(key),self.before.get(key),key)
        for files in self.before['runs'].values():
            for ref in files.values():
                if ref:verified_file(self.w.location(self.sid),ref)

    def test_real_export_all_six_files_trace_and_exact_request_replay_without_recompute(self):
        home=self.w.location(self.sid);record=self.execute();self.stable_science()
        self.assertEqual(len(record['files']),6);self.assertTrue(record['created'])
        self.assertEqual(record['source_run_id'],self.scored['run_id'])
        files={kind:verified_file(home,ref) for kind,ref in record['formats'].items()}
        from openpyxl import load_workbook
        book=load_workbook(files['xlsx'],data_only=True)
        matrix=book['完整评分矩阵'];self.assertEqual(matrix.cell(2,3).value,-0.264)
        self.assertEqual(matrix.cell(3,3).value,'NA');book.close()
        before=self.w.load(self.sid)
        with patch.object(science,'export',side_effect=AssertionError('已发表请求不能重生成')):
            replay=self.execute()
        self.assertEqual(replay['export_id'],record['export_id']);self.assertFalse(replay['created'])
        self.assertEqual(self.w.load(self.sid),before)
        trace=build_trace(self.w,self.sid)
        self.assertEqual(len(trace['plan_decisions']['system_exports']),1)
        encoded=json.dumps(trace,ensure_ascii=False)
        for ref in record['files']:self.assertIn(ref['sha256'],encoded)

    def test_registered_complete_checkpoint_resumes_without_render_after_publication_failure(self):
        save=self.w.save;failed=[]
        def interrupt(m):
            if m.get(registry.INDEX) and not failed:
                failed.append(True);raise OSError('明确合成：回执发表前中断')
            return save(m)
        with patch.object(self.w,'save',side_effect=interrupt),self.assertRaises(OSError):self.execute()
        m=self.w.load(self.sid);self.assertEqual(len(m[registry.CANDIDATES]),1)
        self.assertNotIn(registry.INDEX,m);self.assertEqual(len(m[registry.FAILURES]),1)
        candidate=registry.read_candidate(self.w,m,m[registry.CANDIDATES][0])
        hashes=[ref['sha256'] for ref in candidate['files']]
        with patch.object(science,'export',side_effect=AssertionError('完整检查点不得重生成')):record=self.execute()
        self.assertEqual([ref['sha256'] for ref in record['files']],hashes);self.stable_science()
        self.assertEqual(len(list((self.w.location(self.sid)/'decisions/analysis_plans/system_exports'/self.body['request_id']/'records').glob('*.json'))),2)

    def test_corrupt_completed_file_is_not_repaired_by_silent_regeneration(self):
        record=self.execute();home=self.w.location(self.sid)
        path=verified_file(home,record['formats']['csv']);path.write_bytes(path.read_bytes()+b'CORRUPT')
        with patch.object(science,'export',side_effect=AssertionError('损坏不能用重新生成掩盖')),self.assertRaises(ContractError):self.execute()
        self.stable_science()

    def test_stale_unconfirmed_extra_fields_and_reused_request_with_changed_content_rejected(self):
        for body in (self.body|{'confirmed':False},self.body|{'score':-9},self.body|{'expected_input_hash':'stale'}):
            with self.subTest(body=body),self.assertRaises(ContractError):
                self.w.export_analysis_plan_system_results(self.sid,body)
        self.execute()
        with self.assertRaises(ContractError):self.w.export_analysis_plan_system_results(self.sid,self.body|{'note':'不同内容'})
        self.stable_science()

    def test_hold_blocks_new_generation_but_preserves_readonly_history(self):
        record=self.execute()
        self.w.review(self.sid,self.scored['run_id'],'pending','明确合成测试','暂存导出来源')
        info=self.w.analysis_plan_system_exports_info(self.sid)
        self.assertFalse(info['enabled']);self.assertEqual(info['history'][0]['export_id'],record['export_id'])
        with patch.object(science,'export',side_effect=AssertionError('人工暂停不能新生成')),self.assertRaises(ContractError):self.execute()

    def test_first_version_replay_and_second_version_history_keep_original_artifacts(self):
        from modulea.core import system_exports as old_registry
        from science_modules.a06 import system_exports as old_science
        first=old_registry.execute(self.w,self.sid,self.body)
        original=self.w.load(self.sid)
        self.assertIsNone(self.w.analysis_plan_system_exports_info(self.sid)['current'])
        with patch.object(old_science,'export',side_effect=AssertionError('旧请求不能重新排版')):
            self.assertEqual(self.execute()['export_id'],first['export_id'])
        self.assertEqual(self.w.load(self.sid),original)
        self.body=dict(self.body,request_id='sysexportreq_'+uuid4().hex)
        second=self.execute();self.assertEqual(second['schema_version'],'A06.system_exports.2')
        info=self.w.analysis_plan_system_exports_info(self.sid)
        self.assertEqual(info['current']['export_id'],second['export_id'])
        self.assertEqual([r['schema_version'] for r in info['history']],['A06.system_exports.1','A06.system_exports.2'])
        for ref in first['files']:verified_file(self.w.location(self.sid),ref)
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['system_exports']),2)
        self.stable_science()

    def server(self):
        """创建自己持有的本地隔离HTTP服务，退出时只关闭该实例。"""
        server,app=create_server(Settings(data_root=self.root,runtime_dir=self.folder/'runtime'),0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():server.shutdown();server.server_close();thread.join()
        self.addCleanup(close)
        return server,app

    def call(self,server,app,method,path,body=None,token=True,origin=None):
        """实际HTTP返回原字节，文件下载也核对真实Content-Type。"""
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
        headers={'Content-Type':'application/json'}
        if token:headers['X-ModuleA-Token']=app.token
        if origin:headers['Origin']=origin
        connection.request(method,'/api/v1'+path,None if body is None else json.dumps(body),headers)
        response=connection.getresponse();value=(response.status,response.read(),dict(response.getheaders()));connection.close()
        return value

    def test_actual_http_readonly_info_six_downloads_and_module_view_do_not_write(self):
        record=self.execute();server,app=self.server();before=self.w.load(self.sid)
        prefix=f'/studies/{self.sid}/analysis-plan/system-exports'
        status,raw,_=self.call(server,app,'GET',prefix);self.assertEqual(status,200,raw)
        info=json.loads(raw);self.assertEqual(info['current']['export_id'],record['export_id'])
        for ref in info['current']['files']:
            status,data,headers=self.call(server,app,'GET',ref['download_url'].removeprefix('/api/v1'))
            self.assertEqual(status,200);self.assertEqual(hashlib.sha256(data).hexdigest(),ref['sha256'])
            self.assertIn('Content-Disposition',headers)
        status,raw,_=self.call(server,app,'GET',f'/studies/{self.sid}/modules/A06')
        self.assertEqual(status,200,raw);self.assertEqual(json.loads(raw)['system_exports']['current']['export_id'],record['export_id'])
        self.assertEqual(self.w.load(self.sid),before);self.assertEqual(app.tasks.list(),[])
        status,_,_=self.call(server,app,'GET',prefix+'/'+record['export_id']+'/files/6');self.assertEqual(status,404)

    def test_actual_http_security_and_real_budgeted_worker(self):
        server,app=self.server();prefix=f'/studies/{self.sid}/analysis-plan/system-exports'
        for token,origin in ((False,None),(True,'https://untrusted.example')):
            status,_,_=self.call(server,app,'POST',prefix,self.body,token,origin);self.assertEqual(status,403)
        status,_,_=self.call(server,app,'POST',prefix,self.body|{'confirmed':False});self.assertEqual(status,422)
        self.assertEqual(app.tasks.list(),[])
        status,raw,_=self.call(server,app,'POST',prefix,self.body);self.assertEqual(status,202,raw)
        task=json.loads(raw)['task'];deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            task=app.tasks.get(task['task_id'])
            if task['state'] in ('succeeded','failed','cancelled'):break
            time.sleep(.1)
        self.assertEqual(task['state'],'succeeded',app.tasks.log(task['task_id']))
        for thread in threading.enumerate():
            if thread.name=='modulea-reap-'+task['task_id']:thread.join(timeout=10)
        self.assertEqual(len(self.w.load(self.sid)[registry.INDEX]),1);self.stable_science()


if __name__=='__main__':unittest.main()
