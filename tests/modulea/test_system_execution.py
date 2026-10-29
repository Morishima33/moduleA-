"""真实系统证据交接A01/A03，不覆盖approved或生成伪人工复核；仅隔离合成原件。"""
from copy import deepcopy
from pathlib import Path
import shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from modulea.core.kernel import full_workflow
from modulea.core import system_execution as system
from modulea.core import system_validation
from modulea.core.trace_export import build_trace
from tests.modulea import plan_report_fixture as fixture


class SystemExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=tempfile.TemporaryDirectory(prefix='system_execution_base_');cls.addClassCleanup(cls.base.cleanup)
        cls.source=Path(cls.base.name)/'data';_,cls.sid,_,_=fixture.prepare(cls.source,modern=True,multiple_targets=True)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_execution_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.source,self.root);self.w=full_workflow(self.root)
        self.before=self.w.load(self.sid);value=system.info(self.w,self.sid)
        self.request={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成系统执行测试','note':'一次明确技术批次授权，不是人工科学批准','confirmed':True}

    def start(self):
        self.batch=self.w.start_analysis_plan_system_batch(self.sid,self.request);return self.batch

    def execute(self,module):
        return self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':self.batch['batch_id'],'stage':module,
            'expected_current_run_id':self.w.load(self.sid)['current'].get(module)})

    def test_real_unreviewed_a01_enters_a03_via_actual_system_evidence(self):
        self.start();a01=self.execute('A01');m=self.w.load(self.sid)
        self.assertTrue(self.w.active(m,a01['run_id']));self.assertFalse(self.w.approved(m,a01['run_id']))
        a03=self.execute('A03');m=self.w.load(self.sid)
        self.assertEqual(a03['summary']['交集靶点数'],5);self.assertFalse(self.w.approved(m,a03['run_id']))
        self.assertEqual(m['reviews'],self.before['reviews'])
        for result,count in ((a01,1),(a03,2)):
            run=self.w.run(m,result['run_id']);self.assertEqual(run['execution_protocol'],system.VERSION)
            self.assertEqual(run['parent_review_ids'],{});self.assertEqual(len(run['parent_validation_records']),count)
            for ref in run['parent_validation_records'].values():self.assertTrue(system_validation.read_receipt(self.w,m,ref)['passed'])
        trace=build_trace(self.w,self.sid,include_data=True)
        self.assertEqual(len(trace['plan_decisions']['system_batches']),1);self.assertEqual(len(trace['plan_decisions']['system_batch_events']),2)
        self.assertFalse(system.info(self.w,self.sid)['automatic_execution_available'])

    def test_one_confirmation_stage_idempotence_and_no_science_on_reads(self):
        before=self.w.load(self.sid);system.info(self.w,self.sid);self.assertEqual(before,self.w.load(self.sid))
        first=self.start();duplicate=self.w.start_analysis_plan_system_batch(self.sid,self.request)
        self.assertFalse(duplicate['created']);self.assertEqual(first['batch_id'],duplicate['batch_id'])
        body={'batch_id':first['batch_id'],'stage':'A01','expected_current_run_id':before['current']['A01']}
        result=self.w.execute_analysis_plan_system_stage(self.sid,body);m=self.w.load(self.sid)
        with patch('modulea.core.system_execution_science.a01',side_effect=AssertionError('幂等不能重复计算')):
            self.assertEqual(self.w.execute_analysis_plan_system_stage(self.sid,body),result)
        self.assertEqual(self.w.load(self.sid),m)

    def test_new_draft_during_computation_does_not_replace_bound_batch(self):
        self.start();saved=[]
        from science_modules.a01 import plan_flow
        original=plan_flow.facts
        def calculate(*args):
            if not saved:
                saved.append(self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,
                    'expected_a00':self.request['expected_a00'],'expected_draft_id':self.request['expected_plan_id'],
                    'specification':{'mode':'personalized','parameters':{'a06.seed':7}},'author':'明确合成测试','note':'运行中追加新草稿，旧批继续'})['draft'])
            return original(*args)
        with patch.object(plan_flow,'facts',side_effect=calculate):a01=self.execute('A01')
        a03=self.execute('A03');m=self.w.load(self.sid)
        self.assertTrue(saved);self.assertNotEqual(saved[0]['plan_id'],self.request['expected_plan_id'])
        for result in (a01,a03):self.assertEqual(self.w.run(m,result['run_id'])['inputs']['analysis_plan_id'],self.request['expected_plan_id'])

    def test_explicit_human_hold_vetoes_even_new_passed_canonical_receipt(self):
        self.start();a01=self.execute('A01');a03=self.execute('A03');m=self.w.load(self.sid)
        self.w.review(self.sid,a01['run_id'],'pending','明确合成测试','明确暂存，不允许系统覆盖')
        expected=system_validation.request(self.w,self.sid,a01['run_id'])
        checked=self.w.validate_analysis_plan_scientific_run(self.sid,{key:expected[key] for key in ('expected_run_id','expected_input_hash')}|
            {'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(checked['passed']);self.assertFalse(self.w.active(self.w.load(self.sid),a03['run_id']))
        with self.assertRaises(ContractError):self.execute('A03')

    def test_unknown_fields_stale_input_unsupported_stage_and_trash_reject(self):
        for changes in ({'confirmed':False},{'passed':True},{'path':'outside'},{'parameters':{}},{'expected_input_hash':'old'}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):
                self.w.start_analysis_plan_system_batch(self.sid,self.request|changes)
        self.assertEqual(self.w.load(self.sid),self.before);self.start()
        with self.assertRaises(ContractError):self.execute('A04')
        self.w.set_trashed(self.sid,True,'明确合成测试','回收站保护')
        with self.assertRaises(ContractError):self.execute('A01')

    def test_caller_fake_validator_cannot_publish_forged_scientific_summary(self):
        self.start();from modulea.core import system_execution_science as science
        original=science.a01
        def forged(*args):
            values=list(original(*args));values[2]=dict(values[2],标准化基因数=999);return tuple(values)
        self.w.validators['A01']=lambda *args:None
        with patch.object(science,'a01',side_effect=forged),self.assertRaises(ContractError):self.execute('A01')
        m=self.w.load(self.sid);self.assertEqual(m['current'],self.before['current'])
        self.assertEqual(m['reviews'],self.before['reviews'])
        trace=build_trace(self.w,self.sid,include_data=True);events=trace['plan_decisions']['system_batch_events']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['state'],'failed');self.assertIsNone(events[0]['run_id'])
        self.assertTrue(any(row['role']=='unpublished_system_run' for row in events[0]['files']))
