# A07双报告验收测试；只读当前流程测试研究，不修改任何复核状态。
from pathlib import Path  # 定位项目和当前研究包。
import sys  # 将项目源码目录加入导入路径。
import unittest  # 使用标准库执行可重复验收。
from docx import Document  # 读取两份Word核对共同内容。

ROOT = Path(__file__).resolve().parents[1]  # 从测试文件位置确定项目根目录。
sys.path.insert(0, str(ROOT / "src"))  # 使用当前新项目代码而非旧Kimi目录。

from components import validate_components  # 注册A01领域校验。
from disease import validate_disease  # 注册A02领域校验。
from docking_formal import formal_validator, prep_validator  # 注册A06领域校验。
from enrichment_flow import validator as enrichment_validator  # 注册A05领域校验。
from intersection_flow import validate_intersection, validate_selection  # 注册A03及候选校验。
from normalization import validator as normalization_validator  # 注册标准化结果校验。
from ppi_flow import validator as ppi_validator  # 注册A04领域校验。
from report_flow import CONFIG, validator as report_validator  # 注册并核对A07报告规则。
from report_ui import focus as report_focus  # 核对网页只突出必要人工复核和下载入口。
from storage import read_json, verified_file  # 读取带指纹的报告索引。
from workflow import Workflow  # 使用统一状态内核读取当前研究。

STUDY_ID = "study_28a9580bd87543c98892e3c7ce4d1426"  # 固定本次玉屏风散-COPD流程测试研究。

def workflow():  # 建立与网页相同的完整领域校验器集合。
    return Workflow(ROOT, {  # 返回只读工作流实例。
        "A01": normalization_validator(ROOT, validate_components),  # A01校验。
        "A02": normalization_validator(ROOT, validate_disease),  # A02校验。
        "A03": validate_intersection,  # A03交集校验。
        "A03_SELECT": validate_selection,  # A03主候选校验。
        "A04": ppi_validator(ROOT),  # A04 PPI校验。
        "A05": enrichment_validator(ROOT),  # A05富集校验。
        "A06_PREP": prep_validator(ROOT),  # A06准备校验。
        "A06": formal_validator(ROOT),  # A06正式对接校验。
        "A07": report_validator(ROOT),  # A07双报告校验。
    })  # 完成工作流实例。

def document_text(path):  # 提取Word正文和表格文字供一致性核对。
    document = Document(path)  # 打开生成的Word。
    paragraphs = [paragraph.text for paragraph in document.paragraphs]  # 提取普通段落。
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]  # 提取全部表格单元格。
    return "\n".join(paragraphs + cells)  # 合并为可搜索文本。

class A07ReportTest(unittest.TestCase):  # 检查当前A07修订的核心交付契约。
    @classmethod  # 多个测试共用一次完整指纹核验。
    def setUpClass(cls):  # 准备当前研究视图和报告文件。
        cls.workflow = workflow()  # 建立统一工作流。
        cls.view = cls.workflow.view(STUDY_ID)  # 完整核验当前研究链。
        cls.item = next(item for item in cls.view["modules"] if item["module_id"] == "A07")  # 找到A07当前模块。
        cls.home = cls.workflow.location(STUDY_ID)  # 定位研究包根目录。

    def test_current_report_is_complete_and_approved(self):  # 新修订应完整生成并保存用户明确复核。
        self.assertEqual(self.item["state"], "approved")  # 用户已经明确授权通过当前A07。
        self.assertEqual(self.item["result"]["outcome"], "success")  # 两份Word及索引已经完整生成。
        self.assertEqual(self.item["review"]["decision"], "approved")  # 独立复核记录保存本轮授权。
        self.assertEqual(self.item["result"]["summary"]["结论复核状态"], "待专业复核")  # 生成时摘要保持不可变，复核状态由独立记录表达。
        self.assertFalse(self.item["result"]["summary"]["handoff_blocked"])  # 用户可在网页提交决定。

    def test_report_index_binds_current_upstreams_and_template(self):  # 索引必须精确绑定上游和模板版本。
        records = self.item["result"]["tables"]["report_files"]  # 读取三项正式报告文件记录。
        self.assertEqual({record["role"] for record in records}, {"detailed_report", "concise_report", "report_index"})  # 只允许两份Word和一个索引。
        index_record = next(record for record in records if record["role"] == "report_index")  # 找到报告索引。
        index = read_json(verified_file(self.home, index_record))  # 通过指纹读取索引。
        self.assertEqual(index["template_version"], self.item["run"]["config"]["template_version"])  # 历史报告按自身保存的模板版本校验。
        self.assertEqual(index["parent_runs"], self.item["run"]["parent_runs"])  # 七个上游运行必须一致。
        self.assertTrue(index["conclusion_review_required"])  # 索引明确要求人工复核结论。
        self.assertEqual(len(index["figures"]), 12)  # 六张专业图均同时提供SVG和PNG。
        self.assertEqual(index["comparison_report"]["role"], "comparison_report")  # 独立差异说明纳入索引。

    def test_two_words_share_conclusion_numbers_and_boundaries(self):  # 两版报告必须共用核心事实。
        records = self.item["result"]["tables"]["report_files"]  # 读取报告文件记录。
        detailed = verified_file(self.home, next(record for record in records if record["role"] == "detailed_report"))  # 核验详细版。
        concise = verified_file(self.home, next(record for record in records if record["role"] == "concise_report"))  # 核验简略版。
        detailed_text = document_text(detailed)  # 提取详细版全文。
        concise_text = document_text(concise)  # 提取简略版全文。
        for content in (detailed_text, concise_text):  # 分别检查两份Word。
            for gene in ("TP53", "AKT1", "JUN", "HSP90AA1", "TNF", "ESR1", "IL6", "MAPK1"):  # 核对当前PPI实际前列基因。
                self.assertIn(gene, content)  # 两份报告从当前A04读取而非写死类别结论。
            self.assertIn("β-谷甾醇—AKT1", content)  # 两份报告共用评分最负组合。
            self.assertIn("-10.934", content)  # 两份报告共用五乘五评分事实。
            self.assertIn("208", content)  # 交集靶点数必须一致。
            self.assertIn("15597", content)  # 疾病标准化靶点数必须一致。
            self.assertIn("HSP90AA1", content)  # 五受体及后续比较方向不能在简略版消失。
            self.assertIn("不能据此认定治疗有效", content)  # 两版都必须保留共同结论中的疗效边界。

    def test_detailed_report_contains_receptor_setup_table(self):  # 专业版须完整报告五个受体的对接空间参数。
        records = self.item["result"]["tables"]["report_files"]  # 读取当前报告文件记录。
        detailed = verified_file(self.home, next(record for record in records if record["role"] == "detailed_report"))  # 核验详细版。
        content = document_text(detailed)  # 提取正文和表格文本。
        self.assertIn("受体蛋白结构与分子对接搜索空间参数", content)  # 表题必须存在。
        for value in ("3O96", "1TVO", "4LWE", "2AZ5", "5T92", "IQO A:444", "FRZ A:1001", "FJ2 A:301", "307 A:1", "77W A:601"):  # 核对五个受体及参考配体。
            self.assertIn(value, content)  # 每项均须出现在专业版。
        for value in ("X=9.657", "X=6.487", "X=-0.696", "X=-19.163", "X=-38.914", "1.365", "0.241", "0.636", "0.569", "0.958"):  # 核对坐标与三位小数RMSD。
            self.assertIn(value, content)  # 关键数值不得遗漏。
        self.assertIn("RMSD≤2 Å", content)  # 表下注明统一质控标准。

    def test_research_leads_are_limited_and_traceable(self):  # 首版不得为了展示凑出额外线索。
        leads = self.item["result"]["tables"]["research_leads"]  # 读取网页和报告共同线索。
        self.assertLessEqual(len(leads), CONFIG["maximum_research_leads"])  # 最多三条。
        self.assertEqual([lead["线索"] for lead in leads[:2]], ["AKT1优先核验线索", "跨靶点结构对照线索（HSP90AA1）"])  # 前两条来自当前评分和PPI事实。
        self.assertIn("不用于直接判断哪个靶点更有效", leads[1]["下一步核验"])  # 跨靶点比较目的和边界必须写清。
        self.assertTrue(all(lead["支持事实"] and lead["下一步核验"] for lead in leads))  # 每条都有事实和后续动作。

    def test_web_focus_marks_three_required_checks_and_downloads(self):  # 不让技术明细淹没人工重点。
        html = report_focus(self.item, STUDY_ID)  # 使用生产页面函数生成A07重点区。
        self.assertIn("本轮你只需核对这三项", html)  # 页面明确限定人工任务。
        self.assertIn("共同结论草稿", html)  # 用户无需打开文件即可核对结论。
        self.assertIn("下载专业详细版Word", html)  # 详细版下载入口位于重点区。
        self.assertIn("下载临床简略版Word", html)  # 简略版下载入口位于重点区。
        self.assertIn("实际疾病来源及对接结构限制", html)  # 动态矩阵仍须在首屏提示实际来源和结构限制。

if __name__ == "__main__":  # 允许直接运行本测试文件。
    unittest.main(verbosity=2)  # 输出每项验收结果。

