"""独立试算账本隔离测试：保存、刷新、旧窗口和研究边界，不产生真实评分。"""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from contracts import SCHEMA_VERSION
from modulea.api.trial_view import trial_info
from modulea.core.trial_workflow import TrialWorkflow
from storage import file_record, read_json, verified_file, write_json


class TrialWorkflowTests(unittest.TestCase):
    """仅模拟继承的已批准上游；新增试算锁、索引和过期规则实际执行。"""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workflow = TrialWorkflow(Path(self.temp.name))
        self.sid = "study_" + "1" * 32
        self.root = self.workflow.location(self.sid)
        self.root.mkdir(parents=True)
        self.context = {"source_key": "source-v1"}
        self.display = {
            "study_id": self.sid,
            "source_key": "source-v1",
            "display_id": "display-v1",
            "config": {
                "table_compounds": [f"c{i}" for i in range(15)],
                "table_targets": [f"t{i}" for i in range(15)],
            },
        }
        path = self.root / "decisions/display.json"
        write_json(path, self.display)
        self.manifest = {
            "schema_version": SCHEMA_VERSION,
            "study_id": self.sid,
            "current": {"A06_PREP": "run_old"},
            "runs": {"run_old": {}},
            "reviews": [],
            "matrix_display_records": [file_record(self.root, path, "display")],
        }
        write_json(self.root / "manifest.json", self.manifest)
        self.payload = {
            "expected_display_id": "display-v1",
            "authorization_zh": "隔离虚构授权",
        }
        self.patch = patch.object(
            TrialWorkflow, "coverage_binding", self.coverage_binding
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def coverage_binding(self, *_args, **_kwargs):
        """继承上游规则已有回归覆盖，此处不创建虚构科学批准。"""
        return self.workflow.load(self.sid), self.context, {}, {}, {}

    def test_begin_keeps_formal_history_and_initial_progress(self):
        before = deepcopy(self.workflow.load(self.sid))
        tid, folder, _, _ = self.workflow.begin_trial(self.sid, self.payload)
        after = self.workflow.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(before[key], after[key])
        self.assertIsNone(read_json(folder / "authorization.json")["formal_approval"])
        info = trial_info(self.workflow, after)
        self.assertEqual(info["trial_id"], tid)
        self.assertIsNone(info["matrix"])

    def test_save_draft_refresh_does_not_approve_or_confirm(self):
        tid, *_ = self.workflow.begin_trial(self.sid, self.payload)
        saved = self.workflow.save_trial_review(
            self.sid, tid, "未完成核查说明", "", False
        )
        info = trial_info(self.workflow, self.workflow.load(self.sid))
        self.assertEqual(info["review"], saved)
        self.assertFalse(saved["confirmed"])
        self.assertIsNone(saved["formal_approval"])
        self.assertEqual(self.workflow.load(self.sid)["reviews"], [])
        with self.assertRaises(ValueError):
            self.workflow.save_trial_review(self.sid, tid, "", "", True)

    def test_old_display_and_old_trial_window_rejected(self):
        with self.assertRaises(ValueError):
            self.workflow.begin_trial(
                self.sid, self.payload | {"expected_display_id": "old"}
            )
        tid, *_ = self.workflow.begin_trial(self.sid, self.payload)
        self.workflow.begin_trial(self.sid, self.payload)
        with self.assertRaises(ValueError):
            self.workflow.save_trial_review(self.sid, tid, "旧窗口", "测试人", False)

    def test_cross_study_and_interruption_preserve_original_records(self):
        with self.assertRaises(ValueError):
            self.workflow.save_trial_review(self.sid, "trial_unknown", "", "", False)
        tid, folder, *_ = self.workflow.begin_trial(self.sid, self.payload)
        original = (folder / "authorization.json").read_bytes()
        self.workflow.stop_trial(self.sid, tid, "测试中断")
        rec = self.workflow.load(self.sid)["docking_trial_records"][-1]
        self.assertEqual(rec["state"], "interrupted")
        self.assertEqual(
            verified_file(self.root, rec["authorization"]).read_bytes(), original
        )
        self.assertEqual(
            self.workflow.load(self.sid)["current"], self.manifest["current"]
        )


if __name__ == "__main__":
    unittest.main()
