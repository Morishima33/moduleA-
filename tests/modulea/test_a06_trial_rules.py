"""隔离资料验证试算边界：覆盖、位点优先、区域最低值、NA与225格一致性。"""

import itertools
import random
import unittest
from copy import deepcopy

from modulea.api.trial_view import color
from science_modules.a06.trial_rules import (
    choose_score,
    inside,
    partitions,
    validate_matrix,
)


class TrialRulesTests(unittest.TestCase):
    """预期结果按用户规则独立构造，不依赖真实研究文件。"""

    def test_partition_extremes_and_sparse_empty_boxes(self):
        points = [[-7, -8, -9], [70, 50, 40]]
        boxes = partitions(points)
        for p in points:
            self.assertTrue(any(inside(p, b) for b in boxes))
        self.assertTrue(all(any(inside(p, b) for p in points) for b in boxes))
        self.assertTrue(all(b["size"] == [30.0] * 3 for b in boxes))
        self.assertEqual(len({b["region_id"] for b in boxes}), len(boxes))

    def test_partition_random_points_and_invalid_inputs(self):
        rng = random.Random(13)
        points = [[rng.uniform(-90, 90) for _ in range(3)] for _ in range(50)]
        boxes = partitions(points)
        self.assertTrue(all(any(inside(p, b) for b in boxes) for p in points))
        for points in ([], [[float("nan"), 1, 2]], [[1, 2]]):
            with self.assertRaises(ValueError):
                partitions(points)
        with self.assertRaises(ValueError):
            partitions([[1, 2, 3]], step=31)

    def test_fixed_site_cannot_choose_other_site(self):
        rows = [{"region_id": "fixed", "state": "completed", "score": -6.75}]
        self.assertEqual(choose_score(rows, "fixed_site")["score"], -6.75)
        rows.append({"region_id": "other", "state": "completed", "score": -9})
        with self.assertRaises(ValueError):
            choose_score(rows, "fixed_site")

    def test_minimum_region_and_tie_are_transparent(self):
        rows = [
            {"region_id": "b", "state": "completed", "score": -8.123},
            {"region_id": "a", "state": "completed", "score": -8.123},
            {"region_id": "c", "state": "NA", "score": None},
        ]
        self.assertEqual(choose_score(rows, "predicted_sites")["region_id"], "a")
        self.assertEqual(choose_score(rows, "partitioned_blind")["score"], -8.123)
        self.assertIsNone(choose_score([rows[2]], "partitioned_blind"))

    def packet(self):
        """十五成分乘十五受体；每格只有真实模拟归档值或明确NA。"""
        compounds = [{"compound_id": f"c{i}"} for i in range(15)]
        targets = [{"target_id": f"t{i}"} for i in range(15)]
        pairs = [
            {
                "compound_id": c["compound_id"],
                "target_id": r["target_id"],
                "mode": "fixed_site",
                "state": "completed",
                "score": -7.123456,
                "selected_region_id": "fixed",
                "regions": [
                    {"region_id": "fixed", "state": "completed", "score": -7.123456}
                ],
            }
            for c, r in itertools.product(compounds, targets)
        ]
        return {"compounds": compounds, "receptors": targets, "pairs": pairs}

    def test_complete_225_and_na_keeps_scope(self):
        packet = self.packet()
        self.assertTrue(validate_matrix(packet))
        packet["pairs"][0].update(
            state="NA",
            score=None,
            regions=[],
            selected_region_id=None,
            reason_zh="准备失败",
        )
        self.assertTrue(validate_matrix(packet))
        self.assertEqual(len(packet["pairs"]), 225)
        del packet["pairs"][0]["reason_zh"]
        with self.assertRaises(ValueError):
            validate_matrix(packet)

    def test_missing_duplicate_and_fabricated_value_rejected(self):
        packet = self.packet()
        for change in (
            lambda p: p["pairs"].pop(),
            lambda p: p["pairs"].__setitem__(0, deepcopy(p["pairs"][1])),
            lambda p: p["pairs"][0].__setitem__("score", -99),
        ):
            copy = deepcopy(packet)
            change(copy)
            with self.assertRaises(ValueError):
                validate_matrix(copy)

    def test_palette_full_batch_direction_constant_and_na(self):
        self.assertEqual(color(-10, -10, -3), "#B2182B")
        self.assertEqual(color(-3, -10, -3), "#2166AC")
        self.assertEqual(color(None, None, None), "#DCE1E5")
        self.assertTrue(color(-6, -6, -6).startswith("#"))

    def test_annotation_uses_unrounded_boundary_and_keeps_na(self):
        from science_modules.a06.trial_presentation import highlighted, score_label

        self.assertTrue(highlighted(-8.0))
        self.assertTrue(highlighted(-8.00001))
        self.assertFalse(highlighted(-7.99999))
        self.assertEqual(score_label(-7.99999, mark=True), "-8.00")
        self.assertEqual(score_label(-8.0, mark=True), "-8.00**")
        self.assertEqual(score_label(-8.0), "-8.00")
        self.assertEqual(score_label(None, mark=True), "NA")
        for value in (None, float("nan"), float("inf"), float("-inf"), True):
            self.assertFalse(highlighted(value))


if __name__ == "__main__":
    unittest.main()
