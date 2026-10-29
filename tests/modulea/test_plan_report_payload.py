"""正式Word必须独立重建同批事实；真实系统回执不授权篡改结论或完成状态。"""
from copy import deepcopy
from pathlib import Path
import shutil,tempfile,unittest
from uuid import uuid4
from contracts import ContractError
from modulea.core.kernel import full_workflow
from modulea.core import system_validation as validation
from science_modules.a07 import plan_payload as model
from science_modules.a07.plan_figures import attach
from science_modules.a07.plan_documents import build,validate_document
from tests.modulea.plan_report_fixture import prepare


class PlanReportPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """两种完整上游均来自生产科学发布，测试复核明确标注为合成。"""
        cls.seed=tempfile.TemporaryDirectory(prefix='report_payload_seed_');cls.addClassCleanup(cls.seed.cleanup)
        cls.cases={}
        for empty in (False,True):
            folder=Path(cls.seed.name)/str(empty);w,sid,_,_=prepare(folder,empty=empty)
            for module in ('A00','A01','A02','A03'):
                expected=validation.request(w,sid,w.load(sid)['current'][module])
                value=w.validate_analysis_plan_scientific_run(sid,
                    {key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
                if not value['passed']:raise AssertionError((module,value['error_zh']))
            cls.cases[empty]=(folder,sid)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='report_payload_case_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);folder,self.sid=self.cases[True]
        shutil.copytree(folder,self.root,dirs_exist_ok=True);self.w=full_workflow(self.root);self.home=self.w.location(self.sid)

    def test_same_study_actual_empty_intersection_builds_truthful_formal_word(self):
        """只验证合法空结果报告；没有生成A07或冒充全部非空分支验收。"""
        before=(self.home/'manifest.json').read_bytes();payload=model.build(self.w,self.sid)
        self.assertEqual(payload['completion']['state'],'valid_empty');self.assertTrue(payload['completion']['all_applicable_finished'])
        self.assertEqual(len(payload['validation_records']),4);self.assertIsNone(payload['enrichment']);self.assertIsNone(payload['docking'])
        self.assertEqual([row['state'] for row in payload['completion']['branches']],[ 'valid_empty','not_applicable','not_applicable','not_applicable'])
        payload=attach(self.w,payload,self.home/'report_preview/figures')
        for concise in (False,True):
            path=self.root/('concise.docx' if concise else 'main.docx');build(payload,path,self.home,concise=concise)
            result=validate_document(path,payload,concise=concise);self.assertFalse(result['draft_only'])
        self.assertEqual(before,(self.home/'manifest.json').read_bytes());self.assertNotIn('A07',self.w.load(self.sid)['current'])

    def test_positive_intersection_waits_for_real_applicable_branches(self):
        folder,sid=self.cases[False];w=full_workflow(folder);payload=model.build(w,sid)
        self.assertEqual(payload['completion']['state'],'waiting');self.assertFalse(payload['completion']['all_applicable_finished'])
        self.assertIn('交集1个',payload['conclusion']);self.assertTrue(all(row['state']=='waiting' for row in payload['completion']['branches'][1:]))
        with self.assertRaises(ContractError):build(payload,self.root/'forbidden.docx',w.location(sid))
        self.assertFalse((self.root/'forbidden.docx').exists())

    def test_valid_receipts_cannot_authorize_forged_conclusion_parameters_or_counts(self):
        payload=model.build(self.w,self.sid)
        cases=[]
        for key,value in (('conclusion','证明临床有效'),('network_summary',['虚构100个交集']),('figures',[{'record':'invented'}])):
            changed=deepcopy(payload);changed[key]=value;cases.append(changed)
        changed=deepcopy(payload);changed['intake']['disease']='另一种疾病';cases.append(changed)
        changed=deepcopy(payload);changed['completion']['branches'][0]['reason_zh']='实际并未运行的对接已成功';cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed['conclusion']),self.assertRaises(ContractError):
                build(changed,self.root/'forged.docx',self.home)
        self.assertFalse((self.root/'forged.docx').exists())

    def test_changed_review_invalidates_report_evidence_without_fake_approval(self):
        payload=model.build(self.w,self.sid);m=self.w.load(self.sid);rid=m['current']['A01']
        old=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成测试复核','撤回源结果测试批准',old['review_id'])
        with self.assertRaises(ContractError):build(payload,self.root/'stale.docx',self.home)
        self.assertFalse((self.root/'stale.docx').exists())

    def test_foreign_study_cannot_borrow_real_receipts(self):
        payload=model.build(self.w,self.sid);_,sid=self.cases[False];payload['study_id']=sid
        with self.assertRaises(ContractError):build(payload,self.root/'cross.docx',self.home)
        self.assertFalse((self.root/'cross.docx').exists())

    def test_formal_report_requires_complete_untampered_same_batch_figures(self):
        payload=model.build(self.w,self.sid)
        with self.assertRaises(ContractError):build(payload,self.root/'missing.docx',self.home)
        payload=attach(self.w,payload,self.home/'report_preview/figures')
        model.validate(payload,self.home,require_figures=True)
        from storage import verified_file
        image=verified_file(self.home,payload['figures'][0]['record']);image.write_bytes(image.read_bytes()+b'changed')
        with self.assertRaises(ContractError):build(payload,self.root/'changed.docx',self.home)
        self.assertFalse((self.root/'changed.docx').exists())
