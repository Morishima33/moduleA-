"""未批准系统准备至真实资格修订，实际Meeko与原件验证，不制造人工确认。"""
from pathlib import Path
import shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import read_json,verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_validation
from modulea.core.trace_export import build_trace
from tests.modulea import test_system_preparation as upstream
from tests.modulea.plan_report_scoring_fixture import Sources
from science_modules.a06 import plan_preparation_v2 as prep


class SystemQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        upstream.SystemPreparationTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base);source=Sources()
        with patch.object(prep,'connect',side_effect=source.connect),patch.object(prep,'prepare',side_effect=source.prepare):
            result=w.execute_analysis_plan_system_stage(cls.sid,{'batch_id':cls.batch_id,'stage':'A06_PREP','expected_current_run_id':None},tools=cls.tools)
        cls.prep_rid=result['run_id']

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_qualification_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root);self.before=self.w.load(self.sid)
        self.body={'batch_id':self.batch_id,'expected_preparation_run_id':self.prep_rid}

    def execute(self):return self.w.qualify_analysis_plan_system_preparation(self.sid,self.body)

    def test_real_qualification_upgrades_only_explicit_system_evidence_and_keeps_old_pocket_unchanged(self):
        old=self.w.result(self.before,self.prep_rid)
        result=self.execute();m=self.w.load(self.sid);run=self.w.run(m,result['run_id']);home=self.w.location(self.sid)
        self.assertEqual(result['summary']['ready_pairs'],1);self.assertEqual(result['summary']['na_pairs'],1)
        self.assertEqual(result['summary']['strict_receptors'],0);self.assertEqual(result['summary']['exploratory_receptors'],1)
        self.assertEqual(result['summary']['scored_pairs'],0);self.assertFalse(self.w.approved(m,result['run_id']))
        self.assertTrue(self.w.active(m,result['run_id']));self.assertEqual(run['parent_review_ids'],{});self.assertEqual(m['reviews'],self.before['reviews'])
        fact=read_json(verified_file(home,run['inputs']['qualification_fact']))
        self.assertEqual(fact['receptors'][0]['quality'],'探索');self.assertEqual(fact['receptors'][0]['attempts'][0]['evidence']['pocket']['confirmation'],{})
        self.assertEqual(self.w.result(m,self.prep_rid),old)
        expected=system_validation.request(self.w,self.sid,result['run_id'])
        checked=self.w.validate_analysis_plan_scientific_run(self.sid,{k:expected[k] for k in ('expected_run_id','expected_input_hash')}|
            {'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(checked['passed']);self.assertTrue(checked['scientific_status']['ready_for_successor'])
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['system_qualifications']),1)
        from science_modules.a07.plan_payload import build
        payload=build(self.w,self.sid);self.assertEqual(payload['docking']['counts']['ready'],1)
        self.assertFalse(payload['completion']['all_applicable_finished'])

    def test_idempotence_does_not_recompute_and_client_authority_fields_reject(self):
        result=self.execute();m=self.w.load(self.sid)
        with patch('science_modules.a06.system_qualification.compute',side_effect=AssertionError('幂等不能重算')):self.assertEqual(self.execute(),result)
        self.assertEqual(self.w.load(self.sid),m)
        with self.assertRaises(ContractError):self.w.qualify_analysis_plan_system_preparation(self.sid,self.body|{'approved':True})

    def test_source_hold_during_real_validation_blocks_publication_with_diagnostic(self):
        from science_modules.a06 import system_qualification as science
        original=science.reports;called=[]
        def calculate(*args):
            if not called:
                called.append(True);self.w.review(self.sid,self.prep_rid,'pending','明确合成测试','资格计算期间暂存')
            return original(*args)
        with patch.object(science,'reports',side_effect=calculate),self.assertRaises(ContractError):self.execute()
        m=self.w.load(self.sid);self.assertEqual(m['current']['A06_PREP'],self.prep_rid)
        failures=build_trace(self.w,self.sid)['plan_decisions']['system_qualification_failures'];self.assertEqual(failures[-1]['state'],'failed')

    def test_actual_validator_rejects_forged_strict_or_scores_even_caller_uses_lambda(self):
        from science_modules.a06 import system_qualification as science
        original=science.compute
        def forged(*args):
            values=list(original(*args));values[2]=dict(values[2],strict_receptors=1);return values
        self.w.validators['A06_PREP']=lambda *args:None
        with patch.object(science,'compute',side_effect=forged),self.assertRaises(ContractError):self.execute()
        m=self.w.load(self.sid);self.assertEqual(m['current']['A06_PREP'],self.prep_rid);self.assertEqual(m['reviews'],self.before['reviews'])
        failure=build_trace(self.w,self.sid)['plan_decisions']['system_qualification_failures'][-1]
        self.assertTrue(any(r['role']=='unpublished_system_qualification_run' for r in failure['files']))
