"""隔离验证方案接口、草稿幂等和历史保护；不创建真实研究或启动计算。"""

from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from modulea.api.server import create_server
from modulea.config import Settings
from science_modules.analysis_protocol import VERSION, compile_plan


class AnalysisPlanApiTests(unittest.TestCase):
    """所有研究及运行索引均位于临时目录，网络和科学工具没有执行入口。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="modulea_plan_")
        self.root = Path(self.temp.name)
        self.settings = Settings(data_root=self.root / "data", runtime_dir=self.root / "runtime")
        self.server, self.app = create_server(self.settings, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.workflow = self.app.kernel.workflow()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def study(self, modern=True):
        fields = {"formula": "虚构方案方", "herbs": "虚构药", "disease": "虚构病", "disease_scope": "仅本病",
                  "species": 9606, "operator": "隔离测试", "analysis_purpose": "workflow_test"}
        if modern:
            fields["analysis_plan_profile"] = VERSION
        return self.workflow.create(fields, kind="contract_test")

    def call(self, method, path, body=None, token=True, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-ModuleA-Token"] = self.app.token
        if origin:
            headers["Origin"] = origin
        conn.request(method, "/api/v1" + path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def draft(self, sid, **changes):
        a00 = self.workflow.load(sid)["current"]["A00"]
        return dict({"request_id": "planreq_" + uuid4().hex, "expected_a00": a00, "expected_draft_id": "",
                     "specification": {"mode": "personalized"}, "author": "隔离测试", "note": "不运行"}, **changes)

    def test_catalog_and_validation_are_read_only_and_do_not_offer_execution(self):
        status, catalog = self.call("GET", "/analysis-plans/parameters")
        self.assertEqual(status, 200)
        self.assertFalse(catalog["execution_ready"])
        baseline = compile_plan({"mode": "personalized"})
        status, result = self.call("POST", "/analysis-plans/validate", {"specification": {"mode": "personalized", "parameters": {"a05.go_plot_top": 25}}, "previous": baseline})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["impact"]["stages"], ["A05_DISPLAY", "A07"])
        self.assertFalse(result["execution_available"])
        self.assertFalse(self.settings.studies_dir.exists())
        self.assertEqual(self.app.tasks.list(), [])

    def test_invalid_and_untrusted_inputs_are_rejected(self):
        for body in [{"specification": {"mode": "personalized", "parameters": {"species": 10090}}},
                     {"specification": {"mode": "standard", "parameters": {"a01.ob_min": 40}}},
                     {"specification": {"mode": "personalized"}, "execute": True}]:
            status, result = self.call("POST", "/analysis-plans/validate", body)
            self.assertEqual(status, 422, result)
        for token, origin in [(False, None), (True, "https://invalid.example")]:
            status, _ = self.call("POST", "/analysis-plans/validate", {"specification": {"mode": "standard"}}, token=token, origin=origin)
            self.assertEqual(status, 403)
        self.assertFalse(self.settings.studies_dir.exists())

    def test_draft_is_immutable_idempotent_and_never_changes_runs_or_reviews(self):
        sid = self.study()
        before = self.workflow.load(sid)
        body = self.draft(sid)
        path = f"/studies/{sid}/analysis-plan/drafts"
        status, first = self.call("POST", path, body)
        self.assertEqual(status, 201, first)
        status, duplicate = self.call("POST", path, body)
        self.assertEqual(status, 200, duplicate)
        self.assertEqual(duplicate["draft"], first["draft"])
        self.assertFalse(first["execution_available"])
        self.assertFalse(first["draft"]["applies_to_running_batch"])
        after = self.workflow.load(sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(after["analysis_plan_records"]), 1)
        self.assertEqual(self.app.tasks.list(), [])
        status, _ = self.call("POST", path, dict(body, note="内容不同"))
        self.assertEqual(status, 409)

    def test_stale_draft_is_rejected_and_original_record_is_preserved(self):
        sid = self.study()
        path = f"/studies/{sid}/analysis-plan/drafts"
        body = self.draft(sid)
        _, first = self.call("POST", path, body)
        original_ref = self.workflow.load(sid)["analysis_plan_records"][0]
        original = self.workflow.location(sid) / original_ref["path"]
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        status, _ = self.call("POST", path, self.draft(sid))
        self.assertEqual(status, 409)
        next_body = self.draft(sid, expected_draft_id=first["draft"]["plan_id"],
                               specification={"mode": "personalized", "parameters": {"a01.ob_min": 40}})
        status, second = self.call("POST", path, next_body)
        self.assertEqual(status, 201, second)
        self.assertEqual(second["draft"]["parent_draft_id"], first["draft"]["plan_id"])
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
        status, view = self.call("GET", f"/studies/{sid}/analysis-plan")
        self.assertEqual(status, 200)
        self.assertEqual(view["draft"]["plan_id"], second["draft"]["plan_id"])

    def test_history_trash_cross_study_and_a00_changes_cannot_be_used_to_save(self):
        legacy = self.study(False)
        manifest = self.workflow.location(legacy) / "manifest.json"
        before = manifest.read_bytes()
        status, view = self.call("GET", f"/studies/{legacy}/analysis-plan")
        self.assertEqual(status, 200)
        self.assertFalse(view["supported"])
        self.assertEqual(self.call("POST", f"/studies/{legacy}/analysis-plan/drafts", self.draft(legacy))[0], 422)
        self.assertEqual(before, manifest.read_bytes())
        first, second = self.study(), self.study()
        status, _ = self.call("POST", f"/studies/{second}/analysis-plan/drafts", self.draft(first))
        self.assertEqual(status, 409)
        body = self.draft(first)
        self.workflow.set_trashed(first, True, "隔离测试", "仅测试")
        self.assertEqual(self.call("POST", f"/studies/{first}/analysis-plan/drafts", body)[0], 423)

    def test_running_task_keeps_its_payload_and_state_while_new_draft_is_saved(self):
        sid = self.study()
        with patch.object(self.app.tasks, "_spawn"):
            task, created = self.app.tasks.submit(sid, "continue", "隔离测试", {"plan": "original"})
        self.assertTrue(created)
        before = deepcopy(self.app.tasks._raw(task["task_id"]))
        status, result = self.call("POST", f"/studies/{sid}/analysis-plan/drafts", self.draft(sid))
        self.assertEqual(status, 201, result)
        self.assertEqual(self.app.tasks._raw(task["task_id"]), before)

    def test_changed_registration_invalidates_old_draft_without_destroying_history(self):
        sid = self.study()
        body = self.draft(sid)
        path = f"/studies/{sid}/analysis-plan/drafts"
        _, original = self.call("POST", path, body)
        manifest = self.workflow.load(sid)
        intake = dict(self.workflow.result(manifest, body["expected_a00"])["summary"], formula="修改后的虚构方")
        new_a00 = self.workflow.revise_intake(sid, intake, "隔离测试修改登记", body["expected_a00"])
        self.assertEqual(self.call("POST", path, body)[0], 409)
        status, view = self.call("GET", f"/studies/{sid}/analysis-plan")
        self.assertEqual(status, 200)
        self.assertIsNone(view["draft"])
        self.assertEqual(view["history_count"], 1)
        new_body = self.draft(sid, expected_draft_id=original["draft"]["plan_id"])
        self.assertEqual(new_body["expected_a00"], new_a00)
        self.assertEqual(self.call("POST", path, new_body)[0], 201)

    def test_tampered_archive_and_unknown_fields_are_blocked(self):
        sid = self.study()
        path = f"/studies/{sid}/analysis-plan/drafts"
        body = self.draft(sid)
        self.assertEqual(self.call("POST", path, dict(body, confirmed=True))[0], 422)
        self.assertEqual(self.call("POST", path, body)[0], 201)
        reference = self.workflow.load(sid)["analysis_plan_records"][0]
        (self.workflow.location(sid) / reference["path"]).write_text("{}", encoding="utf-8")
        status, _ = self.call("GET", f"/studies/{sid}/analysis-plan")
        self.assertEqual(status, 503)


if __name__ == "__main__":
    unittest.main()
