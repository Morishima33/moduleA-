"""集中核对隔离回归：保持既有完整门控，缺口和NA不因一次提交自动通过。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from contracts import ContractError
from tests.modulea.test_two_pass import fixture, filled
from science_modules.a06.plan_adapter import source_context
from science_modules.a06.two_pass_plan import blank
from modulea.core.two_pass_workflow import preparation_context


class CombinedConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.f, self.sid = fixture(Path(self.temp.name))
        self.ctx = source_context(self.f, self.sid)

    def tearDown(self):
        self.temp.cleanup()

    def check(self, plan):
        return self.f.check_two_pass(self.sid, {"expected_source": self.ctx["source_key"], "plan": plan})["confirmation"]

    def test_all_missing_listed_together_without_writes(self):
        before = deepcopy(self.f.load(self.sid))
        summary = self.check(blank(self.ctx))
        self.assertFalse(summary["ready"])
        self.assertEqual(len(summary["pending"]), 6)  # 三受体、两成分、一个配置。
        self.assertEqual({r["kind"] for r in summary["pending"]}, {"receptor", "compound", "configuration"})
        self.assertEqual(summary["normal_target_ids"], [])
        self.assertFalse(summary["execution_allowed"])
        self.assertEqual(before, self.f.load(self.sid))
        self.assertFalse(preparation_context(self.f, before)["confirmation"]["ready"])

    def test_full_valid_plan_is_confirmable_not_quality_approved(self):
        before = deepcopy(self.f.load(self.sid))
        summary = self.check(filled(self.ctx))
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["pending"], [])
        self.assertEqual(summary["planned_pair_count"], 6)
        self.assertEqual(summary["normal_target_ids"], [r["target_id"] for r in self.ctx["receptors"]])
        self.assertEqual(before, self.f.load(self.sid))

    def test_na_exception_not_bulk_selected_and_compound_missing_blocks(self):
        plan = filled(self.ctx)
        plan["receptors"][0].update(first=None, second=None, unavailable=True, reason="无适用结构")
        plan["compounds"][0].update(status="unavailable", reason="来源三维不可获取")
        summary = self.check(plan)
        self.assertTrue(summary["ready"])
        self.assertEqual(len(summary["unavailable"]), 2)
        self.assertNotIn(plan["receptors"][0]["target_id"], summary["normal_target_ids"])
        plan["compounds"][1]["status"] = None
        self.assertFalse(self.check(plan)["ready"])
        plan["compounds"] = None
        self.assertFalse(self.check(plan)["ready"])

    def test_unknown_fields_material_scope_and_old_source_cannot_pass(self):
        plan = filled(self.ctx)
        plan["execute"] = True
        self.assertFalse(self.check(plan)["ready"])
        plan = filled(self.ctx)
        plan["receptors"][0]["first"].pop("altloc")
        self.assertFalse(self.check(plan)["ready"])
        plan = filled(self.ctx)
        plan["compounds"][0]["material_id"] = "other-study-file"
        self.assertFalse(self.check(plan)["ready"])
        with self.assertRaises(ContractError):
            self.f.check_two_pass(self.sid, {"expected_source": "old", "plan": filled(self.ctx)})
