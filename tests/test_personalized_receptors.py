"""固定指标验证三种受体模式、A优先及边界并列；不获取网络或运行对接。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from contracts import ContractError
from science_modules.analysis_protocol import compile_plan
from science_modules.a04.personalized_selection import select_receptors


def fixture(tied=False):
    """低度节点固定中位数，高度节点构造可人工核对的两轮及分支交集。"""
    high = []
    for i in range(30):
        degree = (100 if i < 18 else 20) if tied else 100 - i
        value = (18 - i if i < 18 else 0) if tied else (100 - i if i >= 5 else 1)
        high.append({"target_id": f"HGNC:{i:03d}", "symbol": f"G{i}", "degree": degree, "bc": value, "cc": value / 100})
    return high + [{"target_id": f"HGNC:L{i:03d}", "symbol": f"L{i}", "degree": 1, "bc": 0, "cc": 0} for i in range(100)]


class PersonalizedReceptorTests(unittest.TestCase):
    """名单决定发生于A04，PREP不能在此接口替换任何对象。"""

    def plan(self, mode="dual_ab", count=10):
        return compile_plan({"mode": "personalized", "parameters": {"a04.mode": mode, "a06.receptor_count": count}})

    def ids(self, result):
        return [r["target_id"] for r in result["selected"]]

    def test_three_modes_have_the_expected_final_order(self):
        rows = fixture()
        degree = self.ids(select_receptors(rows, self.plan("degree")))
        bc = self.ids(select_receptors(rows, self.plan("bc_cc")))
        dual = select_receptors(rows, self.plan())
        self.assertEqual(degree, [f"HGNC:{i:03d}" for i in range(10)])
        self.assertEqual(bc, [f"HGNC:{i:03d}" for i in range(5, 15)])
        self.assertEqual(self.ids(dual), [f"HGNC:{i:03d}" for i in [5, 6, 7, 8, 9, 0, 1, 2, 3, 4]])
        self.assertEqual([r["candidate_grade"] for r in dual["selected"]], ["A"] * 5 + ["B"] * 5)
        self.assertEqual(dual["range_owner"], "A04")
        self.assertFalse(dual["replacement_after_preparation_failure"])

    def test_ties_expand_actual_count_and_id_never_cuts_the_boundary(self):
        result = select_receptors(fixture(True), self.plan(count=15))
        self.assertEqual(result["requested_count"], 15)
        self.assertEqual(result["actual_count"], 18)
        self.assertEqual(set(self.ids(result)), {f"HGNC:{i:03d}" for i in range(18)})
        self.assertEqual(len(result["thresholds"]), 4)

    def test_shortfall_and_empty_keep_actual_range_without_backfill(self):
        short = select_receptors(fixture(), self.plan(count=25))
        self.assertEqual(short["actual_count"], 15)
        empty = select_receptors([], self.plan())
        self.assertEqual(empty["actual_count"], 0)
        self.assertEqual(empty["selected"], [])

    def test_order_and_unrelated_display_parameters_do_not_change_selection(self):
        rows, plan = fixture(), self.plan()
        result = select_receptors(rows, plan)
        reversed_result = select_receptors(list(reversed(rows)), plan)
        self.assertEqual(result["selected"], reversed_result["selected"])
        self.assertEqual(result["selection_hash"], reversed_result["selection_hash"])
        changed = compile_plan({"mode": "personalized", "parameters": {"a06.receptor_count": 10, "a05.go_plot_top": 25}})
        self.assertEqual(result["selection_hash"], select_receptors(rows, changed)["selection_hash"])

    def test_original_metrics_are_not_recomputed_or_mutated(self):
        rows = fixture()
        saved = [dict(r) for r in rows]
        result = select_receptors(rows, self.plan())
        self.assertEqual(rows, saved)
        expected = {r["target_id"]: r for r in rows}
        for row in result["selected"]:
            for key in ("degree", "bc", "cc"):
                self.assertEqual(row[key], expected[row["target_id"]][key])
        with self.assertRaises(ContractError):
            select_receptors(rows + [rows[0]], self.plan())


if __name__ == "__main__":
    unittest.main()
