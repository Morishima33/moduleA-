"""来源名称及排名边界的展示回归；不写科研资料。"""
import unittest
from modulea.core.source_catalog import source_intro
from modulea.presenters.intersection import present_a03

class SourceDisplayTests(unittest.TestCase):
    def test_current_and_historical_sources(self):
        current = source_intro("A02", {}, {"summary": {"databases": ["GeneCards", "OMIM", "TTD", "PharmGKB", "OTP"]}})
        self.assertIn("五库", current)
        self.assertIn("Open Targets Platform（OTP）", current)
        self.assertNotIn("DisGeNET", current)
        history = source_intro("A02", {}, {"summary": {"databases": ["GeneCards", "OMIM", "TTD", "DisGeNET", "OTP"]}})
        self.assertIn("DisGeNET", history)
        self.assertNotIn("PharmGKB", history)
        self.assertIn("BATMAN-TCM", source_intro("A01", {}, {"summary": {"候选成分分组数": 1}}))
        self.assertNotIn("三库", source_intro("A01", {}, {}))

    def test_top_ten_keeps_boundary_ties_and_full_count(self):
        rows = [{"compound_id": str(i), "name": str(i), "herbs": "药味", "main_rank": i + 1, "intersection_count": 20 - i, "mixed_degree": 21 - i} for i in range(12)]
        rows[10].update(intersection_count=11, main_rank=10)
        parts = present_a03({"summary": {}, "tables": {"ranking": list(reversed(rows))}}, {})
        self.assertEqual(len(parts.special["component_top"]), 11)
        self.assertEqual(parts.table["row_count"], 12)
        self.assertEqual([r["main_rank"] for r in parts.special["component_top"]][-2:], [10, 10])
        self.assertIn("不自动入选对接", parts.special["component_top_note_zh"])

    def test_less_than_ten_and_zero_unranked(self):
        rows = [{"compound_id": "a", "main_rank": 1, "intersection_count": 3}, {"compound_id": "b", "main_rank": None, "intersection_count": 0}]
        parts = present_a03({"summary": {}, "tables": {"ranking": rows}}, {})
        self.assertEqual(len(parts.special["component_top"]), 1)
        self.assertEqual(parts.table["row_count"], 2)
