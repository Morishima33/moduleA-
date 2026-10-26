"""虚构官方响应验证OB/DL同时进入获取与筛选，旧默认语义和来源隔离保持。"""

import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import components
from contracts import ContractError
from science_modules.analysis_protocol import compile_plan
from science_modules.a01 import acquisition as legacy
from science_modules.a01.plan_acquisition import acquire_for_plan
from science_modules.a01.plan_screening import analyze_rows
from tests.test_a01_acquisition import Response


class PlanTcmspTests(unittest.TestCase):
    """三个成分分别触及OB与DL边界，所有响应均为本地虚构字节。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="plan_tcmsp_")
        self.root = Path(self.temp.name)
        self.calls = []
        self.binding = {"study_id": "study_" + uuid4().hex, "a00_run": "run_" + uuid4().hex, "a01_run": ""}

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, **parameters):
        return compile_plan({"mode": "personalized", "parameters": parameters})

    def opener(self, request, timeout):
        url = request.full_url
        self.calls.append(url)
        query = parse_qs(urlsplit(url).query)
        if url == legacy.TCMSP + "tcmsp.php":
            raw = b'<input name="token" value="fixture">'
        elif "qr" in query:
            compounds = [{"MOL_ID": "MOL1", "molecule_name": "C1", "ob": "40", "dl": "0.3"},
                         {"MOL_ID": "MOL2", "molecule_name": "C2", "ob": "20", "dl": "0.3"},
                         {"MOL_ID": "MOL3", "molecule_name": "C3", "ob": "60", "dl": "0.1"}]
            relations = [{"MOL_ID": "MOL" + str(i), "target_ID": str(i), "target_name": "Protein " + str(i)} for i in range(1, 4)]
            raw = ("data:" + json.dumps(compounds) + ",data:" + json.dumps(relations)).encode()
        elif "tcmspsearch.php" in url:
            raw = ('data:' + json.dumps([{"herb_cn_name": "测试药", "herb_en_name": "Fixture herb"}], ensure_ascii=False)).encode()
        elif "target.php" in url:
            raw = ("<td>Protein " + query["qt"][0] + "</td>").encode()
        else:
            search = query["query"][0]
            number = next(str(i) for i in range(1, 4) if 'Protein ' + str(i) in search)
            raw = json.dumps({"results": [{"primaryAccession": "P" + number, "organism": {"taxonId": 9606},
                               "genes": [{"geneName": {"value": "GENE" + number}}],
                               "proteinDescription": {"recommendedName": {"fullName": {"value": "Protein " + number}}}}]}).encode()
        return Response(raw, url)

    def acquire(self, plan=None, binding=None, database="TCMSP"):
        return acquire_for_plan(database, ["测试药"], self.root / "sources", binding or self.binding,
                                plan or self.plan(), opener=self.opener, sleeper=lambda _: None)

    def raw(self, source):
        with ZipFile(io.BytesIO(source["data"])) as archive:
            return archive.read("references/tcmsp_snapshot.tsv")

    def rows(self, source):
        rows = list(csv.DictReader(io.StringIO(self.raw(source).decode("utf-8-sig")), delimiter="\t"))
        return [dict(r, source_line=i) for i, r in enumerate(rows, 2)]

    def test_default_raw_mapping_and_analysis_equal_legacy(self):
        configuration = dict(components.CONFIG)
        original = legacy._tcmsp
        old = legacy.acquire("TCMSP", ["测试药"], self.root / "legacy", opener=self.opener, sleeper=lambda _: None)
        new = self.acquire()
        self.assertEqual(self.raw(old), self.raw(new))
        rows = self.rows(new)
        expected = components.analyze(rows, ["测试药"])
        actual = analyze_rows(rows, ["测试药"], self.plan())
        self.assertEqual((actual["summary"], actual["tables"], actual["anomalies"]), expected)
        self.assertEqual(components.CONFIG, configuration)
        self.assertIs(legacy._tcmsp, original)

    def test_lower_ob_and_dl_fetch_new_targets_and_include_all_three(self):
        plan = self.plan(**{"a01.ob_min": 15, "a01.dl_min": .08})
        source = self.acquire(plan)
        rows = self.rows(source)
        self.assertEqual({r["GeneNames"] for r in rows}, {"GENE1", "GENE2", "GENE3"})
        self.assertEqual(len([u for u in self.calls if "target.php" in u]), 3)
        result = analyze_rows(rows, ["测试药"], plan)
        self.assertEqual(result["summary"]["筛选后不同成分数"], 3)
        self.assertEqual(result["summary"]["不同人类基因数"], 3)
        self.assertFalse(result["mapping_verified"])
        with ZipFile(io.BytesIO(source["data"])) as archive:
            meta = json.loads(archive.read("modulea_source.json"))
            self.assertEqual(meta["screening_parameters"], {"ob_min": 15, "dl_min": .08})

    def test_higher_threshold_skips_unneeded_target_requests_and_records_zero(self):
        plan = self.plan(**{"a01.ob_min": 50})
        source = self.acquire(plan)
        self.assertFalse(any("target.php" in u for u in self.calls))
        result = analyze_rows(self.rows(source), ["测试药"], plan)
        self.assertEqual(result["summary"]["筛选后不同成分数"], 0)
        reasons = {r["reason"] for r in result["tables"]["exclusions"]}
        self.assertIn("未同时达到OB≥50%且DL≥0.18", reasons)
        self.assertEqual(len(self.rows(source)), 3)

    def test_threshold_changes_have_separate_cache_but_display_changes_reuse(self):
        first = self.acquire()
        calls = len(self.calls)
        repeated = self.acquire(self.plan(**{"a05.go_plot_top": 25}))
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(first["data"], repeated["data"])
        changed = self.acquire(self.plan(**{"a01.ob_min": 15}))
        self.assertNotEqual(first["analysis_plan_source"]["binding_hash"], changed["analysis_plan_source"]["binding_hash"])
        self.assertIn("GENE2", self.raw(changed).decode())
        self.assertNotIn("GENE2", self.raw(first).decode())
        self.assertEqual(self.acquire()["data"], first["data"])

    def test_cross_study_does_not_reuse_and_corruption_is_blocked(self):
        first = self.acquire()
        count = len(self.calls)
        other = dict(self.binding, study_id="study_" + uuid4().hex)
        second = self.acquire(binding=other)
        self.assertGreater(len(self.calls), count)
        self.assertNotEqual(first["analysis_plan_source"]["binding_hash"], second["analysis_plan_source"]["binding_hash"])
        key = first["analysis_plan_source"]["binding_hash"]
        (self.root / "sources" / ("plan_source_" + key) / "source.zip").write_bytes(b"corrupted")
        with self.assertRaises(ContractError):
            self.acquire()

    def test_herb_and_batman_keep_original_collectors_without_adme(self):
        for database, function in [("HERB", "_herb"), ("BATMAN", "_batman")]:
            with self.subTest(database=database):
                with patch.object(legacy, function, return_value=({"fixture.txt": b"raw"}, {"测试药": 1}, {})) as collect:
                    source = self.acquire(self.plan(**{"a01.ob_min": 90, "a01.dl_min": .9}), database=database)
                    collect.assert_called_once()
                self.assertIsNone(source["analysis_plan_source"]["screening_parameters"])

    def test_invalid_binding_is_rejected_without_requests(self):
        with self.assertRaises(ContractError):
            self.acquire(binding=dict(self.binding, study_id="../other"))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
