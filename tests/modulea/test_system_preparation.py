"""无人工批准的真实系统准备；外部几何/来源明确合成，工具与生产规范真实执行。"""
from copy import deepcopy
from pathlib import Path
import os,shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import read_json,verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_validation
from modulea.core.trace_export import build_trace
from science_modules.a06 import plan_preparation_v2 as legacy,system_preparation as science
from tests.modulea import test_system_decisions as upstream
from tests.modulea.plan_report_nonempty_fixture import unavailable_sources
from tests.modulea.plan_report_scoring_fixture import Sources


class SystemPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        upstream.SystemDecisionTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base)
        for stage in ('A04_SELECTION','A06_INPUT'):
            w.execute_analysis_plan_system_decision(cls.sid,{'batch_id':cls.batch_id,'stage':stage,'expected_decision_id':None})
        cls.tools=Path(os.environ.get('MODULEA_A06_TOOLS','D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_preparation_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root)
        self.before=self.w.load(self.sid);self.body={'batch_id':self.batch_id,'stage':'A06_PREP','expected_current_run_id':None}

    def execute(self,**kwargs):
        return self.w.execute_analysis_plan_system_stage(self.sid,self.body,tools=kwargs.pop('tools',self.tools),**kwargs)

    def test_actual_fixed_tool_and_full_na_prepare_without_any_fake_approval(self):
        with patch.object(legacy,'connect',side_effect=unavailable_sources):result=self.execute()
        m=self.w.load(self.sid);run=self.w.run(m,result['run_id']);home=self.w.location(self.sid)
        self.assertFalse(self.w.approved(m,result['run_id']));self.assertTrue(self.w.active(m,result['run_id']))
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertEqual(run['parent_review_ids'],{})
        self.assertEqual(set(run['parent_validation_records']),{'A03','A03_SELECT','A04'})
        self.assertEqual(result['summary']['pair_count'],2);self.assertEqual(result['summary']['na_pairs'],2)
        self.assertTrue(all(r['score'] is None and r['state']=='NA' and r['reason_zh'] for r in result['tables']['planned_pairs']))
        fact=read_json(verified_file(home,run['inputs']['preparation_fact']))
        self.assertEqual(fact['vina_version_stdout'],'AutoDock Vina v1.2.7');self.assertFalse(fact['human_review_written'])
        self.assertNotIn('analysis_plan_a06_input_records',m)
        expected=system_validation.request(self.w,self.sid,result['run_id'])
        receipt=self.w.validate_analysis_plan_scientific_run(self.sid,{k:expected[k] for k in ('expected_run_id','expected_input_hash')}|
            {'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(receipt['passed']);self.assertFalse(receipt['scientific_status']['ready_for_successor'])
        from science_modules.a07.plan_payload import build
        payload=build(self.w,self.sid);self.assertEqual(payload['docking']['counts']['NA'],2)
        self.assertFalse(payload['completion']['all_applicable_finished'])

    def test_actual_meeko_and_two_prediction_files_do_not_auto_upgrade_unconfirmed_pocket(self):
        source=Sources()
        with patch.object(legacy,'connect',side_effect=source.connect),patch.object(legacy,'prepare',side_effect=source.prepare):result=self.execute()
        m=self.w.load(self.sid);run=self.w.run(m,result['run_id']);home=self.w.location(self.sid)
        fact=read_json(verified_file(home,run['inputs']['preparation_fact']))
        self.assertEqual(fact['compounds'][0]['state'],'ready');self.assertEqual(fact['compounds'][1]['state'],'NA')
        receptor=fact['receptors'][0];self.assertEqual(receptor['state'],'NA');self.assertEqual(receptor['quality'],'待核查')
        prediction=receptor['attempts'][0]['evidence']['predicted_pocket'];self.assertEqual(len(prediction['files']),2)
        self.assertEqual(result['summary']['scored_pairs'],0);self.assertEqual(result['summary']['na_pairs'],2)
        checked=deepcopy(fact);checked['receptors'][0]['quality']='严格'
        fixed=read_json(verified_file(home,run['inputs']['system_input_ref']))['payload']
        with self.assertRaisesRegex(ContractError,'质控等级'):science.validate_evidence(home,fixed,checked,run['config'])

    def test_new_draft_keeps_original_seed_and_repeat_never_fetches_again(self):
        def connect(home,packet,folder,progress):
            draft=self.w.analysis_plan_info(self.sid)['draft']
            self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],
                'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
                'author':'明确合成测试','note':'准备期间新草稿，原批不变'})
            return unavailable_sources(home,packet,folder,progress)
        with patch.object(legacy,'connect',side_effect=connect):result=self.execute()
        m=self.w.load(self.sid);self.assertEqual(self.w.run(m,result['run_id'])['config']['vina_parameters']['seed'],1)
        with patch.object(legacy,'connect',side_effect=AssertionError('幂等不能再次连接来源')):self.assertEqual(self.execute(),result)
        self.assertEqual(self.w.load(self.sid),m)

    def test_hold_during_sources_blocks_publish_but_keeps_download_and_diagnostic(self):
        def connect(home,packet,folder,progress):
            self.w.review(self.sid,self.before['current']['A04'],'pending','明确合成测试','来源期间明确暂存')
            return unavailable_sources(home,packet,folder,progress)
        with patch.object(legacy,'connect',side_effect=connect),self.assertRaises(ContractError):self.execute()
        m=self.w.load(self.sid);self.assertNotIn('A06_PREP',m['current'])
        failure=build_trace(self.w,self.sid)['plan_decisions']['system_batch_events'][-1]
        self.assertEqual(failure['state'],'failed')
        self.assertTrue(any(r['path'].endswith('/explicit_synthetic_failure.json') for r in failure['files']))

    def test_missing_tools_never_connects_or_publishes_placeholder(self):
        with patch.object(legacy,'connect',side_effect=AssertionError('缺工具不能下载')),self.assertRaisesRegex(ContractError,'固定Vina'):
            self.execute(tools=Path(self.temp.name)/'no_tools')
        m=self.w.load(self.sid);self.assertNotIn('A06_PREP',m['current']);self.assertEqual(m['reviews'],self.before['reviews'])

    def test_forged_counts_rejected_by_actual_validator_even_caller_replaces_validator(self):
        original=science.compute
        def forged(*args):
            values=list(original(*args));values[2]=dict(values[2],scored_pairs=1);return tuple(values)
        self.w.validators['A06_PREP']=lambda *args:None
        with patch.object(legacy,'connect',side_effect=unavailable_sources),patch.object(science,'compute',side_effect=forged):
            with self.assertRaisesRegex(ContractError,'证据复算'):self.execute()
        m=self.w.load(self.sid);self.assertNotIn('A06_PREP',m['current']);self.assertEqual(m['reviews'],self.before['reviews'])

    def test_finished_evidence_survives_failed_validation_and_resumes_without_refetch_or_preparing(self):
        with patch.object(legacy,'connect',side_effect=unavailable_sources),patch.object(science,'validate_evidence',side_effect=ContractError('明确合成发布核查失败')):
            with self.assertRaisesRegex(ContractError,'发布核查失败'):self.execute()
        before=self.w.load(self.sid);self.assertNotIn('A06_PREP',before['current'])
        with patch.object(legacy,'connect',side_effect=AssertionError('恢复不能再次下载')),patch.object(legacy,'prepare',side_effect=AssertionError('恢复不能重新准备')):
            result=self.execute()
        m=self.w.load(self.sid);run=self.w.run(m,result['run_id']);home=self.w.location(self.sid)
        recovery=read_json(verified_file(home,run['inputs']['preparation_recovery']))
        self.assertFalse(recovery['network_requested']);self.assertFalse(recovery['new_preparation_executed'])
        self.assertEqual({Path(verified_file(home,r)).name for r in recovery['implementation_files']},
            {'system_preparation.py','system_preparation_recovery.py'})
        self.assertEqual(result['summary']['na_pairs'],2);self.assertEqual(m['reviews'],self.before['reviews'])
