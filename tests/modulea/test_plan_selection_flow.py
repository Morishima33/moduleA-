import unittest

from science_modules.analysis_protocol import compile_plan
from science_modules.a04.selection_flow import select_from_network, validate_selection


class PlanSelectionFlowTest(unittest.TestCase):
    def setUp(self):
        self.metrics = [{"target_id": "HGNC:" + str(i), "symbol": "G" + str(i),
                         "degree": i, "bc": float(i) / 10, "cc": float(i) / 10, "component": 1}
                        for i in range(1, 9)]
        self.summary = {"参与节点数": 8, "合格边数": 12, "required_score": .90}
        self.tables = {"metrics": self.metrics, "edges": []}

    def make_plan(self, mode):
        return compile_plan({"mode": "personalized", "parameters": {
            "a04.mode": mode, "a06.receptor_count": 2,
            "a04.degree_main_window": 10, "a04.bc_cc_window": 15,
            "a04.degree_pool_window": 15}})

    def test_each_mode_produces_bound_selection(self):
        for mode in ("degree", "bc_cc", "dual_ab"):
            result = select_from_network("run_a04", self.summary, self.tables, self.make_plan(mode))
            self.assertEqual(result["network_run_id"], "run_a04")
            self.assertLessEqual(result["actual_count"], 2)
            self.assertEqual(result["replacement_after_preparation_failure"], False)

    def test_tampered_selection_is_rejected(self):
        p = self.make_plan("degree")
        result = select_from_network("run_a04", self.summary, self.tables, p)
        result["selected"] = [{"target_id": "HGNC:999", "symbol": "FAKE"}]
        with self.assertRaises(Exception):
            validate_selection(result, "run_a04", self.summary, self.tables, p)


if __name__ == "__main__":
    unittest.main()
