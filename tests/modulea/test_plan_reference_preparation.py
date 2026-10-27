import unittest
from pathlib import Path
from uuid import uuid4

from contracts import ContractError
from modulea.core.reference_preparation import info, qualification
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
        self.assertEqual(workflow.run(workflow.load(sid), result["run_id"])["config"]["version"],
                         "A06.plan_reference_preparation.1")
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertEqual(result["summary"]["scored_pairs"], 0)
        self.assertFalse(workflow.approved(workflow.load(sid), result["run_id"]))
        check = qualification(workflow, sid)
        self.assertTrue(check["qualified"], check)
        self.assertTrue(check["can_enter_review"])
        self.assertEqual(check["scored_pairs"], 0)

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


if __name__ == "__main__":
    unittest.main()
