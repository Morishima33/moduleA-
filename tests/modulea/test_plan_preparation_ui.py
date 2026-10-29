"""新版结构准备入口版本保护、第二版科学调用与明确请求追溯；全部合成研究。"""
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from modulea.api.server import create_server
from modulea.core.kernel import full_workflow
from modulea.core.plan_preparation_ui import info, validate
from modulea.core.trace_export import build_trace
from modulea.tasks.worker import run_task
from science_modules.a06 import plan_preparation_v2
from tests.modulea import test_plan_a04_selection_task as fixture
from tests.modulea import test_plan_creation_http as http


class PlanPreparationUiTests(unittest.TestCase):
    payload=fixture.PlanA04SelectionTaskTests.payload
    review_payload=fixture.PlanA04SelectionTaskTests.review_payload
    a06_payload=fixture.PlanA04SelectionTaskTests.a06_payload
    call=http.PlanCreationHttpTests.call
    close=http.PlanCreationHttpTests.close

    def setUp(self):
        fixture.PlanA04SelectionTaskTests.setUp(self);self.addCleanup(self.temp.cleanup)
        selection=self.workflow.save_analysis_plan_a04_selection(self.sid,self.payload())['record']
        review=self.workflow.review_analysis_plan_a04_selection(self.sid,self.review_payload(selection['selection_id']))['review']
        self.source=self.workflow.save_analysis_plan_a06_preparation_input(self.sid,self.a06_payload(selection,review))['record']
        tools=Path(self.temp.name)/'tools';self.binary=tools/'environments/vina_1.2.7/vina_1.2.7_win.exe'
        self.binary.parent.mkdir(parents=True);self.binary.write_bytes(b'synthetic-vina-placeholder-not-executed')
        self.settings.science_tools_root=tools
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/preparation-ui'

    def request(self):
        value=info(self.workflow,self.sid)
        return {'request_id':'planprep_'+uuid4().hex,'expected_input_id':value['expected_input_id'],
            'expected_preparation_run_id':value['expected_preparation_run_id'],'expected_input_hash':value['input_hash'],
            'author':'隔离测试','note':'合成准备入口测试，不执行真实病例','confirmed':True}

    def test_read_only_parameters_guards_and_tools(self):
        home=self.workflow.location(self.sid);before=(home/'manifest.json').read_bytes()
        status,value=self.call('GET',self.path)
        self.assertEqual(status,200,value);self.assertTrue(value['enabled']);self.assertEqual(value['scope']['pair_count'],4)
        self.assertEqual(value['parameters']['a06.exhaustiveness'],8)
        status,module=self.call('GET',f'/studies/{self.sid}/modules/A06_PREP')
        self.assertEqual(status,200,module);self.assertTrue(module['plan_preparation_ui']['enabled'])
        self.assertEqual((home/'manifest.json').read_bytes(),before);self.assertEqual(self.app.tasks.list(),[])
        request=self.request()
        for change in ({'confirmed':False},{'source':'path'},{'parameters':{'a06.seed':2}}):
            self.assertEqual(self.call('POST',self.path,dict(request,**change))[0],422)
        self.assertEqual(self.call('POST',self.path,request,token=False)[0],403)
        self.assertEqual(self.call('POST',self.path,request,origin='https://untrusted.example')[0],403)
        self.assertEqual(self.call('POST',self.path,dict(request,expected_input_hash='old'))[0],409)
        self.settings.science_tools_root=None
        self.assertFalse(self.call('GET',self.path)[1]['enabled'])
        self.assertEqual(self.call('POST',self.path,request)[0],409)
        self.assertEqual(self.app.tasks.list(),[])


    def test_worker_uses_second_version_archives_confirmation_and_receipt(self):
        """仅替换来源连接和Vina版本检测；实际第二版准备、NA和科学校验完整运行。"""
        request=self.request();before=self.workflow.load(self.sid)
        def connection(root,packet,folder,progress):
            return {'id':'synthetic','files':[],
                'compounds':[{**r,'state':'NA','reason_zh':'合成官方来源失败'} for r in packet['compounds']],
                'receptors':[{**r,'state':'NA','reason_zh':'合成结构来源失败','candidates':[]} for r in packet['receptors']]}
        def scientific_child(settings,task,manager):
            body=json.loads(task['payload'])
            self.assertEqual(set(body),{'request_id','expected_input_id','author','note','confirmed'})
            with patch.object(plan_preparation_v2,'_version',return_value=self.binary),patch.object(plan_preparation_v2,'connect',side_effect=connection):
                result=plan_preparation_v2.run(full_workflow(settings.data_root),task['study_id'],body,settings.science_tools_root,lambda _:None)
            folder=settings.runtime_dir/'a06_plan_preparation_requests'/task['task_id'];folder.mkdir(parents=True)
            (folder/'result.json').write_text(json.dumps({'run_id':result['run_id'],'summary':result['summary']}),encoding='utf8')
            return '第二版合成NA准备已归档'
        with patch.object(self.app.tasks,'_spawn'):
            status,queued=self.call('POST',self.path,request)
        self.assertEqual(status,202,queued)
        with patch('modulea.tasks.worker.run_a06_plan_preparation',side_effect=scientific_child):
            self.assertEqual(run_task(self.settings,queued['task']['task_id']),0)
        w=full_workflow(self.settings.data_root);after=w.load(self.sid)
        result=w.result(after,after['current']['A06_PREP']);run=w.run(after,result['run_id'])
        self.assertEqual(run['config']['version'],'A06.plan_preparation.2')
        self.assertEqual(result['summary']['scored_pairs'],0);self.assertEqual(result['summary']['na_pairs'],4)
        self.assertEqual(after['reviews'],before['reviews']);self.assertNotIn('A06',after['current'])
        self.assertEqual(len(after['analysis_plan_preparation_ui_requests']),1)
        self.assertEqual(len(after['analysis_plan_preparation_ui_receipts']),1)
        self.assertFalse(info(w,self.sid)['enabled']);self.assertFalse(w.approved(after,result['run_id']))
        trace=build_trace(w,self.sid,include_data=True)
        self.assertEqual(trace['plan_decisions']['preparation_requests'][0]['request'],request)
        self.assertEqual(trace['plan_decisions']['preparation_receipts'][0]['run_id'],result['run_id'])

    def test_failed_worker_keeps_request_without_success_receipt(self):
        with patch.object(self.app.tasks,'_spawn'):
            status,queued=self.call('POST',self.path,self.request())
        self.assertEqual(status,202,queued)
        with patch('modulea.tasks.worker.run_a06_plan_preparation',side_effect=ValueError('合成科学工具中断')):
            self.assertEqual(run_task(self.settings,queued['task']['task_id']),1)
        m=self.workflow.load(self.sid)
        self.assertEqual(len(m['analysis_plan_preparation_ui_requests']),1)
        self.assertEqual(m.get('analysis_plan_preparation_ui_receipts',[]),[])

    def test_stale_review_trash_busy_and_request_id_conflicts(self):
        request=self.request();m=self.workflow.load(self.sid);a03=m['current']['A03']
        review=self.workflow.latest_review(m,self.workflow.run(m,a03)['artifact_id'])
        self.workflow.review(self.sid,a03,'pending','隔离测试','撤回合成上游',review['review_id'])
        self.assertEqual(self.call('POST',self.path,request)[0],409)
        self.workflow.set_trashed(self.sid,True,'隔离测试','合成回收站')
        self.assertEqual(self.call('POST',self.path,request)[0],423)
        self.assertEqual(self.app.tasks.list(),[])

    def test_preparation_pointer_busy_retry_and_request_conflicts(self):
        original=self.request()
        ref=self.workflow.begin_analysis_plan_preparation_request(self.sid,original)
        self.assertEqual(self.workflow.begin_analysis_plan_preparation_request(self.sid,original),ref)
        with self.assertRaises(ContractError):
            self.workflow.begin_analysis_plan_preparation_request(self.sid,dict(original,note='同编号不同依据'))
        m=self.workflow.load(self.sid)
        input_ref=m['analysis_plan_a06_input_records'][-1]
        run=self.workflow.begin(self.sid,'A06_PREP',{'a06_plan_input':input_ref},
            plan_preparation_v2.execution_config(self.plan_record['plan']),'合成未完成准备，保留原件')
        self.assertEqual(self.call('POST',self.path,original)[0],409)
        status,value=self.call('GET',self.path)
        self.assertEqual(status,200,value);self.assertEqual(value['expected_preparation_run_id'],run['run_id'])
        self.assertFalse(value['current']['completed']);self.assertTrue(value['enabled'])
        with patch.object(self.app.tasks,'active_for',return_value={'state':'running'}):
            self.assertFalse(self.call('GET',self.path)[1]['enabled'])
            self.assertEqual(self.call('POST',self.path,self.request())[0],409)
        status,view=self.call('GET',f'/studies/{self.sid}/modules/A06_PREP')
        self.assertEqual(status,200,view);self.assertFalse(view['plan_preparation_ui']['current']['completed'])
        self.assertEqual(self.app.tasks.list(),[])


class PlanPreparationNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """已有真实Meeko/合成口袋证据，导航仅读取，不重跑准备或评分。"""
        from tests.modulea.test_reviewable_preparation import ReviewablePreparationTests
        cls.fixture=ReviewablePreparationTests
        cls.fixture.setUpClass();cls.addClassCleanup(cls.fixture.doClassCleanups)

    def test_reference_reviewable_and_scoring_navigation_uses_actual_versions(self):
        w=self.fixture.base.workflow;sid=self.fixture.sid;home=w.location(sid)
        before=(home/'manifest.json').read_bytes();value=info(w,sid)
        self.assertFalse(value['enabled']);self.assertTrue(value['current']['matches_input'])
        steps={r['key']:r for r in value['steps']}
        self.assertTrue(steps['review']['available']);self.assertFalse(steps['scoring']['available'])
        self.assertEqual((home/'manifest.json').read_bytes(),before)
        result=w.publish_analysis_plan_a06_reviewable(sid,{'expected_preparation_run_id':self.fixture.source['run_id'],
            'expected_input_id':self.fixture.base.input_record['input_id'],'request_id':'reviewprep_'+uuid4().hex,
            'reviewer':'隔离测试','note':'仅验证本批导航，不批准或评分','confirmed':True})
        value=info(w,sid);self.assertEqual(value['current']['run_id'],result['run_id'])
        self.assertTrue(value['current']['matches_input']);self.assertFalse(value['current']['approved'])
        self.assertTrue(next(r for r in value['steps'] if r['key']=='scoring')['available'])
        self.assertFalse(w.analysis_plan_a06_scoring_info(sid)['enabled'])
