"""失败对接证据可通过一致性检查，但失败事实和旧交接阻塞不能消失。"""
import subprocess,unittest
from unittest.mock import patch
from uuid import uuid4
from tests.modulea import test_plan_scoring as fixture
from modulea.core.kernel import full_workflow
from modulea.core import system_validation as validation
from contracts import ContractError


@unittest.skipUnless(fixture.TOOLS.is_dir(),'只读固定Vina环境不存在')
class SystemValidationScoringTests(unittest.TestCase):
    """真实准备与归档验证器；仅评分进程的报错响应为显式合成故障。"""
    @classmethod
    def setUpClass(cls):
        fixture.PlanScoringTests.setUpClass();cls.addClassCleanup(fixture.PlanScoringTests.doClassCleanups)

    def test_failed_packet_conforms_but_never_becomes_success(self):
        case=fixture.PlanScoringTests('test_process_failure_is_archived_failed_not_zero');case.setUp();self.addCleanup(case.doCleanups)
        actual=subprocess.run
        def fail(arguments,*args,**kwargs):
            """保留实际版本检查，测试固定Vina进程失败后的诊断闭环。"""
            if '--version' in arguments:return actual(arguments,*args,**kwargs)
            return subprocess.CompletedProcess(arguments,1,'synthetic failure test','synthetic tool error')
        with patch('subprocess.run',side_effect=fail):result=case.run_scoring()
        w=full_workflow(case.w.root);before=w.load(case.sid);rid=result['run_id']
        expected=validation.request(w,case.sid,rid)
        receipt=w.validate_analysis_plan_scientific_run(case.sid,
            {key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(receipt['passed'],receipt['error_zh'])
        self.assertEqual(receipt['scientific_status']['result_outcome'],'failed')
        self.assertTrue(receipt['scientific_status']['handoff_blocked']);self.assertFalse(receipt['scientific_status']['ready_for_successor'])
        after=w.load(case.sid);self.assertEqual(after['reviews'],before['reviews']);self.assertEqual(after['current'],before['current'])
        self.assertTrue(all(row['score'] is None for row in result['tables']['plan_scoring_pairs']))
        with self.assertRaises(ContractError):w.review(case.sid,rid,'approved','合成测试','一致性不能代替科学成功')
        self.assertEqual(validation.read_receipt(w,after,after[validation.INDEX][-1]),receipt)
