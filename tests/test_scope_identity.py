# 来源隔离与前置范围核验回归；所有写入只发生在临时合成研究。
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from contracts import ContractError
from disease import parse_source, run_disease, validate_disease
from source_identity import embedded_query, validate_source_identity
from modulea.core.disease_scope import context, review_scope, validate_submission
from workflow import Workflow


def workbook(query="Fixture Disease", footer=True):
    """构造具有真实标题/表头/尾注结构的合成文件。"""
    book = Workbook(); sheet = book.active
    sheet.append(["Gene Map Search - '" + query + "'"]); sheet.append(["Downloaded:", "fixture"])
    sheet.append([]); sheet.append([])
    sheet.append(["Cytogenetic location", "Genomic coordinates", "Approved Symbol", "Entrez Gene ID", "Phenotype", "Phenotype MIM number"])
    sheet.append(["1p", "1:1", "A", "1", "Fixture Disease", "1"])
    sheet.append(["2p", "2:1", "B", "2", "Other Disease", "2"])
    if footer:
        sheet.append([]); sheet.append(["Phenotype Mapping Key"]); sheet.append(["3 - The molecular basis is known"])
        sheet.append(["Inheritance Abbreviations"]); sheet.append(["AD", "Autosomal dominant"])
    stream = io.BytesIO(); book.save(stream); book.close(); return stream.getvalue()


def source(query="Fixture Disease", title=None, fmt="omim_xlsx_v2"):
    return {"database": "OMIM", "format": fmt, "encoding": "utf-8-sig", "query": query, "name": "fixture.xlsx", "retrieved_at": "2026-10-17", "version": "fixture", "source_url": "fixture", "data": workbook(title or query)}


class ScopeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.flow = Workflow(Path(self.temp.name), {"A02": validate_disease})
        self.sid = self.flow.create({"formula": "fixture", "herbs": "fixture", "disease": "fixture", "disease_scope": "fixture", "operator": "test", "species": 9606})
        self.a00 = self.flow.load(self.sid)["current"]["A00"]
        self.flow.review(self.sid, self.a00, "approved", "test", "合成研究")
    def tearDown(self):
        self.temp.cleanup()

    def test_new_excel_ignores_legends_and_old_parser_is_unchanged(self):
        item = source(); rows = parse_source(item, item["data"])
        self.assertEqual([(r["raw_symbol"], r["source_row"]) for r in rows], [("A", "Sheet!6"), ("B", "Sheet!7")])
        self.assertEqual(len(parse_source(dict(item, format="omim_xlsx"), item["data"])), 6)
        self.assertEqual(embedded_query(item, item["data"]), "Fixture Disease")

    def test_mismatched_title_rejected_before_changing_current(self):
        first = run_disease(self.flow, self.sid, self.a00, "", [source()], "合成正确来源")
        manifest = (self.flow.location(self.sid) / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ContractError, "来源检索身份不匹配"):
            run_disease(self.flow, self.sid, self.a00, first["run_id"], [source(title="Wrong Disease")], "合成错文件")
        self.assertEqual((self.flow.location(self.sid) / "manifest.json").read_bytes(), manifest)

    def test_official_alias_is_allowed_but_other_disease_is_not(self):
        item = source(query="Fixture Disease", title="Official Alias")
        a00 = {"mesh_term": "Fixture Disease", "mesh_verification": {"preferred_term": "Fixture Disease", "entry_terms": ["Official Alias"]}}
        validate_source_identity(a00, item, item["data"])
        wrong = source(title="Other Disease")
        with self.assertRaises(ContractError):
            validate_source_identity(a00, wrong, wrong["data"])

    def test_complete_scope_batch_preserves_source_and_does_not_approve(self):
        first = run_disease(self.flow, self.sid, self.a00, "", [source()], "合成来源")
        info = context(self.flow, self.flow.load(self.sid), first, True)
        payload = {"expected_a00": self.a00, "expected_run": first["run_id"], "decisions": [{"scope_id": r["scope_id"], "scope": "outside"} for r in info["items"]], "reviewer": "test", "note": "合成范围决定", "confirmed": True}
        for change in [{"confirmed": False}, {"decisions": payload["decisions"][:1]}, {"decisions": payload["decisions"] * 2}, {"reviewer": ""}]:
            with self.subTest(change=change), self.assertRaises(ContractError):
                review_scope(self.flow, self.sid, dict(payload, **change))
        second = review_scope(self.flow, self.sid, payload)
        self.assertEqual(second["sources"][:-1], first["sources"][:-1])
        self.assertEqual(second["summary"]["待范围复核条目数"], 0)
        self.assertFalse(self.flow.approved(self.flow.load(self.sid), second["run_id"]))
        self.assertNotIn("A03", self.flow.load(self.sid)["current"])
        with self.assertRaises(ContractError):
            review_scope(self.flow, self.sid, payload)

    def test_historical_wrong_source_cannot_be_marked_direct(self):
        with patch("source_identity.validate_source_identity"):
            first = run_disease(self.flow, self.sid, self.a00, "", [source(title="Wrong Disease")], "合成历史错文件")
        info = context(self.flow, self.flow.load(self.sid), first, True)
        self.assertTrue(all(not r["direct_allowed"] for r in info["items"]))
        payload = {"decisions": [{"scope_id": r["scope_id"], "scope": "direct"} for r in info["items"]], "reviewer": "test", "note": "test", "confirmed": True}
        with self.assertRaises(ContractError):
            validate_submission(info, payload)
        batch = [dict(d, reviewer="test", note="合成旧入口核验") for d in payload["decisions"]]
        with self.assertRaises(ContractError):
            run_disease(self.flow, self.sid, self.a00, first["run_id"], [], "合成旧入口", scope_change=batch)

    def test_genecards_title_mismatch_is_rejected(self):
        data = b'"GeneCards - GeneCards - Search results for Other Disease"\n\nSymbol,Name,Type,Relevance Score,Knowledge\nA,N,T,1,2\n'
        item = {"format": "genecards_csv", "encoding": "utf-8-sig", "query": "Fixture Disease"}
        with self.assertRaises(ContractError):
            validate_source_identity({"mesh_term": "Fixture Disease"}, item, data)

    def test_web_omim_default_is_new_excel_parser(self):
        from modulea.core.source_uploads import context as upload_context
        result = run_disease(self.flow, self.sid, self.a00, "", [source()], "合成来源")
        info = upload_context(self.flow, self.flow.load(self.sid), "A02", result)
        omim = next(s for s in info["sources"] if s["database"] == "OMIM")
        self.assertEqual(omim["formats"][0]["value"], "omim_xlsx_v2")
        self.assertEqual(omim["formats"][0]["accept"], ".xlsx")

    def test_omim_data_after_legend_is_rejected(self):
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(workbook()))
        book.active.append(["3p", "3:1", "C", "3", "Late data", "3"])
        stream = io.BytesIO(); book.save(stream); book.close()
        item = source(); item["data"] = stream.getvalue()
        with self.assertRaises(ContractError):
            parse_source(item, item["data"])

    def test_other_study_cannot_use_scope_ids(self):
        first = run_disease(self.flow, self.sid, self.a00, "", [source()], "合成来源")
        info = context(self.flow, self.flow.load(self.sid), first, True)
        wrong = {"decisions": [{"scope_id": "scope_other_study", "scope": "direct"}], "reviewer": "test", "note": "test", "confirmed": True}
        with self.assertRaises(ContractError):
            validate_submission(info, wrong)
