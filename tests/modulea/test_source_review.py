"""来源原件隔离回归：验证原件归档、版本、引用与审批边界，不运行准备或对接。"""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import base64
import hashlib
import tempfile
import unittest
from contracts import ContractError
from storage import verified_file
from tests.modulea.test_two_pass import fixture, filled
from tests.modulea.test_receptor_review import packet as receptor_packet
from science_modules.a06.plan_adapter import source_context
from science_modules.a06.matrix_display import VERSION
from modulea.core.two_pass_workflow import preparation_context


def source_fixture(root):
    f, sid = fixture(root)
    m = f.load(sid)
    rank = f.result(m, m["current"]["A03"])["tables"]["ranking"]
    context = source_context(f, sid)
    binding = f.docking_review_binding(m)
    group, _ = f.candidate_record(m, f.candidate_binding(m))
    receptors = [{**r, "candidate_grade": r["evidence_group"]} for r in group["group_a"] + group["group_b"]]
    compounds = [
        {**r, "name_zh": r["name"], "cid": "1", "identity_prechecked": True,
         "identity_state_zh": "虚构身份", "source_3d_state_zh": "虚构待补", "source_3d_evidence": [],
         "evidence_zh": "虚构隔离", "manual_reason_zh": "虚构测试",
         "official_evidence": {"properties": {"InChIKey": "virtual-key"}}}
        for r in rank
    ]
    cs = [r["compound_id"] for r in compounds]
    ts = [r["target_id"] for r in receptors]
    f.save_docking_review(sid, {
        "schema_version": "A06.compound_review.1", "study_id": sid, "binding": binding,
        "execution_allowed": False, "approval": None, "compounds": compounds,
        "excluded": [], "source_files": [], "receptors": receptors,
        "display": {"version": VERSION, "heatmap_compounds": cs, "table_compounds": cs,
                    "heatmap_targets": ts, "table_targets": ts},
    })
    meta = receptor_packet(f, sid)
    for row in meta["compounds"]:
        row.update(cid="1", name_zh=row["name"], source_3d_state_zh="虚构待补")
    for row in meta["receptors"]:
        row["candidates"][0]["pdb_id"] = "1ABC"
    f.save_receptor_review(sid, meta)
    files = []
    for key, name, url in [
        ("f001", "source_1.sdf", "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/1/SDF?record_type=3d"),
        ("f002", "pdb_1ABC.cif", "https://files.rcsb.org/download/1ABC.cif"),
    ]:
        raw = b"isolated fictional source; no real coordinates or scores"
        files.append({"key": key, "name": name, "url": url,
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "content_base64": base64.b64encode(raw).decode()})
    plan = filled(context)
    rows = [{**r, "pdb_id": "1ABC", "chains": ["A"], "spec": plan["receptors"][i]["first"],
             "identity_matched": True, "altloc_codes": [], "file_key": "f002",
             "reference_count_matches": True, "reference_covalent_count": 0,
             "audit": {"docking_ready": False, "receptor_prepared": False, "coordinate_modified": False}}
            for i, r in enumerate(context["receptors"])]
    packet = {"schema_version": "A06.source_review.1", "study_id": sid,
              "source_key": context["source_key"], "review_id": "source_review_" + uuid4().hex,
              "expected_review_id": None, "authorization_zh": "用户允许获取并核查资料，暂不计算",
              "note_zh": "虚构原件契约测试", "execution_allowed": False, "approval": None,
              "files": files, "choices": [], "receptors": rows,
              "compounds": [{**r, "cid": "1", "name_zh": r["name"], "identity_matched": True,
                             "file_key": "f001", "audit": {"docking_ready": False,
                             "inchi_key": "virtual-key", "coordinate_inchi_key": "virtual-key"}}
                            for r in context["compounds"]]}
    return f, sid, context, packet


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.f, self.sid, self.ctx, self.p = source_fixture(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_archive_retry_preserves_scientific_state(self):
        before = self.f.load(self.sid)
        saved = self.f.save_source_review(self.sid, self.p)
        self.assertEqual(self.f.save_source_review(self.sid, self.p), saved)
        after = self.f.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(len(after["source_review_records"]), 1)
        self.assertFalse(saved["execution_allowed"])
        self.assertIsNone(saved["approval"])
        self.assertEqual(len(preparation_context(self.f, after)["source_review"]["compounds"]), 2)

    def test_scope_url_hash_path_and_execution_rejected(self):
        for mode in ("study", "source", "execute", "approval", "url", "path", "hash", "cid"):
            p = deepcopy(self.p)
            if mode == "study": p["study_id"] = "other-study"
            if mode == "source": p["source_key"] = "old"
            if mode == "execute": p["execution_allowed"] = True
            if mode == "approval": p["approval"] = "approved"
            if mode == "url": p["files"][0]["url"] = "https://untrusted.invalid/source"
            if mode == "path": p["files"][0]["name"] = "../../other.sdf"
            if mode == "hash": p["files"][0]["sha256"] = "0" * 64
            if mode == "cid": p["compounds"][0]["cid"] = "2"
            with self.subTest(mode=mode), self.assertRaises(ContractError):
                self.f.save_source_review(self.sid, p)
        self.assertFalse(self.f.load(self.sid).get("source_review_records"))

    def test_source_updates_invalidate_old_draft_and_final(self):
        saved = self.f.save_source_review(self.sid, self.p)
        plan = filled(self.ctx)
        request = {"expected_source": self.ctx["source_key"], "expected_source_review_id": saved["review_id"],
                   "expected_plan_id": None, "expected_draft_id": None, "draft_id": "draft_" + uuid4().hex,
                   "plan": plan, "checked_target_ids": [], "reviewer": "", "note": "隔离草案"}
        draft = self.f.save_two_pass_draft(self.sid, request)
        final = {"expected_source": self.ctx["source_key"], "expected_source_review_id": saved["review_id"],
                 "expected_plan_id": None, "expected_draft_id": draft["draft_id"],
                 "plan_id": "plan_" + uuid4().hex, "confirmed_target_ids": [r["target_id"] for r in self.ctx["receptors"]],
                 "reviewer": "隔离", "note": "只确认虚构方案", "confirmed": True, "plan": plan}
        self.f.save_two_pass(self.sid, final)
        newer = {**deepcopy(self.p), "review_id": "source_review_" + uuid4().hex,
                 "expected_review_id": saved["review_id"], "note_zh": "另一个原件核查版本"}
        self.f.save_source_review(self.sid, newer)
        info = preparation_context(self.f, self.f.load(self.sid))
        self.assertIsNone(info["draft"])
        self.assertIsNone(info["latest"])
        for req, method in ((request, self.f.save_two_pass_draft), (final, self.f.save_two_pass)):
            with self.assertRaises(ContractError): method(self.sid, req)

    def test_raw_tamper_trash_and_wrong_altloc_block(self):
        saved = self.f.save_source_review(self.sid, self.p)
        plan = filled(self.ctx)
        plan["receptors"][0]["first"]["altloc"] = "A"
        info = self.f.check_two_pass(self.sid, {"expected_source": self.ctx["source_key"],
                    "expected_source_review_id": saved["review_id"], "plan": plan})
        self.assertFalse(info["items"][0]["valid"])
        wrong=filled(self.ctx);wrong["compounds"][0]["cid"]="2"
        self.assertFalse(self.f.check_two_pass(self.sid,{"expected_source":self.ctx["source_key"],
            "expected_source_review_id":saved["review_id"],"plan":wrong})["confirmation"]["ready"])
        raw = verified_file(self.f.location(self.sid), saved["files"][0]["file"])
        before = raw.read_bytes()
        raw.write_bytes(before + b"tampered")
        with self.assertRaises(ContractError): preparation_context(self.f, self.f.load(self.sid))
        raw.write_bytes(before)
        self.f.set_trashed(self.sid, True, "测试", "只读")
        with self.assertRaises(ContractError): self.f.save_source_review(self.sid, self.p)


class SourceHttpTests(unittest.TestCase):
    def test_indexed_download_and_stale_source_guard(self):
        from modulea.config import Settings
        from modulea.api.server import create_server
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import threading, json, sys
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            f, sid, context, payload = source_fixture(root)
            saved = f.save_source_review(sid, payload)
            server, app = create_server(Settings(data_root=root, runtime_dir=root / "runtime",
                                    science_python=sys.executable), 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:" + str(server.server_port)
            try:
                prefix = "/api/v1/studies/" + sid + "/source_reviews/" + saved["review_id"] + "/files/"
                with urlopen(base + prefix + "f001", timeout=30) as response:
                    raw = response.read()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), payload["files"][0]["sha256"])
                for path in (prefix + "f999", prefix.replace(sid, "study_" + uuid4().hex) + "f001"):
                    with self.assertRaises(HTTPError) as denial: urlopen(base + path, timeout=30)
                    self.assertEqual(denial.exception.code, 404)
                body = {"expected_source": context["source_key"],
                        "expected_source_review_id": "old", "plan": filled(context)}
                req = Request(base + "/api/v1/studies/" + sid + "/modules/A06_PREP/actions/check_two_pass",
                        data=json.dumps(body).encode(), headers={"X-ModuleA-Token": app.token,
                        "Origin": base, "Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as denial: urlopen(req, timeout=30)
                self.assertEqual(denial.exception.code, 409)
            finally:
                server.shutdown(); server.server_close(); thread.join()
