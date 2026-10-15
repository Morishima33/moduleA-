"""第23版模板回归：十组展示、正文去重、限制章节删除和分页保护。"""

import unittest

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.oxml.ns import qn

from science_modules.a07.refined_documents import revise_layout, top_pairs
from science_modules.a07.report_heatmap import label_lines


class ReportLayoutTests(unittest.TestCase):
    def test_top_ten_uses_original_score_and_stable_ids(self):
        rows = [
            {"compound_id": str(i), "target_id": "t", "结合能（kcal/mol）": -8 - i / 10}
            for i in range(14)
        ]
        original = [dict(row) for row in rows]
        selected = top_pairs(rows)
        self.assertEqual(len(selected), 10)
        self.assertEqual(selected[0]["compound_id"], "13")
        self.assertEqual(rows, original)

    def test_body_duplicates_removed_but_summary_and_tables_retained(self):
        doc = Document()
        doc.add_heading("1 主要结论", 1)
        doc.add_paragraph("GO BP 生物过程前三：摘要保留")
        doc.add_paragraph("结构方向：旧内容")
        doc.add_paragraph("AKT1：长清单")
        doc.add_paragraph("该界值仅用于标记本批展示组合，不表示统计显著性或实测药效。")
        doc.add_heading("5 GO与KEGG富集结果", 1)
        doc.add_paragraph("GO BP 生物过程前三：正文重复")
        doc.add_paragraph("KEGG统计显著性前五：正文重复")
        doc.add_paragraph("表 A05 01 GO BP 生物过程前十五")
        doc.add_paragraph("表 A05 04 KEGG统计显著性前十")
        doc.add_heading("6 分子对接结果", 1)
        doc.add_section(WD_SECTION_START.NEW_PAGE)
        doc.add_heading("7 待进一步核验的研究线索", 1)
        doc.add_heading("8 主要限制", 1)
        doc.add_paragraph("1. 应删除的章节内容")
        doc.add_heading("9 结果复核说明", 1)
        doc.add_paragraph("仍需人工复核")
        doc.add_heading("10 主要方法参考文献", 1)
        rows = [
            {
                "compound_id": str(i),
                "target_id": "t",
                "成分": "成分",
                "受体": "AKT1",
                "结合能（kcal/mol）": -8 - i / 10,
            }
            for i in range(14)
        ]
        revise_layout(doc, {"strong_pairs": rows})
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("摘要保留", text)
        self.assertNotIn("正文重复", text)
        self.assertNotIn("主要限制", text)
        self.assertNotIn("应删除", text)
        self.assertNotIn("长清单", text)
        self.assertIn("8 结果复核说明", text)
        self.assertIn("9 主要方法参考文献", text)
        self.assertIn("GO BP 生物过程前十五", text)
        self.assertIn("KEGG统计显著性前十", text)
        self.assertEqual(len(doc.tables[-1].rows), 11)
        self.assertEqual(len(doc._element.body.findall(".//" + qn("w:sectPr"))), 2)

    def test_long_chemical_name_wraps_without_losing_characters(self):
        value = "7-hydroxy-3-(4-hydroxyphenyl)chromen-4-one"
        lines = label_lines(value)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), value)
        self.assertLessEqual(max(map(len, lines)), 30)


if __name__ == "__main__":
    unittest.main()
