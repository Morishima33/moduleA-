"""参考资格复算测试：模拟已复验证据，覆盖固定范围、失败和跨批拒绝。"""
import unittest
from copy import deepcopy
from unittest.mock import patch

from contracts import ContractError, fingerprint
from science_modules.a06.plan_reference_qualification_v2 import derive


class ReferenceQualificationV2Tests(unittest.TestCase):
    def setUp(self):
        core = {"schema_version": "A06.plan_preparation_input.1", "study_id": "study_test",
                "compounds": [{"compound_id": "C1"}, {"compound_id": "C2"}],
                "receptors": [{"target_id": "HGNC:1"}, {"target_id": "HGNC:2"}]}
        self.input = {**core, "input_key": fingerprint(core), "pair_count": 4,
                      "structure_preparation_state": "pending", "execution_available": False}
        self.choice = {"target_id": "HGNC:1", "candidate_key": "a" * 64, "reference_key": "b" * 64}
        self.base = {"study_id": "study_test", "input_id": "input_test", "run_id": "run_test",
                     "current_run_id": "run_current", "input_key": self.input["input_key"],
                     "config": {"version": "test"}, "connection": {"receptors": []},
                     "compounds": [{"compound_id": "C1", "state": "ready", "reason_zh": "通过"},
                                   {"compound_id": "C2", "state": "NA", "reason_zh": "缺少配体"}],
                     "receptors": [{"target_id": "HGNC:1", "symbol": "A", "state": "NA", "quality": "待核查", "reason_zh": "缺少参考", "attempts": []},
                                   {"target_id": "HGNC:2", "symbol": "B", "state": "ready", "quality": "探索", "reason_zh": "口袋已核对", "attempts": []}]}
        self.reference = {"schema_version": "A06.plan_reference_review.1", "study_id": "study_test",
                          "input_id": "input_test", "source_preparation_run_id": "run_test",
                          "expected_preparation_run_id": "run_current",
                          "config": self.base["config"], "choices": [self.choice],
                          "results": [{"choice": self.choice, "state": "ready"}]}

    def run_derive(self):
        with patch("science_modules.a06.plan_reference_qualification_v2.validate_choices"), \
             patch("science_modules.a06.plan_reference_qualification_v2.validate_ready",
                   return_value={"state": "ready", "quality": "严格", "reason_zh": "严格通过"}) as verify:
            output = derive(None, self.input, self.base, self.reference)
        return output, verify

    def test_ready_reference_changes_only_target_and_preserves_na_pairs(self):
        original = deepcopy(self.base)
        value, verify = self.run_derive()
        verify.assert_called_once()
        self.assertEqual(value["receptors"][0]["quality"], "严格")
        self.assertEqual(value["receptors"][1], original["receptors"][1])
        self.assertEqual(value["summary"]["ready_pairs"], 2)
        self.assertEqual(value["summary"]["na_pairs"], 2)
        self.assertTrue(value["summary"]["handoff_blocked"])
        self.assertTrue(all(row["score"] is None for row in value["tables"]["planned_pairs"]))
        self.assertEqual(self.base, original)

    def test_failed_reference_preserves_base_and_reason(self):
        self.reference["results"][0].update(state="NA", reason_zh="序列不一致")
        value, verify = self.run_derive()
        verify.assert_not_called()
        self.assertEqual(value["receptors"], self.base["receptors"])
        self.assertEqual(value["tables"]["reference_qualification"][0]["reason_zh"], "序列不一致")

    def test_rejects_cross_batch_or_mismatched_choice(self):
        for key, value in (("study_id", "other"), ("input_id", "other"),
                           ("source_preparation_run_id", "other"),
                           ("expected_preparation_run_id", "other"), ("config", {})):
            before = deepcopy(self.reference)
            self.reference[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.run_derive()
            self.reference = before
        self.reference["results"][0]["choice"] = dict(self.choice, target_id="HGNC:2")
        with self.assertRaises(ContractError):
            self.run_derive()

    def test_rejects_input_fingerprint_mismatch(self):
        self.base["input_key"] = "other"
        with self.assertRaises(ContractError):
            self.run_derive()

    def test_rejects_missing_identity_and_duplicate_compound(self):
        for key in ("study_id", "run_id", "input_id", "current_run_id"):
            original = self.base[key]
            self.base[key] = None
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.run_derive()
            self.base[key] = original
        self.base["compounds"][1]["compound_id"] = "C1"
        self.input["compounds"][1]["compound_id"] = "C1"
        with self.assertRaises(ContractError):
            self.run_derive()

    def test_rejects_invalid_failed_state_or_missing_reason(self):
        self.reference["results"][0].update(state="NA", reason_zh="")
        with self.assertRaises(ContractError):
            self.run_derive()


if __name__ == "__main__":
    unittest.main()
