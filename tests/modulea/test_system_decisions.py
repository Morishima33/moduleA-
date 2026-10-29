"""同批真实系统受体选择与固定范围，无人工选择批准和伪父签名。"""
from copy import deepcopy
import csv,io,json
from pathlib import Path
import shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from modulea.core.kernel import full_workflow
from modulea.core import system_execution as execution,system_decisions as decisions
from modulea.core.trace_export import build_trace,trace_csv
from tests.modulea import plan_report_fixture as fixture
from tests.modulea.plan_report_nonempty_fixture import string_response
from science_modules.a04 import plan_flow as network


class SystemDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempbase=tempfile.TemporaryDirectory(prefix='system_decisions_base_');cls.addClassCleanup(cls.tempbase.cleanup)
        cls.base=Path(cls.tempbase.name)/'data';w,cls.sid,_,_=fixture.prepare(cls.base,modern=True,multiple_targets=True,stop_before_normalization=True)
        info=execution.info(w,cls.sid)
        batch=w.start_analysis_plan_system_batch(cls.sid,{k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成测试','note':'同批系统范围测试，不是人工复核','confirmed':True})
        cls.batch_id=batch['batch_id']
        for stage in ('A01','A02','A03','A03_SELECT','A04'):
            body={'batch_id':cls.batch_id,'stage':stage,'expected_current_run_id':w.load(cls.sid)['current'].get(stage)}
            if stage=='A04':
                with patch.object(network,'request',side_effect=string_response):w.execute_analysis_plan_system_stage(cls.sid,body)
            else:w.execute_analysis_plan_system_stage(cls.sid,body)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_decisions_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root);self.before=self.w.load(self.sid)

    def execute(self,stage):
        return self.w.execute_analysis_plan_system_decision(self.sid,{'batch_id':self.batch_id,'stage':stage,'expected_decision_id':None})

    def test_actual_selection_and_fixed_scope_keep_unapproved_sources_and_no_fake_reviews(self):
        selection=self.execute('A04_SELECTION');fixed=self.execute('A06_INPUT');m=self.w.load(self.sid)
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertEqual(m['current'],self.before['current'])
        self.assertNotIn('analysis_plan_selection_reviews',m)
        self.assertTrue(decisions.active(self.w,m,selection));self.assertTrue(decisions.active(self.w,m,fixed))
        self.assertEqual(selection['payload']['actual_count'],1);packet=fixed['payload']
        self.assertEqual(packet['human_reviews'],{});self.assertFalse(packet['human_review_written'])
        self.assertEqual(len(packet['validation_records']),4);self.assertEqual(packet['pair_count'],2)
        self.assertEqual(packet['receptors'],selection['payload']['selected'])
        self.assertFalse(packet['replacement_after_preparation_failure']);self.assertFalse(packet['execution_available'])
        for module in ('A03','A03_SELECT','A04'):self.assertFalse(self.w.approved(m,m['current'][module]))
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['system_decisions']),2)
        self.assertEqual(trace['plan_decisions']['selection_reviews'],[])
        rows=list(csv.DictReader(io.StringIO(trace_csv(trace).decode('utf-8-sig'))))
        exported=[r for r in rows if r['table_name'].startswith('system_decision.')]
        self.assertTrue(exported);self.assertTrue(all(r['run_id']=='' for r in exported))
        receptor_rows=[json.loads(r['record_json']) for r in exported if r['table_name']==f"system_decision.{fixed['decision_id']}.receptors"]
        self.assertEqual(receptor_rows,packet['receptors'])

    def test_idempotence_read_only_info_and_client_science_overrides_rejected(self):
        first=self.execute('A04_SELECTION');before=self.w.load(self.sid)
        from science_modules.a06 import system_input as science
        with patch.object(science,'facts',side_effect=AssertionError('幂等不得计算')):
            duplicate=self.execute('A04_SELECTION');self.assertFalse(duplicate['created']);self.assertEqual(duplicate['decision_id'],first['decision_id'])
        decisions.info(self.w,self.sid,self.batch_id);self.assertEqual(self.w.load(self.sid),before)
        for extra in ({'selected':[]},{'approved':True},{'path':'other'},{'parameters':{}},{'selection_review_id':'fake'}):
            with self.subTest(extra=extra),self.assertRaises(ContractError):
                self.w.execute_analysis_plan_system_decision(self.sid,{'batch_id':self.batch_id,'stage':'A06_INPUT','expected_decision_id':None}|extra)
        self.assertEqual(self.w.load(self.sid),before)

    def test_original_batch_plan_survives_new_draft_during_selection(self):
        from science_modules.a04 import selection_flow
        original=selection_flow.select_from_network;called=[]
        def choose(*args):
            if not called:
                called.append(True);draft=self.w.analysis_plan_info(self.sid)['draft']
                self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],
                    'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.receptor_count':2}},
                    'author':'明确合成测试','note':'原系统批次保持'})
            return original(*args)
        with patch.object(selection_flow,'select_from_network',side_effect=choose):selection=self.execute('A04_SELECTION')
        fixed=self.execute('A06_INPUT');self.assertEqual(fixed['payload']['receptors'],selection['payload']['selected'])
        self.assertEqual(selection['payload']['requested_count'],15)
        self.assertEqual(fixed['binding']['plan_file'],selection['binding']['plan_file'])

    def test_human_hold_during_choice_blocks_publication_and_preserves_failure(self):
        from science_modules.a04 import selection_flow
        original=selection_flow.select_from_network;called=[]
        def choose(*args):
            if not called:
                called.append(True);self.w.review(self.sid,self.before['current']['A04'],'pending','明确合成测试','选择期间暂存')
            return original(*args)
        with patch.object(selection_flow,'select_from_network',side_effect=choose),self.assertRaises(ContractError):self.execute('A04_SELECTION')
        m=self.w.load(self.sid);self.assertEqual(m.get(decisions.INDEX,[]),[])
        trace=build_trace(self.w,self.sid,include_data=True);failure=trace['plan_decisions']['system_decision_failures'][-1]
        self.assertEqual(failure['state'],'failed');self.assertTrue(failure['error_zh'])

    def test_missing_selection_and_trash_are_not_implicit_permission(self):
        with self.assertRaisesRegex(ContractError,'系统受体选择'):self.execute('A06_INPUT')
        self.w.set_trashed(self.sid,True,'明确合成测试','回收站只读')
        with self.assertRaises(ContractError):self.execute('A04_SELECTION')

    def test_all_na_uses_exact_fixed_pairs_without_rank_replacement_or_zero(self):
        from science_modules.a06.system_input import pair_statuses
        self.execute('A04_SELECTION');packet=self.execute('A06_INPUT')['payload']
        compounds={r['compound_id']:{'state':'ready','reason_zh':''} for r in packet['compounds']}
        receptors={r['target_id']:{'state':'NA','reason_zh':'明确合成来源尚无可用结构'} for r in packet['receptors']}
        rows=pair_statuses(packet,compounds,receptors)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['state']=='NA' and r['score'] is None and r['reason_zh'] for r in rows))
        bad=deepcopy(packet);bad['receptors']=[]
        with self.assertRaises(ContractError):pair_statuses(bad,compounds,receptors)

    def test_downstream_system_decisions_invalidate_after_explicit_source_hold(self):
        selection=self.execute('A04_SELECTION');fixed=self.execute('A06_INPUT')
        self.w.review(self.sid,self.before['current']['A03_SELECT'],'rejected','明确合成测试','退回本批成分名单')
        m=self.w.load(self.sid);self.assertTrue(decisions.active(self.w,m,selection));self.assertFalse(decisions.active(self.w,m,fixed))
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['system_decisions']),2)

    def test_implementation_change_during_choice_cannot_archive_new_code_as_old_calculation(self):
        from science_modules.a06 import system_input as science
        implementation=Path(self.temp.name)/'explicit_test_implementation.py';implementation.write_bytes(b'# explicit synthetic v1\n')
        original=science.facts
        def calculate(*args):
            value=original(*args);implementation.write_bytes(b'# explicit synthetic changed\n');return value
        with patch.object(science,'implementation_files',return_value=[implementation]),patch.object(science,'facts',side_effect=calculate):
            with self.assertRaisesRegex(ContractError,'实现源码已改变'):self.execute('A04_SELECTION')
        m=self.w.load(self.sid);self.assertEqual(m.get(decisions.INDEX,[]),[])
        self.assertEqual(m['reviews'],self.before['reviews'])
