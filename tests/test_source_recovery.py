# 来源恢复回归：使用合成CSV、接口响应及隔离研究，不把真实研究写入代码。
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contracts import ContractError
from disease import parse_source, run_disease, validate_disease
from disease_io import fetch_otp
from genecards_source import COPYRIGHT
from pharmgkb_source import fetch_pharmgkb
from a02_auto_prepare import _failure
from a02_retry_sources import retry_sources
from workflow import Workflow
from test_a02_source_profile import Response


def csv_source(text):
    """仅构造虚构数据的标准导入元信息。"""
    return {"database": "GeneCards", "format": "genecards_csv", "query": "Fixture Disease", "retrieved_at": "2026-10-17", "version": "fixture", "source_url": "fixture", "encoding": "utf-8-sig", "data": text.encode()}


class RecoveryTests(unittest.TestCase):
    def test_csv_preamble_footer_locations_and_precision(self):
        text = '"GeneCards - GeneCards - Search results for Fixture Disease"\n\n' + COPYRIGHT + '\n\nSymbol,Name,Type,Relevance Score,Knowledge\nA,"Name, quoted",RNA Gene,10.7000,99\n\n' + COPYRIGHT + '\n'
        item = csv_source(text)
        rows = parse_source(item, item["data"])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["source_row"], rows[0]["raw_score"], rows[0]["target_name"]), (6, "10.7000", "Name, quoted"))
        self.assertEqual((rows[0]["raw_id"], rows[0]["raw_uniprot"], rows[0]["gifts"]), ("", "", ""))
        self.assertEqual((rows[0]["knowledge"], rows[0]["gene_category"]), ("99", "RNA Gene"))

    def test_csv_rejects_broken_rows_and_unknown_trailers(self):
        header = 'Symbol,Name,Type,Relevance Score,Knowledge\n'
        for body in ['A,N,T,NaN,1\n', 'A,N,T,1\n', 'A,N,T,1,2,extra\n', 'A,"broken\n', COPYRIGHT + '\nA,N,T,1,1\n', 'unexpected footer\n', header]:
            item = csv_source(header + body)
            with self.subTest(body=body), self.assertRaises((ContractError, ValueError)):
                parse_source(item, item["data"])

    def test_pharmgkb_envelope_and_failure_evidence(self):
        for payload in ([{"connectedObject": {"objCls": "Gene", "id": "PA-G", "symbol": "A"}, "connectionTypes": ["DiseaseGene"]}], {"data": [], "status": "success"}, {"data": [], "status": "error"}, {"message": "bad"}):
            replies = iter([{"data": [{"id": "PA1", "name": "Fixture Disease"}]}, payload])
            run = lambda: fetch_pharmgkb(["Fixture Disease"], opener=lambda *args, **kw: Response(next(replies)), sleeper=lambda _: None)
            if isinstance(payload, dict) and payload.get("status") != "success":
                with self.assertRaises(ContractError) as error:
                    run()
                self.assertEqual(error.exception.source_trace["requests"][-1]["response"], payload)
            else:
                result = json.loads(run()["data"])
                self.assertEqual(len(result["records"]), 1 if isinstance(payload, list) else 0)
        payload = {"data": [{"connectedObject": {"objCls": "Gene", "id": "PA-G", "symbol": "A"}, "connectionTypes": []}], "status": "success"}
        replies = iter([{"data": [{"id": "PA1", "name": "Fixture Disease"}]}, payload])
        result = fetch_pharmgkb(["Fixture Disease"], opener=lambda *a, **k: Response(next(replies)), sleeper=lambda _: None)
        self.assertEqual(len(parse_source(result, result["data"])), 1)

    def test_production_otp_accumulates_across_page_widths(self):
        def row(i):
            return {"score": i / 10000, "target": {"id": "ENSG" + str(i), "approvedSymbol": "G" + str(i)}}
        def fetch(did, index, size):
            if size == 3000:
                rows = [row(i) for i in range(1, 3001)] if index == 0 else [row(1)]
            else:
                rows = [row(i) for i in range(2, 3001)] if index == 0 else [row(1), row(3001)]
            return {"data": {"meta": {"dataVersion": {"year": "26", "month": "09", "iteration": None},
                                     "apiVersion": {"x": "26", "y": "9", "z": "0"}},
                             "disease": {"id": did, "name": "Fixture Disease", "associatedTargets": {"count": 3001, "rows": rows}}}}
        with patch("disease_io.request_page", fetch):
            item = fetch_otp("TEST_1", fetch=fetch)
        snapshot = json.loads(item["data"])
        self.assertEqual(len(parse_source(item, item["data"])), 3001)
        self.assertEqual(len(snapshot["pages"]), 4)
        self.assertFalse(snapshot["enableIndirect"])
        self.assertEqual(snapshot["collection_version"], "OTP.direct.complete.3")
        self.assertEqual(item["version"], "26.09")
        snapshot["pages"][1]["data"]["meta"]["dataVersion"]["iteration"] = 2
        with self.assertRaisesRegex(ContractError, "版本"):
            parse_source(item, json.dumps(snapshot).encode())

    def test_otp_release_change_cannot_be_merged(self):
        def fetch(did, index):
            return {"data": {"meta": {"dataVersion": {"year": 26, "month": 9, "iteration": index + 1},
                                     "apiVersion": {"x": 26, "y": 9, "z": 0}},
                             "disease": {"id": did, "name": "Fixture Disease", "associatedTargets": {
                                 "count": 2, "rows": [{"score": 0.5, "target": {"id": str(index), "approvedSymbol": "G"}}]}}}}
        with self.assertRaisesRegex(ContractError, "版本") as error:
            fetch_otp("TEST_1", fetch=fetch)
        self.assertEqual(len(error.exception.source_trace["requests"]), 2)

    def test_failed_trace_is_archived_without_candidate_rows(self):
        with self.assertRaises(ContractError) as error:
            fetch_otp("TEST_1", fetch=lambda *args: {"errors": ["fixture error"]})
        failed = _failure("OTP", error.exception)
        self.assertEqual(parse_source(failed, failed["data"]), [])
        self.assertTrue(json.loads(failed["data"])["trace"]["requests"])

    def test_retry_preserves_other_source_and_rejects_old_version(self):
        with tempfile.TemporaryDirectory() as folder:
            workflow = Workflow(Path(folder), {"A02": validate_disease})
            sid = workflow.create({"formula": "fixture", "herbs": "fixture", "disease": "fixture", "disease_scope": "fixture", "operator": "test", "species": 9606})
            a00 = workflow.load(sid)["current"]["A00"]
            workflow.review(sid, a00, "approved", "test", "合成研究")
            gene = dict(csv_source('Symbol,Name,Type,Relevance Score,Knowledge\nA,N,T,1,2\n'))
            first = run_disease(workflow, sid, a00, "", [gene, _failure("OTP", ValueError("fixture"))], "合成失败来源")
            replacement = dict(gene, database="OTP", format="names", data=b"B\n")
            payload = {"expected_a00": a00, "expected_run": first["run_id"], "databases": ["OTP"], "reason": "合成重试"}
            with patch("a02_retry_sources._otp_source", return_value=(replacement, {})):
                second = retry_sources(workflow, sid, payload)
                with self.assertRaises(ContractError):
                    retry_sources(workflow, sid, payload)
            self.assertEqual(second["summary"]["失败来源库数"], 0)
            self.assertEqual(second["sources"][0], first["sources"][0])
            self.assertFalse(workflow.approved(workflow.load(sid), second["run_id"]))
            self.assertNotIn("A03", workflow.load(sid)["current"])

    def test_source_display_keeps_failure_distinct_from_zero(self):
        from modulea.presenters.sources import present_a02, source_display_rows
        rows = [{"database": "OTP", "availability": "查询失败，等待重试或上传", "records": 0}, {"database": "PharmGKB", "availability": "已查询但0条精确记录", "records": 0}]
        shown = source_display_rows(rows)
        self.assertEqual(shown[0]["records"], "未取得")
        self.assertEqual(shown[1]["records"], 0)
        self.assertEqual(rows[0]["records"], 0)
        parts = present_a02({"tables": {"source_summary": rows}}, {})
        self.assertNotIn("OTP 为 0 条", str(parts.focus))
