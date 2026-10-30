"""统一后台实际HTTP和独立科学worker；只使用空交集合成研究，GET不计算。"""
from pathlib import Path
import json,shutil,tempfile,threading,time,unittest
from unittest.mock import patch
from uuid import uuid4
from modulea.core.kernel import full_workflow
from modulea.core import system_execution,system_pipeline
from storage import read_json,verified_file
from tests.modulea import test_system_pipeline as fixture
from tests.modulea import test_plan_creation_http as http_fixture


class SystemPipelineHttpTests(unittest.TestCase):
    call=http_fixture.PlanCreationHttpTests.call
    close=http_fixture.PlanCreationHttpTests.close
    @classmethod
    def setUpClass(cls):fixture.SystemPipelineTests.setUpClass.__func__(cls)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pipeline_http_');self.addCleanup(self.temp.cleanup)
        source,self.sid,self.batch_id=self.cases[True];self.root=Path(self.temp.name)/'data';shutil.copytree(source,self.root)
        self.w=full_workflow(self.root);m=self.w.load(self.sid)
        self.start_body=read_json(verified_file(self.w.location(self.sid),m[system_execution.BATCHES][-1]))['request']
        from modulea.api.server import create_server
        from modulea.config import Settings
        self.server,self.app=create_server(Settings(data_root=self.root,runtime_dir=self.root/'rt'),0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/system-pipeline'

    def test_actual_http_once_confirmation_worker_and_read_only_history(self):
        before=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertEqual(self.w.load(self.sid),before);self.assertEqual(len(value['batches']),1)
        status,value=self.call('POST',self.path+'/start',self.start_body);self.assertEqual(status,202,value)
        tid=value['task']['task_id'];deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            task=self.app.tasks.get(tid)
            if task['state'] not in ('queued','running'):break
            time.sleep(.2)
        self.assertEqual(task['state'],'succeeded',self.app.tasks.log(tid))
        m=self.w.load(self.sid);self.assertEqual(m['reviews'],before['reviews']);self.assertIn('A07',m['current'])
        self.assertFalse(self.w.approved(m,m['current']['A07']))
        self.assertEqual(len(m[system_execution.BATCHES]),1)
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertEqual(value['batches'][0]['latest_event']['state'],'awaiting_report_review')
        self.assertEqual(self.w.load(self.sid),m)
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertTrue(trace['plan_decisions']['system_pipeline'])

    def test_token_origin_schema_stale_busy_and_trash_do_not_submit_or_compute(self):
        before=self.w.load(self.sid);value=system_pipeline.info(self.w,self.sid)['batches'][0]
        body={'batch_id':self.batch_id,'expected_input_hash':value['expected_input_hash']}
        self.assertEqual(self.call('POST',self.path+'/start',self.start_body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/start',self.start_body,True,'https://untrusted.example')[0],403)
        for extra in ({'parameters':{}},{'passed':True},{'path':'outside'}):
            self.assertEqual(self.call('POST',self.path+'/continue',body|extra)[0],422)
        self.assertEqual(self.call('POST',self.path+'/start',self.start_body|{'confirmed':False})[0],422)
        self.assertEqual(self.call('POST',self.path+'/continue',body|{'expected_input_hash':'old'})[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'explicit_synthetic_busy'}):
            self.assertEqual(self.call('POST',self.path+'/continue',body)[0],409)
        self.assertEqual(self.w.load(self.sid),before);self.assertEqual(self.app.tasks.list(self.sid),[])
        self.w.set_trashed(self.sid,True,'明确合成测试','回收站保护')
        self.assertEqual(self.call('POST',self.path+'/continue',body)[0],423)
        self.assertEqual(self.call('POST',self.path+'/start',self.start_body)[0],423)
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def test_page_parameters_keep_original_batch_when_later_draft_changes_and_trash_is_read_only(self):
        status,session=self.call('GET','/session');self.assertEqual(status,200,session)
        self.assertTrue(session['capabilities']['system_pipeline'])
        before=self.w.load(self.sid);draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
            'author':'明确合成网页参数测试','note':'后来草稿不改变已确认原批参数'})
        m=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertTrue(value['automatic_execution_available'])
        self.assertEqual(next(r['value'] for r in value['start']['parameters'] if r['key']=='a06.seed'),7)
        self.assertEqual(next(r['value'] for r in value['batches'][0]['parameters'] if r['key']=='a06.seed'),1)
        self.assertEqual(self.w.load(self.sid),m);self.assertEqual(self.app.tasks.list(self.sid),[])
        self.w.set_trashed(self.sid,True,'明确合成测试','只读原方案')
        m=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertFalse(value['batches'][0]['continue_enabled']);self.assertTrue(value['batches'][0]['continue_blockers'])
        self.assertEqual(self.w.load(self.sid),m)
