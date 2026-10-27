import json
import unittest
from pathlib import Path

from science_modules.analysis_protocol import compile_plan
from science_modules.a04.plan_flow import calculate, evaluate


def plan(score):
    return compile_plan({"mode": "personalized", "parameters": {"a04.required_score": score}})


class PlanPpiTest(unittest.TestCase):
    def setUp(self):
        self.targets = [{"target_id": "HGNC:1", "symbol": "A"},
                        {"target_id": "HGNC:2", "symbol": "B"},
                        {"target_id": "HGNC:3", "symbol": "C"}]
        self.mapping = [{"queryIndex": i, "ncbiTaxonId": 9606, "preferredName": t["symbol"],
                         "stringId": "9606." + str(i + 1)} for i, t in enumerate(self.targets)]
        self.network = [{"stringId_A": "9606.1", "stringId_B": "9606.2", "score": .70,
                         "ncbiTaxonId": 9606},
                        {"stringId_A": "9606.2", "stringId_B": "9606.3", "score": .89,
                         "ncbiTaxonId": 9606}]

    def test_threshold_is_applied_and_recorded(self):
        summary, tables = calculate(self.targets, self.mapping, self.network, plan(.70))
        self.assertEqual(summary["合格边数"], 2)
        self.assertEqual(summary["required_score"], .70)
        self.assertEqual(tables["discarded_edges"], [])
        summary2, tables2 = calculate(self.targets, self.mapping, self.network, plan(.90))
        self.assertEqual(summary2["合格边数"], 0)
        self.assertEqual(len(tables2["discarded_edges"]), 2)
        self.assertEqual(tables2["discarded_edges"][0]["required_score"], .90)

    def test_evaluate_requires_request_threshold_and_recalculates(self):
        bundle = {"schema_version": "A04.plan_source.1", "analysis_plan_id": plan(.70)["parameter_hash"],
                  "analysis_parameter_hash": plan(.70)["parameter_hash"],
                  "mapped_string_ids": ["9606.1", "9606.2", "9606.3"],
                  "mapping": {"response_text": json.dumps(self.mapping)},
                  "network": {"params": {"identifiers": "9606.1\r9606.2\r9606.3", "species": 9606,
                                            "required_score": 700, "network_type": "functional",
                                            "add_nodes": 0, "caller_identity": "ModuleA"},
                              "response_text": json.dumps(self.network)}}
        summary, tables = evaluate(self.targets, bundle, plan(.70))
        self.assertEqual(summary["required_score"], .70)
        self.assertEqual(len(tables["edges"]), 2)
        bundle["network"]["params"]["required_score"] = 900
        with self.assertRaises(Exception):
            evaluate(self.targets, bundle, plan(.70))
        bundle["network"]["params"]["required_score"] = 700
        bundle["analysis_plan_id"] = plan(.90)["parameter_hash"]
        with self.assertRaises(Exception):
            evaluate(self.targets, bundle, plan(.70))


if __name__ == "__main__":
    unittest.main()
