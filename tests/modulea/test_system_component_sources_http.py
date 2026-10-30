"""真实HTTP及科学worker绑定三库原件；不上传、审批或发布科学A01。"""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from modulea.core import system_component_sources as sources
from tests.modulea import test_system_acquisition_http as fixture


class SystemComponentSourcesHttpTests(unittest.TestCase):
    call=fixture.SystemAcquisitionHttpTests.call
    close=fixture.SystemAcquisitionHttpTests.close
    wait_task=fixture.SystemAcquisitionHttpTests.wait_task

    @classmethod
    def setUpClass(cls):fixture.SystemAcquisitionHttpTests.setUpClass.__func__(cls)

    def setUp(self):
        fixture.SystemAcquisitionHttpTests.setUp(self)
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        bind=value['requests'][0]['binding'];self.assertTrue(bind['enabled']);self.assertFalse(bind['bound'])
        self.bind_body={**bind['request'],'request_id':'systemsourcebindreq_'+uuid4().hex,'author':'明确合成绑定HTTP测试',
            'note':'只绑定科学输入，不发布结果或批准','confirmed':True}

    def test_actual_http_worker_binding_and_identical_retry_preserve_old_scientific_state(self):
        before=self.w.load(self.sid);status,value=self.call('POST',self.path+'/bind',self.bind_body)
        self.assertEqual(status,202,value);task=self.wait_task(value['task']['task_id'])
        self.assertEqual(task['state'],'succeeded',self.app.tasks.log(task['task_id']))
        m=self.w.load(self.sid);self.assertEqual(m['current'],before['current']);self.assertEqual(m['runs'],before['runs'])
        self.assertEqual(m['reviews'],before['reviews']);self.assertNotIn('current_component_uploads',m)
        self.assertEqual(len(m[sources.INDEX]),1);sources.read_record(self.w,m,m[sources.CURRENT])
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertTrue(value['requests'][0]['binding']['bound']);self.assertFalse(value['requests'][0]['binding']['enabled'])
        self.assertEqual(self.w.load(self.sid),m)
        status,value=self.call('POST',self.path+'/bind',self.bind_body);self.assertEqual(status,202,value)
        self.assertEqual(self.wait_task(value['task']['task_id'])['state'],'succeeded');self.assertEqual(self.w.load(self.sid),m)
        status,value=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,value)
        self.assertEqual(len(value['plan_decisions']['system_component_sources']),1)

    def test_bind_preflight_security_stale_busy_trash_only_queue_and_no_science_in_http(self):
        before=self.w.load(self.sid)
        self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body,True,'https://untrusted.example')[0],403)
        for change in ({'confirmed':False},{'path':'outside'},{'passed':True},{'ob_min':0}):
            self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body|change)[0],422,change)
        for field in ('expected_input_hash','expected_record_sha256'):
            self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body|{field:'stale'})[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'explicit_synthetic_busy'}):
            self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body)[0],409)
        with patch.object(self.app.tasks,'submit',return_value=({'task_id':'task_synthetic','state':'queued'},True)),\
                patch('science_modules.a01.system_source_binding.materialize',side_effect=AssertionError('HTTP不可解包')):
            self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body)[0],202)
        self.assertEqual(self.w.load(self.sid),before);self.assertEqual(self.app.tasks.list(self.sid),[])
        self.w.set_trashed(self.sid,True,'明确合成绑定HTTP测试','回收站保护')
        self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body)[0],423)

    def test_actual_worker_rechecks_hold_after_queue_before_materializing(self):
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path+'/bind',self.bind_body)
        self.assertEqual(status,202,value);tid=value['task']['task_id'];m=self.w.load(self.sid)
        self.w.review(self.sid,m['current']['A00'],'pending','明确合成绑定HTTP测试','排队后暂停登记')
        held=self.w.load(self.sid);self.app.tasks._spawn(tid,Path(self.app.tasks._raw(tid)['log_path']))
        self.assertEqual(self.wait_task(tid)['state'],'failed');self.assertEqual(self.w.load(self.sid),held)
        self.assertNotIn(sources.CURRENT,held)

    def test_later_plan_disables_binding_without_new_artifacts(self):
        before=self.w.load(self.sid);draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},
            'author':'明确合成绑定HTTP测试','note':'原获取门槛不冒充新门槛'})
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertFalse(value['requests'][0]['binding']['enabled']);self.assertFalse(value['requests'][0]['binding']['bound'])
        self.assertEqual(self.call('POST',self.path+'/bind',self.bind_body)[0],409)
        self.assertNotIn(sources.INDEX,self.w.load(self.sid))

    def test_partial_acquisition_cannot_bind_or_hide_missing_library(self):
        from contracts import ContractError
        from modulea.core import system_acquisition as acquisition
        from tests.modulea import test_system_acquisition as raw_fixture
        value=acquisition.info(self.w,self.sid);body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systemacqreq_'+uuid4().hex,'author':'明确合成缺库绑定测试','note':'缺库不能当完整','confirmed':True}
        def partial(db,*args,**kwargs):
            if db=='HERB':raise ContractError('明确合成HERB失败')
            return raw_fixture.synthetic_source(db,*args,**kwargs)
        with patch.object(raw_fixture.collection,'acquire_for_plan',side_effect=partial):
            self.w.acquire_analysis_plan_system_a01_sources(self.sid,body)
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        row=next(r for r in value['requests'] if r['request_id']==body['request_id'])
        self.assertEqual(row['state'],'partial_failure');self.assertFalse(row['binding']['enabled'])
        attempt={**self.bind_body,**row['binding']['request'],'request_id':'systemsourcebindreq_'+uuid4().hex}
        before=self.w.load(self.sid);self.assertEqual(self.call('POST',self.path+'/bind',attempt)[0],409)
        self.assertEqual(self.w.load(self.sid),before);self.assertNotIn(sources.INDEX,before)
