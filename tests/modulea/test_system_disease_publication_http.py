"""疾病原件发布候选的实际HTTP/独立科学worker；不请求真实网络来源。"""
import json,shutil,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from modulea.api.server import create_server
from modulea.api.system_disease_acquisition import info
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from modulea.core import system_disease_publication as publication
from tests.modulea import test_system_disease_acquisition as fixture,test_system_acquisition_http as http_fixture


class SystemDiseasePublicationHttpTests(unittest.TestCase):
    call=http_fixture.SystemAcquisitionHttpTests.call
    wait_task=http_fixture.SystemAcquisitionHttpTests.wait_task

    def close(self):
        """只等待本测试的启动器释放日志，任务终态不代表进程已退出。"""
        self.server.shutdown();self.server.server_close();self.thread.join()
        names={'modulea-reap-'+task['task_id'] for task in self.app.tasks.list(self.sid)}
        for thread in threading.enumerate():
            if thread.name in names:
                thread.join(30)
                self.assertFalse(thread.is_alive(),'本测试科学启动器未退出，不能清理仍使用的临时目录')

    @classmethod
    def setUpClass(cls):
        cls.fixture=fixture.SystemDiseaseAcquisitionTests();cls.fixture.setUp();cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.stage_manual();cls.fixture.body=cls.fixture.request()
        with patch.object(fixture.science,'fetch_source',side_effect=fixture.synthetic_source):cls.fixture.execute()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='disease_publication_http_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.fixture.root,self.root)
        self.sid=self.fixture.sid;self.w=full_workflow(self.root)
        self.settings=Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'rt')
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/disease-acquisition'
        self.body=publication.info(self.w,self.w.load(self.sid),self.fixture.body['request_id'])['request']|{
            'request_id':'diseasepublishreq_'+uuid4().hex,'author':'明确合成发布HTTP测试',
            'note':'完整原件实际整理；候选不是标准化集合或人工批准','confirmed':True}

    def test_real_http_and_worker_publish_once_keep_originals_and_never_approve_or_start_downstream(self):
        before=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertTrue(value['requests'][0]['publication']['enabled']);self.assertEqual(self.w.load(self.sid),before)
        status,value=self.call('GET','/session');self.assertEqual(status,200,value);self.assertTrue(value['capabilities']['system_disease_publication'])
        for iteration in range(2):
            status,value=self.call('POST',self.path+'/publish',self.body);self.assertEqual(status,202,value)
            task=self.wait_task(value['task']['task_id']);self.assertEqual(task['state'],'succeeded',self.app.tasks.log(task['task_id']))
            m=self.w.load(self.sid);self.assertEqual(len(m['runs']),len(before['runs'])+1)
            if not iteration:current=dict(m['current'])
            else:self.assertEqual(m['current'],current)
            self.assertEqual(m['reviews'],[]);self.assertEqual(set(m['current']),{'A00','A02'})
            self.assertFalse(self.w.approved(m,m['current']['A02']));self.assertTrue(self.w.result(m,m['current']['A02'])['summary']['handoff_blocked'])
        status,value=self.call('GET',self.path);pub=value['requests'][0]['publication']
        self.assertEqual(status,200,value);self.assertFalse(pub['enabled']);self.assertEqual(pub['candidate_count_text_zh'],'5')
        self.assertEqual(pub['published_run_id'],m['current']['A02']);self.assertNotIn('尚未发布',value['requests'][0]['message_zh'])
        self.assertTrue(all('未发布疾病候选' not in row['reason_zh'] for row in value['requests'][0]['display_sources']))
        self.assertFalse(value['requests'][0]['retry_enabled']);self.assertNotIn('人工意见已改变','；'.join(value['requests'][0]['retry_blockers']))
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        a02=next(row for row in trace['modules'] if row['module_id']=='A02');self.assertIn('acquisition_record',a02);self.assertNotIn('batch_file',a02)

    def test_token_origin_strict_fields_stale_busy_and_trash_do_not_publish(self):
        before=self.w.load(self.sid)
        self.assertEqual(self.call('POST',self.path+'/publish',self.body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/publish',self.body,True,'https://untrusted.example')[0],403)
        for change in ({'confirmed':False},{'path':'outside'},{'passed':True},{'datasets':[]},{'disease_term':'other'}):
            self.assertEqual(self.call('POST',self.path+'/publish',self.body|change)[0],422,change)
        self.assertEqual(self.call('POST',self.path+'/publish',self.body|{'expected_input_hash':'stale'})[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'explicit_synthetic_busy'}):
            self.assertEqual(self.call('POST',self.path+'/publish',self.body)[0],409)
            status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertFalse(value['requests'][0]['publication']['enabled'])
        self.assertEqual(self.app.tasks.list(self.sid),[]);self.assertEqual(self.w.load(self.sid),before)
        self.w.set_trashed(self.sid,True,'明确合成发布HTTP测试','回收站保护')
        self.assertEqual(self.call('POST',self.path+'/publish',self.body)[0],423)

    def test_http_only_queues_without_science_and_new_plan_rejects_unpublished_old_request(self):
        before=self.w.load(self.sid)
        with patch.object(self.app.tasks,'submit',return_value=({'task_id':'task_synthetic','state':'queued'},True)) as submit,\
                patch('modulea.core.system_validation.canonical_validator',side_effect=AssertionError('HTTP不做科学整理')):
            self.assertEqual(self.call('POST',self.path+'/publish',self.body)[0],202)
        self.assertEqual(submit.call_args.args,(self.sid,'plan_system_disease_publication',self.body['author'],self.body))
        self.assertEqual(self.w.load(self.sid),before);draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
            'author':'明确合成发布HTTP测试','note':'新方案不能偷用旧发布确认'})
        self.assertEqual(self.call('POST',self.path+'/publish',self.body)[0],409)

    def test_real_worker_checks_queued_human_pause_before_publishing(self):
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/publish',self.body)
        self.assertEqual(status,202,value);tid=value['task']['task_id'];m=self.w.load(self.sid)
        self.w.review(self.sid,m['current']['A00'],'pending','明确合成发布HTTP测试','排队后暂停')
        held=self.w.load(self.sid);self.app.tasks._spawn(tid,Path(self.app.tasks._raw(tid)['log_path']))
        self.assertEqual(self.wait_task(tid)['state'],'failed');self.assertEqual(self.w.load(self.sid),held)

    def test_new_upload_after_queue_is_rechecked_in_real_worker(self):
        from intake_sources import stage
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/publish',self.body)
        self.assertEqual(status,202,value);tid=value['task']['task_id'];m=self.w.load(self.sid)
        source=fixture.synthetic_source('GeneCards',self.w.result(m,m['current']['A00'])['summary'])[0]
        stage(self.w,self.sid,m['current']['A00'],source);changed=self.w.load(self.sid)
        self.app.tasks._spawn(tid,Path(self.app.tasks._raw(tid)['log_path']))
        self.assertEqual(self.wait_task(tid)['state'],'failed');self.assertEqual(self.w.load(self.sid),changed)

    def test_original_corruption_after_queue_fails_real_worker_without_publishing(self):
        from modulea.core import system_disease_acquisition as acquisition
        from storage import verified_file
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/publish',self.body)
        self.assertEqual(status,202,value);tid=value['task']['task_id'];before=self.w.load(self.sid)
        record=acquisition.read_record(self.w,before,before[acquisition.RECORDS][-1],kind='record')
        path=verified_file(self.w.location(self.sid),record['sources'][0]['archive']);path.write_bytes(path.read_bytes()+b'corrupt')
        self.app.tasks._spawn(tid,Path(self.app.tasks._raw(tid)['log_path']))
        self.assertEqual(self.wait_task(tid)['state'],'failed');self.assertEqual(self.w.load(self.sid),before)

    def test_missing_and_failed_sources_never_expose_publication_or_fabricate_candidate_zero(self):
        from contracts import ContractError
        source=fixture.SystemDiseaseAcquisitionTests();source.setUp();self.addCleanup(source.doCleanups)
        def fetch(db,summary):
            if db=='TTD':raise ContractError('明确合成TTD失败')
            return fixture.synthetic_source(db,summary,empty=db=='OTP')
        with patch.object(fixture.science,'fetch_source',side_effect=fetch):source.execute()
        before=source.w.load(source.sid)
        app=SimpleNamespace(kernel=SimpleNamespace(workflow=lambda:source.w),tasks=SimpleNamespace(active_for=lambda sid:None))
        value=info(app,None,source.sid);pub=value['requests'][0]['publication']
        self.assertFalse(pub['enabled']);self.assertIsNone(pub['published_run_id']);self.assertEqual(pub['candidate_count_text_zh'],'尚未发布')
        self.assertEqual(source.w.load(source.sid),before)
