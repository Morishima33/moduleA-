import unittest
import json
import sys
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

from contracts import ContractError
from modulea.core.reference_preparation import info, qualification, scoring_readiness, validate
from science_modules.a06 import reference_preparation
from science_modules.a06.reference_preparation_contract import validate_request
from storage import file_record, write_json


class ReferencePreparationTests(unittest.TestCase):
    def payload(self, **changes):
        value = {"expected_input_id": "input_" + "a" * 32,
                 "expected_preparation_run_id": "run_" + "b" * 32,
                 "expected_review_id": "refreview_" + "c" * 32,
                 "request_id": "refprep_" + "d" * 32,
                 "reviewer": "隔离核查人", "note": "绑定已核查参考证据",
                 "confirmed": True}
        value.update(changes)
        return value

    def test_binding_request_rejects_science_overrides(self):
        with self.assertRaises(ContractError):
            validate_request(dict(self.payload(), scoring="vina"))
        with self.assertRaises(ContractError):
            validate_request(self.payload(confirmed=False))

    def test_info_without_preparation_does_not_create_state(self):
        workflow = type("Workflow", (), {"load": lambda self, sid: {"current": {}}})()
        value = info(workflow, "study_fixture")
        self.assertFalse(value["supported"])
        self.assertFalse(value["execution_available"])

    def test_binding_creates_new_blocked_preparation_version(self):
        from tests.modulea.test_plan_pockets import PocketReviewTests

        base = PocketReviewTests("test_confirmation_revision_preserves_sources_and_na_without_scoring")
        base.setUp()
        self.addCleanup(base.tearDown)
        workflow, sid, home = base.workflow, base.sid, base.home
        request_id = "refreq_" + uuid4().hex
        review_id = "refreview_" + uuid4().hex
        packet_dir = home / "runs/A06_PREP" / base.source_run_id / "reference_review" / review_id
        packet_dir.mkdir(parents=True)
        packet = {"schema_version": "A06.plan_reference_review.1", "study_id": sid,
                  "input_id": base.input_record["input_id"],
                  "expected_preparation_run_id": base.source_run_id,
                  "source_preparation_run_id": base.source_run_id,
                  "request_id": request_id, "choices": [], "summary": {
                      "choice_count": 0, "ready_count": 0, "na_count": 0,
                      "scored_pairs": 0, "execution_available": False,
                      "handoff_blocked": True},
                  "folder": packet_dir.relative_to(home).as_posix(), "files": []}
        packet_path = packet_dir / "packet.json"
        write_json(packet_path, packet)
        packet_ref = file_record(home, packet_path, "reference_review_packet")
        decision_path = home / "decisions/analysis_plans/a06_reference_reviews" / (review_id + ".json")
        review = {"schema_version": "A06.plan_reference_review.1", "study_id": sid,
                  "review_id": review_id, "expected_preparation_run_id": base.source_run_id,
                  "request": {"request_id": request_id}, "request_hash": "fixture",
                  "packet": packet_ref, "summary": packet["summary"]}
        write_json(decision_path, review)
        manifest = workflow.load(sid)
        manifest.setdefault("analysis_plan_a06_reference_records", []).append(
            {"decision": file_record(home, decision_path, "a06_pocket_decision"),
             "run_id": base.source_run_id})
        workflow.save(manifest)
        payload = {"expected_input_id": base.input_record["input_id"],
                   "expected_preparation_run_id": base.source_run_id,
                   "expected_review_id": review_id, "request_id": "refprep_" + uuid4().hex,
                   "reviewer": "隔离核查人", "note": "绑定测试参考证据", "confirmed": True}
        result = reference_preparation.publish(workflow, sid, payload)
        self.assertEqual(validate(workflow, sid, payload), {"repeated": True, "run_id": result["run_id"]})
        with self.assertRaises(ContractError):
            validate(workflow, sid, dict(payload, note="不同内容"))
        self.assertEqual(workflow.run(workflow.load(sid), result["run_id"])["config"]["version"],
                         "A06.plan_reference_preparation.1")
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertEqual(result["summary"]["scored_pairs"], 0)
        self.assertFalse(workflow.approved(workflow.load(sid), result["run_id"]))
        check = qualification(workflow, sid)
        self.assertTrue(check["qualified"], check)
        self.assertFalse(check["can_enter_review"])
        self.assertEqual(check["scored_pairs"], 0)
        readiness = scoring_readiness(workflow, sid)
        self.assertFalse(readiness["scoring_allowed"])
        self.assertFalse(readiness["execution_available"])
        self.assertIn("新版评分执行入口尚未接通", readiness["blockers"])

    def test_full_reference_review_binding_and_qualification_chain(self):
        from tests.modulea.test_plan_pockets import PocketReviewTests
        from science_modules.a06 import reference_review

        base = PocketReviewTests("test_confirmation_revision_preserves_sources_and_na_without_scoring")
        base.setUp()
        self.addCleanup(base.tearDown)
        workflow, sid = base.workflow, base.sid
        review_payload = {"expected_input_id": base.input_record["input_id"],
                          "expected_preparation_run_id": base.source_run_id,
                          "request_id": "refreq_" + uuid4().hex,
                          "reviewer": "隔离核查人", "note": "空清单链路核查",
                          "confirmed": True, "choices": []}
        review_result = reference_review.run(workflow, sid, review_payload,
                                             Path(base.base.temp.name), lambda _: None)
        review_id = review_result["review"]["review_id"]
        bind_payload = {"expected_input_id": base.input_record["input_id"],
                        "expected_preparation_run_id": base.source_run_id,
                        "expected_review_id": review_id,
                        "request_id": "refprep_" + uuid4().hex,
                        "reviewer": "隔离绑定人", "note": "绑定空参考清单链路",
                        "confirmed": True}
        bound = reference_preparation.publish(workflow, sid, bind_payload)
        check = qualification(workflow, sid)
        self.assertEqual(bound["run_id"], check["current_run_id"])
        self.assertTrue(check["qualified"], check)
        self.assertEqual(check["scored_pairs"], 0)

    def test_real_worker_subprocesses_accept_exact_request_and_archive(self):
        from tests.modulea.test_plan_pockets import PocketReviewTests
        from modulea.tasks.worker import run_a06_plan_reference_review, run_a06_plan_reference_preparation
        from modulea.config import PROJECT_ROOT, load_settings

        # 优先使用已配置的只读固定工具，未配置时保留原测试路径回退。
        tools = load_settings().science_tools_root or PROJECT_ROOT.parent / "environment" / "a06_runtime_v1"
        if not tools.is_dir():
            self.skipTest("固定科学工具未安装")
        base = PocketReviewTests("test_confirmation_revision_preserves_sources_and_na_without_scoring")
        base.setUp()
        self.addCleanup(base.doCleanups)
        settings = base.base.settings
        settings.science_python = sys.executable
        settings.science_tools_root = tools
        review = {"expected_input_id": base.input_record["input_id"],
                  "expected_preparation_run_id": base.source_run_id,
                  "request_id": "refreq_" + uuid4().hex, "reviewer": "测试",
                  "note": "隔离测试空选择", "confirmed": True, "choices": []}
        task = {"task_id": "task_" + uuid4().hex, "study_id": base.sid, "payload": json.dumps(review)}
        manager = Mock()
        run_a06_plan_reference_review(settings, task, manager)
        manifest = base.workflow.load(base.sid)
        from storage import read_json, verified_file
        record = read_json(verified_file(base.home, manifest["analysis_plan_a06_reference_records"][-1]["decision"]))
        bind = {"expected_input_id": base.input_record["input_id"],
                "expected_preparation_run_id": base.source_run_id,
                "expected_review_id": record["review_id"], "request_id": "refprep_" + uuid4().hex,
                "reviewer": "测试", "note": "隔离绑定", "confirmed": True}
        task = {"task_id": "task_" + uuid4().hex, "study_id": base.sid, "payload": json.dumps(bind)}
        run_a06_plan_reference_preparation(settings, task, manager)
        manifest = base.workflow.load(base.sid)
        result = base.workflow.result(manifest, manifest["current"]["A06_PREP"])
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertEqual(result["summary"]["scored_pairs"], 0)

    def test_real_worker_nonempty_candidate_preserves_failed_reference_as_na(self):
        from tests.modulea.test_plan_pockets import PocketReviewTests
        from tests.modulea.test_reference_docking import fixture
        from science_modules.a06.reference_candidates import discover
        from modulea.tasks.worker import run_a06_plan_reference_review
        from modulea.config import PROJECT_ROOT, load_settings
        from storage import read_json, verified_file

        # 只调整夹具的工具定位，不改变参考失败保留为NA或原科学协议。
        tools = load_settings().science_tools_root or PROJECT_ROOT.parent / "environment" / "a06_runtime_v1"
        if not tools.is_dir():
            self.skipTest("固定科学工具未安装")

        class CandidateFixture(PocketReviewTests):
            def connect(self, home, packet, folder, progress):
                source = super().connect(home, packet, folder, progress)
                cif = folder / "candidate.cif"
                cif.write_text(fixture(), encoding="utf-8")
                candidate = source["receptors"][0]["candidates"][0]
                candidate["cif"] = file_record(home, cif, "synthetic_structure")
                candidate["spec"]["pdb_id"] = "TEST"
                source["files"].append(candidate["cif"])
                return source

        base = CandidateFixture("test_confirmation_revision_preserves_sources_and_na_without_scoring")
        base.setUp()
        self.addCleanup(base.doCleanups)
        settings = base.base.settings
        settings.science_python = sys.executable
        settings.science_tools_root = tools
        choices = discover(base.home, base.source["connection"])
        self.assertTrue(choices[0]["selectable"])
        choice = {key: choices[0][key] for key in ("target_id", "candidate_key", "reference_key")}
        request = {"expected_input_id": base.input_record["input_id"],
                   "expected_preparation_run_id": base.source_run_id,
                   "request_id": "refreq_" + uuid4().hex, "reviewer": "测试",
                   "note": "隔离测试非空选择的失败保留", "confirmed": True, "choices": [choice]}
        task = {"task_id": "task_" + uuid4().hex, "study_id": base.sid, "payload": json.dumps(request)}
        run_a06_plan_reference_review(settings, task, Mock())
        manifest = base.workflow.load(base.sid)
        review = read_json(verified_file(base.home, manifest["analysis_plan_a06_reference_records"][-1]["decision"]))
        packet = read_json(verified_file(base.home, review["packet"]))
        self.assertEqual(packet["summary"]["choice_count"], 1)
        self.assertEqual(packet["summary"]["na_count"], 1)
        self.assertEqual(packet["results"][0]["state"], "NA")
        self.assertTrue(packet["results"][0]["reason_zh"])
        self.assertTrue(packet["summary"]["handoff_blocked"])


if __name__ == "__main__":
    unittest.main()
