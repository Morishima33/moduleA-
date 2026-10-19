"""隔离虚构研究验证一次授权、不可覆盖、完整矩阵、异常及版本保护。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from contracts import ContractError, fingerprint
from storage import file_record, new_id, read_json, verified_file, write_json
from modulea.core.automatic_docking import AutomaticDockingWorkflow, automatic_context
from modulea.devtools.demo_data import build
from science_modules.a06.automatic_rules import VERSION, POLICY, assess
from science_modules.a06.automatic_sources import conformer, Fetcher, compound_source
from science_modules.a06.automatic_engine import run, validator


class AutomaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = TemporaryDirectory()
        cls.sid = build(Path(cls.base.name))

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        shutil.copytree(self.base.name, self.data)
        self.workflow = AutomaticDockingWorkflow(self.data, {"A06": validator(self.data, lambda *a: None)})
        self.home = self.workflow.location(self.sid)
        manifest, bound = self.workflow.automatic_binding(self.sid)
        self.key = fingerprint(bound)
        self.compounds = [{"compound_id": "MOL_TEST1", "name": "虚构成分甲"}, {"compound_id": "MOL_TEST2", "name": "虚构成分乙"}]
        self.receptors = [{"target_id": "HGNC:1", "symbol": "TEST1"}, {"target_id": "HGNC:2", "symbol": "TEST2"}, {"target_id": "HGNC:3", "symbol": "TEST3"}]
        self.packet = {"id": new_id("connection"), "study_id": self.sid, "binding": self.key, "policy": POLICY,
            "context": {"compounds": self.compounds, "receptors": self.receptors},
            "compounds": [dict(c, state="unavailable", reason_zh="隔离虚构身份不明") for c in self.compounds],
            "receptors": [dict(r, state="failed" if i == 0 else "unavailable", candidates=[], reason_zh="隔离虚构来源异常") for i,r in enumerate(self.receptors)],
            "summary": {"connected_compounds": 1, "connected_receptors": 1, "exceptions": 5},
            "counts": {"compounds": 2, "receptors": 3, "pairs": 6}, "objects": [], "exceptions": [], "files": []}
        # 仅虚构连接包测试状态边界；不代表连接或准备通过。
        self.connection = self.workflow.save_automatic_connection(self.sid, self.key, self.packet, [])
        self.payload = {"expected_binding": self.key, "expected_connection_id": self.connection["id"],
            "expected_a06": manifest["current"].get("A06"), "request_id": new_id("auto"),
            "policy_version": VERSION, "reviewer": "隔离测试", "note": "虚构输入验证，不运行研究计算", "confirmed": True}

    def test_explicit_authorization_and_exact_fields(self):
        for changed in ({"confirmed": False}, {"confirmed": 1}, {"reviewer": ""}, {"policy_version": "old"}, {"tools_root": "unexpected"}):
            with self.subTest(changed=changed), self.assertRaises(ContractError):
                self.workflow.authorize_automatic(self.sid, dict(self.payload, **changed))
        self.assertNotIn("automatic_batches", self.workflow.load(self.sid))

    def test_once_idempotent_no_approval(self):
        before = deepcopy(self.workflow.load(self.sid)["reviews"])
        record = self.workflow.authorize_automatic(self.sid, self.payload)
        again = self.workflow.authorize_automatic(self.sid, self.payload)
        self.assertEqual(record, again)
        self.assertEqual(before, self.workflow.load(self.sid)["reviews"])
        saved = read_json(verified_file(self.home, record["authorization"]))
        self.assertIsNone(saved["approval"])
        with self.assertRaises(ContractError):
            self.workflow.authorize_automatic(self.sid, dict(self.payload, note="不同请求"))

    def test_current_result_conflict(self):
        with self.assertRaises(ContractError):
            self.workflow.begin_automatic(self.sid, dict(self.payload, expected_a06="outdated"))

    def test_connection_change_stales_authorization(self):
        batch, run_info, _ = self.workflow.begin_automatic(self.sid, self.payload)
        self.assertTrue(self.workflow.active(self.workflow.load(self.sid), run_info["run_id"]))
        self.workflow.save_automatic_connection(self.sid, self.key, dict(self.packet, id=new_id("connection")), [])
        self.assertFalse(self.workflow.active(self.workflow.load(self.sid), run_info["run_id"]))
        with self.assertRaises(ContractError):
            self.workflow.validate_automatic_request(self.sid, self.payload)

    def test_connection_collision_preserves_original(self):
        with self.assertRaises(ContractError):
            self.workflow.save_automatic_connection(self.sid, self.key, dict(self.packet, objects=[{"changed": True}]), [])
        self.assertEqual(read_json(verified_file(self.home, self.connection["packet"])), self.packet)

    def test_authorization_bytes_change_invalidates_run(self):
        _, run_info, _ = self.workflow.begin_automatic(self.sid, self.payload)
        m = self.workflow.load(self.sid)
        self.assertTrue(self.workflow.active(m, run_info["run_id"]))
        authorization = verified_file(self.home, run_info["inputs"]["automatic_authorization"])
        authorization.write_text("changed", encoding="utf-8")
        self.assertFalse(self.workflow.active(m, run_info["run_id"]))

    def test_retry_new_run_keeps_old_attempt(self):
        _, first, _ = self.workflow.begin_automatic(self.sid, self.payload)
        self.workflow.fail_automatic(self.sid, self.payload["request_id"], "隔离失败")
        _, second, _ = self.workflow.begin_automatic(self.sid, self.payload)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertTrue((self.home / "runs/A06" / first["run_id"] / "run.json").is_file())
        self.assertEqual(len(self.workflow.automatic_record(self.workflow.load(self.sid), self.payload["request_id"])["attempts"]), 2)

    def test_trash_foreign_and_upstream_change(self):
        for changed in ({"expected_connection_id": new_id("connection")}, {"expected_binding": "outdated"}):
            with self.assertRaises(ContractError):
                self.workflow.validate_automatic_request(self.sid, dict(self.payload, **changed))
        m = self.workflow.load(self.sid)
        m["trashed"] = True
        self.workflow.save(m)
        with self.assertRaises(ContractError):
            self.workflow.validate_automatic_request(self.sid, self.payload)

    def test_historical_is_read_only(self):
        self.assertIsNone(automatic_context(self.workflow, self.workflow.load(self.sid), historical=True))

    def test_counts_derive_candidates_not_missing_a04_table(self):
        with patch("science_modules.a06.candidates.build", return_value={"degree_top15": self.receptors}):
            m = self.workflow.load(self.sid)
            m["automatic_connections"] = []
            context = automatic_context(self.workflow, m)
        self.assertEqual(context["counts"]["receptors"], 3)
        self.assertEqual(context["counts"]["pairs"], context["counts"]["compounds"] * 3)

    def test_api_submit_stale_busy_and_download_hash(self):
        from modulea.api.server import App
        from modulea.config import Settings
        from modulea.api.errors import ApiError
        app = App(Settings(data_root=self.data, runtime_dir=Path(self.temp.name)/"runtime", science_tools_root=Path(self.temp.name)))
        request = type("Request", (), {"json": lambda obj: self.payload})()
        with patch.object(app.tasks, "active_for", return_value=[]), patch.object(app.tasks, "submit", return_value=({"task_id": "synthetic"}, True)) as submit:
            response, status = app.post_automatic_run(request, self.sid)
            self.assertEqual(status, 202)
            self.assertEqual(submit.call_args.args[1], "a06_auto_run")
            self.assertNotIn("automatic_batches", app.kernel.workflow().load(self.sid))
        with patch.object(app.tasks, "active_for", return_value=[{}]), self.assertRaises(ApiError) as blocked:
            app.post_automatic_run(request, self.sid)
        self.assertEqual(blocked.exception.status, 409)
        with self.assertRaises(ApiError):
            app.get_automatic_file(None, self.sid, new_id("connection"), "0")
        path = self.home / "test_evidence.txt"
        path.write_text("original", encoding="utf-8")
        m = self.workflow.load(self.sid)
        self.workflow.automatic_record(m, self.connection["id"])["files"] = [file_record(self.home, path, "evidence")]
        self.workflow.save(m)
        self.assertEqual(app.get_automatic_file(None, self.sid, self.connection["id"], "0")[1], path)
        path.write_text("changed", encoding="utf-8")
        with self.assertRaises(ContractError):
            app.get_automatic_file(None, self.sid, self.connection["id"], "0")

    def test_full_dynamic_matrix_exception_pipeline(self):
        tools = Path(self.temp.name) / "tools"
        binary = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"isolated fake binary, never executed")
        code = Path(__file__).resolve().parents[2]
        fake_version = type("Version", (), {"returncode": 0, "stdout": "AutoDock Vina v1.2.7"})()
        with patch("science_modules.a06.automatic_engine.subprocess.run", return_value=fake_version), patch("science_modules.a06.quality_engine.prepare_compounds", return_value=[]), patch("science_modules.a06.trial_compute.score_region") as score:
            result = run(self.workflow, self.sid, self.payload, tools, code, {"synthetic": True}, lambda t: None)
            score.assert_not_called()
        self.assertEqual(result["summary"]["计划组合数"], 6)
        self.assertEqual(result["summary"]["失败组合数"], 2)
        self.assertEqual(result["summary"]["NA组合数"], 4)
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertTrue(all(p["score"] is None for p in result["tables"]["pairs"]))
        m = self.workflow.load(self.sid)
        batch = self.workflow.automatic_record(m, self.payload["request_id"])
        self.assertTrue(any(f["path"].endswith("A06_automatic_heatmap.png") for f in batch["files"]))
        self.assertEqual(batch["state"], "completed")
        with self.assertRaises(ContractError):
            self.workflow.begin(self.sid, "A07", {}, {}, "禁止错误报告")
        packet_record = result["tables"]["automatic_packet"][0]
        facts = read_json(verified_file(self.home, packet_record))
        facts["pairs"].pop()
        bad_path = self.home / "forged.json"
        write_json(bad_path, facts)
        tables = deepcopy(result["tables"])
        tables["automatic_packet"] = [file_record(self.home, bad_path, "automatic_packet")]
        with self.assertRaises(ContractError):
            validator(self.data, lambda *a: None)(self.workflow.run(m, result["run_id"]), result["summary"], tables, [], "success")

    def test_successful_pair_files_parameters_and_tamper(self):
        """模拟科学执行，实际归档并复查CSV、盒、原子及命令，不运行研究分子。"""
        import gemmi
        from docking_p2rank import _prediction_rows, box_from_prediction
        from science_modules.a06.two_pass import pocket_key
        from science_modules.a06.quality_engine import environment_audit
        from science_modules.a06.trial_rules import VINA, fingerprint as execution_key
        from docking_top10_execute import _vina_arguments
        fixtures = self.home / "synthetic_inputs"
        fixtures.mkdir()
        pdb = "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \nEND\n"
        cif = fixtures / "source.cif"
        structure = gemmi.read_pdb_string(pdb)
        structure.setup_entities()
        structure.make_mmcif_document().write_file(str(cif))
        sdf = fixtures / "ligand.sdf";sdf.write_text("synthetic source, preparation mocked", encoding="utf-8")
        spec = {"source_type":"experimental", "pdb_id":"1ABC", "chains":["A"], "uniprot":"P12345", "pocket":"p2rank", "altloc":None}
        candidate = {"spec":spec, "identity":[], "cif":file_record(self.home,cif,"source")}
        packet = deepcopy(self.packet);packet["id"] = new_id("connection")
        packet["compounds"][0].update(state="connected", name_zh="虚构", cid=1, audit={}, sdf=file_record(self.home,sdf,"source"))
        packet["receptors"][1].update(state="connected", candidates=[candidate])
        packet["files"] = [candidate["cif"], packet["compounds"][0]["sdf"]]
        connection = self.workflow.save_automatic_connection(self.sid,self.key,packet,packet["files"])
        payload = dict(self.payload,expected_connection_id=connection["id"])
        tools = Path(self.temp.name)/"tools";binary = tools/"environments/vina_1.2.7/vina_1.2.7_win.exe"
        binary.parent.mkdir(parents=True);binary.write_bytes(b"synthetic, never executed")
        atom = f"ATOM  {1:5d}  C   LIG A   1    {0:8.3f}{0:8.3f}{0:8.3f}  0.00  0.00    {0:6.3f} C\n"
        atom = atom[:77] + "C\n"  # 保留PDBQT固定原子类型列。
        def prepare(root, source, plan, folder, progress):
            path = folder/"ligand.pdbqt";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(atom,encoding="ascii")
            return [{"compound_id":self.compounds[0]["compound_id"], "state":"ready", "reason_zh":"synthetic", "files":[file_record(root,path,"prepared_ligand")]}]
        def attempt(root, source, row, selected, round_no, folder, tools, progress):
            folder.mkdir(parents=True)
            input_pdb=folder/"prediction.pdb";input_pdb.write_text(pdb,encoding="ascii")
            pred_files=[]
            for i in range(2):
                path=folder/f"prediction_{i}.csv";path.write_text("rank,score,probability,center_x,center_y,center_z,residue_ids\n1,1,1,0,0,0,A_1\n",encoding="utf-8")
                pred_files.append(file_record(root,path,"p2rank_prediction"))
            raw=_prediction_rows(root/pred_files[0]["path"])[0]
            box=box_from_prediction(pdb,raw)
            pocket={"rank":1,"runs":[raw,raw],"mapped_indices":["A_1"]};pocket["pocket_key"]=pocket_key(selected,pocket)
            receptor=folder/"receptor.pdbqt";receptor.write_text(atom,encoding="ascii")
            env=environment_audit(cif.read_text("utf-8"),selected,box,{("A","1")})
            return {"structure_id":"1ABC", "identity":{"target_id":row["target_id"],"uniprot":"P12345","species":9606,"polymer_type":"Protein","sequence_matches":True,"chains":["A"],"source_review_id":connection["id"]},
                "receptor_ready":True,"pocket_complete":env["pocket_complete"],"environment_resolved":env["environment_resolved"],"environment_audit":env,
                "pocket":pocket,"box":box,"receptor":file_record(root,receptor,"receptor"),"predicted_pocket":{"files":pred_files,"input_pdb":file_record(root,input_pdb,"p2rank_input_pdb")},"files":pred_files}
        def score(root, folder, executable, compound, receptor, region):
            path=folder/"synthetic_score/poses.pdbqt";path.parent.mkdir(parents=True)
            path.write_text("MODEL 1\nREMARK VINA RESULT: -6.321 0.0 0.0\n"+atom+"ENDMDL\n",encoding="ascii")
            ligand=compound["files"][0]
            config={"compound":ligand,"receptor":receptor["receptor"],"region":region,"version":"synthetic","vina":VINA,"executable_sha256":__import__('hashlib').sha256(executable.read_bytes()).hexdigest()}
            return {"state":"completed","score":-6.321,"reason_zh":"","pose":file_record(root,path,"pose"),"config":config,"input_key":execution_key(config),"returncode":0,
                "command":_vina_arguments(executable,root/receptor["receptor"]["path"],root/ligand["path"],region,path)+["--cpu","2"]}
        version=type("Version",(),{"returncode":0,"stdout":"AutoDock Vina v1.2.7"})()
        with patch("science_modules.a06.automatic_engine.subprocess.run",return_value=version), patch("science_modules.a06.quality_engine.prepare_compounds",side_effect=prepare), patch("science_modules.a06.quality_engine.attempt",side_effect=attempt), patch("science_modules.a06.trial_compute.score_region",side_effect=score):
            result=run(self.workflow,self.sid,payload,tools,Path(__file__).resolve().parents[2],{"synthetic":True},lambda t:None)
        self.assertEqual(result["summary"]["成功组合数"],1)
        self.assertEqual(result["summary"]["探索受体数"],1)
        self.assertEqual(result["summary"]["主要受体数"],0)
        m=self.workflow.load(self.sid);run_info=self.workflow.run(m,result["run_id"])
        original=read_json(verified_file(self.home,result["tables"]["automatic_packet"][0]))
        self.assertEqual(next(r for r in original["pairs"] if r["state"]=="completed")["score"],-6.321)
        for index,change in enumerate(("score","command","candidate")):
            forged=deepcopy(original)
            scored=next(r for r in forged["pairs"] if r["state"]=="completed")
            if change=="score":scored["score"]=-9.9
            if change=="command":scored["execution"]["command"][-1]="9"
            if change=="candidate":forged["receptors"][1]["selected_candidate"]["spec"]["pdb_id"]="2ABC"
            path=self.home/f"forged_{index}.json";write_json(path,forged)
            tables=deepcopy(result["tables"]);tables["automatic_packet"]=[file_record(self.home,path,"automatic_packet")]
            with self.subTest(change=change),self.assertRaises(ContractError):
                validator(self.data,lambda *a:None)(run_info,result["summary"],tables,[],"success")


class SourceTests(unittest.TestCase):
    def test_conformer_none_unique_tie_and_disagreement(self):
        self.assertIsNone(conformer({"alternate_residues": [], "partial_occupancy_atoms": []})[0])
        row = {"auth_chain": "A", "auth_sequence": "1", "atom": "CA"}
        inspection = {"alternate_residues": [{"locations": ["A", "B"]}], "partial_occupancy_atoms": [dict(row, altloc="A", occupancy=.7), dict(row, altloc="B", occupancy=.3)]}
        self.assertEqual(conformer(inspection)[0], "A")
        inspection["partial_occupancy_atoms"][1]["occupancy"] = .7
        with self.assertRaises(ContractError):
            conformer(inspection)

    def test_pubchem_ambiguous_never_picks_first(self):
        fetch = type("Fetch", (), {"get": lambda self, *args: ({"IdentifierList": {"CID": [1, 2]}}, None)})()
        with self.assertRaises(ContractError):
            compound_source({"name": "ambiguous", "compound_id": "MOL_TEST"}, fetch)

    def test_failed_request_leaves_evidence(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fetch = Fetcher(root, root / "raw")
            with patch("urllib.request.urlopen", side_effect=TimeoutError("isolated timeout")), self.assertRaises(TimeoutError):
                fetch.get("https://pubchem.ncbi.nlm.nih.gov/test")
            self.assertEqual(len(fetch.records), 1)
            self.assertEqual(read_json(verified_file(root, fetch.records[0]))["state"], "failed")

    def test_predicted_evidence_cannot_pretend_identity(self):
        spec = {"source_type": "experimental", "pdb_id": "1ABC", "chains": ["A"], "uniprot": "P12345", "pocket": "p2rank"}
        with self.assertRaises(ContractError):
            assess(spec, {"structure_id": "2ABC"}, new_id("auto"), {"target_id": "HGNC:1"})

    def test_policy_authorization_exploration_stays_separate(self):
        from science_modules.a06.two_pass import pocket_key
        spec = {"source_type": "experimental", "pdb_id": "1ABC", "chains": ["A"], "uniprot": "P12345", "pocket": "p2rank", "altloc": None}
        pocket = {"rank": 1, "runs": [{"rank": 1, "residue_ids": "A_1"}]*2, "mapped_indices": ["A_1"]}
        pocket["pocket_key"] = pocket_key(spec, pocket)
        evidence = {"structure_id": "1ABC", "identity": {"target_id": "HGNC:1", "uniprot": "P12345", "chains": ["A"], "species": 9606, "polymer_type": "Protein", "sequence_matches": True}, "receptor_ready": True, "pocket_complete": True, "environment_resolved": True, "pocket": pocket}
        self.assertEqual(assess(spec, evidence, new_id("auto"), {"target_id": "HGNC:1"})["quality"], "探索")
        self.assertNotIn("confirmation", pocket)
        evidence["environment_resolved"] = False
        with self.assertRaises(ContractError):
            assess(spec, evidence, new_id("auto"), {"target_id": "HGNC:1"})


if __name__ == "__main__":
    unittest.main()
