"""Word报告独立验证：同研究、真实终态/参数、完整矩阵、禁止补零或伪造签名。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from docx import Document
from contracts import ContractError
from science_modules.analysis_protocol import compile_plan
from science_modules.a07.plan_facts import docking,completion
from science_modules.a07.plan_documents import check,build,validate_document
from tests.modulea.test_plan_report_facts import packet


def payload():
    """纯模板测试数据明确合成，不冒充实际科学验证或发布的A07。"""
    raw=packet();raw.update(study_id='study_synthetic',run_id='run_synthetic')
    facts=docking(raw,{'version':'explicit_synthetic'})
    return {'schema_version':'A07.plan_payload.1','study_id':'study_synthetic','intake':{'formula':'合成方','disease':'合成病'},
            'plan':compile_plan({'mode':'personalized','parameters':{'a06.exhaustiveness':4,'a06.seed':7}}),
            'completion':completion([{'branch':'合成对接分支','state':'partial','reason_zh':'2组原分数、1准备NA、1工具失败'}]),
            'enrichment':None,'docking':facts,'branch_reasons':{'enrichment':'仅合成模板测试，无富集输入，不编写结果'},
            'conclusion':'仅验证完整原分数与缺失矩阵，不是正式研究结论。','sources':[{'label':'合成来源','description':'明确合成模板数据'}],
            'network_summary':['未提供合成网络数据，不补写指标。'],'research_leads':['仅为后续独立核验提供测试呈现。'],
            'validation_records':[],'references':['合成测试没有额外方法来源声明'],'figures':[]}


class PlanReportDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_report_document_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.payload=payload();self.path=self.root/'preview.docx'

    def test_draft_body_appendix_and_all_matrix_cells_are_verified(self):
        build(self.payload,self.path,self.root,draft=True)
        value=validate_document(self.path,self.payload,draft=True)
        self.assertEqual(value['matrix_cells_verified'],4);self.assertTrue(value['draft_only'])
        document=Document(self.path);text='\n'.join(p.text for p in document.paragraphs)
        self.assertIn('原始Vina评分≤−8',text);self.assertIn('不表示统计显著性',text)
        self.assertNotIn('225格',text);self.assertNotIn('exhaustiveness=8',text)

    def test_no_system_validation_receipt_cannot_generate_formal_report(self):
        with self.assertRaises(ContractError):build(self.payload,self.path,self.root)
        self.assertFalse(self.path.exists())
        cross=deepcopy(self.payload);cross['docking']['study_id']='study_other'
        with self.assertRaises(ContractError):check(cross,draft=True)

    def test_unregistered_passed_flag_cannot_authorize_formal_word(self):
        self.payload['validation_records']=[{'study_id':'study_synthetic','module':'A06','authority_kind':'system_validation',
            'passed':True,'source':{'path':'fake_passed.json','sha256':'0'*64,'bytes':1}}]
        with self.assertRaises(ContractError):build(self.payload,self.path,self.root)
        self.assertFalse(self.path.exists())

    def test_na_changed_to_zero_or_missing_matrix_column_rejects_word(self):
        for change in ('zero','column'):
            build(self.payload,self.path,self.root,draft=True);doc=Document(self.path)
            table=next(t for t in doc.tables if t.rows[0].cells[0].text=='成分' and len(t.columns)==3)
            if change=='zero':table.rows[1].cells[2].text='0.00'
            else:table.rows[0].cells[2].text='其他受体'
            doc.save(self.path)
            with self.subTest(change=change),self.assertRaises(ContractError):validate_document(self.path,self.payload,draft=True)

    def test_parameter_or_complete_status_changed_in_word_rejects(self):
        for change in ('parameter','state'):
            build(self.payload,self.path,self.root,draft=True);doc=Document(self.path)
            if change=='parameter':
                row=next(row for t in doc.tables for row in t.rows if row.cells[0].text=='Vina搜索投入');row.cells[1].text='8'
            else:
                next(p for p in doc.paragraphs if p.text.startswith('本报告状态')).text='本报告状态 适用分支已完成。'
            doc.save(self.path)
            with self.subTest(change=change),self.assertRaises(ContractError):validate_document(self.path,self.payload,draft=True)
