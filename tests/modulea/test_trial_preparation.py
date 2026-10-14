"""隔离虚构研究验证准备关联、审批保护、来源失效及只读文件索引。"""

import unittest
from copy import deepcopy

import test_trial_handoff as handoff_tests
from test_trial_handoff import FixtureWorkflow

from modulea.api.errors import ApiError
from modulea.api.trial_preparation_view import present_context
from modulea.api.views import Views
from modulea.config import Settings
from modulea.core.kernel import Kernel
from modulea.core.status import map_state
from modulea.core.trial_preparation_workflow import TrialPreparationWorkflow
from modulea.tasks.manager import TaskManager
from storage import file_record, read_json, write_json


class PreparationFixture(TrialPreparationWorkflow, FixtureWorkflow):
    """只替代已有来源绑定，实际写锁、审批、文件核验使用生产实现。"""


class PreparationTests(unittest.TestCase):
    def setUp(self):
        handoff_tests.HandoffTests.setUp(self)
        self.workflow = PreparationFixture(self.data)
        m = self.workflow.load(self.sid)
        rec = m["docking_trial_records"][-1]
        packet_path = self.root / rec["packet"]["path"]
        packet = read_json(packet_path)
        for c in packet["compounds"]:
            c.update(
                state="ready",
                cid="1",
                preparation={"identity": {"identity_check": "matched"}},
            )
            c["files"] = []
            for role in ("source_3d", "prepared_ligand"):
                path = self.root / (c["compound_id"] + role + ".txt")
                path.write_text("isolated structure", encoding="utf8")
                c["files"].append(file_record(self.root, path, role))
        for r in packet["receptors"]:
            path = self.root / (r["target_id"] + ".pdbqt")
            path.write_text("isolated receptor", encoding="utf8")
            r.update(
                state="ready",
                receptor=file_record(self.root, path, "prepared_receptor"),
                source=file_record(self.root, path, "source_original"),
            )
        packet_path = self.root / "fixture_preparation_packet.json"
        write_json(packet_path, packet)
        rec["packet"] = file_record(self.root, packet_path, "fixture_packet")
        self.workflow.save(m)
        result = self.workflow.publish_trial_handoff(self.sid, "trial_fixture", "隔离")
        self.rid = result["run_id"]
        self.review = self.workflow.review(
            self.sid, self.rid, "approved", "原核验人", "仅隔离模拟批准", None
        )

    def link(self):
        return self.workflow.link_trial_preparation(
            self.sid, self.rid, self.review["review_id"], "隔离关联，沿用已有核查"
        )

    def test_link_is_idempotent_and_never_changes_runs_or_reviews(self):
        before = self.workflow.load(self.sid)
        link = self.link()
        self.assertEqual(self.link()["link_id"], link["link_id"])
        after = self.workflow.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(before[key], after[key])
        self.assertFalse(hasattr(self.workflow, "_view_cache"))
        self.assertNotIn("approval", link)

    def test_context_status_and_downloads_use_confirmed_sources(self):
        self.link()
        view = self.workflow.view(self.sid)
        context = view["trial_preparation"]
        self.assertTrue(context["active"])
        self.assertTrue(context["read_only"])
        self.assertEqual(len(context["receptors"]), 15)
        self.assertEqual(len(context["compounds"]), 15)
        raw = next(r for r in view["modules"] if r["module_id"] == "A06_PREP")
        state = map_state("A06_PREP", raw)
        self.assertEqual(state.code, "scope_confirmed")
        self.assertFalse(state.can_review)
        self.assertFalse(state.handoff_blocked)
        self.assertNotEqual(state.code, "approved")
        info = present_context(self.sid, context)
        self.assertIn("/files/prep_link_", info["compounds"][0]["files"][0]["url"])

    def test_a06_review_change_invalidates_link(self):
        self.link()
        self.workflow.review(
            self.sid, self.rid, "pending", "隔离", "撤回", self.review["review_id"]
        )
        context = self.workflow.trial_preparation_context(self.workflow.load(self.sid))
        self.assertFalse(context["active"])
        self.assertEqual(context["receptors"], [])
        self.assertIn("?run_id=" + self.rid, context["result_url"])
        with self.assertRaises(ValueError):
            self.link()

    def test_preparation_bytes_and_source_changes_invalidate(self):
        link = self.link()
        f = self.root / link["binding"]["preparation_files"][0]["path"]
        original = f.read_bytes()
        f.write_bytes(b"changed")
        self.assertFalse(
            self.workflow.trial_preparation_context(self.workflow.load(self.sid))[
                "active"
            ]
        )
        f.write_bytes(original)
        m = self.workflow.load(self.sid)
        m["fixture_source"] = "new-source"
        self.workflow.save(m)
        self.assertFalse(self.workflow.trial_preparation_context(m)["active"])

    def test_old_review_request_and_cross_study_cannot_create_link(self):
        with self.assertRaises(ValueError):
            self.workflow.link_trial_preparation(
                self.sid, self.rid, "review_outdated", "隔离"
            )
        with self.assertRaises(ValueError):
            self.workflow.link_trial_preparation(
                self.sid, "run_other", self.review["review_id"], "隔离"
            )
        self.assertNotIn("trial_preparation_link_records", self.workflow.load(self.sid))

    def test_no_link_preserves_legacy_state_and_trash_blocks_writes(self):
        before = self.workflow.view(self.sid)
        self.assertIsNone(before["trial_preparation"])
        self.assertNotEqual(
            next(r for r in before["modules"] if r["module_id"] == "A06_PREP")["state"],
            "scope_confirmed",
        )
        self.link()
        m = self.workflow.load(self.sid)
        m["trashed"] = True
        self.workflow.save(m)
        with self.assertRaises(ValueError):
            self.link()
        self.assertFalse(self.workflow.trial_preparation_context(m)["active"])

    def test_trial_review_update_invalidates_link_without_rewriting_it(self):
        self.link()
        before = deepcopy(
            self.workflow.load(self.sid)["trial_preparation_link_records"]
        )
        self.workflow.save_trial_review(
            self.sid, "trial_fixture", "新草案", "隔离", False
        )
        m = self.workflow.load(self.sid)
        self.assertFalse(self.workflow.trial_preparation_context(m)["active"])
        self.assertEqual(before, m["trial_preparation_link_records"])

    def test_reused_sources_require_matching_prepared_fingerprint_and_identity(self):
        m = self.workflow.load(self.sid)
        packet = read_json(self.root / m["docking_trial_records"][-1]["packet"]["path"])
        row = packet["receptors"][0]
        original = deepcopy(row["source"])
        row.update(
            source=None, reused=True, structure_id="TEST", spec={"uniprot": "fixture"}
        )
        source = {
            "study_id": self.sid,
            "review_id": "source_fixture",
            "receptors": [
                {
                    "target_id": row["target_id"],
                    "pdb_id": "TEST",
                    "identity_matched": True,
                    "spec": row["spec"],
                    "file_key": "f1",
                }
            ],
            "files": [{"key": "f1", "file": original}],
        }
        source_path = self.root / "source_fixture.json"
        write_json(source_path, source)
        m["source_review_records"] = [
            file_record(self.root, source_path, "source_review")
        ]
        base = {
            "receptors": [
                {
                    "target_id": row["target_id"],
                    "selected": {
                        "receptor": row["receptor"],
                        "identity": {"source_review_id": "source_fixture"},
                    },
                }
            ]
        }
        base_path = self.root / "base_fixture.json"
        write_json(base_path, base)
        packet["base_packet"] = file_record(self.root, base_path, "base")
        resolved, evidence = self.workflow._resolve_preparation_sources(m, packet)
        self.assertEqual(resolved["receptors"][0]["source"], original)
        self.assertIsNone(packet["receptors"][0]["source"])
        self.assertEqual(len(evidence), 2)
        packet["receptors"][0]["receptor"] = dict(row["receptor"], sha256="wrong")
        with self.assertRaises(ValueError):
            self.workflow._resolve_preparation_sources(m, packet)

    def test_downloads_reject_out_of_range_and_foreign_study(self):
        link = self.link()
        settings = Settings(data_root=self.data, runtime_dir=self.data / "runtime")
        views = Views(Kernel(settings), TaskManager(settings))
        path, _, _ = views.file(self.sid, link["link_id"] + ".0")
        self.assertTrue(path.is_file())
        for sid, suffix in [
            (self.sid, ".999999"),
            (self.sid, ".-1"),
            ("study_other", ".0"),
        ]:
            with self.assertRaises(ApiError):
                views.file(sid, link["link_id"] + suffix)
