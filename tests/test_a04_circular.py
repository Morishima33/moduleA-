"""圆形第二轮图回归：图源与表源不同、真实边、并列、空结果和历史不变。"""

from pathlib import Path
import copy
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from docx import Document
from contracts import ContractError
from test_a04_dual import metrics, source_bundle
from test_a04_first_round import study
from science_modules.a04 import selection_v2, selection_v3
from science_modules.a04.circular_figures import draw_degree, circular_layout, degree_caption
from science_modules.a04.flow_v3 import run_ppi, validator, validate_network_svg
from science_modules.a07.circular_reports import (
    add_dual_section,
    degree_rows,
    bc_cc_rows,
    validate_word_tables,
)
from modulea.presenters.network import present_a04


class CircularTests(unittest.TestCase):
    def test_distinct_round_sources_and_unchanged_science(self):
        source = ({"参与节点数": 8, "合格边数": 12}, {"metrics": metrics(), "edges": []})
        old_s, old_t = selection_v2.from_legacy(*copy.deepcopy(source))
        summary, tables = selection_v3.from_legacy(*copy.deepcopy(source))
        self.assertEqual(tables, old_t)
        for key, value in old_s.items():
            if key != "selection_version":
                self.assertEqual(summary[key], value)
        view = present_a04({"summary": summary, "tables": tables}, {})
        ppi = view.special["ppi_dual"]
        self.assertEqual(ppi["network_round"], 2)
        self.assertEqual(ppi["degree_round"], 1)
        self.assertEqual(ppi["degree_rows"], tables["degree_round1_top10"])
        self.assertNotEqual(tables["degree_round1_top10"], tables["degree_top10"])
        document = Document()
        add_dual_section(document, {"tables": tables})
        self.assertIn("第一轮前十表及第二轮候选网络", document.paragraphs[0].text)
        self.assertIn("第一轮前十", document.paragraphs[1].text)
        with patch(
            "science_modules.a07.circular_reports.legacy._add_figure",
            side_effect=lambda doc, *args: doc.add_paragraph("第二轮图件占位"),
        ):
            ordered = Document()
            add_dual_section(ordered, {"tables": tables}, ({}, Path(".")))
        elements = list(ordered._element.body)
        graph = next(p._p for p in ordered.paragraphs if p.text == "第二轮图件占位")
        self.assertLess(elements.index(ordered.tables[0]._tbl), elements.index(graph))
        self.assertLess(elements.index(graph), elements.index(ordered.tables[1]._tbl))
        archive = {"a04_degree_top10": degree_rows(tables), "a04_bc_cc_top15": bc_cc_rows(tables)}
        validate_word_tables(document, {"tables": tables}, archive)
        self.assertEqual(
            [c.text for c in document.tables[0].rows[0].cells],
            ["基因", "HGNC", "Degree", "Betweenness", "Closeness"],
        )

    def test_layout_preserves_isolates_ties_and_spreads_nodes(self):
        for count, top_count in [(0, 0), (1, 1), (2, 2), (17, 17), (121, 10), (250, 14)]:
            rows = [
                {"target_id": str(i), "symbol": "NODE" + str(i), "degree": 20} for i in range(count)
            ]
            top = rows[:top_count]
            positions, sizes, width, height, cx, cy = circular_layout(rows, top)
            self.assertEqual(set(positions), {r["target_id"] for r in rows})
            for i, a in enumerate(positions):
                for b in list(positions)[i + 1 :]:
                    self.assertGreater(
                        math.dist(positions[a], positions[b]) - sizes[a] - sizes[b], 15
                    )
            with tempfile.TemporaryDirectory() as directory:
                tables = {"degree_round2": rows, "degree_top10": top, "edges": []}
                paths = draw_degree(tables, Path(directory) / "network")
                validate_network_svg(paths["svg"], tables)
                tree = ET.parse(paths["svg"]).getroot()
            children = list(tree)
            circles = [i for i, c in enumerate(children) if c.tag.endswith("circle")]
            labels = [
                i
                for i, c in enumerate(children)
                if c.tag.endswith("text") and c.text and c.text.startswith("NODE")
            ]
            if circles and labels:
                self.assertGreater(min(labels), max(circles))

    def test_svg_identity_and_edges_tampering(self):
        rows = [
            {"target_id": str(i), "symbol": "GENE" + str(i), "degree": 20 - i} for i in range(3)
        ]
        tables = {
            "degree_round2": rows,
            "degree_top10": rows[:1],
            "edges": [
                {"source": "0", "target": "1"},
                {"source": "1", "target": "2"},
                {"source": "2", "target": "outside"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = draw_degree(tables, Path(directory) / "network")["svg"]
            validate_network_svg(path, tables)
            original = path.read_text(encoding="utf-8")
            for old, new in [
                ('data-target-id="2"', 'data-target-id="wrong"'),
                ('data-source="0"', 'data-source="2"'),
                ("#D9555D", "#3D7FA6"),
            ]:
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                with self.assertRaises(ContractError):
                    validate_network_svg(path, tables)
            self.assertIn("第二轮3节点", degree_caption(tables))

    def test_new_run_preserves_previous_and_remains_unapproved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            w, sid, a03, targets = study(root)
            w.validators["A04"] = validator(root)
            from science_modules.a04.flow_v2 import run_ppi as old_run

            with patch("ppi_flow.request", side_effect=AssertionError("禁止联网")):
                old = old_run(w, sid, a03, "", "旧版虚构检查", source_bundle(targets))
                old_png = w.location(sid) / old["tables"]["degree_network"][0]["png_path"]
                before = old_png.read_bytes()
                new = run_ppi(w, sid, a03, old["run_id"], "新图虚构检查", source_bundle(targets))
            self.assertEqual(old_png.read_bytes(), before)
            m = w.load(sid)
            self.assertEqual(w.result(m, old["run_id"]), old)
            self.assertFalse(w.approved(m, new["run_id"]))
            self.assertEqual(
                new["tables"]["degree_network"][0]["network_rule"], selection_v3.NETWORK_RULE
            )
            bad = copy.deepcopy(new["tables"])
            bad["degree_network"][0]["network_rule"] = "wrong"
            with self.assertRaises(ContractError):
                validator(root)(w.run(m, new["run_id"]), new["summary"], bad, [], new["outcome"])


if __name__ == "__main__":
    unittest.main()
