"""报告上游不得用占位结果假通过：三库、五库、交集逐项生产复算。"""
from pathlib import Path
import tempfile,unittest
from uuid import uuid4
from tests.modulea.plan_report_fixture import prepare
from modulea.core import system_validation as validation


class PlanReportUpstreamTests(unittest.TestCase):
    def test_actual_three_five_sources_intersection_and_all_canonical_receipts(self):
        """正交集与合法空交集均不省略原件和科学校验；明确是合成测试。"""
        for empty in (False,True):
            with self.subTest(empty=empty),tempfile.TemporaryDirectory(prefix='report_full_upstream_') as folder:
                w,sid,draft,result=prepare(Path(folder),empty=empty);before=w.load(sid)
                actual=w.result(before,before['current']['A03'])
                self.assertEqual(actual['summary']['交集靶点数'],0 if empty else 1)
                self.assertEqual(actual['outcome'],'empty' if empty else 'success')
                self.assertEqual(actual['summary']['analysis_parameter_hash'],draft['plan']['parameter_hash'])
                for module in ('A00','A01','A02','A03'):
                    expected=validation.request(w,sid,before['current'][module])
                    value=w.validate_analysis_plan_scientific_run(sid,
                        {key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
                    self.assertTrue(value['passed'],(module,value['error_zh']))
                after=w.load(sid);self.assertEqual(after['current'],before['current']);self.assertEqual(after['reviews'],before['reviews'])
                self.assertFalse(w.approved(after,after['current']['A03']))
