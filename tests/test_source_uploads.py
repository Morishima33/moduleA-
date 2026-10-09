"""上传、替换、跨研究绑定与三库整理回归；仅使用临时虚构资料。"""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import openpyxl
from contracts import ContractError
from disease import run_disease, validate_disease
from storage import file_record, verified_file, write_lock
from workflow import Workflow
from science_modules.a01.uploads import stage, current, process, validator, unpack

HERBS = ["测试药"]
KEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"

# 生成符合现有官方字段结构的合成三库包，不作为科研资料。
def package(database, gene="A", herbs=HERBS):
    meta = {"database": database, "version": "A01.source_package.1", "herbs": herbs}
    files = {}
    if database == "TCMSP":
        files["references/tcmsp_snapshot.tsv"] = "Chinesename\tMOLID\tmoleculename\tob\tdl\tUniProtAC\tGeneNames\tOrganism\n测试药\tMOL1\tTest compound\t40\t0.3\tP1\tA\tHomo sapiens (Human)\n".encode()
    elif database == "HERB":
        meta["herb_files"] = {"测试药": "herb.xlsx"}
        files["HERB_ingredient_info_v2.txt"] = ("Ingredient_id\tIngredient_name\tIngredient_alias_name\tInChIKey\tMolecular_formula\tTCMSP_id\tPubChem_id\nHBIN000001\tTest compound\t\t" + KEY + "\tC1\tMOL1\t1\n").encode()
        book = openpyxl.Workbook(); sheet = book.active
        sheet.append(["Ingredient id", "Ingredient name"]); sheet.append(["HBIN000001", "Test compound"])
        out = io.BytesIO(); book.save(out); book.close(); files["herb.xlsx"] = out.getvalue()
        files["HERB_target_browse_page001.json"] = json.dumps({"total_num": 1, "browse_data": [["header"], [{"title": "HBTAR000001"}, gene]]}).encode()
        files["HERB_existing_details/HBIN000001.json"] = json.dumps({"summary": [["id"], ["HBIN000001"]], "ingredient_target": [["Target id", "Target name", "Database sources"], [{"title": "HBTAR000001"}, gene, "fixture"]]}).encode()
    else:
        meta["herb_names"] = {"CE_SHI": "测试药"}
        files["BATMAN_herb_browse.txt"] = "Pinyin.Name\tChinese.Name\tLatin.Name\tIngredients\nCE_SHI\t测试药\tTest\tTest compound(1)\n".encode()
        files["BATMAN_known_browse_by_ingredients.txt.gz"] = gzip.compress(b"PubChem_CID\tIUPAC_name\tknown_target_proteins\n1\tTest compound\tA\n")
    files["modulea_source.json"] = json.dumps(meta, ensure_ascii=False).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return out.getvalue()

# 每项研究具有独立登记与可追溯的共同HGNC测试快照。
def fixture(root):
    flow = Workflow(root)
    sid = flow.create({"formula": "合成方", "herbs": "测试药", "disease": "测试病", "disease_scope": "虚构测试", "operator": "test", "species": 9606, "analysis_purpose": "workflow_test"}, kind="contract_test")
    manifest = flow.load(sid); a00 = manifest["current"]["A00"]
    flow.review(sid, a00, "approved", "test", "测试登记")
    raw = b"hgnc_id\tsymbol\tstatus\tprev_symbol\talias_symbol\tensembl_gene_id\tuniprot_ids\nHGNC:1\tA\tApproved\t\t\tENSG1\tP1\n"
    path = flow.location(sid) / "raw/hgnc.tsv"; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    run = flow.begin(sid, "A02", {"mapping_file": file_record(flow.location(sid), path, "mapping_source"), "identity_evidence_files": []}, {}, "合成身份依据")
    flow.finish(sid, run["run_id"], {"namespace": "HGNC", "mapping_rule": "HGNC.resolve.3", "mapping_snapshot": hashlib.sha256(raw).hexdigest(), "identity_evidence_snapshot": "", "handoff_blocked": False}, {"normalized_targets": [{"target_id": "HGNC:1", "symbol": "A"}]})
    flow.validators["A01"] = validator(root, lambda *args: None)
    return flow, sid, a00

class ScientificUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.flow, self.sid, self.a00 = fixture(self.root)
        self.runtime = self.root / "runtime"
    def tearDown(self): self.temp.cleanup()
    def upload(self, database, gene="A"):
        m = self.flow.load(self.sid)
        source = {"database": database, "format": "source_zip", "name": database + ".zip", "data": package(database, gene), "query": "测试药", "retrieved_at": "2026-10-09", "version": "fixture", "source_url": "test"}
        return stage(self.flow, self.sid, self.a00, m["current"].get("A01", ""), (m.get("current_component_uploads") or {}).get("sha256", ""), source, self.runtime)
    def make_all(self, gene="A"):
        for db in ("TCMSP", "HERB", "BATMAN"): self.upload(db, gene)
    def run_sources(self):
        m = self.flow.load(self.sid)
        return process(self.flow, self.sid, self.a00, m["current"].get("A01", ""), m["current_component_uploads"]["sha256"], "测试整理")

    def test_complete_import_deduplicates_and_never_approves(self):
        self.make_all(); before = self.flow.load(self.sid)
        self.assertNotIn("A01", before["current"])
        result = self.run_sources()
        self.assertEqual(result["summary"]["候选成分分组数"], 1)
        self.assertEqual(result["summary"]["标准化基因数"], 1)
        self.assertEqual(result["summary"]["去重成分—人类基因关系数"], 1)
        self.assertFalse(result["summary"]["handoff_blocked"])
        self.assertEqual(len(result["tables"]["component_sources"]), 3)
        after = self.flow.load(self.sid)
        self.assertFalse(self.flow.approved(after, result["run_id"]))
        self.assertNotIn("A03", after["current"])
        self.assertEqual(before["current"]["A02"], after["current"]["A02"])

    def test_new_identity_problem_is_retained_and_blocks(self):
        self.make_all("UNKNOWN"); result = self.run_sources()
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertEqual(result["tables"]["identity_issues"][0]["raw_symbol"], "UNKNOWN")
        with self.assertRaises(ContractError): self.flow.review(self.sid, result["run_id"], "approved", "test", "不得省略未知")

    def test_single_library_replacement_retains_history_and_current_result(self):
        self.make_all(); result = self.run_sources(); m = self.flow.load(self.sid)
        old = current(self.flow, m); original = {r["database"]: r for r in old["datasets"]}
        old_result_record = m["runs"][result["run_id"]]
        old_bytes = verified_file(self.flow.location(self.sid), original["HERB"]["source_record"]).read_bytes()
        self.upload("HERB", "UNKNOWN"); m2 = self.flow.load(self.sid)
        new = {r["database"]: r for r in current(self.flow, m2)["datasets"]}
        self.assertEqual(m2["current"]["A01"], result["run_id"])
        self.assertEqual(old_result_record, m2["runs"][result["run_id"]])
        self.assertEqual(original["TCMSP"], new["TCMSP"])
        self.assertEqual(original["BATMAN"], new["BATMAN"])
        self.assertNotEqual(original["HERB"]["source_record"], new["HERB"]["source_record"])
        self.assertEqual(len(m2["component_upload_versions"]), 4)
        self.assertEqual(verified_file(self.flow.location(self.sid), original["HERB"]["source_record"]).read_bytes(), old_bytes)

    def test_missing_library_cannot_process(self):
        self.upload("TCMSP")
        with self.assertRaises(ContractError): self.run_sources()
        self.assertNotIn("A01", self.flow.load(self.sid)["current"])

    def test_stale_version_and_cross_study_are_rejected(self):
        self.upload("TCMSP"); m = self.flow.load(self.sid)
        s = {"database": "HERB", "format": "source_zip", "data": package("HERB")}
        for a00, stamp in ((self.a00, ""), ("run_other_study", m["current_component_uploads"]["sha256"])):
            with self.assertRaises(ContractError): stage(self.flow, self.sid, a00, "", stamp, s, self.runtime)
        self.assertEqual(len(self.flow.load(self.sid)["component_upload_versions"]), 1)

    def test_tampered_source_cannot_be_reused(self):
        self.make_all(); m = self.flow.load(self.sid); first = current(self.flow, m)["datasets"][0]
        verified_file(self.flow.location(self.sid), first["source_record"]).write_bytes(b"tampered")
        with self.assertRaises(ContractError): self.run_sources()
        self.assertNotIn("A01", self.flow.load(self.sid)["current"])

    def test_zip_paths_links_and_duplicate_names_are_rejected(self):
        for mode in ("traversal", "link", "duplicate"):
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as z:
                if mode == "traversal": z.writestr("../outside.txt", "bad")
                elif mode == "link":
                    entry = zipfile.ZipInfo("link"); entry.external_attr = (0o120777 << 16); z.writestr(entry, "outside")
                else: z.writestr("x", "a"); z.writestr("X", "b")
            with tempfile.TemporaryDirectory(dir=self.root) as path, self.assertRaises(ContractError): unpack(out.getvalue(), Path(path))
        self.assertFalse((self.root / "outside.txt").exists())

    def test_wrong_herbs_leave_no_uploaded_manifest(self):
        source = {"database": "TCMSP", "format": "source_zip", "data": package("TCMSP", herbs=["其他药"])}
        with self.assertRaises(ContractError): stage(self.flow, self.sid, self.a00, "", "", source, self.runtime)
        self.assertNotIn("current_component_uploads", self.flow.load(self.sid))

    def test_disease_upload_updates_one_library_and_retains_bytes(self):
        # 新建独立疾病测试研究，不使用上面合成身份运行作为来源。
        flow = Workflow(self.root / "disease", {"A02": validate_disease})
        sid = flow.create({"formula": "合成方", "herbs": "测试药", "disease": "测试病", "disease_scope": "虚构测试", "operator": "test", "species": 9606}, kind="contract_test")
        a00 = flow.load(sid)["current"]["A00"]; flow.review(sid, a00, "approved", "test", "测试")
        def source(db, data): return {"database": db, "format": "tsv", "query": "测试病", "retrieved_at": "2026-10-09", "version": "fixture", "source_url": "fixture", "name": "fixture.tsv", "encoding": "utf-8-sig", "data": data}
        old = run_disease(flow, sid, a00, "", [source("GeneCards", b"raw_symbol\tdisease_term\nA\tTest\n"), source("OMIM", b"raw_symbol\tdisease_term\nB\tTest\n")], "首次上传")
        old_bytes = (flow.location(sid) / "runs/A02" / old["run_id"] / "result.json").read_bytes()
        new = run_disease(flow, sid, a00, old["run_id"], [source("GeneCards", b"raw_symbol\tdisease_term\nC\tTest\n")], "替换一库")
        self.assertEqual({r["raw_symbol"] for r in new["tables"]["candidate_records"]}, {"B", "C"})
        self.assertTrue(new["summary"]["handoff_blocked"])
        self.assertEqual((flow.location(sid) / "runs/A02" / old["run_id"] / "result.json").read_bytes(), old_bytes)
        self.assertFalse(flow.approved(flow.load(sid), new["run_id"]))

    def test_new_upload_rerun_never_falls_back_on_changed_a00(self):
        from science_modules.a01.uploads import run_components
        self.make_all(); result = self.run_sources()
        with self.assertRaises(ContractError):
            run_components(self.flow, self.sid, "run_changed_a00", result["run_id"], "测试")
        self.assertEqual(self.flow.load(self.sid)["current"]["A01"], result["run_id"])

    def test_omim_template_is_readable_and_not_fake_data(self):
        from modulea.core.source_uploads import template
        from disease import parse_source
        data, name, mime = template("A02", "OMIM", "omim_xlsx", [])
        book = openpyxl.load_workbook(io.BytesIO(data))
        sheet = book.active
        self.assertEqual([c.value for c in sheet[1]], ["Approved Symbol", "Phenotype", "Phenotype MIM number", "Entrez Gene ID"])
        sheet.append(["A", "测试病", "123456", "1"])
        stream = io.BytesIO(); book.save(stream); book.close()
        rows = parse_source({"database": "OMIM", "format": "omim_xlsx", "encoding": "utf-8-sig", "name": name, "query": "测试病"}, stream.getvalue())
        self.assertTrue(rows)
