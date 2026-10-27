"""隔离验证A04方案受体选择经接口路由与后台任务归档；不联网或执行真实研究。"""

import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from modulea.api.errors import ApiError, from_contract
from modulea.api.server import App
from modulea.config import Settings
from modulea.core.analysis_plans import AnalysisPlanConflict, AnalysisPlanWorkflow
from modulea.tasks.worker import run_task
from science_modules.analysis_protocol import VERSION as PLAN_VERSION
from science_modules.a04.plan_flow import validator as a04_validator
from science_modules.a04.selection_flow import validate_selection
from storage import file_record, write_json


class PlanA04SelectionTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="plan_a04_selection_")
        root = Path(self.temp.name)
        self.settings = Settings(data_root=root / "data", runtime_dir=root / "runtime")
        self.workflow = AnalysisPlanWorkflow(self.settings.data_root, {
            "A04": a04_validator(self.settings.data_root, lambda *args: None)})
        self.sid = self.workflow.create({
            "formula": "虚构方", "herbs": "虚构药", "disease": "虚构病", "disease_scope": "仅本病",
            "species": 9606, "operator": "隔离测试", "analysis_purpose": "workflow_test",
            "analysis_plan_profile": PLAN_VERSION}, kind="contract_test")
        self.a00 = self.workflow.load(self.sid)["current"]["A00"]
        self.workflow.review(self.sid, self.a00, "approved", "隔离测试", "核对登记")
        self.plan_record = self.workflow.save_analysis_plan_draft(self.sid, {
            "request_id": "planreq_" + uuid4().hex, "expected_a00": self.a00,
            "expected_draft_id": "", "specification": {"mode": "personalized", "parameters": {
                "a04.mode": "degree", "a06.receptor_count": 2}},
            "author": "隔离测试", "note": "仅测试受体选择"})["draft"]
        targets = [{"target_id": "HGNC:" + str(i), "symbol": "G" + str(i)} for i in range(1, 9)]
        for module in ("A01", "A02", "A03"):
            run = self.workflow.begin(self.sid, module, {}, {}, "隔离上游")
            self.workflow.finish(self.sid, run["run_id"], {},
                                 {"intersection_targets": targets} if module == "A03" else {})
            self.workflow.review(self.sid, run["run_id"], "approved", "隔离测试", "核对上游")
        mapping = [{"queryIndex": i, "ncbiTaxonId": 9606, "preferredName": target["symbol"],
                    "stringId": "9606." + str(i + 1)} for i, target in enumerate(targets)]
        edges = [{"stringId_A": "9606." + str(hub), "stringId_B": "9606." + str(leaf),
                  "score": .95, "ncbiTaxonId": 9606}
                 for hub in (1, 2) for leaf in range(3, 9)]
        edges.append({"stringId_A": "9606.1", "stringId_B": "9606.2", "score": .95,
                      "ncbiTaxonId": 9606})
        ids = ["9606." + str(i) for i in range(1, 9)]
        source = {"schema_version": "A04.plan_source.1", "string_version": "12.0",
                  "analysis_plan_id": self.plan_record["plan"]["parameter_hash"],
                  "analysis_parameter_hash": self.plan_record["plan"]["parameter_hash"],
                  "mapped_string_ids": ids,
                  "mapping": {"response_text": json.dumps(mapping)},
                  "network": {"params": {"identifiers": "\r".join(ids), "species": 9606,
                                         "required_score": 900, "network_type": "functional",
                                         "add_nodes": 0, "caller_identity": "ModuleA"},
                              "response_text": json.dumps(edges)}}
        source_path = self.workflow.location(self.sid) / "raw/a04_source.json"
        write_json(source_path, source)
        source_ref = file_record(self.workflow.location(self.sid), source_path, "string_source")
        a03 = self.workflow.load(self.sid)["current"]["A03"]
        result = self.workflow.publish_analysis_plan_a04_network(self.sid, {
            "expected_a00": self.a00, "expected_a03": a03,
            "expected_plan_id": self.plan_record["plan_id"],
            "source_file": source_ref, "reason": "隔离网络发布"})
        self.a04 = result["run_id"]
        self.summary, self.tables = result["summary"], result["tables"]
        self.workflow.review(self.sid, self.a04, "approved", "隔离测试", "核对网络")
        self.app = App(self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **changes):
        return dict({"request_id": "planreq_" + uuid4().hex, "expected_a00": self.a00,
                     "expected_a04": self.a04, "expected_plan_id": self.plan_record["plan_id"],
                     "author": "隔离测试", "note": "仅保存选择"}, **changes)

    def call(self, method, path, body=None):
        class Request:
            def json(self):
                return body
        for route_method, pattern, handler in self.app.routes:
            match = re.fullmatch(pattern, "/api/v1" + path) if route_method == method else None
            if match:
                try:
                    result = handler(Request(), *match.groups())
                    return (result[1], result[0]) if isinstance(result, tuple) else (200, result)
                except ApiError as error:
                    return error.status, error.body()
                except ContractError as error:
                    api_error = from_contract(str(error))
                    return api_error.status, api_error.body()
        self.fail("未登记接口：" + method + " " + path)

    def test_route_task_archives_recalculated_selection_without_changing_runs_or_reviews(self):
        before = self.workflow.load(self.sid)
        body = self.payload()
        with patch.object(self.app.tasks, "_spawn"):
            status, queued = self.call("POST", f"/studies/{self.sid}/analysis-plan/a04-selection", body)
        self.assertEqual(status, 202, queued)
        self.assertEqual(run_task(self.settings, queued["task"]["task_id"]), 0)
        after = self.workflow.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(after["analysis_plan_selection_records"]), 1)
        status, info = self.call("GET", f"/studies/{self.sid}/analysis-plan")
        self.assertEqual(status, 200, info)
        self.assertEqual(info["a04_selection_history_count"], 1)
        record = info["a04_selection"]
        self.assertEqual(record["state"], "draft")
        self.assertFalse(record["execution_available"])
        self.assertEqual(record["expected_a04"], self.a04)
        self.assertEqual(record["selection"]["actual_count"], 2)
        validate_selection(record["selection"], self.a04, self.summary, self.tables, self.plan_record["plan"])
        duplicate = self.workflow.save_analysis_plan_a04_selection(self.sid, body)
        self.assertFalse(duplicate["created"])
        self.assertEqual(len(self.workflow.load(self.sid)["analysis_plan_selection_records"]), 1)
        with self.assertRaises(AnalysisPlanConflict):
            self.workflow.save_analysis_plan_a04_selection(self.sid, dict(body, note="改变内容"))
        current = self.workflow.load(self.sid)
        previous = self.workflow.latest_review(current, self.workflow.run(current, self.a04)["artifact_id"])
        self.workflow.review(self.sid, self.a04, "pending", "隔离测试", "撤回通过",
                             expected_review=previous["review_id"])
        _, invalidated = self.call("GET", f"/studies/{self.sid}/analysis-plan")
        self.assertIsNone(invalidated["a04_selection"])
        self.assertEqual(invalidated["a04_selection_history_count"], 1)

    def test_unapproved_wrong_plan_and_stale_versions_cannot_archive(self):
        other = self.workflow.save_analysis_plan_draft(self.sid, {
            "request_id": "planreq_" + uuid4().hex, "expected_a00": self.a00,
            "expected_draft_id": self.plan_record["plan_id"],
            "specification": {"mode": "personalized", "parameters": {"a04.mode": "bc_cc"}},
            "author": "隔离测试", "note": "另一方案"})["draft"]
        with self.assertRaises(ContractError):
            self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload(expected_plan_id=other["plan_id"]))
        self.assertEqual(self.call("POST", f"/studies/{self.sid}/analysis-plan/a04-selection",
                                   self.payload(expected_a04="run_" + "0" * 32))[0], 409)
        manifest = self.workflow.load(self.sid)
        previous = self.workflow.latest_review(manifest, self.workflow.run(manifest, self.a04)["artifact_id"])
        self.workflow.review(self.sid, self.a04, "pending", "隔离测试", "撤回通过",
                             expected_review=previous["review_id"])
        self.assertEqual(self.call("POST", f"/studies/{self.sid}/analysis-plan/a04-selection",
                                   self.payload())[0], 409)
        self.assertNotIn("analysis_plan_selection_records", self.workflow.load(self.sid))

    def test_tampered_selection_archive_is_not_displayed(self):
        self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())
        reference = self.workflow.load(self.sid)["analysis_plan_selection_records"][0]
        (self.workflow.location(self.sid) / reference["path"]).write_text("{}", encoding="utf-8")
        self.assertEqual(self.call("GET", f"/studies/{self.sid}/analysis-plan")[0], 503)


if __name__ == "__main__":
    unittest.main()
