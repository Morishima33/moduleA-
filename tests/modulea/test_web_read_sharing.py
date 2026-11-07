"""虚构研究验证网页并发提速、写后新版本及下载完整性，不读写真实研究。"""

import http.client
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
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
from modulea.config import Settings, load_settings
from modulea.devtools.demo_data import build


class SharedViewTests(unittest.TestCase):
    """同时读取可以合并，但后续请求和不同版本不得复用旧结果。"""

    def setUp(self):
        """网页证据范围引入后，旧无路径Mock夹具改为真实临时Settings与研究登记。"""
        self.tmp = tempfile.TemporaryDirectory(prefix="shared_view_fixture_")
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name) / "data"
        self.data_root.mkdir()
        self.settings = Settings(data_root=self.data_root, runtime_dir=Path(self.tmp.name) / "runtime")

    def write_manifest(self, manifest):
        """最小登记仅供真实证据范围读取及退出复验，不伪造科学结果或人工复核。"""
        path = self.settings.studies_dir / manifest["study_id"] / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        return path

    def kernel_for(self, manifests):
        """只mock卡片上游列表；数据根及manifest保留真实I/O，不屏蔽证据范围。"""
        for manifest in manifests:
            self.write_manifest(manifest)
        kernel = Mock(settings=self.settings)
        kernel.read_workflow.return_value.studies.side_effect = lambda **kwargs: deepcopy(manifests)
        return kernel

    def assert_read_scope(self, study_id):
        """确认卡片实际进入当前研究的证据范围，避免缺manifest使范围退化为关闭。"""
        from modulea.core.read_evidence import current_evidence
        evidence = current_evidence(self.data_root)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence.study_id, study_id)

    def test_independent_studies_read_in_parallel_without_reordering(self):
        manifests = [{"study_id": sid} for sid in ("c", "a", "b")]
        views = Views(self.kernel_for(manifests), Mock())
        rendezvous = threading.Barrier(3)

        def card(sid, **kwargs):
            self.assert_read_scope(sid)
            rendezvous.wait(timeout=5)
            return {"id": sid}

        with patch.object(views, "study_card", side_effect=card):
            self.assertEqual(views._build_cards(manifests), [{"id": sid} for sid in ("c", "a", "b")])

    def test_cards_share_assembly_and_keep_independent_containers(self):
        manifest = {"study_id": "study_test", "version": 1}
        kernel = self.kernel_for([manifest])
        tasks = Mock()
        tasks.active_for.return_value = None
        views = Views(kernel, tasks)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def card(*args, **kwargs):
            self.assert_read_scope(args[0])
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
        manifest = {"study_id": "study_test", "version": 1}
        kernel, tasks = self.kernel_for([manifest]), Mock()
        tasks.active_for.return_value = None
        views = Views(kernel, tasks)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def card(*args, **kwargs):
            self.assert_read_scope(args[0])
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
                self.write_manifest(manifest)
                self.assertEqual(pool.submit(views._card_batch).result(5), [{"_states": {}}])
                tasks.active_for.return_value = {"state": "running"}
                self.assertEqual(pool.submit(views._card_batch).result(5), [{"_states": {}}])
                self.assertEqual(len(calls), 3)
            finally:
                release.set()
            # 新版本独立组装保持原断言；旧请求遇到真实登记替换，须由退出复验拒绝旧快照。
            with self.assertRaisesRegex(ContractError, "登记已改变"):
                first.result()
            self.assertFalse(views._cards_flight._pending)

    def test_result_sharing_version_boundary_and_failure_retry(self):
        views = Views(self.kernel_for([]), Mock())
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
