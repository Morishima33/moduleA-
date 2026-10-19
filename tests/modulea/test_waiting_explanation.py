"""等待待办展示实际阻断原因；不改变Workflow状态和后台任务。"""

import unittest
from modulea.api.views import inbox_text


class WaitingExplanationTests(unittest.TestCase):
    # A04身份、A05缺译与人工确认应给出各自的原始等待原因。
    def test_waiting_uses_exact_workflow_reason(self):
        for module, reason in (("A04", "3个靶点身份待核验"), ("A05", "需完成：KEGG展示范围确认、图表版式确认")):
            state = {"code": "waiting", "reason_zh": reason}
            self.assertTrue(inbox_text(module, state).endswith("：" + reason))
            self.assertEqual(state, {"code": "waiting", "reason_zh": reason})

    # 没有细节时保持既有待办回退；复核不误标为计算或等待。
    def test_fallback_and_review_are_unchanged(self):
        self.assertIn("等待资料或待决事项", inbox_text("A04", {"code": "waiting"}))
        self.assertTrue(inbox_text("A04", {"code": "review", "reason_zh": "其他说明"}).startswith("请复核 A04"))


if __name__ == "__main__":
    unittest.main()
