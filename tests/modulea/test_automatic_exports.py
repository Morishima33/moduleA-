"""自动展示的全矩阵一致性、动态范围、异常及按需姿势来源验收。"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from science_modules.a06.automatic_exports import build_view, validate_view, heatmap_svg
from science_modules.a06.drawing_packages import _source_files
from modulea.core.docking_artifacts import catalog
from storage import file_record, write_json


def packet():
    """虚构少量对象覆盖有效、边界、失败及NA，避免镜像225的旧假设。"""
    return {"schema_version": "A06.automatic.2", "study_id": "study_fixture", "run_id": "run_fixture", "id": "request_fixture",
            "compounds": [{"compound_id": "c1", "name": "compound one", "name_zh": ""}, {"compound_id": "c2", "name": "compound two"}],
            "receptors": [{"target_id": "t1", "symbol": "ONE", "candidate_grade": "A", "quality": "探索"}, {"target_id": "t2", "symbol": "TWO", "candidate_grade": "B", "quality": "未通过"}],
            "pairs": [{"compound_id": "c1", "target_id": "t1", "state": "completed", "score": -8.0, "quality": "探索", "reason_zh": ""},
                      {"compound_id": "c1", "target_id": "t2", "state": "failed", "score": None, "quality": "探索", "reason_zh": "姿势越界"},
                      {"compound_id": "c2", "target_id": "t1", "state": "completed", "score": -7.9999, "quality": "探索", "reason_zh": ""},
                      {"compound_id": "c2", "target_id": "t2", "state": "NA", "score": None, "quality": "未通过", "reason_zh": "没有通过准备"}], "summary": {}}


class AutomaticExportTests(unittest.TestCase):
    def test_report_heatmap_moves_explanations_to_appendix_without_changing_cells(self):
        view = build_view(packet())
        normal = heatmap_svg(view)
        report = heatmap_svg(view, include_notes=False)
        self.assertIn('A/B为候选梯队', normal)
        self.assertNotIn('A/B为候选梯队', report)
        self.assertIn('NA', report)
        self.assertIn('-8.00', report)
        self.assertIn('kcal/mol', report)

    def test_selection_keeps_complete_range_and_input_bytes(self):
        original = packet()
        before = json.dumps(original, ensure_ascii=False)
        view = build_view(original, {"c1": {"name_zh": "来源中文", "name_en": "source english"}}, ["c2"], ["t1"])
        self.assertEqual(view["score_range"], [-8, -7.9999])
        self.assertEqual(view["heatmap"]["cells"][0][0]["score"], -7.9999)
        self.assertEqual(len(view["table"]["cells"]), 2)
        self.assertEqual(view["table"]["rows"][0]["name_zh"], "来源中文")
        self.assertEqual(view["table"]["rows"][1]["name_zh"], "")
        self.assertEqual(before, json.dumps(original, ensure_ascii=False))

    def test_threshold_uses_raw_score_and_preserves_two_failure_kinds(self):
        view = build_view(packet())
        cells = view["table"]["cells"]
        self.assertEqual(cells[0][0]["threshold_mark"], "**")
        self.assertEqual(cells[1][0]["display_score"], "-8.00")
        self.assertEqual(cells[1][0]["threshold_mark"], "")
        self.assertEqual(cells[0][1]["state"], "failed")
        self.assertEqual(cells[1][1]["state"], "NA")
        self.assertIn('stroke-dasharray="4 4"', heatmap_svg(view))
        self.assertNotIn("225", heatmap_svg(view))

    def test_all_na_has_no_invented_color_range(self):
        value = packet()
        for p in value["pairs"]:
            p.update(state="NA", score=None, reason_zh="未通过")
        view = build_view(value)
        self.assertEqual(view["score_range"], [None, None])
        self.assertIn("NA", heatmap_svg(view))

    def test_dynamic_default_eight_and_explicit_original_order(self):
        value = packet()
        value["receptors"] = [{"target_id": str(i), "symbol": str(i)} for i in range(10)]
        value["pairs"] = [{"compound_id": c["compound_id"], "target_id": r["target_id"], "score": -i, "state": "completed"} for c in value["compounds"] for i, r in enumerate(value["receptors"])]
        self.assertEqual(len(build_view(value)["heatmap"]["columns"]), 8)
        self.assertEqual([r["target_id"] for r in build_view(value, selected_targets=["7", "1"])["heatmap"]["columns"]], ["1", "7"])

    def test_rejects_unknown_duplicate_incomplete_and_nonfinite(self):
        for chosen in ([], ["bad"], ["c1", "c1"]):
            with self.assertRaises(ValueError):
                build_view(packet(), selected_compounds=chosen)
        value = packet()
        value["pairs"].pop()
        with self.assertRaises(ValueError):
            build_view(value)
        value = packet()
        value["pairs"][0]["score"] = float("nan")
        with self.assertRaises(ValueError):
            build_view(value)

    def test_validator_rejects_changed_color_and_subset_score(self):
        view = build_view(packet())
        view["heatmap"]["cells"][0][0]["score"] = -99
        with self.assertRaises(ValueError):
            validate_view(view)
        view = build_view(packet())
        view["table"]["cells"][0][0]["color"] = "#FFFFFF"
        with self.assertRaises(ValueError):
            validate_view(view)

    def test_catalog_uses_only_same_run_actual_selected_execution(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            value = packet()
            value["pairs"][0]["execution"] = {"state": "completed", "score": -8, "region_id": "site"}
            value["pairs"][2]["execution"] = {"state": "completed", "score": -7.9999, "region_id": "site"}
            write_json(root / "packet.json", value)
            record = file_record(root, root / "packet.json", "automatic_packet")
            manifest = {"study_id": "study_fixture", "current": {}, "runs": {"run_fixture": {"result_file": {"sha256": "x"}}}}
            workflow = SimpleNamespace(location=lambda sid: root,
                                       run=lambda m, r: {"inputs": {}, "parent_runs": {}},
                                       result=lambda m, r: {"tables": {"automatic_packet": [record]}})
            binding, pairs = catalog(workflow, manifest, "run_fixture")
            self.assertEqual(binding["automatic_packet"], record)
            self.assertEqual([p["eligible"] for p in pairs], [True, False, False, False])
            value["study_id"] = "other"
            write_json(root / "packet.json", value, replace=True)
            record.update(file_record(root, root / "packet.json", "automatic_packet"))
            with self.assertRaisesRegex(ValueError, "来源研究"):
                catalog(workflow, manifest, "run_fixture")

    def test_automatic_package_verifies_input_ownership(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name, text in (("protein.pdbqt", "ATOM receptor"), ("ligand.pdbqt", "ATOM ligand"), ("poses.pdbqt", "MODEL 1\nREMARK VINA RESULT: -8.000 0 0\nATOM fixture\nENDMDL\n")):
                (root / name).write_text(text, encoding="ascii")
            protein = file_record(root, root / "protein.pdbqt", "receptor")
            ligand = file_record(root, root / "ligand.pdbqt", "prepared_ligand")
            pose = file_record(root, root / "poses.pdbqt", "pose")
            pair = {"automatic": True, "score": -8, "mode": "predicted_sites", "compound": {"files": [ligand]}, "receptor": {"receptor": protein},
                    "region": {"state": "completed", "score": -8, "region_id": "site", "pose": pose, "command": ["saved_vina"],
                               "config": {"compound": ligand, "receptor": protein, "region": {"center": [0, 0, 0], "size": [20, 20, 20]},
                                          "vina": {"scoring": "vina", "exhaustiveness": 8, "num_modes": 9, "energy_range": 3, "seed": 1}}}}
            dest = root / "chosen"
            dest.mkdir()
            source = _source_files(root, pair, dest)
            self.assertEqual(source["selected_region_id"], "site")
            self.assertIn("-8.000", (dest / "selected_pose.pdbqt").read_text())
            pair["compound"]["files"] = []
            other = root / "other"
            other.mkdir()
            with self.assertRaisesRegex(ValueError, "不属于"):
                _source_files(root, pair, other)


if __name__ == "__main__":
    unittest.main()
