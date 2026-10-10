"""身份确认必须真实可提交；安全、并发、跨研究与历史边界均使用虚构研究。"""

import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from modulea.api.server import create_server
from modulea.config import load_settings
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from identity_plan_fixture import seed


class IdentityPlanApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.w, self.sid, self.payload = seed(self.root / "data")
        self.server, self.app = create_server(
            load_settings(data_root=self.root / "data", runtime_dir=self.root / "runtime"), 0
        )
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def call(self, method, tail="", body=None, token=True, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-ModuleA-Token"] = self.app.token
        if origin:
            headers["Origin"] = origin
        connection.request(
            method,
            f"/api/v1/studies/{self.sid}/modules/A04" + tail,
            json.dumps(body) if body is not None else None,
            headers,
        )
        response = connection.getresponse()
        raw = json.loads(response.read())
        status = response.status
        connection.close()
        return status, raw

    def test_actual_action_enqueues_exact_scope_and_requires_human_confirmation(self):
        status, view = self.call("GET")
        self.assertEqual(status, 200)
        self.assertTrue(view["identity_plan"]["enabled"])
        with patch.object(self.app.tasks, "_spawn"):
            status, result = self.call("POST", "/actions/identity_plan", self.payload)
        self.assertEqual(status, 202)
        self.assertEqual(result["task"]["kind"], "a04_identity")
        private = json.loads(self.app.tasks._raw(result["task"]["task_id"])["payload"])
        self.assertEqual(private["check_ids"], ["HGNC:1"])
        self.assertEqual(private["omit_ids"], [])
        self.assertNotIn("payload", result["task"])
        self.assertFalse(self.w.load(self.sid).get("identity_decisions"))
        self.assertEqual(self.call("POST", "/actions/identity_plan", self.payload)[0], 409)

    def test_rejects_missing_confirmation_unsafe_origin_token_and_foreign_scope(self):
        for changes in (
            {"confirmed": False},
            {"reviewer": " "},
            {"note": ""},
            {"check_ids": ["HGNC:999"]},
            {"omit_ids": ["HGNC:2"]},
        ):
            self.assertEqual(
                self.call("POST", "/actions/identity_plan", dict(self.payload, **changes))[0], 422
            )
        self.assertEqual(
            self.call("POST", "/actions/identity_plan", self.payload, token=False)[0], 403
        )
        self.assertEqual(
            self.call("POST", "/actions/identity_plan", self.payload, origin="https://example.com")[
                0
            ],
            403,
        )
        self.assertEqual(
            self.call(
                "POST", "/actions/identity_plan", dict(self.payload, expected_a04="run_foreign")
            )[0],
            409,
        )
        self.assertFalse(self.w.load(self.sid).get("identity_decisions"))

    def test_plan_persists_without_changing_identity_gate_and_history_is_readonly(self):
        original = self.w.result(self.w.load(self.sid), self.payload["expected_a04"])
        self.w.save_identity_plan(self.sid, self.payload)
        status, view = self.call("GET")
        self.assertEqual(status, 200)
        self.assertEqual(view["identity_plan"]["latest"]["reviewer"], "模拟核验人")
        self.assertIsNone(view["identity_plan"]["latest"]["applied_run_id"])
        self.assertTrue(view["state"]["handoff_blocked"])
        self.assertNotIn("approved", view["review"]["allowed_decisions"])
        self.assertEqual(
            self.w.result(self.w.load(self.sid), self.payload["expected_a04"]), original
        )
        self.assertEqual(self.call("POST", "/actions/identity_plan", self.payload)[0], 409)
