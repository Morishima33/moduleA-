"""原生提交的版本竞争回归：使用独立虚构研究，不执行实际科学工具。"""
from copy import deepcopy
import http.client
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError
from modulea.api import native_execution as api
from modulea.api.errors import ApiError
from modulea.api.server import create_server
from modulea.core import native_execution as core
from storage import new_id
from tests.modulea import test_native_execution as fixture


class NativeVersionTests(unittest.TestCase):
    """复用生产Workflow夹具，但不导入TestCase别名导致重复收集。"""

    def setUp(self):
        self.seed = fixture.NativeExecutionTests()
        self.seed.setUp()
        self.addCleanup(self.seed.doCleanups)
        self.w, self.sid = self.seed.w, self.seed.sid

    def assert_stale(self, body, stage="prepare"):
        """版本不符必须在排队前409，且保持原研究索引。"""
        app = self.seed.base.app
        before = self.w.load(self.sid)
        with patch.object(app.tasks, "submit", return_value=({}, True)) as submit, \
                patch.object(api, "digest_file", return_value=(0, "0" * 64)), \
                patch.object(api, "configuration_blockers", return_value=[]), \
                self.assertRaises(ApiError) as caught:
            api.submit(app, SimpleNamespace(json=lambda: body), self.sid, stage)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "STALE_VERSION"))
        submit.assert_not_called()
        self.assertEqual(self.w.load(self.sid), before)

    def test_prepare_mismatched_version_rejected_before_enqueue(self):
        body = dict(self.seed.body, expected_preparation_run_id=new_id("run"))
        self.assert_stale(body)

    def test_old_prepare_page_cannot_start_another_request(self):
        self.seed.execute()
        self.assert_stale(dict(self.seed.body, request_id=new_id("nativeprep")))

    def test_changed_request_cannot_impersonate_same_run_resume(self):
        self.seed.execute()
        for field, value in (("note", "已改变执行依据"), ("author", "其他登记人")):
            with self.subTest(field=field):
                self.assert_stale(dict(self.seed.body, **{field: value}))

    def test_exact_request_can_read_completed_run_without_writes(self):
        result = self.seed.execute()
        before = self.w.load(self.sid)
        manifest, _, _ = core.source(self.w, self.sid, "prepare", self.seed.body)
        self.assertEqual(manifest["current"]["A06_PREP"], result["run_id"])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.seed.execute(), result)

    def test_interrupted_exact_request_remains_resumable(self):
        validator = self.w.validators["A06_PREP"]

        def interrupt(*args):
            """只中断发表，保留已登记对象供原请求接续。"""
            validator(*args)
            raise RuntimeError("合成发表中断")

        with patch.dict(self.w.validators, {"A06_PREP": interrupt}), self.assertRaises(RuntimeError):
            self.seed.execute()
        rid = self.w.load(self.sid)["current"]["A06_PREP"]
        core.source(self.w, self.sid, "prepare", self.seed.body)
        self.assertEqual(self.seed.execute()["run_id"], rid)
        self.assertEqual(self.seed.connects, 1)

    def test_worker_rechecks_version_after_http_preflight(self):
        stale = dict(self.seed.body, request_id=new_id("nativeprep"))
        core.source(self.w, self.sid, "prepare", stale)
        result = self.seed.execute()
        before = self.w.load(self.sid)
        config = self.w.run(before, result["run_id"])["config"]
        with self.assertRaises(ContractError):
            core.begin(self.w, self.sid, "prepare", stale, deepcopy(config))
        self.assertEqual(self.w.load(self.sid), before)

    def test_score_mismatched_current_run_rejected_before_enqueue(self):
        body = {"request_id": new_id("nativescore"), "platform_protocol": core.SCORING,
                "expected_preparation_run_id": None, "expected_preparation_result_sha256": "0" * 64,
                "expected_preparation_review_id": new_id("review"), "expected_a06_run_id": new_id("run"),
                "author": "合成测试", "note": "旧评分版本不得排队", "confirmed": True}
        self.assert_stale(body, "score")

    def test_real_http_stale_request_is_409_without_queue_or_science(self):
        """实际HTTP路由和token检查后，在任何任务创建之前拒绝旧版本。"""
        server, app = create_server(self.seed.settings, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        before = self.w.load(self.sid)
        try:
            with patch.object(app.tasks, "submit") as submit, \
                    patch.object(api, "configuration_blockers", return_value=[]):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                try:
                    body = dict(self.seed.body, expected_preparation_run_id=new_id("run"))
                    connection.request("POST", f"/api/v1/studies/{self.sid}/native-compute/prepare",
                                       json.dumps(body), {"X-ModuleA-Token": app.token,
                                       "Content-Type": "application/json",
                                       "Origin": f"http://127.0.0.1:{server.server_port}"})
                    response = connection.getresponse()
                    value = json.loads(response.read())
                    self.assertEqual(response.status, 409, value)
                    self.assertEqual(value["error"]["code"], "STALE_VERSION")
                finally:
                    connection.close()
                submit.assert_not_called()
            self.assertEqual(self.w.load(self.sid), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
