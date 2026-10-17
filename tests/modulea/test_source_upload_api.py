"""分库HTTP安全、模板与私有任务输入回归；使用临时虚构研究。"""
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from modulea.api.server import create_server
from modulea.config import load_settings
from modulea.devtools.demo_data import build

class SourceUploadApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        data = self.root / "data"; self.sid = build(data)
        self.server, self.app = create_server(load_settings(data_root=data, runtime_dir=self.root / "runtime"), 0)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.temp.cleanup()
    def call(self, method, path, body=None, content_type="application/json", token=True, origin=None):
        headers = {"Content-Type": content_type}
        if token: headers["X-ModuleA-Token"] = self.app.token
        if origin: headers["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.request(method, path, body, headers); response = conn.getresponse(); raw = response.read(); status = response.status; conn.close()
        try: return status, json.loads(raw)
        except ValueError: return status, raw
    def endpoint(self, tail="sources", module="A01"): return f"/api/v1/studies/{self.sid}/modules/{module}/{tail}"
    def form(self, **changes):
        status, info = self.call("GET", self.endpoint()); self.assertEqual(status, 200)
        fields = {k: info[k] for k in ("expected_a00", "expected_run", "expected_staging")}
        fields.update(database="TCMSP", format="source_zip", confirmed="yes", query="fixture", retrieved_at="2026-10-09", version="fixture", source_url="fixture", reason="fixture", encoding="utf-8-sig")
        fields.update(changes); boundary="upload-fixture"
        body=b""
        for key,value in fields.items(): body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="upload"; filename="fixture.zip"\r\nContent-Type: application/zip\r\n\r\n').encode() + b"fixture" + (f'\r\n--{boundary}--\r\n').encode()
        return body, "multipart/form-data; boundary=" + boundary

    def test_names_templates_and_history_are_read_only(self):
        status, info = self.call("GET", self.endpoint()); self.assertEqual(status, 200)
        self.assertEqual([s["label_zh"] for s in info["sources"]], ["TCMSP", "HERB", "BATMAN-TCM"])
        path=info["sources"][0]["formats"][0]["template_url"]
        status, data = self.call("GET", path); self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as z: self.assertEqual(json.loads(z.read("modulea_source.json"))["database"], "TCMSP")
        self.assertEqual(self.app.tasks.list(self.sid), [])

    def test_upload_token_origin_and_versions(self):
        data,mime=self.form()
        status,_=self.call("POST",self.endpoint("actions/upload"),data,mime,token=False);self.assertEqual(status,403)
        status,_=self.call("POST",self.endpoint("actions/upload"),data,mime,origin="https://outside.invalid");self.assertEqual(status,403)
        data,mime=self.form(expected_run="run_other_study")
        status,value=self.call("POST",self.endpoint("actions/upload"),data,mime);self.assertEqual(status,409);self.assertEqual(value["error"]["code"],"STALE_VERSION")
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def test_unknown_database_or_format_is_not_queued(self):
        for change in ({"database":"GeneCards"},{"format":"names"},{"confirmed":"no"}):
            data,mime=self.form(**change)
            status,_=self.call("POST",self.endpoint("actions/upload"),data,mime);self.assertEqual(status,422)
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def test_task_inputs_are_private_and_retry_keeps_source(self):
        data,mime=self.form()
        with patch.object(self.app.tasks,"_spawn"):
            status,result=self.call("POST",self.endpoint("actions/upload"),data,mime)
            self.assertEqual(status,202);task=result["task"];self.assertNotIn("payload",task)
            private=self.app.tasks._raw(task["task_id"]);payload=json.loads(private["payload"])
            self.assertEqual((self.app.settings.runtime_dir/"upload_queue"/payload["blob_name"]).read_bytes(),b"fixture")
            self.app.tasks.update(task["task_id"],state="failed")
            retried,created=self.app.tasks.retry(task["task_id"],"fixture retry")
            self.assertTrue(created);self.assertEqual(json.loads(self.app.tasks._raw(retried["task_id"])["payload"]),payload)
            status,_=self.call("POST",self.endpoint("actions/upload"),data,mime);self.assertEqual(status,409)

    def test_missing_complete_sources_cannot_start_process(self):
        _,info=self.call("GET",self.endpoint())
        body={k:info[k] for k in ("expected_a00","expected_run","expected_staging")};body["reason"]="fixture"
        status,_=self.call("POST",self.endpoint("actions/process_sources"),json.dumps(body));self.assertEqual(status,409)
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def test_failed_source_retry_security_versions_and_payload(self):
        info = {"enabled": True, "expected_a00": "run_fixture_a00", "expected_run": "run_fixture_a02", "expected_staging": "", "sources": [{"database": "OTP", "can_retry": True}, {"database": "TTD", "can_retry": False}]}
        body = {k: info[k] for k in ("expected_a00", "expected_run", "expected_staging")}
        body.update(databases=["OTP"], reason="合成失败来源重试")
        endpoint = self.endpoint("actions/retry_sources", "A02")
        with patch.object(self.app, "get_sources", return_value=info), patch.object(self.app.tasks, "_spawn"):
            self.assertEqual(self.call("POST", endpoint, json.dumps(body), token=False)[0], 403)
            self.assertEqual(self.call("POST", endpoint, json.dumps(body), origin="https://outside.invalid")[0], 403)
            self.assertEqual(self.call("POST", endpoint, json.dumps(dict(body, expected_run="old")))[0], 409)
            for databases in ([], ["TTD"], ["OTP", "OTP"], [None], ["GeneCards"]):
                self.assertEqual(self.call("POST", endpoint, json.dumps(dict(body, databases=databases)))[0], 422)
            self.assertEqual(self.app.tasks.list(self.sid), [])
            status, value = self.call("POST", endpoint, json.dumps(body))
            self.assertEqual(status, 202)
            self.assertNotIn("payload", value["task"])
            payload = json.loads(self.app.tasks._raw(value["task"]["task_id"])["payload"])
            self.assertEqual(payload, body)
            self.assertEqual(self.call("POST", endpoint, json.dumps(body))[0], 409)
