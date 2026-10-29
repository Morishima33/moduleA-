"""新版报告生产归档按真实系统依赖执行，不写人工reviews，不通过旧批准门控冒充自动化。"""
from pathlib import Path
import shutil,tempfile,unittest
from uuid import uuid4
from unittest.mock import patch
from contracts import ContractError
from modulea.core.kernel import full_workflow
from modulea.core import plan_reports as report
from modulea.core import system_validation as validation
from tests.modulea import test_plan_report_payload as fixture
from tests.modulea.plan_report_fixture import prepare


class PlanReportWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PlanReportPayloadTests.setUpClass.__func__(cls)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='report_workflow_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);folder,self.sid=self.cases[True];shutil.copytree(folder,self.root,dirs_exist_ok=True)
        self.w=full_workflow(self.root)

    def body(self):
        """采用只读资格中的当前运行与实际指纹，不传结论、图件或通过标记。"""
        value=report.info(self.w,self.sid)
        return {key:value[key] for key in ('expected_report_run_id','expected_input_hash')}|{
            'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成报告测试','note':'实际同批系统依赖生成报告，未签人工审核','confirmed':True}

    def test_real_production_report_has_system_dependencies_without_human_approval(self):
        before=self.w.load(self.sid);body=self.body();self.assertTrue(report.info(self.w,self.sid)['enabled'])
        result=self.w.publish_analysis_plan_report(self.sid,body);after=self.w.load(self.sid);rid=result['run_id'];run=self.w.run(after,rid)
        self.assertEqual(after['reviews'],before['reviews']);self.assertEqual(run['parent_review_ids'],{})
        self.assertEqual(run['execution_authority'],'system_validation');self.assertEqual(set(run['parent_validation_records']),{'A00','A01','A02','A03'})
        self.assertTrue(self.w.active(after,rid));self.assertFalse(self.w.approved(after,rid))
        self.assertEqual(result['outcome'],'empty');self.assertEqual(result['tables']['key_counts'][0]['数值'],0)
        self.assertEqual(len(result['tables']['report_files']),2);self.assertEqual(len(after[report.RECEIPTS]),1)
        check=self.w.validators['A07'];check(run,result['summary'],result['tables'],result['anomalies'],result['outcome'])
        self.assertEqual(self.w.publish_analysis_plan_report(self.sid,body),result)
        self.assertEqual(len(self.w.load(self.sid)[report.REQUESTS]),1)

    def test_explicit_test_report_review_does_not_invalidate_report_or_upstream(self):
        """仅合成研究模拟实际终验动作；生产生成器自身没有签署任何人工决定。"""
        before=self.w.load(self.sid);a00=before['current']['A00'];expected=validation.request(self.w,self.sid,a00)
        result=self.w.publish_analysis_plan_report(self.sid,self.body());rid=result['run_id']
        self.w.review(self.sid,rid,'approved','明确合成测试复核','仅测试报告最终复核关系，不代表用户验收')
        after=self.w.load(self.sid);self.assertTrue(self.w.active(after,rid));self.assertTrue(self.w.approved(after,rid))
        self.assertEqual(validation.request(self.w,self.sid,a00),expected)
        self.w.validators['A07'](self.w.run(after,rid),result['summary'],result['tables'],[],result['outcome'])

    def test_relevant_approval_withdrawal_invalidates_report_preserving_old_files(self):
        result=self.w.publish_analysis_plan_report(self.sid,self.body());m=self.w.load(self.sid);rid=m['current']['A01']
        review=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成测试复核','撤回报告相关来源的测试批准',review['review_id'])
        m=self.w.load(self.sid);self.assertFalse(self.w.active(m,result['run_id']))
        self.assertEqual(self.w.result(m,result['run_id']),result)

    def test_no_real_system_receipts_cannot_enter_report_and_client_flags_reject(self):
        folder=self.root/'missing';w,sid,_,_=prepare(folder,empty=True)
        value=report.info(w,sid);self.assertFalse(value['enabled']);self.assertIn('等待实际系统校验','；'.join(value['blockers']))
        before=w.load(sid)
        body={key:value[key] for key in ('expected_report_run_id','expected_input_hash')}|{
            'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成测试','note':'缺证据不能生成','confirmed':True}
        with self.assertRaises(ContractError):w.publish_analysis_plan_report(sid,body)
        self.assertEqual(w.load(sid),before)
        with self.assertRaises(ContractError):self.w.publish_analysis_plan_report(self.sid,self.body()|{'passed':True})

    def test_document_failure_preserves_diagnostics_and_new_explicit_request_recovers(self):
        """故障不伪造Word或结果，重试同请求不复算，新的明确请求仅追加报告版本。"""
        before=self.w.load(self.sid);body=self.body()
        with patch('science_modules.a07.plan_documents.build',side_effect=OSError('explicit synthetic document failure')):
            with self.assertRaises(OSError):self.w.publish_analysis_plan_report(self.sid,body)
        failed=self.w.load(self.sid);rid=failed['current']['A07']
        self.assertIsNone(failed['runs'][rid]['result_file']);self.assertEqual(failed['reviews'],before['reviews'])
        self.assertEqual(len(failed[report.FAILURES]),1);self.assertFalse(failed.get(report.RECEIPTS))
        with self.assertRaises(ContractError):self.w.publish_analysis_plan_report(self.sid,body)
        result=self.w.publish_analysis_plan_report(self.sid,self.body());after=self.w.load(self.sid)
        self.assertNotEqual(result['run_id'],rid);self.assertIsNone(after['runs'][rid]['result_file'])
        self.assertEqual(after['reviews'],before['reviews']);self.assertEqual(len(after[report.RECEIPTS]),1)

    def test_new_conformance_receipt_cannot_override_explicit_source_hold(self):
        """规范复算通过与用户暂存决定分别保留，不能借新系统回执覆盖人为停止。"""
        m=self.w.load(self.sid);rid=m['current']['A03']
        self.w.review(self.sid,rid,'pending','明确合成测试复核','明确暂存交集结果，不进入报告')
        expected=validation.request(self.w,self.sid,rid)
        receipt=self.w.validate_analysis_plan_scientific_run(self.sid,
            {key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(receipt['passed'],receipt['error_zh'])
        value=report.info(self.w,self.sid);self.assertFalse(value['enabled'])
        self.assertIn('明确暂存','；'.join(value['blockers']))
        with self.assertRaises(ContractError):self.w.publish_analysis_plan_report(self.sid,self.body())
        self.assertNotIn('A07',self.w.load(self.sid)['current'])

    def test_new_pending_plan_during_generation_does_not_replace_or_invalidate_bound_report(self):
        """实际Word生成期间另存草稿，旧批仍按原方案完成，报告继续有效。"""
        from science_modules.a07 import plan_documents
        original=plan_documents.build;changed=[];before=self.w.load(self.sid);old=report.info(self.w,self.sid)['expected_input_hash']
        def save_draft_then_build(*args,**kwargs):
            if not changed:
                m=self.w.load(self.sid);draft=self.w._analysis_plan_records(m)[-1]
                self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
                    'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.component_count':2}},
                    'author':'明确合成测试','note':'运行期间仅另存下一批草稿'})
                changed.append(True)
            return original(*args,**kwargs)
        with patch('science_modules.a07.plan_documents.build',side_effect=save_draft_then_build):
            result=self.w.publish_analysis_plan_report(self.sid,self.body())
        m=self.w.load(self.sid);self.assertTrue(changed);self.assertTrue(self.w.active(m,result['run_id']))
        self.assertEqual(report.info(self.w,self.sid)['expected_input_hash'],old)
        self.assertEqual(m['reviews'],before['reviews']);self.assertEqual(len(m['analysis_plan_records']),len(before['analysis_plan_records'])+1)
