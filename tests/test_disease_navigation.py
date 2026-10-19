"""A02操作定位只读回归，不改变Workflow状态或科研决定。"""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modulea.core.disease_navigation import context


class DiseaseNavigationTests(unittest.TestCase):
    """验证资料、范围、预览、生成与整体复核的实际阶段边界。"""
    def setUp(self):
        self.workflow = Mock()
        self.workflow.approved.return_value = False
        self.manifest = {"current": {"A01": "formula", "A02": "disease"}}
        self.result = {"summary": {}, "tables": {"source_summary": [{"availability": "已有候选资料，待核验"}]}}
        self.state = {"code": "waiting"}

    def guide(self, normalization=None):
        return context(self.workflow, self.manifest, self.result, normalization, self.state)

    def test_missing_failed_and_pending_sources_have_specific_locations(self):
        self.assertEqual(context(self.workflow, self.manifest, None, None, self.state)["current_step"], 1)
        self.result["summary"]["失败来源库数"] = 1
        self.assertEqual(self.guide()["next_target"], "disease-source-inputs")
        self.result["summary"] = {"待范围复核条目数": 3}
        self.assertEqual(self.guide()["next_target"], "disease-scope-review")

    def test_preview_and_confirmation_are_different_steps(self):
        info = {"enabled": True, "preview": None}
        self.assertEqual(self.guide(info)["current_step"], 3)
        info["preview"] = {"stamp": "same_version"}
        guide = self.guide(info)
        self.assertEqual(guide["current_step"], 4)
        self.assertEqual(guide["next_target"], "normalization-confirmation")
        self.workflow.approved.assert_not_called()

    def test_normalized_results_need_workflow_approval_before_a03(self):
        self.result["summary"] = {"标准化基因数": 1, "待范围复核条目数": 3}
        self.assertEqual(self.guide()["current_step"], 5)
        self.workflow.approved.return_value = True
        self.assertEqual(self.guide()["current_step"], 6)
        self.assertEqual(self.guide()["next_target"], "A03")

    def test_dependency_and_readonly_reason_are_retained_without_mutation(self):
        before = copy.deepcopy(self.manifest)
        info = {"enabled": False, "disabled_reason_zh": "缺少固定参考文件", "preview": None}
        self.assertEqual(self.guide(info)["note_zh"], "缺少固定参考文件")
        self.state = {"code": "stale", "reason_zh": "上游版本已变化"}
        self.assertEqual(self.guide(info)["note_zh"], "上游版本已变化")
        self.assertEqual(self.manifest, before)


if __name__ == "__main__":
    unittest.main()
