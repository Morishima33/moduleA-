"""报告上游不得用占位结果假通过：三库、五库、交集逐项生产复算。"""
from pathlib import Path
import tempfile,unittest
from uuid import uuid4
from tests.modulea.plan_report_fixture import prepare
from modulea.core import system_validation as validation


class PlanReportUpstreamTests(unittest.TestCase):
    def test_modern_creation_and_current_five_sources_are_real_public_path(self):
        """现代建档及PharmGKB五库必须实际运行，不用旧DisGeNET名单冒充新版验证。"""
        with tempfile.TemporaryDirectory(prefix='modern_report_upstream_') as folder:
            w,sid,_,_=prepare(Path(folder),empty=True,modern=True);m=w.load(sid)
            self.assertEqual(m['workflow_profile'],'A00.preupload.2');self.assertTrue(m['initial_analysis_plan'])
            a02=w.result(m,m['current']['A02']);self.assertEqual(a02['summary']['source_profile'],'A02.source_profile.3')
            self.assertEqual(a02['summary']['databases'],['GeneCards','OMIM','TTD','PharmGKB','OTP'])
            for module in ('A00','A01','A02','A03'):
                expected=validation.request(w,sid,m['current'][module]);value=w.validate_analysis_plan_scientific_run(sid,
                    {key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
                self.assertTrue(value['passed'],(module,value['error_zh']))

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
