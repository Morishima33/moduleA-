"""新架构接口层的契约测试。

使用临时目录中的虚构研究（devtools.demo_data 的内置数据），不读取、不修改任何真实研究。
运行：PYTHONPATH=src python3 -m unittest discover -s tests/modulea -v
"""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from modulea.api.server import create_server  # noqa: E402
from modulea.config import load_settings  # noqa: E402
from modulea.core import modules as registry  # noqa: E402
from modulea.core.status import map_state  # noqa: E402
from modulea.devtools.demo_data import build  # noqa: E402


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        data_root = Path(cls.tmp.name) / "data"
        cls.study = build(data_root)
        settings = load_settings(data_root=str(data_root), runtime_dir=str(Path(cls.tmp.name) / "runtime"))
        cls.server, cls.app = create_server(settings, 0)
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    # ---- 辅助 ----
    def call(self, method, path, body=None, token=True, host=None, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token and method == "POST":
            headers["X-ModuleA-Token"] = self.app.token
        if origin:
            headers["Origin"] = origin
        conn.request(method, path, json.dumps(body or {}) if method == "POST" else None, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            return response.status, json.loads(data)
        except ValueError:
            return response.status, data

    # ---- 读取 ----
    def test_session_and_studies(self):
        status, body = self.call("GET", "/api/v1/session")
        self.assertEqual(status, 200)
        self.assertEqual(body["token"], self.app.token)
        status, body = self.call("GET", "/api/v1/studies")
        self.assertEqual(status, 200)
        card = body["items"][0]
        self.assertEqual(card["study"]["study_id"], self.study)
        self.assertEqual(card["progress"]["total"], len(registry.ORDER))
        self.assertEqual(card["next_step"]["module_id"], "A07")
        self.assertEqual(card["purpose"]["analysis_purpose"], "workflow_test")

    def test_every_module_view(self):
        for module in registry.ORDER:
            status, body = self.call("GET", f"/api/v1/studies/{self.study}/modules/{module}")
            self.assertEqual(status, 200, (module, body))
            for key in ("module", "state", "kpis", "flow", "focus", "params", "review", "downstream", "trace", "files", "tables", "history"):
                self.assertIn(key, body, (module, key))
        status, body = self.call("GET", f"/api/v1/studies/{self.study}/modules/A06")
        heat = body["special"]["heatmap"]
        self.assertEqual([r["name"] for r in heat["receptors"]], ["GENE1"])  # 整列 NA 的受体不进入图面
        self.assertEqual(heat["omitted"][0]["name"], "GENE2")
        status, body = self.call("GET", f"/api/v1/studies/{self.study}/modules/A07")
        self.assertEqual(body["state"]["code"], "review")
        self.assertEqual(len(body["focus"]), 3)

    def test_table_paging_and_unknown(self):
        status, body = self.call("GET", f"/api/v1/studies/{self.study}/modules/A01/tables/herb_summary?size=1&page=2")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["items"]), 1)
        status, body = self.call("GET", f"/api/v1/studies/{self.study}/modules/A01/tables/nothing")
        self.assertEqual(status, 404)
        status, body = self.call("GET", "/api/v1/studies/study_00000000000000000000000000000000")
        self.assertEqual(status, 404)

    # ---- 安全 ----
    def test_security_checks(self):
        status, body = self.call("GET", "/api/v1/session", host="evil.example:80")
        self.assertEqual(body["error"]["code"], "FORBIDDEN_ORIGIN")
        status, body = self.call("POST", f"/api/v1/studies/{self.study}:continue", token=False)
        self.assertEqual(body["error"]["code"], "BAD_TOKEN")
        status, body = self.call("POST", f"/api/v1/studies/{self.study}:continue", origin="http://evil.example")
        self.assertEqual(body["error"]["code"], "FORBIDDEN_ORIGIN")
        status, body = self.call("GET", f"/api/v1/studies/{self.study}/files/run_x.99")
        self.assertIn(status, (400, 404))

    # ---- 复核 ----
    def test_review_flow_and_stale_version(self):
        status, view = self.call("GET", f"/api/v1/studies/{self.study}/modules/A07")
        review = view["review"]
        payload = {"run_id": review["run_id"], "expected_review_id": review["expected_review_id"], "decision": "pending",
                   "reviewer": "测试", "note": "暂存", "after": "save"}
        status, body = self.call("POST", f"/api/v1/studies/{self.study}/modules/A07/reviews", payload)
        self.assertEqual(status, 201, body)
        self.assertIsNone(body["task"])
        # 用旧页面的 expected_review_id 再提交一次，必须被拒绝
        status, body = self.call("POST", f"/api/v1/studies/{self.study}/modules/A07/reviews", payload)
        self.assertEqual(body["error"]["code"], "STALE_VERSION")
        # 空意见被拒绝
        status, view = self.call("GET", f"/api/v1/studies/{self.study}/modules/A07")
        bad = dict(payload, expected_review_id=view["review"]["expected_review_id"], note="")
        status, body = self.call("POST", f"/api/v1/studies/{self.study}/modules/A07/reviews", bad)
        self.assertEqual(status, 422)
        status, view = self.call("GET", f"/api/v1/studies/{self.study}/modules/A07")
        self.assertEqual(view["state"]["code"], "hold")

    def test_trash_roundtrip(self):
        status, study = self.call("GET", f"/api/v1/studies/{self.study}")
        expected = study["management"]["expected_action_id"]
        status, body = self.call("POST", f"/api/v1/studies/{self.study}:trash", {"operator": "测试", "reason": "测试", "expected_action_id": expected})
        self.assertEqual(status, 422)  # 未勾选确认
        status, body = self.call("POST", f"/api/v1/studies/{self.study}:trash", {"operator": "测试", "reason": "测试", "expected_action_id": expected, "confirm": True})
        self.assertEqual(status, 201, body)
        status, body = self.call("GET", "/api/v1/trash")
        self.assertEqual(len(body["items"]), 1)
        # 回收站中照常显示原状态（不是“已失效”），但不能复核
        status, view = self.call("GET", f"/api/v1/studies/{self.study}/modules/A04")
        self.assertEqual(view["state"]["code"], "approved")
        self.assertFalse(view["review"]["can_review"])
        status, view = self.call("GET", f"/api/v1/studies/{self.study}/modules/A07")
        self.assertFalse(view["review"]["continue"]["available"])
        self.assertIn("最后一步", view["review"]["continue"]["note_zh"])
        status, study = self.call("GET", f"/api/v1/studies/{self.study}")
        status, body = self.call("POST", f"/api/v1/studies/{self.study}:restore",
                                 {"operator": "测试", "reason": "恢复", "expected_action_id": study["management"]["expected_action_id"], "confirm": True})
        self.assertEqual(status, 201, body)


class StatusMappingTest(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(map_state("A04", {"state": "waiting"}).code, "idle")
        self.assertEqual(map_state("A04", {"state": "running"}).code, "incomplete")
        self.assertEqual(map_state("A04", {"state": "running"}, task_active=True).code, "running")
        self.assertEqual(map_state("A04", {"state": "awaiting_review", "result": {"outcome": "empty", "summary": {}}}).code, "empty")
        self.assertEqual(map_state("A02", {"state": "awaiting_review", "result": {"outcome": "success", "summary": {"handoff_blocked": True}}}).code, "waiting")
        self.assertEqual(map_state("A07", {"state": "approved"}).code, "published")
        self.assertEqual(map_state("A04", {"state": "rejected"}).code, "returned")

    def test_downstream(self):
        self.assertEqual(registry.dependents("A05"), ["A07"])
        self.assertIn("A06", registry.dependents("A03_SELECT"))
        self.assertNotIn("A05", registry.dependents("A04"))


if __name__ == "__main__":
    unittest.main()
