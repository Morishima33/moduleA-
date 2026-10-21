"""操作建议的分支与只读边界；所有输入均为虚构展示数据。"""

from copy import deepcopy
import unittest

from modulea.api.module_navigation import context
from modulea.core.modules import ORDER


def view(mid, approved=False):
    """创建最小展示事实，不模拟或修改真实研究归档。"""
    return {"module": {"module_id": mid}, "historical": False, "run": {"run_id": "synthetic"},
            "state": {"code": "approved" if approved else "review", "label_zh": "已通过" if approved else "待复核",
                      "handoff_blocked": False, "reason_zh": None},
            "review": {"already_approved": approved, "can_review": True}, "special": {}}


def current(info):
    """读取建议步骤的稳定标识，避免将建议位置当作完成状态。"""
    return info["steps"][info["current_step"] - 1]["key"]


class ModuleNavigationTests(unittest.TestCase):
    """验证候选、确认、复核、已批准及准备关联之间的导航区别。"""

    def test_stale_results_guide_execution_instead_of_nonexistent_new_graphs(self):
        value = view("A06")
        value["automatic_docking"] = {"latest": {"state": "stale"}, "connection": {"id": "new"}}
        info = context(value)
        self.assertEqual(current(info), "new_execution")
        self.assertEqual(info["steps"][0]["module_id"], "A06_PREP")
        self.assertIn("尚未启动评分", info["note_zh"])
        value["automatic_docking"]["connection"] = None
        self.assertEqual(current(context(value)), "new_execution")
        value["automatic_docking"]["latest"]["state"] = "completed"
        self.assertEqual(current(context(value)), "review")

    def test_stale_automatic_batch_does_not_skip_new_connection(self):
        value = view("A06_PREP")
        value["automatic_docking"] = {"latest": {"state": "stale"}, "connection": None,
                                      "scope": {"ready": True}}
        self.assertEqual(current(context(value)), "connect")
        value["automatic_docking"]["connection"] = {"id": "new_connection"}
        self.assertEqual(current(context(value)), "authorize")
        for state in ("running", "completed"):
            value["automatic_docking"]["latest"]["state"] = state
            self.assertEqual(current(context(value)), "result")

    def test_all_modules_and_history_are_readonly(self):
        """覆盖全部注册模块、缺结果及只读状态，不得回写权限或事实。"""
        for mid in ORDER:
            for code in ("idle", "running", "failed", "stale", "review", "approved"):
                with self.subTest(mid=mid, code=code):
                    value = view(mid, code == "approved")
                    value["state"].update(code=code, reason_zh="原状态说明")
                    value["review"]["can_review"] = code == "review"
                    value["run"] = None if code == "idle" else value["run"]
                    original = deepcopy(value)
                    info = context(value)
                    self.assertEqual(value, original)
                    if mid == "A02":
                        self.assertIsNone(info)
                    else:
                        self.assertGreaterEqual(info["current_step"], 1)
                        self.assertLessEqual(info["current_step"], len(info["steps"]))
                        self.assertEqual(len(info["steps"]), len({s["key"] for s in info["steps"]}))
                        self.assertIn("原状态说明", info["note_zh"])
                        for step in info["steps"]:
                            self.assertTrue(step["target"] or step.get("module_id") or step.get("href"))
                    value["historical"] = True
                    self.assertIsNone(context(value))

    def test_raw_a01_approval_does_not_skip_joint_normalization(self):
        """旧候选通过不能被导航误当成两侧标准化已经完成。"""
        value = view("A01", True)
        self.assertEqual(current(context(value, {"summary": {}})), "identity")
        self.assertEqual(current(context(value, {"summary": {"标准化基因数": 0}})), "intersection")
        value["review"]["already_approved"] = False
        self.assertEqual(current(context(value, {"summary": {"标准化基因数": 0}})), "review")

    def test_enrichment_confirmation_and_missing_maps_are_separate(self):
        """范围、版式、缺图及人工复核不能被单一通过标志吞掉。"""
        value = view("A05")
        value["enrichment_display"] = {"exclusions_confirmed": False, "layout_confirmed": False}
        value["ranked_pathway_maps"] = {"items": []}
        value["special"]["enrichment_display_tables"] = {"bp_top15": [], "kegg_p_top10": [{"ID": "synthetic"}]}
        self.assertEqual(current(context(value)), "scope")
        value["enrichment_display"]["exclusions_confirmed"] = True
        self.assertEqual(current(context(value)), "layout")
        value["enrichment_display"]["layout_confirmed"] = True
        self.assertEqual(current(context(value)), "maps")
        value["ranked_pathway_maps"]["items"] = [{"png_url": "/verified-file"}]
        self.assertEqual(current(context(value)), "review")
        value["review"]["already_approved"] = True
        self.assertEqual(current(context(value)), "report")
        value["ranked_pathway_maps"]["items"] = []
        value["special"]["enrichment_display_tables"]["kegg_p_top10"] = []
        self.assertEqual(current(context(value)), "report")

    def test_trial_preparation_uses_associated_result_and_no_repeat_approval(self):
        """已关联准备只看证据，失效时不定位已隐藏的受体和成分表。"""
        value = view("A06_PREP")
        value["trial_preparation"] = {"active": True, "result_url": "#/studies/example/A06?run_id=old"}
        info = context(value)
        self.assertEqual(current(info), "result")
        self.assertNotIn("review", {s["key"] for s in info["steps"]})
        self.assertEqual(info["steps"][-1]["href"], value["trial_preparation"]["result_url"])
        value["trial_preparation"]["active"] = False
        info = context(value)
        self.assertEqual(current(info), "source")
        self.assertEqual([s["key"] for s in info["steps"]], ["source", "result"])

    def test_preparation_and_trial_gates_remain_distinct(self):
        """准备确认、试算核查和正式A06批准分别引导，不能互相代替。"""
        prep = view("A06_PREP")
        prep["docking_coverage"] = {"confirmed": False}
        self.assertEqual(current(context(prep)), "quality")
        prep["docking_coverage"]["confirmed"] = True
        self.assertEqual(current(context(prep)), "review")
        prep["trial_handoff"] = {"active": True}
        self.assertEqual(current(context(prep)), "result")
        self.assertNotIn("review", {s["key"] for s in context(prep)["steps"]})
        result = view("A06")
        result["docking_trial"] = {"review": None}
        self.assertEqual(current(context(result)), "trial")
        result["docking_trial"]["review"] = {"confirmed": True}
        self.assertEqual(current(context(result)), "review")
        result["state"]["handoff_blocked"] = True
        self.assertEqual(current(context(result)), "scores")
        result["review"]["already_approved"] = True
        result["state"]["handoff_blocked"] = False
        self.assertEqual(current(context(result)), "report")

    def test_stale_intersection_points_to_updated_input_review(self):
        """已修订上游时先指向新版复核，不能引导用户继续批准旧零交集。"""
        value = view("A03")
        value["state"]["code"] = "stale"
        value["review"]["can_review"] = False
        info = context(value)
        self.assertEqual(current(info), "updated_inputs")
        self.assertEqual(info["steps"][info["current_step"] - 1]["module_id"], "A02")
        self.assertFalse(value["review"]["can_review"])


if __name__ == "__main__":
    unittest.main()
