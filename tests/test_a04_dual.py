"""双分支筛选、来源复算、等权并列及报告实际单元格回归；仅虚构资料。"""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contracts import ContractError
from science_modules.a04.selection import (
    select,
    average_ranks,
    ranked,
    boundary_top,
    from_legacy,
    VERSION,
)
from science_modules.a04.flow import evaluate, validator, run_ppi, CONFIG, docking_validator
from modulea.presenters.network import present_a04
from workflow import Workflow
from storage import read_json
from docx import Document
from science_modules.a07.dual_reports import (
    add_dual_section,
    validate_word_tables,
    degree_rows,
    bc_cc_rows,
    run_reports,
)


# 有限正指标，不调用数据库或用户研究。
def metrics():
    return [
        {
            "target_id": f"HGNC:{i + 1}",
            "symbol": f"D{i + 1}",
            "degree": d,
            "bc": i,
            "cc": i / 10,
            "component": 1,
        }
        for i, d in enumerate([2, 4, 6, 8, 12, 20, 24, 40])
    ]


def result():
    return dict(
        zip(
            ("summary", "tables"),
            from_legacy(
                {"参与节点数": 8, "合格边数": 12},
                {"metrics": metrics(), "edges": [], "round1": [], "round2": [], "thresholds": []},
            ),
        )
    )


class DualTests(unittest.TestCase):
    def test_two_branches_thresholds_and_fixed_metrics(self):
        original = metrics()
        snapshot = copy.deepcopy(original)
        t = select(original)
        self.assertEqual(original, snapshot)
        self.assertEqual([r["degree"] for r in t["degree_round1"]], [20, 24, 40])
        self.assertEqual([r["degree"] for r in t["degree_round2"]], [40, 24])
        self.assertEqual(t["dual_thresholds"][0]["degree_threshold"], 20)
        self.assertEqual(t["dual_thresholds"][1]["degree_threshold"], 24)
        self.assertEqual(len(t["bc_cc_round1"]), 4)
        self.assertEqual(len(t["bc_cc_round2"]), 2)
        for old, new in zip(snapshot, t["metrics"]):
            for k in ("degree", "bc", "cc"):
                self.assertEqual(old[k], new[k])

    def test_strict_bc_cc_empty_and_degree_no_shrink_on_ties(self):
        rows = [dict(r, degree=4, bc=0, cc=0.5) for r in metrics()]
        t = select(rows)
        self.assertFalse(t["degree_round1"])
        self.assertFalse(t["bc_cc_round1"])
        self.assertIsNone(t["dual_thresholds"][1]["degree_threshold"])
        rows = [dict(r, degree=(1 if i < 5 else 8)) for i, r in enumerate(metrics())]
        t = select(rows)
        self.assertEqual(len(t["degree_round1"]), 3)
        self.assertEqual(len(t["degree_round2"]), 3)

    def test_average_ranks_equal_weight_and_no_raw_addition(self):
        rows = [
            {"target_id": "a", "bc": 9, "cc": 1},
            {"target_id": "b", "bc": 9, "cc": 2},
            {"target_id": "c", "bc": 3, "cc": 2},
        ]
        self.assertEqual(average_ranks(rows, "bc"), {"a": 1.5, "b": 1.5, "c": 3})
        self.assertEqual(average_ranks(rows, "cc"), {"b": 1.5, "c": 1.5, "a": 3})
        t = select(metrics())
        self.assertTrue(
            all(r["mean_rank"] == (r["bc_rank"] + r["cc_rank"]) / 2 for r in t["bc_cc_round2"])
        )

    def test_true_ties_and_boundary_group(self):
        rows = [{"target_id": str(i).zfill(2), "degree": 20 if i < 9 else 10} for i in range(13)]
        ranked_rows = ranked(rows, "degree", True)
        self.assertEqual([r["rank"] for r in ranked_rows], [1] * 9 + [10] * 4)
        self.assertEqual(len(boundary_top(ranked_rows, 10, "degree")), 13)
        # 第二轮有14个，但只将前十截断并列的13个标红；无边候选仍交给绘图器。
        from science_modules.a04.figures import draw_degree

        first = [dict(r, symbol=r["target_id"]) for r in ranked_rows] + [
            {"target_id": "low", "symbol": "LOW", "degree": 4}
        ]
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as directory:
            output = draw_degree(
                {
                    "degree_round1": first,
                    "degree_round2": first,
                    "degree_top10": first[:13],
                    "edges": [],
                },
                Path(directory) / "demo",
                demo=True,
            )
            picture = ET.parse(output["svg"]).getroot()
        circles = list(picture.iter("{http://www.w3.org/2000/svg}circle"))
        self.assertEqual(len(circles), 14)
        self.assertEqual(sum(c.get("fill") == "#D9555D" for c in circles), 13)
        self.assertEqual(sum(c.get("fill") == "#3D7FA6" for c in circles), 1)
        labels = [node.text for node in picture.iter("{http://www.w3.org/2000/svg}text")]
        self.assertNotIn("LOW", labels)
        self.assertTrue(any("演示数据" in (label or "") for label in labels))
        rows = ranked([{"target_id": str(i), "mean_rank": 8.5} for i in range(18)], "mean_rank")
        self.assertEqual(len(boundary_top(rows, 15, "mean_rank")), 18)

    def test_empty_duplicates_and_nonfinite_rejected(self):
        self.assertEqual(select([])["bc_cc_top15"], [])
        for rows in [
            metrics() + [metrics()[0]],
            [dict(metrics()[0], bc=float("nan"))],
            [dict(metrics()[0], degree=0)],
        ]:
            with self.assertRaises(ContractError):
                select(rows)

    def test_new_presenter_and_old_presenter_do_not_mix(self):
        r = result()
        p = present_a04(r, {})
        self.assertNotIn("ppi_top", p.special)
        self.assertEqual(p.special["ppi_dual"]["degree_rows"], r["tables"]["degree_top10"])
        old = present_a04({"summary": {}, "tables": {"round1": []}}, {})
        self.assertIn("ppi_top", old.special)
        self.assertNotIn("ppi_dual", old.special)

    def test_network_metrics_calculated_once_per_evaluation(self):
        import ppi_flow

        target = [{"target_id": "HGNC:1", "symbol": "D1"}, {"target_id": "HGNC:2", "symbol": "D2"}]
        source = source_bundle(target)
        with patch("ppi_flow.calculate", wraps=ppi_flow.calculate) as calculation:
            summary, tables = evaluate(target, source, "workflow_test")
            calculation.assert_called_once()
        self.assertEqual(summary["参与节点数"], 2)
        self.assertNotIn("round1", tables)
        self.assertEqual(summary["selection_version"], VERSION)

    def test_identity_scope_missing_does_not_fallback(self):
        with self.assertRaisesRegex(ContractError, "明确授权"):
            evaluate([], {"schema_version": "A04.source.2"}, "workflow_test", b"fake", None)

    def test_unapproved_archive_tampering_and_docking_guard(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            w = Workflow(root, {"A04": validator(root)})
            sid = w.create(
                {
                    "formula": "合成方",
                    "herbs": "合成药",
                    "disease": "合成病",
                    "disease_scope": "仅测试",
                    "operator": "test",
                    "species": 9606,
                },
                kind="contract_test",
            )
            m = w.load(sid)
            w.review(sid, m["current"]["A00"], "approved", "test", "合成检查")
            target = [
                {"target_id": "HGNC:1", "symbol": "D1"},
                {"target_id": "HGNC:2", "symbol": "D2"},
            ]
            for mid in ("A01", "A02", "A03"):
                run = w.begin(sid, mid, {}, {}, "合成输入")
                w.finish(
                    sid,
                    run["run_id"],
                    {"analysis_purpose": "workflow_test"},
                    {"intersection_targets": target} if mid == "A03" else {},
                )
                w.review(sid, run["run_id"], "approved", "test", "合成检查")
            m = w.load(sid)
            a03 = m["current"]["A03"]
            with patch("ppi_flow.request", side_effect=AssertionError("禁止联网")):
                r = run_ppi(w, sid, a03, "", "仅合成来源包", source_bundle(target))
            self.assertFalse(w.approved(w.load(sid), r["run_id"]))
            record = w.run(w.load(sid), r["run_id"])
            bad = copy.deepcopy(r["tables"])
            bad["degree_round2"] = [{"target_id": "fake"}]
            with self.assertRaisesRegex(ContractError, "复算不一致"):
                validator(root)(record, r["summary"], bad, [], r["outcome"])
            with self.assertRaisesRegex(ContractError, "对接候选来源"):
                docking_validator(root, lambda *args: None)(
                    {"study_id": sid, "parent_runs": {"A04": r["run_id"]}}
                )
            with patch("science_modules.a04.figures.NETWORK_DESIGN_APPROVED", False):
                with self.assertRaisesRegex(ContractError, "版式"):
                    run_reports(w, sid, "", "不能提前发布")
            before = (w.location(sid) / "runs/A04" / r["run_id"] / "result.json").read_bytes()
            newer = run_ppi(w, sid, a03, r["run_id"], "第二个合成版本", source_bundle(target))
            self.assertNotEqual(newer["run_id"], r["run_id"])
            self.assertEqual(
                (w.location(sid) / "runs/A04" / r["run_id"] / "result.json").read_bytes(), before
            )
            self.assertFalse(w.approved(w.load(sid), newer["run_id"]))
            with patch("ppi_flow.request", side_effect=AssertionError("过期页禁止联网")):
                with self.assertRaises(ContractError):
                    run_ppi(w, sid, a03, "", "过期版本")

    def test_new_professional_section_replaces_old_ppi_only(self):
        from science_modules.a07.dual_reports import build_detailed

        a04 = result()

        def prior(payload, destination, root, revision):
            d = Document()
            d.add_paragraph("4 交集、成分与PPI网络")
            d.add_paragraph("A03已经确认的表")
            d.add_paragraph("药味—成分—交集靶点完整网络旧说明")
            d.add_paragraph("旧PPI图")
            d.add_table(rows=1, cols=1).cell(0, 0).text = "旧表"
            d.add_paragraph("第二轮旧参考名单")
            d.add_paragraph("5 GO与KEGG富集结果")
            d.save(destination)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "professional.docx"
            with patch(
                "science_modules.a07.dual_reports.previous.build_detailed", side_effect=prior
            ), patch("science_modules.a04.figures.NETWORK_DESIGN_APPROVED", False):
                build_detailed({"a04_dual": a04}, destination, Path(directory), "test")
            doc = Document(destination)
            texts = [p.text for p in doc.paragraphs]
            self.assertIn("A03已经确认的表", texts)
            self.assertNotIn("旧PPI图", texts)
            self.assertLess(
                texts.index("A04 01 Degree分支第二轮前十"),
                texts.index("A04 02 BC与CC联合筛选第二轮前十五"),
            )
            self.assertLess(
                texts.index("A04 02 BC与CC联合筛选第二轮前十五"), texts.index("5 GO与KEGG富集结果")
            )
            validate_word_tables(
                doc,
                a04,
                {
                    "a04_degree_top10": degree_rows(a04["tables"]),
                    "a04_bc_cc_top15": bc_cc_rows(a04["tables"]),
                },
            )

    def test_worker_keeps_a05_independent_and_blocks_docking(self):
        import ast, types, sys
        from types import SimpleNamespace
        from unittest.mock import Mock
        from modulea.tasks.worker import run_continue

        # 执行冻结编排函数本身，科学调用全部替换为测试桩，禁止联网或R运行。
        path = Path(__file__).resolve().parents[1] / "src/auto_continue.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = {"_approved", "_needs_run", "_modern_profile", "continue_after_review", "message"}
        module = types.ModuleType("auto_continue")
        ns = module.__dict__
        exec(
            compile(
                ast.Module(
                    body=[
                        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                    ],
                    type_ignores=[],
                ),
                str(path),
                "exec",
            ),
            ns,
        )
        old_ppi = Mock(side_effect=AssertionError("不得使用旧PPI入口"))
        ns["run_ppi"] = old_ppi
        ns["run_enrichment"] = Mock(return_value={"module_id": "A05"})
        w = Mock()
        w.load.return_value = {"current": {"A00": "a00", "A01": "a01", "A02": "a02", "A03": "a03"}}
        w.active.return_value = True
        w.approved.return_value = True
        with (
            patch.dict(sys.modules, {"auto_continue": module}),
            patch("modulea.tasks.worker.full_workflow", return_value=w),
            patch("ppi_dispatch.run_ppi", side_effect=ContractError("合成STRING失败")) as new_ppi,
        ):
            text = run_continue(
                SimpleNamespace(data_root=Path("unused")),
                {"task_id": "test", "study_id": "test"},
                Mock(),
            )
        new_ppi.assert_called_once()
        ns["run_enrichment"].assert_called_once()
        old_ppi.assert_not_called()
        self.assertIs(ns["run_ppi"], old_ppi)
        self.assertIn("合成STRING失败", text)
        # 已有双分支A04但A05缺失时，仍允许独立A05重试并在A06前停止。
        w.load.return_value = {"current": {"A00": "a00", "A03": "a03", "A04": "a04"}}
        w.result.return_value = {"summary": {"docking_candidate_source_pending": True}}
        fake_enrichment = types.ModuleType("enrichment_flow")
        fake_enrichment.run_enrichment = Mock()
        with (
            patch.dict(sys.modules, {"auto_continue": module, "enrichment_flow": fake_enrichment}),
            patch("modulea.tasks.worker.full_workflow", return_value=w),
        ):
            text = run_continue(
                SimpleNamespace(data_root=Path("unused")),
                {"task_id": "test", "study_id": "test"},
                Mock(),
            )
        fake_enrichment.run_enrichment.assert_called_once()
        self.assertIn("未启动A06", text)
        w.load.return_value["current"]["A05"] = "a05"
        fake_enrichment.run_enrichment.reset_mock()
        with (
            patch.dict(sys.modules, {"auto_continue": module, "enrichment_flow": fake_enrichment}),
            patch("modulea.tasks.worker.full_workflow", return_value=w),
        ):
            text = run_continue(
                SimpleNamespace(data_root=Path("unused")),
                {"task_id": "test", "study_id": "test"},
                Mock(),
            )
        fake_enrichment.run_enrichment.assert_not_called()
        self.assertIn("未启动A06", text)

    def test_professional_word_table_values_and_tamper(self):
        a04 = result()
        doc = Document()
        doc.add_paragraph("4 交集、成分与PPI网络")
        add_dual_section(doc, a04)
        doc.add_paragraph("5 GO与KEGG富集结果")
        data = {
            "a04_degree_top10": degree_rows(a04["tables"]),
            "a04_bc_cc_top15": bc_cc_rows(a04["tables"]),
        }
        validate_word_tables(doc, a04, data)
        self.assertEqual(
            [c.text for c in doc.tables[0].rows[0].cells],
            ["基因", "HGNC", "Degree", "Betweenness", "Closeness"],
        )
        self.assertEqual(doc.tables[0].rows[1].cells[2].text, "40")
        doc.tables[0].rows[1].cells[2].text = "999"
        with self.assertRaises(ContractError):
            validate_word_tables(doc, a04, data)


# 官方请求结构的虚构包，仅用于验证归档与网络身份契约。
def source_bundle(targets):
    import ppi_flow

    mapped = [
        {
            "queryIndex": i,
            "ncbiTaxonId": 9606,
            "preferredName": r["symbol"],
            "stringId": f"9606.D{i}",
        }
        for i, r in enumerate(targets)
    ]
    network = (
        [{"stringId_A": "9606.D0", "stringId_B": "9606.D1", "ncbiTaxonId": 9606, "score": 0.95}]
        if len(targets) > 1
        else []
    )
    ids = sorted(r["stringId"] for r in mapped)
    return {
        "schema_version": "A04.source.1",
        "string_version": "12.0",
        "mapping": {
            "url": ppi_flow.BASE + "get_string_ids",
            "params": {
                "identifiers": "\r".join(r["symbol"] for r in targets),
                "species": 9606,
                "echo_query": 1,
                "caller_identity": "ModuleA",
            },
            "retrieved_at": "2026-10-10",
            "response_text": json.dumps(mapped),
        },
        "network": {
            "url": ppi_flow.BASE + "network",
            "params": {
                "identifiers": "\r".join(ids),
                "species": 9606,
                "required_score": 900,
                "network_type": "functional",
                "add_nodes": 0,
                "caller_identity": "ModuleA",
            },
            "retrieved_at": "2026-10-10",
            "response_text": json.dumps(network),
        },
    }


if __name__ == "__main__":
    unittest.main()
