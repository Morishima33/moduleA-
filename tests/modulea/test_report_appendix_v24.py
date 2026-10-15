"""第24版回归：解释只在附录、图先表后，以及热图完整标签和原格值保护。"""

from copy import deepcopy
from unittest.mock import patch
import unittest

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from contracts import ContractError
from science_modules.a07.appendix_documents import (
    APPENDIX,
    APPENDIX_TITLE,
    add_appendix,
    revise_body,
    validate_document,
)
from science_modules.a07.appendix_heatmap import drawing, heatmap_svg, layout
from science_modules.a06.matrix_palette import RED_BLUE, color


class AppendixTests(unittest.TestCase):
    def document(self):
        """合成文档保留实际章节顺序与节断，批注修改不能影响这些边界。"""
        doc = Document()
        for text in (
            "成分与靶点概览：前十成分为甲；PPI第二轮Degree前十靶点为旧重复名单。",
            "PPI方向：保留完整交集名单。",
            "成分与方剂靶点：完整InChIKey是化学结构的标准身份标识，跨库合并要求完整标识一致且分子式无冲突。",
            "疾病靶点：GeneCards：已有候选资料，待核验（27条）；TTD：已查询但0条精确记录（0条）。",
            "PPI：使用人类9606的功能关联网络。",
            "分子对接：以exhaustiveness=8、最多9个姿势、energy_range=3、seed=1运行。",
            "混合Degree为交集靶点数加来源药味数，仅供参考。主排名保留。",
        ):
            doc.add_paragraph(text)
        doc.add_paragraph("表 A05 01 GO BP 生物过程前十五")
        table = doc.add_table(rows=2, cols=1)
        table.cell(0, 0).text = "保留表头"
        table.cell(1, 0).text = "原始统计数据"
        self.graph(doc, "图 A05 01 GO图")
        doc.add_paragraph("表 A05 04 KEGG统计显著性前十")
        self.graph(doc, "图 A05 02 KEGG图")
        doc.add_paragraph("9 主要方法参考文献")
        return doc

    def graph(self, doc, caption):
        paragraph = doc.add_paragraph()
        paragraph.add_run()._r.append(OxmlElement("w:drawing"))
        doc.add_paragraph(caption)

    def test_appendix_keeps_explanations_out_of_body_and_preserves_data(self):
        doc = self.document()
        table_before = doc.tables[0]._tbl.xml
        revise_body(doc, True)
        with (
            patch("science_modules.a06.bilingual_heatmap.matrix", return_value={}),
            patch(
                "science_modules.a06.matrix_exports.na_lines", return_value=["NA[1]：合成缺失原因"]
            ),
        ):
            add_appendix(doc, {"trial_packet": {}, "compound_names": {}})
        validate_document(doc, True)
        text = [p.text for p in doc.paragraphs]
        body = "\n".join(text[: text.index(APPENDIX_TITLE)])
        self.assertIn("完整InChIKey一致且分子式无冲突", body)
        self.assertIn("已有候选资料（27条）", body)
        self.assertIn("0条精确记录（0条）", body)
        self.assertIn("PPI方向：保留完整交集名单。", body)
        self.assertNotIn("旧重复名单", body)
        self.assertNotIn("9606", body)
        self.assertIn("NA[1]：合成缺失原因", text)
        self.assertEqual(doc.tables[0]._tbl.xml, table_before)
        self.assertTrue(
            next(
                p for p in doc.paragraphs if p.text == APPENDIX_TITLE
            ).paragraph_format.page_break_before
        )

    def test_graph_moves_as_pair_without_moving_table_or_section(self):
        doc = self.document()
        section = doc._element.body.find(qn("w:sectPr"))
        revise_body(doc, True)
        text = [p.text for p in doc.paragraphs]
        self.assertLess(text.index("图 A05 01 GO图"), text.index("表 A05 01 GO BP 生物过程前十五"))
        self.assertLess(text.index("图 A05 02 KEGG图"), text.index("表 A05 04 KEGG统计显著性前十"))
        self.assertIs(doc._element.body[-1], section)

    def test_validator_rejects_explanation_drifting_back_into_body(self):
        doc = Document()
        doc.add_paragraph("分子对接exhaustiveness=8")
        doc.add_heading(APPENDIX_TITLE, 1)
        for title, explanation in APPENDIX:
            doc.add_heading(title, 2)
            doc.add_paragraph(explanation)
        with self.assertRaises(ContractError):
            validate_document(doc, False)

    def test_heatmap_labels_values_and_colors_survive_compact_layout(self):
        rows = [
            {
                "compound_id": "c",
                "name_zh": "合成成分",
                "name_en": "7-hydroxy-3-(4-hydroxyphenyl)chromen-4-one",
            }
        ]
        columns = [{"target_id": "t", "symbol": "SYNTHETIC", "candidate_grade": "A"}]
        cell = {
            "compound_id": "c",
            "target_id": "t",
            "state": "completed",
            "score": -8.123,
            "color": color(-8.123, -10, -5, RED_BLUE),
            "text_color": "#FFFFFF",
        }
        part = {"rows": rows, "columns": columns, "cells": [[cell]]}
        matrix = {
            "ready": True,
            "palette": RED_BLUE,
            "score_range": [-10, -5],
            "heatmap": part,
            "table": part,
        }
        before = deepcopy(matrix)
        geometry, elements = drawing(matrix)
        svg = heatmap_svg(matrix)
        labels = [item[3] for item in elements if item[0] == "text"]
        self.assertIn("-8.12", labels)
        self.assertIn(cell["color"], svg)
        self.assertIn(rows[0]["name_en"], "".join(labels))
        self.assertNotIn("Vina评分不能直接证明药效", svg)
        self.assertNotIn("颜色范围取完整同批", svg)
        self.assertLess(geometry["left"], 308)
        self.assertEqual(matrix, before)
        self.assertEqual(layout(matrix), geometry)


if __name__ == "__main__":
    unittest.main()
