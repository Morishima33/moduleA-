# “通过并继续”验收；确认只推进已有规则的步骤并停在下一人工关口。
from pathlib import Path  # 建立独立临时项目。
import sys  # 加载新项目源码和测试夹具。
import tempfile  # 不向正式研究写入测试数据。
import unittest  # 使用标准测试框架。

ROOT = Path(__file__).resolve().parents[1]  # 定位独立新项目。
sys.path.insert(0, str(ROOT / "src"))  # 使用当前生产代码。
sys.path.insert(0, str(ROOT / "tests"))  # 复用虚构TCMSP来源夹具。

from auto_continue import _modern_profile, continue_after_review  # 使用正式自动接续入口并核对新版流程识别。
from components import validate_components  # 核验自动生成的A01。
from test_components import fixture  # 创建明确标记的虚构资料。
from web import review_form  # 核对网页提供两个清楚选择。
from workflow import Workflow  # 使用统一研究状态内核。


class AutoContinueTests(unittest.TestCase):  # 自动化不能跨越新的人工决定。
    def test_missing_genecards_profile_uses_modern_automation(self):  # 缺GeneCards测试研究不得退回旧流程。
        self.assertTrue(_modern_profile({"workflow_profile": "A00.preupload.2"}))  # 新测试配置应自动准备A01和A02。
        self.assertTrue(_modern_profile({"workflow_profile": "A00.preupload.1"}))  # 既有新版配置继续兼容。
        self.assertFalse(_modern_profile({"workflow_profile": "legacy"}))  # 历史研究不被无意迁移。

    def test_a00_approval_creates_a01_and_stops(self):  # 最早阶段只能自动整理已有方剂资料。
        with tempfile.TemporaryDirectory(prefix="moduleA_auto_continue_") as temporary:  # 测试结束自动清理。
            root = Path(temporary)  # 建立隔离项目根目录。
            fixture(root)  # 写入一条虚构TCMSP记录。
            flow = Workflow(root, {"A01": validate_components})  # 注册本测试会生成的模块校验。
            study_id = flow.create({"formula": "测试方", "herbs": "测试甲", "disease": "测试病", "disease_scope": "仅自动接续测试", "operator": "自动验收", "species": 9606})  # 建立虚构研究。
            manifest = flow.load(study_id)  # 取得A00运行编号。
            a00 = manifest["current"]["A00"]  # 当前登记等待复核。
            flow.review(study_id, a00, "approved", "自动验收", "只验证通过后接续", None)  # 模拟用户明确通过。
            outcome = continue_after_review(flow, study_id)  # 运行到下一人工关口。
            manifest = flow.load(study_id)  # 重新读取自动生成状态。
            self.assertEqual(outcome["created"], ["A01"])  # 只生成一个明确模块。
            self.assertIn("A02疾病资料", outcome["waiting"])  # 页面说明为什么不能继续到A03。
            self.assertFalse(flow.approved(manifest, manifest["current"]["A01"]))  # 系统不得替用户批准A01。
            self.assertNotIn("A02", manifest["current"])  # 不伪造疾病资料。

    def test_current_completed_study_is_not_rerun(self):  # A07通过后点击继续不得生成重复版本。
        from test_a07_reports import workflow, STUDY_ID  # 复用当前研究完整校验器。
        flow = workflow()  # 建立只读状态内核。
        before = dict(flow.load(STUDY_ID)["current"])  # 保存当前各模块指针。
        outcome = continue_after_review(flow, STUDY_ID)  # 已完成时只返回终态。
        after = dict(flow.load(STUDY_ID)["current"])  # 再次读取指针。
        self.assertEqual(before, after)  # 不重复生成报告或其他结果。
        self.assertIn("流程完成", outcome["waiting"])  # 给用户明确冻结前的完整终态。

    def test_review_form_offers_save_or_continue(self):  # 用户可以控制是否立即启动下游。
        item = {"result": {"summary": {}}, "state": "awaiting_review", "review": None, "run": {"run_id": "run_" + "1" * 32}}  # 构造最小有效显示对象。
        html = review_form(item, "study_" + "2" * 32, "token", False)  # 调用生产表单函数。
        self.assertIn("仅保存复核决定", html)  # 保留分次工作的选择。
        self.assertIn("保存并继续到下一人工关口", html)  # 提供自动接续选择。


if __name__ == "__main__":  # 支持独立验收。
    unittest.main(verbosity=2)  # 输出每项结果。
