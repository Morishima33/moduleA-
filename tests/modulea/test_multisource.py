"""三库归档展示和旧版本调度；只用虚构输入，不写真实研究。"""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from modulea.presenters.sources import present_a01
import components_multisource_flow as flow

class MultisourceViewTest(unittest.TestCase):
    def test_pending_groups_are_not_labelled_verified_compounds(self):
        result = {"summary": {"候选成分分组数": 4, "结构键分组数": 1, "结构待核分组数": 3,
                              "标准化基因数": 2, "去重成分—人类基因关系数": 3},
                  "tables": {"component_sources": [{"source": "HERB", "source_id": "x", "herb": "甲"},
                            {"source": "HERB", "source_id": "x", "herb": "乙"},
                            {"source": "TCMSP", "source_id": "y", "herb": "甲"}]}}
        parts = present_a01(result, {})
        self.assertEqual(parts.kpis[0]["label_zh"], "候选成分分组")
        self.assertEqual(parts.table["rows"], [{"source": "HERB", "source_ids": 1}, {"source": "TCMSP", "source_ids": 1}])
        self.assertNotIn("通过 OB/DL", [s["label_zh"] for s in parts.flow])
        self.assertFalse(any(f["tier"] == "must_handle" for f in parts.focus))

    def test_unknown_identity_blocks_handoff_without_reusing_approval(self):
        parts = present_a01({"summary": {"候选成分分组数": 1, "handoff_blocked": True}}, {})
        self.assertEqual(parts.focus[0]["blocks"], ["A03"])
        self.assertEqual(parts.params, [])

    def test_legacy_tcmsp_keeps_its_existing_presentation(self):
        parts = present_a01({"summary": {"筛选后不同成分数": 2, "原始关系记录数": 5, "通过OB/DL的关系记录数": 3}}, {})
        self.assertEqual(parts.kpis[0]["label_zh"], "筛选后成分")
        self.assertEqual(parts.flow[1]["label_zh"], "通过 OB/DL")

    def test_bound_multisource_rerun_does_not_fall_back_to_single_source(self):
        workflow = Mock()
        workflow.run.return_value = {"config": {"version": flow.VERSION}, "inputs": {"bound": "evidence"}}
        with patch.object(flow, "publish", return_value={"ok": True}) as publish, patch.object(flow, "legacy_run_components") as legacy:
            self.assertEqual(flow.run_components(workflow, "study_fixture", "a00", "a01", "复算"), {"ok": True})
            publish.assert_called_once()
            legacy.assert_not_called()

    def test_non_multisource_history_stays_on_legacy_rule(self):
        workflow = Mock()
        workflow.run.return_value = {"config": {"version": "A01.1"}}
        with patch.object(flow, "legacy_run_components", return_value={"ok": True}) as legacy:
            self.assertEqual(flow.run_components(workflow, "study_fixture", "a00", "a01", "复算"), {"ok": True})
            legacy.assert_called_once()

if __name__ == "__main__":
    unittest.main()
