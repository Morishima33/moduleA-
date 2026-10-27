import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from contracts import ContractError
from science_modules.a06.reference_review import run
from science_modules.a06.reference_review_contract import validate_request


class ReferenceReviewTests(unittest.TestCase):
    def payload(self, **changes):
        value = {"expected_input_id": "input_" + "a" * 32,
                 "expected_preparation_run_id": "run_" + "b" * 32,
                 "request_id": "refreq_" + "c" * 32,
                 "reviewer": "隔离核查人", "note": "只记录明确不采用参考",
                 "confirmed": True, "choices": []}
        value.update(changes)
        return value

    def test_request_rejects_hidden_science_fields(self):
        with self.assertRaises(ContractError):
            validate_request(dict(self.payload(), box_padding=9))
        with self.assertRaises(ContractError):
            validate_request(self.payload(confirmed=False))

    def test_empty_choice_is_archived_without_scoring(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "studies" / "study_fixture"
            home.mkdir(parents=True)
            workflow = type("Workflow", (), {})()
            workflow.location = lambda sid: home
            workflow.publish_analysis_plan_a06_reference_review = lambda sid, payload, packet: {
                "review": {"review_id": "refreview_fixture"}, "created": True}
            data = {"current_run": {"run_id": "run_" + "b" * 32,
                                     "config": {"version": "A06.plan_preparation.2"}},
                    "input_record": {"input_id": "input_" + "a" * 32},
                    "source_run": {"run_id": "run_" + "b" * 32,
                                    "config": {"version": "A06.plan_preparation.2"}},
                    "source_fact": {"connection": {"compounds": [], "receptors": []}}}
            with patch("modulea.core.plan_pockets.context", return_value=data):
                result = run(workflow, "study_fixture", self.payload(), Path(folder), lambda _: None)
            self.assertEqual(result["summary"]["choice_count"], 0)
            self.assertEqual(result["summary"]["scored_pairs"], 0)
            self.assertTrue(result["summary"]["handoff_blocked"])
            packet = next((home / "runs/A06_PREP" / data["current_run"]["run_id"] / "reference_review").rglob("packet.json"))
            packet_data = json.loads(packet.read_text(encoding="utf-8"))
            self.assertFalse(any(ref["path"].endswith("/packet.json") for ref in packet_data["files"]))


if __name__ == "__main__":
    unittest.main()
