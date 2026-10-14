"""隔离资料验证出图授权边界、固定姿势、附件保护和图片真实解码。"""

import io
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import zipfile

import test_trial_handoff as handoff_fixture
from test_trial_handoff import FixtureWorkflow
from modulea.core.docking_artifacts import DockingArtifactWorkflow
from modulea.tasks.drawing import validate_image
from modulea.tasks.drawing import run_packages
from modulea.config import Settings
from science_modules.a06.drawing_packages import prepare_packages, build_selected_bundle
from storage import file_record, read_json, write_json


class DrawingFixture(DockingArtifactWorkflow, FixtureWorkflow):
    """来源采用虚构绑定，真实版本校验、写锁和归档均走生产方法。"""


class DrawingTests(unittest.TestCase):
    def test_stopped_old_batch_request_cannot_resume(self):
        """用户改为按需按钮后，旧批量任务重试必须在制作前被拒绝。"""
        import json

        manager = types.SimpleNamespace(update=lambda *args, **kwargs: None)
        with patch("science_modules.a06.drawing_packages.prepare_packages") as prepare:
            with self.assertRaisesRegex(ValueError, "旧批量整理请求已停用"):
                run_packages(
                    Settings(data_root=self.data),
                    {"payload": json.dumps(self.payload), "study_id": self.sid},
                    manager,
                )
            prepare.assert_not_called()

    def test_on_demand_button_makes_only_selected_package_and_bundle(self):
        """一次页面选择完成单组包与对应合集，其他224组保持未制作。"""
        import json
        import sys

        runtime = self.data / "drawing_runtime"
        runtime.mkdir()
        (runtime / "drawing_runtime.json").write_text(
            json.dumps({"pymol_executable": sys.executable}), encoding="utf-8"
        )
        payload = {**self.payload, "request_version": "A06.drawing.on_demand.2"}
        task = {"task_id": "isolated", "study_id": self.sid, "payload": json.dumps(payload)}
        manager = types.SimpleNamespace(update=lambda *args, **kwargs: None)
        with (
            patch("modulea.tasks.drawing.full_workflow", return_value=self.workflow),
            patch(
                "science_modules.a06.drawing_packages.subprocess.run", side_effect=self.fake_pymol
            ) as external,
        ):
            result = run_packages(Settings(data_root=self.data, runtime_dir=runtime), task, manager)
        self.assertIn("所选1组", result)
        self.assertEqual(external.call_count, 1)
        rows = self.workflow.artifact_records(self.workflow.load(self.sid))
        self.assertEqual([r["kind"] for r in rows], ["package", "bundle"])
        self.assertEqual(rows[1]["pair_keys"], [self.key])

    def setUp(self):
        handoff_fixture.HandoffTests.setUp(self)
        self.workflow = DrawingFixture(self.data)
        m = self.workflow.load(self.sid)
        rec = m["docking_trial_records"][0]
        packet = read_json(self.root / rec["packet"]["path"])
        receptor = self.root / "receptor.pdbqt"
        ligand = self.root / "ligand.pdbqt"
        receptor.write_text("ATOM receptor\n", encoding="ascii")
        ligand.write_text("ATOM ligand\n", encoding="ascii")
        self.pose = self.root / "poses.pdbqt"
        self.pose.write_text(
            "MODEL 1\nREMARK VINA RESULT: -8.000 0 0\nATOM pose1\nENDMDL\n"
            "MODEL 2\nREMARK VINA RESULT: -7.000 0 0\nATOM pose2\nENDMDL\n",
            encoding="ascii",
        )
        packet["pairs"][0].update(
            score=-8.0,
            selected_region_id="site_1",
            mode="fixed_site",
            regions=[
                {
                    "region_id": "site_1",
                    "state": "completed",
                    "score": -8.0,
                    "pose": file_record(self.root, self.pose, "trial_pose"),
                    "command": ["archived_vina"],
                    "config": {
                        "receptor": file_record(self.root, receptor, "receptor"),
                        "compound": file_record(self.root, ligand, "ligand"),
                        "vina": {
                            "scoring": "vina",
                            "exhaustiveness": 8,
                            "num_modes": 9,
                            "energy_range": 3,
                            "seed": 1,
                        },
                        "region": {"center": [1, 2, 3], "size": [20, 20, 20]},
                    },
                }
            ],
        )
        packet["pairs"][1]["score"] = -7.9999
        packet_path = self.root / "drawing_fixture_packet.json"
        write_json(packet_path, packet)
        rec["packet"] = file_record(self.root, packet_path, "trial_packet")
        self.workflow.save(m)
        self.rid = self.workflow.publish_trial_handoff(self.sid, "trial_fixture", "隔离出图")[
            "run_id"
        ]
        _, self.binding, self.pairs = self.workflow.artifact_source(self.sid, self.rid)
        self.key = self.pairs[0]["pair_key"]
        self.payload = {"expected_a06": self.rid, "pair_keys": [self.key]}

    def fake_pymol(self, args, cwd, **kwargs):
        """仅替代外部格式工具；固定姿势提取、来源核验和ZIP内容仍实测。"""
        pair_id = Path(cwd).name
        for name in (f"result_{pair_id}.pdb", f"session_{pair_id}.pse", "hbond_info.txt"):
            (Path(cwd) / name).write_text("isolated generated output", encoding="ascii")
        return types.SimpleNamespace(returncode=0, stdout="isolated pymol", stderr="")

    def prepare(self):
        with patch(
            "science_modules.a06.drawing_packages.subprocess.run", side_effect=self.fake_pymol
        ) as call:
            result = prepare_packages(
                self.workflow, self.sid, self.payload, __import__("sys").executable
            )
        return result, call

    def test_exact_raw_threshold_and_no_science_mutation(self):
        self.assertTrue(self.pairs[0]["eligible"])
        self.assertFalse(self.pairs[1]["eligible"])
        before = self.workflow.load(self.sid)
        items, call = self.prepare()
        self.assertEqual(call.call_count, 1)
        after = self.workflow.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(before[key], after[key])
        path = self.workflow.docking_artifact_file(after, items[0]["artifact_id"], 0)
        with zipfile.ZipFile(path) as archive:
            pose = archive.read(self.key + "/selected_pose.pdbqt").decode()
            self.assertIn("ATOM pose1", pose)
            self.assertNotIn("ATOM pose2", pose)
            self.assertIn(self.key + "/session_" + self.key + ".pse", archive.namelist())
        _, call = self.prepare()
        self.assertEqual(call.call_count, 0)

    def test_noneligible_unknown_and_duplicate_selection_rejected(self):
        for keys in ([self.pairs[1]["pair_key"]], ["pair_fake"], [self.key, self.key], []):
            with self.assertRaises(ValueError):
                self.workflow.validate_artifact_request(
                    self.sid, {**self.payload, "pair_keys": keys}
                )

    def test_bundle_only_selected_ready_packages(self):
        with self.assertRaises(ValueError):
            build_selected_bundle(self.workflow, self.sid, self.payload)
        self.prepare()
        item = build_selected_bundle(self.workflow, self.sid, self.payload)
        path = self.workflow.docking_artifact_file(
            self.workflow.load(self.sid), item["artifact_id"], 0
        )
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {self.key + ".zip", "组合索引.json"})

    def test_corrupt_source_and_download_rejected(self):
        self.pose.write_text("altered", encoding="ascii")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_trash_stale_and_source_withdrawal_protect_writes(self):
        with self.assertRaises(ValueError):
            self.workflow.artifact_source(self.sid, "run_old")
        m = self.workflow.load(self.sid)
        m["trashed"] = True
        self.workflow.save(m)
        with self.assertRaises(ValueError):
            self.workflow.artifact_source(self.sid, self.rid)
        m["trashed"] = False
        m["fixture_source"] = "source_changed"
        self.workflow.save(m)
        with self.assertRaises(ValueError):
            self.workflow.artifact_source(self.sid, self.rid)

    def test_png_decode_append_and_original_bytes_preserved(self):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (12, 10), "white").save(buffer, format="PNG")
        data = buffer.getvalue()
        info = validate_image(data)
        before = self.workflow.load(self.sid)
        payload = {
            "expected_a06": self.rid,
            "caption": "隔离示意",
            "pair_key": self.key,
            "name": "../示意.png",
        }
        one = self.workflow.save_docking_figure(self.sid, payload, data, info)
        two = self.workflow.save_docking_figure(self.sid, payload, data, info)
        self.assertNotEqual(one["artifact_id"], two["artifact_id"])
        after = self.workflow.load(self.sid)
        self.assertEqual(
            self.workflow.docking_artifact_file(after, one["artifact_id"], 0).read_bytes(), data
        )
        for key in ("current", "runs", "reviews"):
            self.assertEqual(before[key], after[key])
        context = self.workflow.docking_artifact_context(after, self.rid, historical=True)
        self.assertFalse(context["enabled"])
        self.assertEqual(len(context["images"]), 2)
        self.assertEqual(one["name_zh"], "示意.png")
        for bad in (b"fake.png", data[:40]):
            with self.assertRaises(ValueError):
                validate_image(bad)
        with self.assertRaises(ValueError):
            self.workflow.docking_artifact_file(after, "dock_artifact_other_study", 0)
        image_path = self.workflow.docking_artifact_file(after, one["artifact_id"], 0)
        image_path.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            self.workflow.docking_artifact_file(after, one["artifact_id"], 0)


if __name__ == "__main__":
    unittest.main()
