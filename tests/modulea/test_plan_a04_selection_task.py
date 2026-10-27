"""隔离验证A04方案受体选择经接口路由与后台任务归档；不联网或执行真实研究。"""

import json
from copy import deepcopy
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch, Mock
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
from science_modules.a06.plan_input import pair_statuses
from science_modules.a06 import plan_preparation
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
        for module in ("A01", "A02", "A03", "A03_SELECT"):
            run = self.workflow.begin(self.sid, module, {}, {}, "隔离上游")
            tables = ({"intersection_targets": targets} if module == "A03" else
                      {"selected": [{"compound_id": "CMP1", "name": "成分一"},
                                    {"compound_id": "CMP2", "name": "成分二"}]} if module == "A03_SELECT" else {})
            self.workflow.finish(self.sid, run["run_id"], {}, tables)
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

    def review_payload(self, selection_id, **changes):
        return dict({"request_id": "planreq_" + uuid4().hex, "expected_a00": self.a00,
                     "expected_a04": self.a04, "selection_id": selection_id,
                     "expected_review_id": None, "decision": "approved",
                     "reviewer": "隔离复核", "note": "核对方案、网络和完整受体顺序"}, **changes)

    def a06_payload(self, selection, review, **changes):
        return dict({"request_id": "planreq_" + uuid4().hex, "expected_a00": self.a00,
                     "expected_a03": self.workflow.load(self.sid)["current"]["A03"],
                     "expected_a03_select": self.workflow.load(self.sid)["current"]["A03_SELECT"],
                     "expected_a04": self.a04, "expected_selection_id": selection["selection_id"],
                     "expected_selection_review_id": review["review_id"],
                     "expected_plan_id": self.plan_record["plan_id"],
                     "author": "隔离测试", "note": "只编制准备输入"}, **changes)

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

    def test_a06_input_requires_separate_selection_review_and_keeps_all_na_pairs(self):
        selection = self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())["record"]
        pending = self.a06_payload(selection, {"review_id": "selectionreview_" + "0" * 32})
        with self.assertRaises(ContractError):
            self.workflow.save_analysis_plan_a06_preparation_input(self.sid, pending)
        review_body = self.review_payload(selection["selection_id"])
        status, answer = self.call("POST", f"/studies/{self.sid}/analysis-plan/a04-selection/{selection['selection_id']}/reviews", review_body)
        self.assertEqual(status, 201, answer)
        review = answer["review"]
        self.assertEqual(self.call("POST", f"/studies/{self.sid}/analysis-plan/a04-selection/{selection['selection_id']}/reviews", review_body)[0], 200)
        before = self.workflow.load(self.sid)
        body = self.a06_payload(selection, review)
        with patch.object(self.app.tasks, "_spawn"):
            status, queued = self.call("POST", f"/studies/{self.sid}/analysis-plan/a06-preparation-input", body)
        self.assertEqual(status, 202, queued)
        self.assertEqual(run_task(self.settings, queued["task"]["task_id"]), 0)
        after = self.workflow.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(after["analysis_plan_a06_input_records"]), 1)
        _, info = self.call("GET", f"/studies/{self.sid}/analysis-plan")
        packet = info["a06_preparation_input"]["packet"]
        self.assertFalse(packet["execution_available"])
        self.assertEqual(packet["pair_count"], 4)
        self.assertEqual([row["target_id"] for row in packet["receptors"]],
                         [row["target_id"] for row in selection["selection"]["selected"]])
        compounds = {row["compound_id"]: {"state": "ready", "reason_zh": ""}
                     for row in packet["compounds"]}
        receptors = {row["target_id"]: {"state": "ready", "reason_zh": ""}
                     for row in packet["receptors"]}
        receptors[packet["receptors"][0]["target_id"]] = {"state": "NA", "reason_zh": "结构质控失败"}
        pairs = pair_statuses(packet, compounds, receptors)
        self.assertEqual(len(pairs), 4)
        self.assertEqual(sum(row["state"] == "NA" for row in pairs), 2)
        self.assertTrue(all(row["score"] is None for row in pairs))
        self.assertEqual({row["target_id"] for row in pairs},
                         {row["target_id"] for row in packet["receptors"]})
        changed = deepcopy(packet)
        changed["receptors"][0]["target_id"] = "HGNC:999"
        with self.assertRaises(ContractError):
            pair_statuses(changed, compounds, receptors)
        repeated = self.workflow.save_analysis_plan_a06_preparation_input(self.sid, body)
        self.assertFalse(repeated["created"])
        with self.assertRaises(AnalysisPlanConflict):
            self.workflow.save_analysis_plan_a06_preparation_input(self.sid, dict(body, note="不同内容"))
        self.settings.science_tools_root = Path(self.temp.name)
        with patch.object(self.app.tasks, "_spawn"):
            status, queued = self.call("POST", f"/studies/{self.sid}/analysis-plan/a06-preparation", {
                "expected_input_id": repeated["record"]["input_id"],
                "request_id": "planprep_" + uuid4().hex, "author": "隔离测试",
                "note": "明确准备固定对象", "confirmed": True})
        self.assertEqual(status, 202, queued)
        self.assertEqual(queued["task"]["kind"], "a06_plan_preparation")

    def test_review_revocation_invalidates_current_a06_input_without_deleting_history(self):
        selection = self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())["record"]
        review = self.workflow.review_analysis_plan_a04_selection(
            self.sid, self.review_payload(selection["selection_id"]))["review"]
        body = self.a06_payload(selection, review)
        self.workflow.save_analysis_plan_a06_preparation_input(self.sid, body)
        revoked = self.workflow.review_analysis_plan_a04_selection(
            self.sid, self.review_payload(selection["selection_id"],
                expected_review_id=review["review_id"], decision="pending"))["review"]
        self.assertEqual(revoked["decision"], "pending")
        _, info = self.call("GET", f"/studies/{self.sid}/analysis-plan")
        self.assertIsNone(info["a06_preparation_input"])
        self.assertEqual(info["a06_preparation_input_history_count"], 1)
        with self.assertRaises(ContractError):
            self.workflow.save_analysis_plan_a06_preparation_input(self.sid, body)

    def test_tampered_a06_input_archive_blocks_read(self):
        selection = self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())["record"]
        review = self.workflow.review_analysis_plan_a04_selection(
            self.sid, self.review_payload(selection["selection_id"]))["review"]
        self.workflow.save_analysis_plan_a06_preparation_input(
            self.sid, self.a06_payload(selection, review))
        reference = self.workflow.load(self.sid)["analysis_plan_a06_input_records"][0]
        (self.workflow.location(self.sid) / reference["path"]).write_text("{}", encoding="utf-8")
        self.assertEqual(self.call("GET", f"/studies/{self.sid}/analysis-plan")[0], 503)

    def test_a03_select_review_change_invalidates_a06_input(self):
        selection = self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())["record"]
        review = self.workflow.review_analysis_plan_a04_selection(
            self.sid, self.review_payload(selection["selection_id"]))["review"]
        body = self.a06_payload(selection, review)
        self.workflow.save_analysis_plan_a06_preparation_input(self.sid, body)
        manifest = self.workflow.load(self.sid)
        selected_run = manifest["current"]["A03_SELECT"]
        previous = self.workflow.latest_review(manifest, self.workflow.run(manifest, selected_run)["artifact_id"])
        self.workflow.review(self.sid, selected_run, "pending", "隔离测试", "撤回成分选择",
                             expected_review=previous["review_id"])
        _, info = self.call("GET", f"/studies/{self.sid}/analysis-plan")
        self.assertIsNone(info["a06_preparation_input"])
        self.assertEqual(info["a06_preparation_input_history_count"], 1)
        with self.assertRaises(ContractError):
            self.workflow.save_analysis_plan_a06_preparation_input(self.sid, body)

    def test_a06_preparation_archives_failed_sources_as_na_without_scoring(self):
        """实际准备发布必须有同一固定输入和完整矩阵；来源失败不能补位。"""
        from modulea.core.kernel import full_workflow
        selection = self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())["record"]
        review = self.workflow.review_analysis_plan_a04_selection(
            self.sid, self.review_payload(selection["selection_id"]))["review"]
        input_record = self.workflow.save_analysis_plan_a06_preparation_input(
            self.sid, self.a06_payload(selection, review))["record"]
        packet = input_record["packet"]
        fake_vina = Path(self.temp.name) / "fixed_vina.exe"
        fake_vina.write_bytes(b"isolated-test-only")
        source = {"id": "isolated", "files": [],
                  "compounds": [{**row, "state": "NA", "reason_zh": "官方来源不可用"}
                                for row in packet["compounds"]],
                  "receptors": [{**row, "state": "NA", "reason_zh": "结构身份未通过",
                                 "candidates": []} for row in packet["receptors"]]}
        ligands = [{"compound_id": row["compound_id"], "state": "NA",
                    "reason_zh": "官方来源不可用"} for row in packet["compounds"]]
        proteins = [{"target_id": row["target_id"], "symbol": row["symbol"],
                     "state": "NA", "reason_zh": "结构身份未通过", "quality": "待核查",
                     "attempts": []} for row in packet["receptors"]]
        workflow = full_workflow(self.settings.data_root)
        request = {"expected_input_id": input_record["input_id"],
                   "request_id": "planprep_" + uuid4().hex,
                   "author": "隔离测试", "note": "测试失败来源完整留NA", "confirmed": True}
        with patch.object(plan_preparation, "_version", return_value=fake_vina), \
             patch.object(plan_preparation, "connect", return_value=source), \
             patch.object(plan_preparation, "prepare", return_value=(ligands, proteins)):
            result = plan_preparation.run(workflow, self.sid, request,
                                          Path(self.temp.name), lambda _: None)
        self.assertEqual(result["summary"]["pair_count"], 4)
        self.assertEqual(result["summary"]["ready_pairs"], 0)
        self.assertEqual(result["summary"]["na_pairs"], 4)
        self.assertEqual(result["summary"]["scored_pairs"], 0)
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertTrue(all(row["score"] is None and row["state"] == "NA"
                            for row in result["tables"]["planned_pairs"]))
        self.assertFalse(workflow.approved(workflow.load(self.sid), result["run_id"]))
        self.assertEqual(plan_preparation.run(workflow, self.sid, request,
                         Path(self.temp.name), lambda _: None)["run_id"], result["run_id"])
        with self.assertRaises(ContractError):
            plan_preparation.run(workflow, self.sid, dict(request, note="不同请求内容"),
                                 Path(self.temp.name), lambda _: None)

    def test_a06_preparation_v2_archives_bound_config_and_delegates_v1(self):
        from modulea.core.kernel import full_workflow
        from science_modules.a06 import plan_preparation_v2
        selection = self.workflow.save_analysis_plan_a04_selection(self.sid, self.payload())["record"]
        review = self.workflow.review_analysis_plan_a04_selection(
            self.sid, self.review_payload(selection["selection_id"]))["review"]
        source_input = self.workflow.save_analysis_plan_a06_preparation_input(
            self.sid, self.a06_payload(selection, review))["record"]
        packet = source_input['packet']
        source = {'id':'isolated', 'files':[],
                  'compounds':[{**r,'state':'NA','reason_zh':'缺少来源'} for r in packet['compounds']],
                  'receptors':[{**r,'state':'NA','reason_zh':'缺少结构','candidates':[]} for r in packet['receptors']]}
        ligands = [{'compound_id': r['compound_id'],'state':'NA','reason_zh':'缺少来源'} for r in packet['compounds']]
        receptors = [{'target_id':r['target_id'],'symbol':r['symbol'],'state':'NA',
                      'reason_zh':'缺少结构','quality':'待核查','attempts':[]} for r in packet['receptors']]
        binary = Path(self.temp.name)/'vina.exe'; binary.write_bytes(b'fixture')
        request = {'expected_input_id':source_input['input_id'], 'request_id':'planprep_'+uuid4().hex,
                   'author':'隔离测试', 'note':'版本验证', 'confirmed':True}
        workflow = full_workflow(self.settings.data_root)
        with patch.object(plan_preparation_v2, '_version', return_value=binary), \
             patch.object(plan_preparation_v2, 'connect', return_value=source), \
             patch.object(plan_preparation_v2, 'prepare', return_value=(ligands, receptors)):
            result = plan_preparation_v2.run(workflow, self.sid, request, Path(self.temp.name), lambda _:None)
        run = workflow.run(workflow.load(self.sid), result['run_id'])
        self.assertEqual(run['config']['version'], 'A06.plan_preparation.2')
        self.assertEqual(run['config']['vina_parameters']['exhaustiveness'], 8)
        self.assertEqual(result['summary']['na_pairs'], 4)
        legacy = Mock()
        plan_preparation_v2.validator(self.settings.data_root, legacy)(
            {'config': {'version': 'A06.plan_preparation.1'}}, {}, {}, [], 'success')
        legacy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
