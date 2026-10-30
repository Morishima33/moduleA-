"""同批系统资格至真实Vina及中断恢复；全部研究与几何明确为合成测试。"""
from pathlib import Path
import hashlib,shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import read_json,verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_validation
from modulea.core.trace_export import build_trace
from science_modules.a06 import system_scoring as science
from tests.modulea import test_system_qualification as upstream


class SystemScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        upstream.SystemQualificationTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base)
        cls.qualified=w.qualify_analysis_plan_system_preparation(cls.sid,{'batch_id':cls.batch_id,'expected_preparation_run_id':cls.prep_rid})

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_scoring_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root);self.before=self.w.load(self.sid)
        self.body={'batch_id':self.batch_id,'expected_preparation_run_id':self.qualified['run_id'],'expected_scoring_run_id':None}

    def execute(self):
        return self.w.score_analysis_plan_system_preparation(self.sid,self.body,tools=self.tools)

    def packet(self,result):
        return read_json(verified_file(self.w.location(self.sid),result['tables']['scoring_packet'][0]))

    def test_actual_vina_top1_and_na_without_human_approval_then_report_payload(self):
        result=self.execute();m=self.w.load(self.sid);run=self.w.run(m,result['run_id']);packet=self.packet(result)
        self.assertEqual(result['summary']['scored_pairs'],1);self.assertEqual(result['summary']['na_pairs'],1)
        self.assertEqual(result['summary']['strict_scored_pairs'],0);self.assertEqual(result['summary']['exploratory_scored_pairs'],1)
        self.assertAlmostEqual(packet['pairs'][0]['score'],-0.264);self.assertIsNone(packet['pairs'][1]['score'])
        home=self.w.location(self.sid);execution=read_json(verified_file(home,packet['pairs'][0]['execution']))
        pose=verified_file(home,execution['pose']).read_text('ascii')
        first=float(next(line for line in pose.splitlines() if line.startswith('REMARK VINA RESULT:')).split()[3])
        self.assertEqual(packet['pairs'][0]['score'],first);self.assertEqual(execution['returncode'],0);self.assertEqual(execution['top_mode'],1)
        self.assertFalse(self.w.approved(m,result['run_id']));self.assertTrue(self.w.active(m,result['run_id']))
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertEqual(run['parent_review_ids'],{})
        expected=system_validation.request(self.w,self.sid,result['run_id'])
        checked=self.w.validate_analysis_plan_scientific_run(self.sid,{k:expected[k] for k in ('expected_run_id','expected_input_hash')}|
            {'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(checked['passed']);self.assertTrue(checked['scientific_status']['ready_for_successor'])
        from science_modules.a07.plan_payload import build
        payload=build(self.w,self.sid);self.assertEqual(payload['docking']['counts']['scored'],1)
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['system_scores']),1)
        with patch.object(science,'compute',side_effect=AssertionError('完成评分不得重算')):self.assertEqual(self.execute(),result)

    def test_interruption_after_real_execution_reuses_exact_original_without_rerun(self):
        original=science.execute_pair
        def interrupt(*args):
            original(*args);raise ContractError('明确测试：真实组合完成后发布前中断')
        with patch.object(science,'execute_pair',side_effect=interrupt),self.assertRaises(ContractError):self.execute()
        failed=self.w.load(self.sid);rid=failed['current']['A06'];self.assertIsNone(failed['runs'][rid]['result_file'])
        home=self.w.location(self.sid);folder=home/'runs/A06'/rid/'system_scoring'
        before={p.relative_to(home).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
        with patch.object(science,'execute_pair',side_effect=AssertionError('完成组合不能再次执行')):result=self.execute()
        self.assertEqual(result['run_id'],rid);self.assertEqual(result['summary']['scored_pairs'],1)
        self.assertTrue(all(hashlib.sha256((home/path).read_bytes()).hexdigest()==sha for path,sha in before.items()))
        packet=self.packet(result);recovery=read_json(verified_file(home,packet['recovery']))
        self.assertEqual(len(recovery['reused_executions']),1);self.assertTrue(recovery['only_unfinished_pairs_executed'])
        trace=build_trace(self.w,self.sid)['plan_decisions'];self.assertEqual(len(trace['system_scoring_failures']),1)
        self.assertEqual(len(trace['system_scores']),1);self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])

    def test_corrupt_completed_evidence_blocks_resume_without_recalculation(self):
        original=science.execute_pair
        def interrupt(*args):
            original(*args);raise ContractError('明确测试中断')
        with patch.object(science,'execute_pair',side_effect=interrupt),self.assertRaises(ContractError):self.execute()
        m=self.w.load(self.sid);rid=m['current']['A06'];home=self.w.location(self.sid)
        pose=next((home/'runs/A06'/rid/'system_scoring/scores').rglob('poses.pdbqt'));pose.write_bytes(pose.read_bytes()+b'\nCORRUPT\n')
        with patch.object(science,'execute_pair',side_effect=AssertionError('损坏原件不能用重算掩盖')),self.assertRaises(ContractError):self.execute()
        self.assertIsNone(self.w.load(self.sid)['runs'][rid]['result_file'])

    def test_explicit_source_hold_and_client_parameter_override_block_before_vina(self):
        self.w.review(self.sid,self.qualified['run_id'],'pending','明确合成测试','暂停测试准备')
        with patch.object(science,'execute_pair',side_effect=AssertionError('人工暂存不能计算')),self.assertRaises(ContractError):self.execute()
        self.assertNotIn('A06',self.w.load(self.sid)['current'])
        with self.assertRaises(ContractError):self.w.score_analysis_plan_system_preparation(self.sid,self.body|{'seed':2},tools=self.tools)

    def test_production_validator_rejects_forged_strict_count_even_with_fake_caller_validator(self):
        original=science.compute
        def forged(*args):
            stats,tables,sources=original(*args)
            return dict(stats,strict_scored_pairs=1),tables,sources
        self.w.validators['A06']=lambda *args:None
        with patch.object(science,'compute',side_effect=forged),self.assertRaises(ContractError):self.execute()
        m=self.w.load(self.sid);self.assertIsNone(m['runs'][m['current']['A06']]['result_file'])
        self.assertEqual(m['reviews'],self.before['reviews'])

    def test_rechecking_same_parent_keeps_original_scoring_but_latest_failed_validation_blocks(self):
        result=self.execute();before=self.w.load(self.sid);run_before=self.w.run(before,result['run_id'])
        expected=system_validation.request(self.w,self.sid,self.qualified['run_id'])
        def recheck():
            return self.w.validate_analysis_plan_scientific_run(self.sid,{k:expected[k] for k in ('expected_run_id','expected_input_hash')}|
                {'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(recheck()['passed']);m=self.w.load(self.sid)
        self.assertTrue(self.w.active(m,result['run_id']));self.assertEqual(self.w.run(m,result['run_id']),run_before)
        from science_modules.a06 import system_preparation
        with patch.object(system_preparation,'validate_evidence',side_effect=ContractError('明确测试：当前规范重新检查失败')):
            checked=recheck()
        self.assertFalse(checked['passed']);self.assertFalse(self.w.active(self.w.load(self.sid),result['run_id']))
        self.assertEqual(self.w.load(self.sid)['reviews'],before['reviews'])
