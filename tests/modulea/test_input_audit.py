"""输入数量溯源与空集示意回归，使用合成归档事实，不写入真实研究。"""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from modulea.api.input_audit import context
from modulea.presenters.intersection import present_a03


class InputAuditTests(unittest.TestCase):
    """验证数量单位、来源覆盖及父版本隔离，避免把排除导致的空集当作未读取。"""

    def setUp(self):
        self.formula = {"run_id": "old_formula", "summary": {"筛选后不同成分数": 3, "标准化基因数": 2},
                        "tables": {"normalized_compound_targets": [{}, {}, {}, {}]}}
        self.disease = {"run_id": "old_disease", "summary": {"候选记录数": 9, "标准化基因数": 0},
                        "tables": {"scope_groups": [{"scope": "outside", "records": 8}, {"scope": "subtype", "records": 1}]}}
        self.result = {"summary": {"方剂靶点数": 2, "疾病靶点数": 0}}
        self.manifest = {"workflow_profile": "A00.preupload.2", "current": {"A01": "new_formula", "A02": "new_disease"}}
        self.run = {"parent_runs": {"A01": "old_formula", "A02": "old_disease"}}
        self.flow = Mock()
        self.flow.result.side_effect = lambda manifest, rid: {"old_formula": self.formula, "old_disease": self.disease}[rid]

    def test_parent_versions_and_units_are_explicit_without_mutation(self):
        before = deepcopy((self.formula, self.disease, self.manifest, self.result))
        info = context(self.flow, self.manifest, "A03", self.run, self.result)
        self.assertEqual(info["formula"]["component_count"], 3)
        self.assertEqual(info["formula"]["target_count"], 2)
        self.assertEqual(info["formula"]["relationship_count"], 4)
        self.assertEqual(info["formula"]["sources"], ["TCMSP"])
        self.assertEqual(info["formula"]["missing_sources"], ["HERB", "BATMAN"])
        self.assertIn("9条候选记录", info["disease"]["empty_reason_zh"])
        self.assertIn("不是数据库没有读取", info["disease"]["empty_reason_zh"])
        self.assertEqual(self.flow.result.call_count, 2)
        self.assertEqual([call.args[1] for call in self.flow.result.call_args_list], ["old_formula", "old_disease"])
        self.assertEqual(before, (self.formula, self.disease, self.manifest, self.result))

    def test_group_counts_do_not_invent_gene_counts(self):
        self.disease["tables"]["scope_groups"] = [{"scope": "pending", "records": 7}, {"scope": "direct", "records": 2}]
        info = context(self.flow, self.manifest, "A02", {"run_id": "old_disease"}, self.disease)
        values = {row["value"]: row for row in info["disease"]["scope_counts"]}
        self.assertEqual(values["pending"]["count"], 1)
        self.assertEqual(values["pending"]["records"], 7)
        self.assertEqual(info["disease"]["target_count"], 0)
        self.assertIn("待核验", info["disease"]["empty_reason_zh"])

    def test_multisource_grouping_and_mismatch_are_not_hidden(self):
        self.formula["summary"].update(component_source_profile="A01.multisource.1", 候选成分分组数=5)
        self.result["summary"]["方剂靶点数"] = 6
        info = context(self.flow, self.manifest, "A03", self.run, self.result)
        self.assertEqual(info["formula"]["component_count"], 5)
        self.assertEqual(info["formula"]["component_label_zh"], "候选成分分组")
        self.assertEqual(info["formula"]["missing_sources"], [])
        self.assertTrue(any(row["level"] == "warning" and "数量不一致" in row["detail_zh"] for row in info["checks"]))

    def test_no_result_or_unrelated_module_has_no_fabricated_audit(self):
        self.assertIsNone(context(self.flow, self.manifest, "A03", None, None))
        self.assertIsNone(context(self.flow, self.manifest, "A04", self.run, self.result))
        raw = deepcopy(self.disease)
        del raw["summary"]["标准化基因数"]
        info = context(self.flow, self.manifest, "A02", {}, raw)
        # 无run时不显示；有run但未标准化时保留“尚未标准化”，不能补0。
        self.assertIsNone(info)
        info = context(self.flow, self.manifest, "A02", {"run_id": "candidate"}, raw)
        self.assertIsNone(info["disease"]["target_count"])
        self.assertEqual(info["disease"]["empty_reason_zh"], "")

    def test_venn_layout_matches_archived_zero_cases(self):
        for T, D, I, expected in [(2, 3, 1, "overlap"), (2, 3, 0, "disjoint"), (2, 0, 0, "empty_disease"), (0, 3, 0, "empty_formula"), (0, 0, 0, "empty_both")]:
            with self.subTest(expected=expected):
                result = {"summary": {"方剂靶点数": T, "疾病靶点数": D, "交集靶点数": I}, "tables": {}}
                venn = present_a03(result, {}).special["venn"]
                self.assertEqual(venn["layout"], expected)
                self.assertEqual(venn["both"], I)
