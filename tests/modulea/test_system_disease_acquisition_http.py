"""疾病获取真实本机HTTP/独立科学worker与缺失失败展示；全部合成原件，不请求真实来源。"""
import json,shutil,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from uuid import uuid4
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from modulea.core import system_disease_acquisition as core
from modulea.api.system_disease_acquisition import info
from modulea.tasks.worker import run_system_disease_acquisition
from tests.modulea import test_system_disease_acquisition as fixture,test_system_acquisition_http as http_fixture


class SystemDiseaseAcquisitionHttpTests(unittest.TestCase):
    call=http_fixture.SystemAcquisitionHttpTests.call
    close=http_fixture.SystemAcquisitionHttpTests.close
    wait_task=http_fixture.SystemAcquisitionHttpTests.wait_task

    @classmethod
    def setUpClass(cls):
        cls.fixture=fixture.SystemDiseaseAcquisitionTests();cls.fixture.setUp();cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.stage_manual();cls.fixture.body=cls.fixture.request()
        with patch.object(fixture.science,'fetch_source',side_effect=fixture.synthetic_source):cls.fixture.execute()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='disease_acquisition_http_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.fixture.root,self.root)
        self.sid=self.fixture.sid;self.body=dict(self.fixture.body);self.w=full_workflow(self.root)
        self.settings=Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'rt')
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/disease-acquisition'

    def test_actual_http_worker_rechecks_complete_originals_without_fetch_or_research_change(self):
        before=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertTrue(value['enabled']);self.assertEqual(value['requests'][0]['state'],'complete')
        self.assertEqual(len(value['requests'][0]['display_sources']),5);self.assertEqual(self.w.load(self.sid),before)
        status,value=self.call('POST',self.path+'/execute',self.body);self.assertEqual(status,202,value)
        task=self.wait_task(value['task']['task_id']);self.assertEqual(task['state'],'succeeded',self.app.tasks.log(task['task_id']))
        self.assertEqual(self.w.load(self.sid),before)
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertEqual(len(trace['plan_decisions']['disease_acquisition_sources']),5)

    def test_token_origin_schema_stale_busy_and_trash_never_queue_or_modify(self):
        before=self.w.load(self.sid)
        self.assertEqual(self.call('POST',self.path+'/execute',self.body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/execute',self.body,True,'https://untrusted.example')[0],403)
        for change in ({'confirmed':False},{'path':'outside'},{'url':'https://untrusted.example'},{'passed':True},{'disease_term':'other'}):
            self.assertEqual(self.call('POST',self.path+'/execute',self.body|change)[0],422,change)
        stale=self.body|{'request_id':'diseaseacqreq_'+uuid4().hex,'expected_input_hash':'stale'}
        self.assertEqual(self.call('POST',self.path+'/execute',stale)[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'explicit_synthetic_busy'}):
            self.assertEqual(self.call('POST',self.path+'/execute',self.body)[0],409)
        self.assertEqual(self.app.tasks.list(self.sid),[]);self.assertEqual(self.w.load(self.sid),before)
        self.w.set_trashed(self.sid,True,'明确合成疾病HTTP测试','回收站保护')
        self.assertEqual(self.call('POST',self.path+'/execute',self.body)[0],423)
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertFalse(value['enabled'])
        self.assertFalse(value['requests'][0]['retry_enabled'])

    def test_http_only_queues_and_later_plan_does_not_replace_original_retry(self):
        status,session=self.call('GET','/session');self.assertEqual(status,200,session)
        self.assertTrue(session['capabilities']['system_disease_acquisition'])
        before=self.w.load(self.sid);draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
            'author':'明确合成疾病HTTP测试','note':'新草稿不替换原获取'})
        m=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertNotEqual(value['expected_plan_id'],self.body['expected_plan_id']);self.assertEqual(value['requests'][0]['request'],self.body)
        with patch.object(self.app.tasks,'submit',return_value=({'task_id':'task_synthetic','state':'queued'},True)) as submit,\
                patch('modulea.core.system_validation.canonical_validator',side_effect=AssertionError('HTTP不做科学校验')):
            self.assertEqual(self.call('POST',self.path+'/execute',self.body)[0],202)
        self.assertEqual(submit.call_args.args,(self.sid,'plan_system_disease_acquisition',self.body['author'],self.body))
        self.assertEqual(self.w.load(self.sid),m)

    def test_real_worker_rechecks_human_pause_after_queue_before_fetch(self):
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/execute',self.body)
        self.assertEqual(status,202,value);tid=value['task']['task_id'];m=self.w.load(self.sid)
        self.w.review(self.sid,m['current']['A00'],'pending','明确合成疾病HTTP测试','排队后暂停')
        held=self.w.load(self.sid);self.app.tasks._spawn(tid,Path(self.app.tasks._raw(tid)['log_path']))
        self.assertEqual(self.wait_task(tid)['state'],'failed');self.assertEqual(self.w.load(self.sid),held)

    def test_incomplete_get_and_worker_keep_missing_failure_and_valid_zero_distinct(self):
        from contracts import ContractError
        source=fixture.SystemDiseaseAcquisitionTests();source.setUp();self.addCleanup(source.doCleanups)
        def fetch(db,summary):
            if db=='TTD':raise ContractError('明确合成TTD失败')
            return fixture.synthetic_source(db,summary,empty=db=='OTP')
        with patch.object(fixture.science,'fetch_source',side_effect=fetch):result=source.execute()
        before=source.w.load(source.sid);app=SimpleNamespace(kernel=SimpleNamespace(workflow=lambda:source.w),tasks=SimpleNamespace(active_for=lambda sid:None))
        value=info(app,None,source.sid);rows={r['database']:r for r in value['requests'][0]['display_sources']}
        self.assertEqual(rows['GeneCards']['state'],'missing');self.assertEqual(rows['TTD']['state'],'failed')
        self.assertEqual(rows['OTP']['records_text_zh'],'0');self.assertEqual(rows['GeneCards']['records_text_zh'],'未取得有效结果')
        self.assertEqual(source.w.load(source.sid),before)
        manager=Mock();workflow=Mock();workflow.acquire_analysis_plan_system_disease_sources.return_value=result
        with patch('modulea.tasks.worker.full_workflow',return_value=workflow),self.assertRaisesRegex(ValueError,'不是0条结果'):
            run_system_disease_acquisition(self.settings,{'study_id':self.sid,'task_id':'task_synthetic','payload':json.dumps(self.body)},manager)
        self.assertFalse(any(c.kwargs.get('progress',{}).get('done')==5 for c in manager.update.call_args_list))
