"""展示口径的回归：完整名单求交、边界并列及未经舍入的评分标记。"""

import unittest
from science_modules.a07.commented_facts import ppi_intersection, strong_pairs, enrichment_sections


class ReportFactsTests(unittest.TestCase):
    def test_intersection_uses_full_lists_and_keeps_degree_ties(self):
        rows = [{"target_id": str(i), "symbol": "G" + str(i), "degree": 100 - i} for i in range(13)]
        rows[10]["degree"] = rows[9]["degree"]
        tables = {
            "degree_round2": rows,
            "bc_cc_round2": rows,
            "degree_round1_top10": rows[:1],
            "bc_cc_top15": rows[:1],
        }
        complete, top = ppi_intersection(tables)
        self.assertEqual(len(complete), 13)
        self.assertEqual(len(top), 11)
        self.assertEqual(top[-1]["degree"], top[-2]["degree"])

    def test_threshold_uses_original_value_and_binds_stable_ids(self):
        packet = {
            "compounds": [{"compound_id": "c", "name_zh": "甲"}],
            "receptors": [{"target_id": "r", "symbol": "R"}, {"target_id": "s", "symbol": "S"}],
            "pairs": [
                {"compound_id": "c", "target_id": "r", "state": "completed", "score": -7.999},
                {"compound_id": "c", "target_id": "s", "state": "completed", "score": -8},
            ],
        }
        rows = strong_pairs(packet, {"c": {"name_zh": "甲", "name_en": "A"}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["受体"], "S")
        self.assertEqual(rows[0]["成分"], "甲（A）")

    def test_summary_has_three_go_groups_and_two_kegg_rankings(self):
        rows = [
            {"Description": "Term" + str(i), "description_zh": "条目" + str(i)} for i in range(15)
        ]
        t = {
            key: rows
            for key in ("bp_top15", "cc_top15", "mf_top15", "kegg_p_top10", "kegg_count_top10")
        }
        sections = enrichment_sections(t)
        self.assertEqual([r["结论"].count("（") for r in sections], [3, 3, 3, 5, 5])


if __name__ == "__main__":
    unittest.main()
