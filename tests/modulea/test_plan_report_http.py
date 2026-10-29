"""新报告实际HTTP/worker/下载/追溯验证；GET与页面状态不得伪造人工批准。"""
from pathlib import Path
import http.client,io,json,shutil,tempfile,threading,time,unittest
from unittest.mock import patch
from uuid import uuid4
from docx import Document
from modulea.core.kernel import full_workflow
from modulea.core import plan_reports as report
from tests.modulea import test_plan_report_payload as fixture
from tests.modulea import test_plan_creation_http as http_fixture


class PlanReportHttpTests(unittest.TestCase):
    call=http_fixture.PlanCreationHttpTests.call
    close=http_fixture.PlanCreationHttpTests.close
    @classmethod
    def setUpClass(cls):fixture.PlanReportPayloadTests.setUpClass.__func__(cls)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='report_http_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);folder,self.sid=self.cases[True];shutil.copytree(folder,self.root,dirs_exist_ok=True)
        self.w=full_workflow(self.root)
        from modulea.api.server import create_server
        from modulea.config import Settings
        settings=Settings(data_root=self.root,runtime_dir=self.root/'rt',science_rscript=self.root/'forbidden_Rscript.exe')
        self.server,self.app=create_server(settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/reports'

    def body(self):
        value=report.info(self.w,self.sid)
        return {key:value[key] for key in ('expected_report_run_id','expected_input_hash')}|{
            'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成HTTP报告测试','note':'原统计和评分不重算，仅本批报告','confirmed':True}

    def test_actual_worker_download_trace_and_no_human_review(self):
        before=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertTrue(value['enabled']);self.assertEqual(self.w.load(self.sid),before)
        status,module=self.call('GET',f'/studies/{self.sid}/modules/A07');self.assertEqual(status,200,module)
        self.assertEqual(module['state']['code'],'ready');self.assertIsNotNone(module['plan_reports'])
        status,value=self.call('POST',self.path+'/generate',self.body());self.assertEqual(status,202,value)
        tid=value['task']['task_id'];deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            task=self.app.tasks.get(tid)
            if task['state'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(task['state'],'succeeded',self.app.tasks.log(tid))
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertEqual(len(value['history']),1)
        item=value['history'][0];self.assertTrue(item['active']);self.assertFalse(item['approved'])
        for entry in item['downloads']:
            connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
            connection.request('GET',entry['url']);response=connection.getresponse();raw=response.read();connection.close()
            self.assertEqual(response.status,200);document=Document(io.BytesIO(raw));text='\n'.join(row.text for row in document.paragraphs)
            self.assertIn('用途：流程测试',text);self.assertIn('交集为空',text)
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertEqual(len(trace['plan_decisions']['report_requests']),1);self.assertEqual(len(trace['plan_decisions']['report_receipts']),1)
        module=next(row for row in trace['modules'] if row['module_id']=='A07')
        self.assertEqual(module['parent_review_ids'],{});self.assertEqual(len(module['parent_validation_records']),4)
        self.assertEqual(module['execution_authority'],'system_validation')
        self.assertTrue(any(row.get('role')=='plan_report_figure_index' for row in trace['files']))
        self.assertEqual(self.w.load(self.sid)['reviews'],before['reviews'])

    def test_security_fields_stale_busy_trash_reject_without_task(self):
        body=self.body()
        self.assertEqual(self.call('POST',self.path+'/generate',body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/generate',body,True,'https://untrusted.example')[0],403)
        for value in ({'confirmed':False},{'passed':True},{'path':'outside'},{'conclusion':'invented'}):
            with self.subTest(value=value):self.assertEqual(self.call('POST',self.path+'/generate',body|value)[0],422)
        self.assertEqual(self.call('POST',self.path+'/generate',body|{'expected_input_hash':'old'})[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'synthetic_active'}):
            self.assertEqual(self.call('POST',self.path+'/generate',body)[0],409)
        self.w.set_trashed(self.sid,True,'明确合成测试','只读保护')
        self.assertEqual(self.call('POST',self.path+'/generate',body)[0],423)
        self.assertEqual(self.app.tasks.list(self.sid),[])
