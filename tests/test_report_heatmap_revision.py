from pathlib import Path  # 明确项目归属。
import sys, unittest  # 使用标准库检查。
from unittest.mock import patch  # 构造未审核的负例。
ROOT = Path(__file__).resolve().parents[1]  # 正式测试位置。
sys.path.insert(0, str(ROOT / 'src'))  # 使用统一报告代码。
from contracts import ContractError  # 必须拒绝非法发布。
from docking_automation import workflow_instance  # 完整科学校验。
from report_flow import report_heatmap_record, assemble_payload, _add_heatmap  # 同源选择与报告图注。
from storage import read_json  # 读取明确版本。
from docx import Document  # 检查实际生成的Word段落。
SID = 'study_26fce8e06ccc44a1a4fa7cefc8f789ba'  # 本轮真实修订案例。
class ReportHeatmapRevisionTests(unittest.TestCase):  # 不修改真实复核状态。
    @classmethod  # 三项共享同一次只读核验。
    def setUpClass(cls):  # 保存当前真实对象。
        cls.flow = workflow_instance(ROOT)  # 与网页同一校验。
        cls.manifest = cls.flow.load(SID)  # 唯一当前运行索引。
        cls.result = cls.flow.result(cls.manifest, cls.manifest['current']['A06'])  # 核对实际A06。
        cls.index = read_json(cls.flow.location(SID) / 'governance' / 'A06_figure_index.json')  # 用户批准的图件。
    def test_report_uses_approved_revision(self):  # 网页与报告不能继续引用不同版本。
        record = report_heatmap_record(self.flow, self.result)  # 通过正式选择入口。
        self.assertEqual(record, self.index['metadata'])  # 完整指纹而非仅文件名相同。
    def test_pending_figure_cannot_be_published(self):  # 助手检查不能替代用户批准。
        pending = dict(self.index, review_status='awaiting_user_review')  # 构造未通过状态。
        with patch('report_flow.read_json', return_value=pending):  # 只影响本次内存读取。
            with self.assertRaises(ContractError):  # 不能退回旧图悄悄发布。
                report_heatmap_record(self.flow, self.result)  # 明确拒绝未审核新图。
    def test_caption_distinguishes_projection_and_plan(self):  # 图面8×6不能被误写为10×7。
        a07 = self.flow.run(self.manifest, self.manifest['current']['A07'])  # 使用当前报告父版本。
        payload = assemble_payload(self.flow, self.manifest, a07['parent_runs'], self.index['metadata'])  # 唯一同源事实包。
        document = Document()  # 不生成落地文件。
        _add_heatmap(document, payload, self.flow.location(SID))  # 实际调用图注生成逻辑。
        text = '\n'.join(row.text for row in document.paragraphs)  # 提取生成文字。
        self.assertIn('6个候选成分与8个受体', text)  # 图面身份正确。
        self.assertIn('共70组', text)  # 原计划未丢失。
        self.assertIn('47组形成有效评分', text)  # 有效数与来源一致。
        self.assertIn('23组未形成有效评分', text)  # 失败没有被视觉删减掩盖。
if __name__ == '__main__':  # 支持独立验证。
    unittest.main(verbosity=2)  # 输出明确检查结果。
