"""隔离虚构资料验证接入后的正式复核、撤回与过期阻断，不产生研究评分。"""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from contracts import require
from modulea.core.trial_handoff_workflow import TrialHandoffWorkflow
from modulea.devtools.demo_data import build
from storage import file_record, write_json


class FixtureWorkflow(TrialHandoffWorkflow):
    def trial_binding(self, sid, payload, manifest=None):
        m = manifest or self.load(sid)
        require(
            m.get("fixture_source") == payload["expected_source"], "隔离来源版本改变"
        )
        require(not m.get("trashed"), "回收站只读")
        return m, {}, {}, {}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.sid = build(self.data)
        self.workflow = FixtureWorkflow(self.data)
        self.root = self.workflow.location(self.sid)
        m = self.workflow.load(self.sid)
        m["fixture_source"] = "source-v1"
        compounds = [
            {"compound_id": f"c{i}", "name_zh": f"虚构成分{i}"} for i in range(15)
        ]
        receptors = [
            {
                "target_id": f"t{i}",
                "symbol": f"TEST{i}",
                "mode": "fixed_site",
                "regions": [],
                "spec": {},
            }
            for i in range(15)
        ]
        packet = {
            "study_id": self.sid,
            "trial_id": "trial_fixture",
            "compounds": compounds,
            "receptors": receptors,
            "summary": {"completed": 225, "NA": 0},
            "pairs": [
                {
                    "compound_id": c["compound_id"],
                    "target_id": r["target_id"],
                    "score": -7.0,
                }
                for c in compounds
                for r in receptors
            ],
        }
        path = self.root / "fixture_packet.json"
        write_json(path, packet)
        rec = file_record(self.root, path, "fixture_packet")
        review_path = self.root / "fixture_review.json"
        write_json(
            review_path,
            {
                "trial_id": "trial_fixture",
                "confirmed": True,
                "reviewer": "隔离",
                "note": "虚构",
            },
        )
        m["docking_trial_records"] = [
            {
                "trial_id": "trial_fixture",
                "state": "completed",
                "payload": {"expected_source": "source-v1"},
                "packet": rec,
                "files": [],
            }
        ]
        m["docking_trial_review_records"] = [
            file_record(self.root, review_path, "fixture_review")
        ]
        self.workflow.save(m)
        self.before = deepcopy(m)

    def publish(self):
        return self.workflow.publish_trial_handoff(
            self.sid, "trial_fixture", "仅隔离模拟"
        )

    def test_new_a06_pending_preserves_preparation_and_reviews(self):
        result = self.publish()
        m = self.workflow.load(self.sid)
        self.assertEqual(m["current"]["A06_PREP"], self.before["current"]["A06_PREP"])
        self.assertEqual(m["reviews"], self.before["reviews"])
        self.assertTrue(self.workflow.active(m, result["run_id"]))
        self.assertFalse(self.workflow.approved(m, result["run_id"]))
        self.assertFalse(result["summary"]["all_receptors_strict_passed"])
        self.assertEqual(len(result["tables"]["score_matrix"]), 15)
        self.assertEqual(self.publish()["run_id"], result["run_id"])

    def test_explicit_formal_review_and_old_window_guard(self):
        result = self.publish()
        self.workflow.review(
            self.sid, result["run_id"], "approved", "隔离", "模拟复核", None
        )
        self.assertTrue(
            self.workflow.approved(self.workflow.load(self.sid), result["run_id"])
        )
        with self.assertRaises(ValueError):
            self.workflow.review(
                self.sid, result["run_id"], "approved", "隔离", "旧窗口", None
            )

    def test_upstream_withdrawal_blocks_result_and_reports(self):
        result = self.publish()
        m = self.workflow.load(self.sid)
        rid = m["current"]["A04"]
        review = self.workflow.latest_review(
            m, self.workflow.run(m, rid)["artifact_id"]
        )
        self.workflow.review(
            self.sid, rid, "pending", "隔离", "撤回复核", review["review_id"]
        )
        self.assertFalse(
            self.workflow.active(self.workflow.load(self.sid), result["run_id"])
        )
        with self.assertRaises(ValueError):
            self.workflow.review(
                self.sid, result["run_id"], "approved", "隔离", "强行通过", None
            )

    def test_trial_review_change_and_source_change_block_old_result(self):
        result = self.publish()
        self.workflow.save_trial_review(
            self.sid, "trial_fixture", "新草案", "隔离", False
        )
        self.assertFalse(
            self.workflow.active(self.workflow.load(self.sid), result["run_id"])
        )
        with self.assertRaises(ValueError):
            self.publish()
        m = self.workflow.load(self.sid)
        m["fixture_source"] = "source-v2"
        self.workflow.save(m)
        with self.assertRaises(ValueError):
            self.publish()

    def test_cache_cleared_and_trash_is_read_only(self):
        self.publish()
        self.assertFalse(hasattr(self.workflow, "_view_cache"))
        m = self.workflow.load(self.sid)
        m["trashed"] = True
        self.workflow.save(m)
        with self.assertRaises(ValueError):
            self.publish()
