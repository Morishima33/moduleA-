"""自动报告协议适配：真实规模、原评分、人工关口和历史兼容。"""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import write_json, file_record
from science_modules.a07 import automatic_reports as reports


def packet():
    """2×3合成资料验证动态范围，不借用旧225格事实。"""
    return dict(schema_version="A06.automatic.2", study_id="synthetic", id="auto_test", run_id="a06", compounds=[{"compound_id": "c1", "name": "One"}, {"compound_id": "c2", "name": "Two"}], receptors=[{"target_id": "t1", "symbol": "T1"}, {"target_id": "t2", "symbol": "T2"}, {"target_id": "t3", "symbol": "T3"}], pairs=[{"compound_id": c, "target_id": t, "state": state, "score": score} for c, t, state, score in (("c1", "t1", "completed", -8.001), ("c1", "t2", "failed", None), ("c1", "t3", "NA", None), ("c2", "t1", "completed", -7.999), ("c2", "t2", "completed", -6.125), ("c2", "t3", "completed", -5))])


def matrix_doc(value):
    """分两张窄表覆盖同一矩阵，含原阈值而非四舍五入阈值。"""
    from docx import Document
    from science_modules.a06.trial_presentation import score_label
    doc = Document()
    pairs = {(p["compound_id"], p["target_id"]): p for p in value["pairs"]}
    for targets in (value["receptors"][:2], value["receptors"][2:]):
        table = doc.add_table(rows=1, cols=1 + len(targets))
        for cell, label in zip(table.rows[0].cells, ["成分"] + [r["symbol"] for r in targets]):
            cell.text = label
        for compound in value["compounds"]:
            row = table.add_row()
            row.cells[0].text = compound["name"]
            for cell, receptor in zip(row.cells[1:], targets):
                cell.text = score_label(pairs[(compound["compound_id"], receptor["target_id"])]["score"], mark=True)
    return doc


class AutomaticReports(unittest.TestCase):
    def test_report_cannot_publish_before_approval_or_from_trash_or_stale_inputs(self):
        with TemporaryDirectory() as folder:
            current = {key: key.lower() for key in ('A00', 'A01', 'A02', 'A03', 'A04', 'A05', 'A06')}
            for options, expected in (({'approved': False}, '独立复核'), ({'trashed': True}, '只读'), ({'active': False}, '更新')):
                manifest = {'current': current, 'trashed': options.get('trashed', False)}
                workflow = SimpleNamespace(root=Path(folder), load=lambda _: manifest,
                    approved=lambda *args: options.get('approved', True), active=lambda *args: options.get('active', True))
                with self.subTest(options=options), self.assertRaisesRegex(ContractError, expected):
                    reports.run_reports(workflow, 'synthetic', '', 'QA should stop before publication')

    def test_research_leads_use_confirmed_display_scope(self):
        payload = {"research_leads": [{"线索": "功能与通路线索", "支持事实": "hsa04933 excluded"}, {"线索": "结构线索", "支持事实": "unchanged"}], "a05_display": {"tables": {"bp_graph8": [{"ID": "GO:1", "Description": "retained process"}], "kegg_graph15": [{"ID": "hsa04668", "Description": "TNF signaling pathway"}]}}}
        reports.align_research_leads(payload)
        self.assertNotIn("hsa04933", str(payload["research_leads"]))
        self.assertIn("hsa04668", str(payload["research_leads"]))
        self.assertEqual(payload["research_leads"][1]["支持事实"], "unchanged")

    def test_matrix_retains_values_na_and_raw_threshold(self):
        doc = matrix_doc(packet())
        reports.validate_matrix(doc, packet())
        self.assertEqual(doc.tables[0].rows[1].cells[1].text, "-8.00**")
        self.assertEqual(doc.tables[0].rows[2].cells[1].text, "-8.00")
        self.assertEqual(doc.tables[0].rows[1].cells[2].text, "NA")

    def test_zero_cannot_replace_na(self):
        doc = matrix_doc(packet())
        doc.tables[0].rows[1].cells[2].text = "0.00"
        with self.assertRaises(ContractError): reports.validate_matrix(doc, packet())

    def test_missing_or_duplicate_matrix_columns_rejected(self):
        doc = matrix_doc(packet())
        doc.tables[1].rows[0].cells[1].text = "T2"
        with self.assertRaises(ContractError): reports.validate_matrix(doc, packet())

    def test_packet_cannot_cross_study_or_omit_pairs(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            for mutation in ("cross_study", "omit", "fill_na"):
                data = packet()
                if mutation == "cross_study": data["study_id"] = "other"
                elif mutation == "omit": data["pairs"].pop()
                else: data["pairs"][1]["score"] = 0
                path = home / (mutation + ".json");write_json(path, data)
                workflow = SimpleNamespace(location=lambda _: home, run=lambda *_: {"config": {"schema_version": "A06.automatic.2"}}, result=lambda *_: {"tables": {"automatic_packet": [file_record(home, path, "automatic_packet")]}})
                with self.assertRaises(ContractError): reports.packet_for(workflow, {"study_id": "synthetic"}, "a06")

    def test_display_latest_same_run_only(self):
        first, second = {"a06_run": "a06", "id": "first"}, {"a06_run": "a06", "id": "second"}
        manifest = {"automatic_displays": [first, {"a06_run": "other", "id": "other"}, second]}
        self.assertEqual(reports.display_for(manifest, "a06"), second)
        self.assertIsNone(reports.display_for(manifest, "missing"))

    def test_run_reports_cannot_skip_a06_review(self):
        with TemporaryDirectory() as folder:
            manifest = {"current": {m: m.lower() for m in ("A00", "A01", "A02", "A03", "A04", "A05", "A06")}}
            workflow = SimpleNamespace(root=Path(folder), load=lambda _: manifest, approved=lambda _, rid: rid != "a06")
            with patch.object(reports, "assemble_payload") as assemble:
                with self.assertRaises(ContractError): reports.run_reports(workflow, "synthetic", "", "test")
                assemble.assert_not_called()

    def test_old_version_validator_delegated(self):
        calls=[]
        reports.validator("unused", lambda *args: calls.append(args))({"config": {"schema_version": "A07.report.config.24"}}, {}, {}, [], "success")
        self.assertEqual(len(calls), 1)


class Continuation(unittest.TestCase):
    def run_continue(self, *, a06_approved=True, a05_approved=True, a07=False, maps=True):
        from modulea.tasks.worker import run_continue
        current = {"A06": "a06", "A05": "a05"}
        if a07: current["A07"] = "a07"
        workflow = SimpleNamespace(load=lambda _: {"current": current}, run=lambda *_: {"config": {"schema_version": "A06.automatic.2"}}, handoff_read_cache=nullcontext, approved=lambda _, rid: a06_approved if rid == "a06" else a05_approved, active=lambda *_: True, ranked_maps_for=lambda *_: {} if maps else None, result=lambda *_: {"tables": {"kegg_p_top10": [1], "kegg_count_top10": [2]}})
        manager = SimpleNamespace(update=lambda *args, **kwargs: None)
        with patch("modulea.tasks.worker.full_workflow", return_value=workflow), patch("report_dispatch.run_reports", return_value={"run_id": "new_a07"}) as generate:
            text=run_continue(SimpleNamespace(data_root="synthetic"), {"study_id": "synthetic", "task_id": "task"}, manager)
            return text, generate.call_count

    def test_pending_a06_stops(self):
        text, count=self.run_continue(a06_approved=False)
        self.assertIn("复核", text); self.assertEqual(count, 0)

    def test_pending_a05_or_missing_maps_stops(self):
        for options in ({"a05_approved": False}, {"maps": False}):
            text,count=self.run_continue(**options);self.assertEqual(count,0)

    def test_existing_a07_preserved(self):
        text,count=self.run_continue(a07=True);self.assertEqual(count,0);self.assertIn("保留",text)

    def test_approved_generates_without_recalculating(self):
        text,count=self.run_continue();self.assertEqual(count,1);self.assertIn("未重算Vina",text)


if __name__ == "__main__": unittest.main()
