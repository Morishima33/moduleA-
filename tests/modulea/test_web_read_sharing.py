"""虚构研究验证网页并发提速、写后新版本及下载完整性，不读写真实研究。"""

import http.client
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from contracts import ContractError
from modulea.api.server import create_server
from modulea.api.views import Views
from modulea.config import load_settings
from modulea.devtools.demo_data import build


class SharedViewTests(unittest.TestCase):
    """同时读取可以合并，但后续请求和不同版本不得复用旧结果。"""

    def test_independent_studies_read_in_parallel_without_reordering(self):
        views = Views(Mock(), Mock())
        rendezvous = threading.Barrier(3)

        def card(sid, **kwargs):
            rendezvous.wait(timeout=5)
            return {"id": sid}

        manifests = [{"study_id": sid} for sid in ("c", "a", "b")]
        with patch.object(views, "study_card", side_effect=card):
            self.assertEqual(views._build_cards(manifests), [{"id": sid} for sid in ("c", "a", "b")])

    def test_cards_share_assembly_and_keep_independent_containers(self):
        manifest = {"study_id": "study_test", "version": 1}
        kernel = Mock()
        kernel.read_workflow.return_value.studies.return_value = [manifest]
        tasks = Mock()
        tasks.active_for.return_value = None
        views = Views(kernel, tasks)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def card(*args, **kwargs):
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(10))
            return {"study": {"updated_at": "2026"}, "_states": {}}

        with patch.object(views, "study_card", side_effect=card), ThreadPoolExecutor(2) as pool:
            first = pool.submit(views.study_cards)
            self.assertTrue(entered.wait(10))
            second = pool.submit(views._card_batch)
            future = next(iter(views._cards_flight._pending.values()))
            with future._condition:
                self.assertTrue(future._condition.wait_for(lambda: bool(future._condition._waiters), timeout=5))
            release.set()
            a, b = first.result(), second.result()
            self.assertEqual(len(calls), 1)
            self.assertNotIn("_states", a[0])
            self.assertIn("_states", b[0])
            a[0]["study"]["updated_at"] = "changed"
            self.assertEqual(b[0]["study"]["updated_at"], "2026")
            views.study_cards()
            self.assertEqual(len(calls), 2)

    def test_changed_manifest_and_task_do_not_join_inflight_cards(self):
        kernel, tasks = Mock(), Mock()
        manifest = {"study_id": "study_test", "version": 1}
        kernel.read_workflow.return_value.studies.side_effect = lambda **kwargs: [dict(manifest)]
        tasks.active_for.return_value = None
        views = Views(kernel, tasks)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def card(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(10))
            return {"_states": {}}

        with patch.object(views, "study_card", side_effect=card), ThreadPoolExecutor(2) as pool:
            first = pool.submit(views._card_batch)
            self.assertTrue(entered.wait(10))
            try:
                manifest["version"] = 2
                self.assertEqual(pool.submit(views._card_batch).result(5), [{"_states": {}}])
                tasks.active_for.return_value = {"state": "running"}
                self.assertEqual(pool.submit(views._card_batch).result(5), [{"_states": {}}])
                self.assertEqual(len(calls), 3)
            finally:
                release.set()
            first.result()

    def test_result_sharing_version_boundary_and_failure_retry(self):
        views = Views(Mock(), Mock())
        workflow = Mock()
        manifest = {"study_id": "study_test", "runs": {"run_test": {"sha": "v1"}}}
        entered, release = threading.Event(), threading.Event()

        def read(*args):
            entered.set()
            self.assertTrue(release.wait(10))
            return {"rows": [1]}

        workflow.result.side_effect = read
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(views._read_result, workflow, manifest, "run_test")
            self.assertTrue(entered.wait(10))
            second = pool.submit(views._read_result, workflow, manifest, "run_test")
            future = next(iter(views._result_flight._pending.values()))
            with future._condition:
                self.assertTrue(future._condition.wait_for(lambda: bool(future._condition._waiters), timeout=5))
            release.set()
            a, b = first.result(), second.result()
        self.assertEqual(workflow.result.call_count, 1)
        a["rows"].append(2)
        self.assertEqual(b, {"rows": [1]})
        manifest["runs"]["run_test"]["sha"] = "v2"
        workflow.result.side_effect = ContractError("bad bytes")
        with self.assertRaises(ContractError):
            views._read_result(workflow, manifest, "run_test")
        workflow.result.side_effect = None
        workflow.result.return_value = {"rows": [3]}
        self.assertEqual(views._read_result(workflow, manifest, "run_test"), {"rows": [3]})
        self.assertEqual(workflow.result.call_count, 3)


class StreamingTests(unittest.TestCase):
    """实际HTTP校验分块发送的字节、响应头及篡改阻断。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.sid = build(cls.root / "data")
        static = cls.root / "static"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><title>isolated</title>", encoding="utf-8")
        cls.payload = bytes(range(256)) * 4097
        (static / "sample.png").write_bytes(cls.payload)
        cls.server, cls.app = create_server(load_settings(data_root=cls.root / "data", runtime_dir=cls.root / "runtime", static_dir=static), 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=30)
        conn.request("GET", path)
        response = conn.getresponse()
        status, headers, data = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, headers, data

    def test_static_stream_retains_all_bytes_and_security_headers(self):
        status, headers, data = self.get("/sample.png")
        self.assertEqual(status, 200)
        self.assertEqual(data, self.payload)
        self.assertEqual(int(headers["Content-Length"]), len(self.payload))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("Content-Security-Policy", headers)

    def test_selected_archive_file_is_verified_again_after_download(self):
        workflow = self.app.kernel.read_workflow()
        manifest = workflow.load(self.sid)
        rid = manifest["current"]["A07"]
        result = workflow.result(manifest, rid)
        record = result["files"][0]
        target = workflow.location(self.sid) / record["path"]
        path = f"/api/v1/studies/{self.sid}/files/{rid}.0"
        status, headers, data = self.get(path)
        self.assertEqual(status, 200)
        self.assertEqual(data, target.read_bytes())
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        target.write_bytes(data + b"tamper")
        self.assertNotEqual(self.get(path)[0], 200)


if __name__ == "__main__":
    unittest.main()
