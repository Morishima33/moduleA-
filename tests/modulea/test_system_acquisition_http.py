"""真实本机HTTP及独立worker复用合成三库原件；不访问真实来源或研究。"""
import io,json,shutil,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from uuid import uuid4
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from modulea.core import system_acquisition as core
from modulea.tasks.system_acquisition import run
from tests.modulea import test_plan_creation_http as http_fixture,test_system_acquisition as source_fixture


class SystemAcquisitionHttpTests(unittest.TestCase):
    call=http_fixture.PlanCreationHttpTests.call
    close=http_fixture.PlanCreationHttpTests.close

    @classmethod
    def setUpClass(cls):
        cls.fixture=source_fixture.SystemAcquisitionTests();cls.fixture.setUp();cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.w.acquire_analysis_plan_system_a01_sources(cls.fixture.sid,cls.fixture.body,
            opener=source_fixture.OriginalResponseFixture(),sleeper=lambda _:None)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_acquisition_http_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.fixture.root,self.root)
        self.sid=self.fixture.sid;self.body=dict(self.fixture.body);self.w=full_workflow(self.root)
        self.settings=Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'rt')
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/system-acquisition'

    def wait_task(self,tid):
        """只等本测试任务进入终态，超时给出实际日志，不取消其他进程。"""
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            value=self.app.tasks.get(tid)
            if value['state'] not in ('queued','running'):return value
            time.sleep(.1)
        self.fail(self.app.tasks.log(tid))

    def test_actual_http_and_isolated_worker_reuse_complete_without_writing_research(self):
        before=self.w.load(self.sid);status,value=self.call('GET',self.path)
        self.assertEqual(status,200,value);self.assertTrue(value['enabled']);self.assertEqual(value['requests'][0]['state'],'complete')
        self.assertEqual(value['requests'][0]['source_receipt_count'],3);self.assertEqual(self.w.load(self.sid),before)
        status,value=self.call('POST',self.path+'/execute',self.body);self.assertEqual(status,202,value)
        task=self.wait_task(value['task']['task_id']);self.assertEqual(task['state'],'succeeded',self.app.tasks.log(task['task_id']))
        self.assertEqual(self.w.load(self.sid),before)
        self.assertEqual(self.call('GET',self.path)[1]['requests'][0]['record_count'],1)
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertEqual(len(trace['plan_decisions']['system_acquisition_sources']),3)

    def test_security_schema_stale_busy_and_trash_do_not_queue(self):
        before=self.w.load(self.sid)
        self.assertEqual(self.call('POST',self.path+'/execute',self.body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/execute',self.body,True,'https://untrusted.example')[0],403)
        for change in ({'confirmed':False},{'passed':True},{'path':'outside'},{'url':'https://untrusted.example'},{'ob_min':0}):
            self.assertEqual(self.call('POST',self.path+'/execute',self.body|change)[0],422,change)
        new=self.body|{'request_id':'systemacqreq_'+uuid4().hex,'expected_input_hash':'stale'}
        self.assertEqual(self.call('POST',self.path+'/execute',new)[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'explicit_synthetic_busy'}):
            self.assertEqual(self.call('POST',self.path+'/execute',self.body)[0],409)
        self.assertEqual(self.app.tasks.list(self.sid),[]);self.assertEqual(self.w.load(self.sid),before)
        self.w.set_trashed(self.sid,True,'明确合成HTTP测试','验证回收站')
        self.assertEqual(self.call('POST',self.path+'/execute',self.body)[0],423)
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertFalse(value['enabled']);self.assertFalse(value['requests'][0]['retry_enabled'])

    def test_http_submission_only_queues_without_scientific_validation_or_mutation(self):
        status,session=self.call('GET','/session');self.assertEqual(status,200,session)
        self.assertTrue(session['capabilities']['system_acquisition'])
        before=self.w.load(self.sid);task={'task_id':'task_'+uuid4().hex,'state':'queued'}
        with patch.object(self.app.tasks,'submit',return_value=(task,True)) as submit,\
                patch('modulea.core.system_validation.canonical_validator',side_effect=AssertionError('HTTP不得运行科学验证')):
            status,value=self.call('POST',self.path+'/execute',self.body)
        self.assertEqual(status,202,value);self.assertEqual(self.w.load(self.sid),before)
        self.assertEqual(submit.call_args.args,(self.sid,'plan_system_acquisition',self.body['author'],self.body))

    def test_later_draft_changes_new_request_but_original_explicit_retry_is_pinned(self):
        before=self.w.load(self.sid);draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},
            'author':'明确合成HTTP测试','note':'新草稿不替换旧获取请求'})
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertNotEqual(value['expected_plan_id'],self.body['expected_plan_id'])
        self.assertEqual(value['requests'][0]['request'],self.body);self.assertTrue(value['requests'][0]['retry_enabled'])
        self.assertEqual(value['screening_parameters']['ob_min'],45)
        self.assertEqual(value['requests'][0]['screening_parameters']['ob_min'],30)
        status,value=self.call('POST',self.path+'/execute',self.body);self.assertEqual(status,202,value)
        self.assertEqual(self.wait_task(value['task']['task_id'])['state'],'succeeded')
        self.assertEqual(len(self.w.load(self.sid)[core.REQUESTS]),1)

    def test_display_uses_archived_checkpoint_when_no_batch_record_exists(self):
        value=core.info(self.w,self.sid);body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systemacqreq_'+uuid4().hex,'author':'明确合成检查点页面测试','note':'未形成整批不显示完整','confirmed':True}
        def interrupted(db,*args,**kwargs):
            if db=='HERB':raise KeyboardInterrupt('合成中断')
            return source_fixture.synthetic_source(db,*args,**kwargs)
        with patch.object(source_fixture.collection,'acquire_for_plan',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            self.w.acquire_analysis_plan_system_a01_sources(self.sid,body)
        before=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        record=next(r for r in value['requests'] if r['request_id']==body['request_id'])
        self.assertEqual(record['state'],'incomplete');self.assertEqual(record['record_count'],0)
        self.assertEqual(record['source_receipt_count'],1);self.assertEqual(record['display_sources'][0]['database'],'TCMSP')
        self.assertEqual(record['display_sources'][0]['state_label_zh'],'已核验归档');self.assertTrue(record['retry_enabled'])
        self.assertEqual(self.w.load(self.sid),before)

    def test_human_hold_after_queue_is_rechecked_in_actual_worker_before_fetch(self):
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/execute',self.body)
        self.assertEqual(status,202,value);tid=value['task']['task_id']
        m=self.w.load(self.sid);self.w.review(self.sid,m['current']['A00'],'pending','明确合成HTTP测试','排队后暂停')
        held=self.w.load(self.sid);self.app.tasks._spawn(tid,Path(self.app.tasks._raw(tid)['log_path']))
        task=self.wait_task(tid);self.assertEqual(task['state'],'failed',self.app.tasks.log(tid))
        self.assertEqual(self.w.load(self.sid),held)
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertFalse(value['enabled']);self.assertFalse(value['requests'][0]['retry_enabled'])

    def test_partial_scientific_child_result_cannot_be_reported_as_successful_task(self):
        task={'task_id':'task_'+uuid4().hex,'study_id':self.sid,'payload':json.dumps(self.body)}
        def child(command,**kwargs):
            output=Path(command[command.index('--result-file')+1]);output.write_text(json.dumps({'state':'partial_failure',
                'sources':[{'database':'HERB','state':'failed','reason_zh':'明确合成缺库'}]}),encoding='utf8')
            process=Mock();process.stdout=io.StringIO('PROGRESS 合成部分失败\n');process.wait.return_value=0
            process.__enter__=Mock(return_value=process);process.__exit__=Mock(return_value=False)
            return process
        manager=Mock()
        with patch('modulea.tasks.system_acquisition.subprocess.Popen',side_effect=child),self.assertRaisesRegex(ValueError,'不是零结果'):
            run(self.settings,task,manager)
        self.assertFalse(any(call.kwargs.get('progress',{}).get('done')==3 for call in manager.update.call_args_list))
