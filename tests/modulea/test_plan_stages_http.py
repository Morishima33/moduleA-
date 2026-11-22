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

    def test_joint_input_review_queues_a03_without_second_confirmation(self):
        manifest = self.w.load(self.sid)
        manifest['workflow_profile'] = 'A00.preupload.2'
        self.w.save(manifest)
        entries = {}
        for module in ('A01', 'A02'):
            manifest = self.w.load(self.sid)
            rid = manifest['current'][module]
            previous = self.w.latest_review(manifest, self.w.run(manifest, rid)['artifact_id'])
            saved = self.w.review(self.sid, rid, 'pending', '测试', '等待两侧一并核对', previous['review_id'])
            entries[module] = {'run_id': rid, 'expected_review_id': saved['review_id'],
                               'action': 'decide', 'decision': 'approved', 'note': '两侧核查完成'}
        path = f'/studies/{self.sid}/reviews:batch'
        payload = {'reviewer': '测试', 'entries': entries, 'continue_to_a03': True,
                   'expected_plan_id': self.plan['plan_id']}
        self.assertEqual(self.call('POST', path, dict(payload, expected_plan_id='stale'))[0], 409)
        self.assertNotIn('A03', self.w.load(self.sid)['current'])
        status, result = self.call('POST', path, payload)
        self.assertEqual(status, 201, result)
        self.assertEqual(len(result['reviews']), 2)
        self.assertIsNotNone(result['task'], result)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            task = self.app.tasks.get(result['task']['task_id'])
            if task['state'] not in ('queued', 'running'):
                break
            time.sleep(.1)
        self.assertEqual(task['state'], 'succeeded', task)
        manifest = self.w.load(self.sid)
        result = self.w.result(manifest, manifest['current']['A03'])
        self.assertEqual(result['summary']['交集靶点数'], 4)
        self.assertTrue(result['figures'])

    def test_a05_can_start_while_real_a04_waits_for_string(self):
        from types import SimpleNamespace
        from modulea.tasks import a03_followup
        from science_modules.a04 import plan_flow
        from tests.modulea.test_plan_stages import network_request

        result = self.w.execute_analysis_plan_stage(self.sid, body(self.w, self.sid, 'A03'))
        review = self.w.review(self.sid, result['run_id'], 'approved', '隔离测试', '同一交集接续网络和富集')
        approval = {'plan_id':self.plan['plan_id'], 'run_id':result['run_id'], 'review_id':review['review_id']}
        enrichment_started = threading.Event()

        def string(method, params, opener=None):
            self.assertTrue(enrichment_started.wait(10), 'A05 应在 STRING 等待期间开始')
            return network_request(method, params, opener)

        def enrichment(sid, request, *, progress):
            self.assertEqual(sid, self.sid)
            self.assertEqual(request['expected_a03'], result['run_id'])
            self.assertNotIn('A04', self.w.load(sid)['current'])
            enrichment_started.set()
            raise RuntimeError('隔离测试：R运行失败')

        def workflow():
            w = type(self.w)(self.settings.data_root, self.w.validators)
            w.publish_analysis_plan_a05 = enrichment
            return w

        with patch.object(plan_flow, 'request', side_effect=string):
            with self.assertRaisesRegex(Exception, 'A04 已归档.*A05.*R运行失败'):
                a03_followup.execute(workflow, self.sid, approval, rscript=__file__, progress=lambda _:None)
        self.assertIn('A04', self.w.load(self.sid)['current'])

    def test_personalized_a03_approval_queues_both_siblings_with_the_same_review(self):
        result = self.w.execute_analysis_plan_stage(self.sid, body(self.w, self.sid, 'A03'))
        with (patch('modulea.api.server.is_plan_created', return_value=True),
              patch.object(self.app.tasks, '_spawn')):
            status, saved = self.call('POST', f'/studies/{self.sid}/modules/A03/reviews', {
                'run_id':result['run_id'], 'expected_review_id':None, 'decision':'approved',
                'reviewer':'隔离测试', 'note':'明确核对交集', 'after':'save'})
        self.assertEqual(status, 201, saved)
        self.assertEqual(saved['task']['kind'], 'plan_a03_followup')
        import json
        payload = json.loads(self.app.tasks._raw(saved['task']['task_id'])['payload'])
        self.assertEqual(payload, {'run_id':result['run_id'], 'review_id':saved['review']['review_id'],
                                   'plan_id':self.plan['plan_id']})

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
