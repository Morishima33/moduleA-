"""隔离目录验证新建登记、请求安全、项目隔离及中断重试；不产生真实研究。"""

import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from contracts import ContractError
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.study_creation import PROJECT_FOLDERS, StudyCreation


def official_fixture(term, mesh_id):
    """仅测试中替换网络，生产环境仍由原NLM核对函数生成证据。"""
    return {"status": "verified", "mesh_id": mesh_id, "preferred_term": term,
            "mesh_year": "2026", "descriptor_resource": "https://id.nlm.nih.gov/mesh/" + mesh_id,
            "evidence": {"years_sha256": "fixture-years", "descriptor_sha256": "fixture-id", "details_sha256": "fixture-details"}}


class StudyCreationTests(unittest.TestCase):
    """所有写入发生于临时测试根，绝不对生产资料发起新建或复核。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(data_root=self.root / "data", runtime_dir=self.root / "runtime")
        self.server, self.app = create_server(self.settings, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.verifier = patch("modulea.core.study_creation.verify_mesh_identity", side_effect=official_fixture)
        self.mock_verify = self.verifier.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.verifier.stop()
        self.temp.cleanup()

    def fields(self):
        """虚构的疾病名称与编号，不向外部发送。"""
        return {"request_id": "create_" + uuid4().hex, "formula": "隔离测试方剂", "herbs": "测试药甲、测试药乙",
                "disease": "虚构疾病", "mesh_term": "Fixture disease", "mesh_id": "D123456",
                "operator": "隔离核验", "analysis_purpose": "workflow_test"}

    def call(self, body, token=True, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=30)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-ModuleA-Token"] = self.app.token
        if origin:
            headers["Origin"] = origin
        conn.request("POST", "/api/v1/studies", json.dumps(body), headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def test_new_study_has_six_private_folders_only_a00_and_no_review_or_task(self):
        body = self.fields()
        body["formula"] = "../名称不作为路径"
        status, result = self.call(body)
        self.assertEqual(status, 201, result)
        location = Path(result["directory"])
        self.assertEqual(location.parent, self.settings.studies_dir.resolve())
        for row in PROJECT_FOLDERS:
            self.assertTrue((location / row["name"]).is_dir())
        workflow = self.app.kernel.workflow()
        manifest = workflow.load(result["study_id"])
        self.assertEqual(set(manifest["current"]), {"A00"})
        self.assertEqual(manifest["workflow_profile"], "A00.preupload.2")
        self.assertEqual(manifest["reviews"], [])
        self.assertEqual(self.app.tasks.list(), [])
        saved = workflow.result(manifest, result["run_id"])["summary"]
        self.assertEqual(saved["species"], 9606)
        self.assertEqual(saved["disease_scope"], "仅本病，不纳入亚型")
        self.assertEqual(saved["analysis_purpose"], "workflow_test")
        storage = self.app.views.study(result["study_id"])["storage"]
        self.assertEqual(storage["directory"], result["directory"])
        self.assertEqual(storage["folders"], PROJECT_FOLDERS)

    def test_same_disease_new_request_is_separate_and_old_manifest_unchanged(self):
        body = self.fields()
        _, first = self.call(body)
        old = Path(first["directory"]) / "manifest.json"
        before = hashlib.sha256(old.read_bytes()).hexdigest()
        body["request_id"] = "create_" + uuid4().hex
        body["analysis_purpose"] = "formal_research"
        status, second = self.call(body)
        self.assertEqual(status, 201, second)
        self.assertNotEqual(first["study_id"], second["study_id"])
        self.assertNotEqual(first["directory"], second["directory"])
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(), before)
        self.assertEqual(self.app.kernel.workflow().load(second["study_id"])["reviews"], [])

    def test_concurrent_duplicate_submission_creates_once(self):
        body = self.fields()
        barrier = threading.Barrier(2)

        def submit():
            barrier.wait()
            return self.call(body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sorted(row[0] for row in results), [200, 201])
        self.assertEqual(results[0][1]["study_id"], results[1][1]["study_id"])
        self.assertEqual(self.mock_verify.call_count, 1)
        self.assertEqual(len(list(self.settings.studies_dir.iterdir())), 1)

    def test_restart_and_lost_runtime_record_recover_original_a00(self):
        body = self.fields()
        _, first = self.call(body)
        ledger = self.settings.runtime_dir / "study-creation" / (body["request_id"] + ".json")
        ledger.unlink()
        self.app.creation = StudyCreation(self.app.kernel)
        status, second = self.call(body)
        self.assertEqual(status, 200, second)
        self.assertEqual(first["study_id"], second["study_id"])
        self.assertEqual(self.mock_verify.call_count, 1)
        body["disease"] = "修改后的疾病"
        status, error = self.call(body)
        self.assertEqual(status, 409, error)

    def test_network_or_identity_failure_does_not_create_study(self):
        for reason, expected in [("暂时无法连接NLM官方MeSH服务", 503), ("MeSH首选词与编号不一致", 422)]:
            self.mock_verify.side_effect = ContractError(reason)
            status, error = self.call(self.fields())
            self.assertEqual(status, expected, error)
        self.assertFalse(self.settings.studies_dir.exists())
        self.assertEqual(self.app.tasks.list(), [])

    def test_missing_purpose_extra_evidence_and_invalid_id_are_rejected_before_network(self):
        for change in [{"analysis_purpose": ""}, {"mesh_verification": official_fixture("forged", "D123456")}, {"request_id": "../outside"}, {"mesh_id": "123456"}, {"directory": "C:/outside"}]:
            status, error = self.call(dict(self.fields(), **change))
            self.assertEqual(status, 422, error)
        self.mock_verify.assert_not_called()
        self.assertFalse(self.settings.studies_dir.exists())

    def test_write_security_and_capability(self):
        for token, origin in [(False, None), (True, "https://invalid.example")]:
            status, error = self.call(self.fields(), token=token, origin=origin)
            self.assertEqual(status, 403, error)
        self.assertTrue(self.app.session(None)["capabilities"]["create_study"])
        self.mock_verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
