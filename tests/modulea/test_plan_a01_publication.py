"""隔离验证方案→三库原件→HGNC→A01发布与复算；不用真实研究或联网数据。"""

from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

from contracts import ContractError
from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core.kernel import full_workflow
from modulea.core.trace_export import build_trace, trace_csv
from science_modules.analysis_protocol import VERSION as PLAN_VERSION
from science_modules.a01 import collection_flow, plan_flow, uploads
from storage import file_record, verified_file
import tests.test_plan_tcmsp as tcmsp_fixture
from tests.test_source_uploads import package


def source_package(database, *, complete=True, unknown=False):
    """复用旧三库的真实字段形状，扩充三条TCMSP样例并保留原始ZIP。"""
    with zipfile.ZipFile(io.BytesIO(package(database, "UNKNOWN" if unknown else "A"))) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    meta = json.loads(files["modulea_source.json"])
    if database == "TCMSP":
        header = "Chinesename\tMOLID\tmoleculename\tob\tdl\tUniProtAC\tGeneNames\tOrganism\n"
        rows = [("MOL1", "40", "0.3", "A", "P1"),
                ("MOL2", "20", "0.3", "B", "P2"),
                ("MOL3", "60", "0.1", "C", "P3")]
        files["references/tcmsp_snapshot.tsv"] = (header + "".join(
            f"测试药\t{cid}\tTest {cid}\t{ob}\t{dl}\t{acc}\t{gene}\tHomo sapiens (Human)\n"
            for cid, ob, dl, gene, acc in rows)).encode()
    if complete:
        meta["completeness"] = {"测试药": {"status": "complete", "records": 3 if database == "TCMSP" else 1,
                                          "basis": "隔离虚构完整清单"}}
    files["modulea_source.json"] = json.dumps(meta, ensure_ascii=False).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return output.getvalue()


class PlanA01PublicationTests(unittest.TestCase):
    """参数必须进入最终关系，旧版本、疾病侧和复核历史须保持。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="plan_a01_publish_")
        self.root = Path(self.temp.name)
        self.workflow = AnalysisPlanWorkflow(self.root, {"A01": plan_flow.validator(self.root, lambda *args: None)})
        self.sid, self.a00 = self.study()
        self.before_a02 = self.workflow.load(self.sid)["current"]["A02"]
        for db in uploads.DATABASES:
            self.stage(db)
        self.draft = self.save_plan()

    def tearDown(self):
        self.temp.cleanup()

    def study(self, modern=True):
        """每个研究自有三基因HGNC快照，不依赖生产references。"""
        intake = {"formula": "隔离三库方", "herbs": "测试药", "disease": "隔离病", "disease_scope": "仅本病",
                  "species": 9606, "operator": "隔离测试", "analysis_purpose": "workflow_test"}
        if modern:
            intake["analysis_plan_profile"] = PLAN_VERSION
        sid = self.workflow.create(intake, kind="contract_test")
        a00 = self.workflow.load(sid)["current"]["A00"]
        self.workflow.review(sid, a00, "approved", "隔离测试", "仅测试登记")
        raw = ("hgnc_id\tsymbol\tstatus\tprev_symbol\talias_symbol\tensembl_gene_id\tuniprot_ids\n"
               "HGNC:1\tA\tApproved\t\tGENE1\tENSG1\tP1\n"
               "HGNC:2\tB\tApproved\t\tGENE2\tENSG2\tP2\n"
               "HGNC:3\tC\tApproved\t\tGENE3\tENSG3\tP3\n").encode()
        path = self.workflow.location(sid) / "raw/hgnc.tsv"
        path.write_bytes(raw)
        run = self.workflow.begin(sid, "A02", {"mapping_file": file_record(self.workflow.location(sid), path, "mapping_source"),
                                               "identity_evidence_files": []}, {}, "隔离HGNC来源")
        self.workflow.finish(sid, run["run_id"], {"mapping_rule": "HGNC.resolve.3",
                             "mapping_snapshot": hashlib.sha256(raw).hexdigest(), "identity_evidence_snapshot": ""}, {})
        self.workflow.review(sid, run["run_id"], "approved", "隔离测试", "仅测试疾病侧")
        return sid, a00

    def stage(self, database, **options):
        """资料上传使用原校验器和不可变归档，不直接写manifest。"""
        manifest = self.workflow.load(self.sid)
        source = {"database": database, "format": "source_zip", "version": "fixture",
                  "data": source_package(database, **options)}
        return uploads.stage(self.workflow, self.sid, self.a00, manifest["current"].get("A01", ""),
                             (manifest.get("current_component_uploads") or {}).get("sha256", ""),
                             source, self.root / "parse")

    def save_plan(self, **parameters):
        """新参数只保存本研究草稿，不自动发布。"""
        info = self.workflow.analysis_plan_info(self.sid)
        return self.workflow.save_analysis_plan_draft(self.sid, {
            "request_id": "planreq_" + uuid4().hex, "expected_a00": self.a00,
            "expected_draft_id": info["expected_draft_id"],
            "specification": {"mode": "personalized", "parameters": parameters},
            "author": "隔离测试", "note": "不启动下游"})["draft"]

    def payload(self):
        manifest = self.workflow.load(self.sid)
        return {"expected_a00": self.a00, "expected_a01": manifest["current"].get("A01", ""),
                "expected_plan_id": self.draft["plan_id"],
                "expected_staging": manifest["current_component_uploads"]["sha256"], "reason": "隔离发布"}

    def publish(self, **changes):
        return self.workflow.publish_analysis_plan_a01(self.sid, dict(self.payload(), **changes))

    def test_default_matches_old_scientific_tables_and_never_approves(self):
        before = self.workflow.load(self.sid)
        inputs = {"study_id": self.sid, "bound_a00": self.a00,
                  "staging_file": before["current_component_uploads"], "herbs": ["测试药"],
                  "analysis_purpose": "workflow_test", "disease_identity": None,
                  "mapping": uploads.mapping_binding(self.workflow, before)}
        old_summary, old_tables, _ = collection_flow.facts(self.workflow.location(self.sid), inputs)
        result = self.publish()
        for name, table in old_tables.items():
            self.assertEqual(result["tables"][name], table, name)
        for key in ("标准化基因数", "去重成分—人类基因关系数", "候选成分分组数", "namespace", "mapping_snapshot"):
            self.assertEqual(result["summary"][key], old_summary[key], key)
        after = self.workflow.load(self.sid)
        self.assertEqual(after["reviews"], before["reviews"])
        self.assertEqual(after["current"]["A02"], self.before_a02)
        self.assertFalse(self.workflow.approved(after, result["run_id"]))
        self.assertNotIn("A03", after["current"])

    def test_lower_threshold_changes_final_hgnc_edges_preserves_a02_and_old_run(self):
        first = self.publish()
        first_bytes = (self.workflow.location(self.sid) / "runs/A01" / first["run_id"] / "result.json").read_bytes()
        self.draft = self.save_plan(**{"a01.ob_min": 15, "a01.dl_min": .08})
        result = self.publish()
        self.assertEqual(first["summary"]["标准化基因数"], 1)
        self.assertEqual(result["summary"]["标准化基因数"], 3)
        self.assertEqual({r["target_id"] for r in result["tables"]["normalized_compound_targets"]},
                         {"HGNC:1", "HGNC:2", "HGNC:3"})
        self.assertEqual(result["summary"]["effective_tcmsp_parameters"], {"ob_min": 15, "dl_min": .08})
        manifest = self.workflow.load(self.sid)
        self.assertEqual(manifest["current"]["A02"], self.before_a02)
        self.assertTrue(self.workflow.approved(manifest, self.before_a02))
        self.assertEqual((self.workflow.location(self.sid) / "runs/A01" / first["run_id"] / "result.json").read_bytes(), first_bytes)
        # 历史复算只读本批方案，不读取最新草稿。
        self.workflow.validators["A01"](self.workflow.run(manifest, first["run_id"]), first["summary"],
                                         first["tables"], first["anomalies"], "success")

    def test_no_ob_dl_is_applied_to_herb_or_batman(self):
        self.draft = self.save_plan(**{"a01.ob_min": 99, "a01.dl_min": 2})
        result = self.publish()
        self.assertEqual(result["tables"]["tcmsp_screened_components"], [])
        self.assertEqual({row["source"] for row in result["tables"]["component_sources"]}, {"HERB", "BATMAN"})
        self.assertEqual(result["summary"]["标准化基因数"], 1)
        self.assertTrue(all("99" in row["reason"] for row in result["tables"]["tcmsp_exclusions"]))

    def test_completeness_and_unknown_identity_remain_blocking(self):
        self.stage("HERB", complete=False, unknown=True)
        result = self.publish()
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertEqual(result["summary"]["完整性待核项数"], 1)
        self.assertEqual(result["tables"]["identity_issues"][0]["raw_symbol"], "UNKNOWN")
        with self.assertRaises(ContractError):
            self.workflow.review(self.sid, result["run_id"], "approved", "隔离测试", "不允许绕过")

    def test_stale_plan_and_staging_are_rejected_before_publication(self):
        stale = self.payload()
        self.save_plan(**{"a01.ob_min": 15})
        with self.assertRaises(ContractError):
            self.workflow.publish_analysis_plan_a01(self.sid, stale)
        self.assertNotIn("A01", self.workflow.load(self.sid)["current"])
        self.draft = self.workflow.analysis_plan_info(self.sid)["draft"]
        stale = self.payload()
        self.stage("HERB")
        with self.assertRaises(ContractError):
            self.workflow.publish_analysis_plan_a01(self.sid, stale)

    def test_tampered_sources_mapping_and_plan_are_rejected(self):
        manifest = self.workflow.load(self.sid)
        paths = [verified_file(self.workflow.location(self.sid), manifest["analysis_plan_records"][-1]),
                 self.workflow.location(self.sid) / "raw/hgnc.tsv",
                 verified_file(self.workflow.location(self.sid), uploads.current(self.workflow, manifest)["datasets"][0]["source_record"])]
        for path in paths:
            raw = path.read_bytes()
            try:
                path.write_bytes(raw + b"tamper")
                with self.assertRaises(ContractError):
                    self.publish()
            finally:
                path.write_bytes(raw)
        self.assertNotIn("A01", self.workflow.load(self.sid)["current"])

    def test_validator_rejects_changed_counts_tables_parameters_and_cross_study(self):
        result = self.publish()
        manifest = self.workflow.load(self.sid)
        run = self.workflow.run(manifest, result["run_id"])
        check = self.workflow.validators["A01"]
        summary = dict(result["summary"], **{"标准化基因数": 999})
        with self.assertRaises(ContractError):
            check(run, summary, result["tables"], result["anomalies"], "success")
        tables = deepcopy(result["tables"])
        tables["normalized_compound_targets"][0]["target_id"] = "HGNC:999"
        with self.assertRaises(ContractError):
            check(run, result["summary"], tables, result["anomalies"], "success")
        altered = deepcopy(run)
        altered["config"]["tcmsp_ob_min"] = 15
        with self.assertRaises(ContractError):
            check(altered, result["summary"], result["tables"], result["anomalies"], "success")
        other, _ = self.study()
        altered = deepcopy(run)
        altered["study_id"] = other
        with self.assertRaises(ContractError):
            check(altered, result["summary"], result["tables"], result["anomalies"], "success")

    def test_trace_and_csv_include_same_plan_sources_and_real_hgnc_edges(self):
        self.draft = self.save_plan(**{"a01.ob_min": 15, "a01.dl_min": .08})
        result = self.publish()
        trace = build_trace(self.workflow, self.sid, include_data=True)
        module = next(row for row in trace["modules"] if row["module_id"] == "A01")
        self.assertEqual(module["run_id"], result["run_id"])
        self.assertEqual(module["inputs"]["analysis_plan_id"], self.draft["plan_id"])
        self.assertEqual(len(module["result"]["tables"]["tcmsp_identity_mapping"]), 3)
        self.assertTrue(any(row["role"] == "analysis_plan_draft" for row in trace["files"]))
        exported = list(csv.DictReader(io.StringIO(trace_csv(trace).decode("utf-8-sig"))))
        rows = [row for row in exported if row["module_id"] == "A01" and row["table_name"] == "normalized_compound_targets"]
        self.assertEqual({json.loads(row["record_json"])["target_id"] for row in rows}, {"HGNC:1", "HGNC:2", "HGNC:3"})

    def test_old_study_and_trash_never_enable_new_protocol(self):
        old, old_a00 = self.study(modern=False)
        payload = dict(self.payload(), expected_a00=old_a00)
        with self.assertRaises(ContractError):
            self.workflow.publish_analysis_plan_a01(old, payload)
        self.workflow.set_trashed(self.sid, True, "隔离测试", "隔离回收站", None)
        with self.assertRaises(ContractError):
            self.publish()

    def test_full_production_validator_dispatch_is_registered(self):
        result = self.publish()
        real = full_workflow(self.root)
        manifest = real.load(self.sid)
        real.validators["A01"](real.run(manifest, result["run_id"]), result["summary"],
                                result["tables"], result["anomalies"], "success")

    def test_acquisition_stage_and_publication_use_same_lower_threshold(self):
        self.draft = self.save_plan(**{"a01.ob_min": 15, "a01.dl_min": .08})
        fake = tcmsp_fixture.PlanTcmspTests()
        fake.calls = []
        before = self.workflow.load(self.sid)
        results = plan_flow.acquire_sources(self.workflow, self.sid, dict(self.payload(), databases=["TCMSP"]),
                                            opener=fake.opener, sleeper=lambda _: None)
        self.assertEqual(results[0]["status"], "success", results)
        after = self.workflow.load(self.sid)
        self.assertEqual(before["current"], after["current"])
        self.assertEqual(before["reviews"], after["reviews"])
        result = self.publish()
        self.assertEqual(result["summary"]["标准化基因数"], 3)
        self.assertFalse(result["summary"]["handoff_blocked"])
        self.assertEqual(len([url for url in fake.calls if "target.php" in url]), 3)

    def test_acquisition_threshold_mismatch_blocks_incomplete_mapping(self):
        fake = tcmsp_fixture.PlanTcmspTests()
        fake.calls = []
        result = plan_flow.acquire_sources(self.workflow, self.sid, dict(self.payload(), databases=["TCMSP"]),
                                           opener=fake.opener, sleeper=lambda _: None)
        self.assertEqual(result[0]["status"], "success", result)
        self.draft = self.save_plan(**{"a01.ob_min": 15, "a01.dl_min": .08})
        with self.assertRaisesRegex(ContractError, "门槛|参数"):
            self.publish()
        self.assertNotIn("A01", self.workflow.load(self.sid)["current"])

    def test_partial_acquisition_failure_keeps_raw_and_never_publishes(self):
        before = self.workflow.load(self.sid)
        def offline(*args, **kwargs):
            raise OSError("隔离模拟网络失败")
        results = plan_flow.acquire_sources(self.workflow, self.sid, dict(self.payload(), databases=["TCMSP"]),
                                            opener=offline, sleeper=lambda _: None)
        self.assertEqual(results[0]["status"], "failed")
        after = self.workflow.load(self.sid)
        self.assertEqual(after["current"], before["current"])
        self.assertEqual(after["current_component_uploads"], before["current_component_uploads"])
        self.assertTrue(list((self.workflow.location(self.sid) / "raw/A01_plan_acquisition").glob("attempt_*.json")))

    def test_public_herb_acquisition_retains_original_capacity_guard_and_binding(self):
        def opener(request, timeout):
            p = json.loads(request.data)
            if p["func_name"] == "search_api":
                value = {"res_data": [["Herb id", "Herb pinyin name", "Herb Chinese name"],
                                      [{"title": "HERB1"}, "TEST", "测试药"]]}
            elif p["func_name"] == "browse_api":
                value = {"total_num": 1, "browse_data": [["Target id", "Gene name", "Gene alias"],
                                                         [{"title": "HBTAR1"}, "A", ""]]}
            elif p["label"] == "Herb":
                value = {"summary": [["Herb id", "Herb pinyin name", "Herb Chinese name"],
                                      ["HERB1", "TEST", "测试药"]],
                         "herb_ingredient": [["Ingredient id", "Ingredient name"], [{"title": "HBIN1"}, "Test compound"]]}
            else:
                value = {"summary": [["Ingredient id", "Ingredient name", "Molecule formula", "TCMSP id", "PubChem id"],
                                      ["HBIN1", "Test compound", "C1", {"title": "MOL1"}, {"title": "1"}]],
                         "ingredient_target": [["Target id", "Target name", "Database sources"],
                                               [{"title": "HBTAR1"}, "A", "existing"]]}
            return tcmsp_fixture.Response(json.dumps(value).encode(), request.full_url)

        with patch("science_modules.a01.acquisition.urllib.request.urlopen", side_effect=opener):
            results = self.workflow.acquire_analysis_plan_a01_sources(
                self.sid, dict(self.payload(), databases=["HERB"]))
        self.assertEqual(results[0]["status"], "success", results)
        slot = next(row for row in uploads.current(self.workflow, self.workflow.load(self.sid))["datasets"] if row["database"] == "HERB")
        self.assertEqual(slot["acquisition_adapter_version"], "A01.plan_acquisition.1")
        self.assertEqual(slot["analysis_plan_source"]["binding"]["study_id"], self.sid)
        self.assertFalse(self.publish()["summary"]["handoff_blocked"])

    def test_missing_library_is_rejected_without_creating_run(self):
        self.sid, self.a00 = self.study()
        self.stage("TCMSP")
        self.draft = self.save_plan()
        with self.assertRaisesRegex(ContractError, "三库"):
            self.publish()
        self.assertNotIn("A01", self.workflow.load(self.sid)["current"])

    def test_new_draft_during_acquisition_keeps_original_parameters(self):
        fake = tcmsp_fixture.PlanTcmspTests()
        fake.calls = []
        original = self.draft
        changed = []
        def opener(request, timeout):
            if not changed:
                changed.append(self.save_plan(**{"a01.ob_min": 15, "a01.dl_min": .08}))
            return fake.opener(request, timeout)
        results = plan_flow.acquire_sources(self.workflow, self.sid, dict(self.payload(), databases=["TCMSP"]),
                                            opener=opener, sleeper=lambda _: None)
        self.assertEqual(results[0]["status"], "success", results)
        slot = next(row for row in uploads.current(self.workflow, self.workflow.load(self.sid))["datasets"] if row["database"] == "TCMSP")
        self.assertEqual(slot["analysis_plan_source"]["screening_parameters"], {"ob_min": 30, "dl_min": .18})
        self.assertEqual(self.workflow.analysis_plan_info(self.sid)["draft"]["plan_id"], changed[0]["plan_id"])
        self.assertNotEqual(changed[0]["plan_id"], original["plan_id"])
        self.assertEqual(len([url for url in fake.calls if "target.php" in url]), 1)
        with self.assertRaises(ContractError):
            self.publish()


if __name__ == "__main__":
    unittest.main()
