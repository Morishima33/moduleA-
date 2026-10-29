"""真实本机HTTP、独立任务进程及追溯接口验证；只用隔离合成研究。"""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from modulea.api.server import create_server
from modulea.config import Settings
from modulea.tasks.worker import run_task
from tests.modulea import test_plan_creation_http as creation_http
from tests.modulea.test_plan_stages import fixture, body


class PlanStagesHttpTests(unittest.TestCase):
    call=creation_http.PlanCreationHttpTests.call
    close=creation_http.PlanCreationHttpTests.close

    def setUp(self):
        """用当前测试解释器实际启动后台；不配置个人工具路径。"""
        self.temp=tempfile.TemporaryDirectory(prefix='plan_stages_http_');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.settings=Settings(data_root=root/'data',runtime_dir=root/'runtime')
        self.w,self.sid,self.plan=fixture(self.settings.data_root)
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/stages'

    def test_real_subprocess_a03_and_trace_export(self):
        """真实202任务进程生成四基因交集，HTTP导出请求及回执，人工复核保持。"""
        before=self.w.load(self.sid)
        status,readiness=self.call('GET',self.path)
        self.assertEqual(status,200,readiness)
        self.assertTrue(next(r for r in readiness['stages'] if r['stage']=='A03')['enabled'])
        status,value=self.call('POST',self.path+'/execute',body(self.w,self.sid,'A03'))
        self.assertEqual(status,202,value)
        task_id=value['task']['task_id'];deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            task=self.app.tasks.get(task_id)
            if task['state'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(task['state'],'succeeded',task)
        after=self.w.load(self.sid);self.assertEqual(after['reviews'],before['reviews'])
        result=self.w.result(after,after['current']['A03'])
        self.assertEqual(result['summary']['交集靶点数'],4)
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json')
        self.assertEqual(status,200,trace)
        self.assertEqual(trace['stage_execution']['receipts'][0]['run_id'],result['run_id'])
        self.assertFalse(self.w.approved(after,result['run_id']))
        status,view=self.call('GET',f'/studies/{self.sid}/modules/A03')
        self.assertEqual(status,200,view);self.assertFalse(view['review']['continue']['available'])
        status,_=self.call('POST',f'/studies/{self.sid}:continue',{})
        self.assertEqual(status,409)
        status,saved=self.call('POST',f'/studies/{self.sid}/modules/A03/reviews',{
            'run_id':result['run_id'],'expected_review_id':None,'decision':'approved','reviewer':'隔离测试',
            'note':'仅合成测试复核，不代表正式研究','after':'continue'})
        self.assertEqual(status,201,saved);self.assertIsNone(saved['task'])
        self.assertEqual(len(self.app.tasks.list(self.sid)),1)

    def test_csrf_hidden_stale_busy_and_worker_revalidation(self):
        """非法请求不入队，排队后上游改变则实际科学任务失败且不发布结果。"""
        request=body(self.w,self.sid,'A03')
        for token,origin in ((False,None),(True,'https://untrusted.example')):
            self.assertEqual(self.call('POST',self.path+'/execute',request,token,origin)[0],403)
        self.assertEqual(self.call('POST',self.path+'/execute',dict(request,approved=True))[0],422)
        self.assertEqual(self.call('POST',self.path+'/execute',dict(request,expected_input_hash='old'))[0],409)
        self.assertEqual(self.app.tasks.list(),[])
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/execute',request)
        self.assertEqual(status,202,value)
        status,readiness=self.call('GET',self.path)
        self.assertEqual(status,200,readiness)
        self.assertTrue(all(not r['enabled'] for r in readiness['stages']))
        self.assertEqual(self.call('POST',self.path+'/execute',request)[0],409)
        m=self.w.load(self.sid);a02=m['current']['A02'];review=self.w.latest_review(m,self.w.run(m,a02)['artifact_id'])
        self.w.review(self.sid,a02,'pending','隔离测试','撤回合成上游',review['review_id'])
        self.assertEqual(run_task(self.settings,value['task']['task_id']),1)
        m=self.w.load(self.sid);self.assertNotIn('A03',m['current'])
        self.assertEqual(m.get('analysis_plan_stage_receipts',[]),[])

    def test_legacy_and_trash_are_read_only(self):
        """历史固定研究和回收站不能借新版入口执行。"""
        legacy=self.w.create({'formula':'合成旧方','herbs':'合成药','disease':'合成病','disease_scope':'仅本病',
            'operator':'隔离测试','species':9606},kind='contract_test')
        status,value=self.call('GET',f'/studies/{legacy}/analysis-plan/stages')
        self.assertEqual(status,200,value);self.assertFalse(value['supported']);self.assertEqual(value['stages'],[])
        self.assertEqual(self.call('POST',f'/studies/{legacy}/analysis-plan/stages/execute',body(self.w,self.sid,'A03'))[0],409)
        request=body(self.w,self.sid,'A03');self.w.set_trashed(self.sid,True,'隔离测试','合成回收站')
        self.assertEqual(self.call('POST',self.path+'/execute',request)[0],423)
        self.assertEqual(self.app.tasks.list(),[])
