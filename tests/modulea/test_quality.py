"""新版质控隔离回归：授权、版本、两遍顺序、真实归档与历史委托。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch, Mock
from uuid import uuid4
from tests.modulea.test_source_review import source_fixture
from tests.modulea.test_two_pass import filled
from modulea.core.quality_workflow import QualityWorkflow, STAGES
from science_modules.a06.quality_flow import prepare_quality, validator, reports
from science_modules.a06.quality_engine import run_engine, inside_box, environment_audit, target_folder
from storage import read_json, verified_file


class QualityTests(TestCase):
    """临时研究不触及原项目；工具调用在隔离测试明确替换。"""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        f, self.sid, ctx, packet = source_fixture(self.root)
        self.f = QualityWorkflow(self.root, f.validators)
        self.f.validators["A06_PREP"] = validator(self.root, Mock())
        self.source = self.f.save_source_review(self.sid, packet)
        self.plan = filled(ctx)
        payload = {"expected_source":ctx["source_key"], "expected_source_review_id":self.source["review_id"],
            "expected_plan_id":None, "plan_id":"plan_"+uuid4().hex,
            "confirmed_target_ids":[r["target_id"] for r in ctx["receptors"]],
            "reviewer":"隔离核验人", "note":"虚构方案核查", "confirmed":True, "plan":self.plan}
        saved = self.f.save_two_pass(self.sid, payload)
        self.ctx = ctx
        self.request = {"expected_source":ctx["source_key"],
            "expected_source_review_id":self.source["review_id"], "expected_plan_id":saved["plan_id"],
            "stages":STAGES, "authorization_zh":"隔离授权准备与质控，批量评分未授权"}

    def authorization(self):
        """生成隔离执行授权，测试不可代签科学结果。"""
        before = deepcopy(self.f.load(self.sid))
        data = self.f.authorize_quality(self.sid, self.request)
        after = self.f.load(self.sid)
        for key in ("current", "runs", "reviews"):
            self.assertEqual(before[key], after[key])
        self.assertFalse(data["batch_docking_allowed"])
        self.assertIsNone(data["approval"])
        return {k:self.request[k] for k in ("expected_source","expected_source_review_id","expected_plan_id")} | {
            "authorization_id":data["authorization_id"]}

    def test_scope_and_no_approval(self):
        self.authorization()
        for changes in ({"stages":STAGES+["batch_docking"]}, {"execute":True}):
            with self.assertRaises(ValueError):
                self.f.authorize_quality(self.sid, self.request | changes)

    def test_cross_version_before_tools(self):
        request = self.authorization()
        for key in ("expected_plan_id","expected_source_review_id","expected_source","authorization_id"):
            with self.assertRaises(ValueError):
                self.f.quality_authorization(self.sid, request | {key:"old"})

    def test_old_validator_delegation(self):
        old = Mock()
        validator(self.root, old)({"config":{"version":"historical"}},{},{},[],"success")
        old.assert_called_once()

    def test_two_pass_order_and_skip(self):
        plan = deepcopy(self.plan)
        plan["receptors"][0]["second"] = {**plan["receptors"][0]["first"],"pdb_id":"2ABC"}
        def evidence(home, source, row, spec, round_no, folder, tools, progress):
            return {"structure_id":spec["pdb_id"], "identity":{"target_id":row["target_id"],
                "uniprot":spec["uniprot"],"species":9606,"polymer_type":"Protein",
                "sequence_matches":True,"chains":spec["chains"]},
                "receptor_ready":True,"environment_resolved":True,"pocket_complete":True,
                "reference":{k:spec[k] for k in ("reference_code","reference_chain","reference_sequence")},
                "top1_rmsd":1.0}
        with patch("science_modules.a06.quality_engine.prepare_compounds",return_value=[]), patch(
                "science_modules.a06.quality_engine.attempt",side_effect=evidence) as call:
            result,_ = run_engine(self.root,self.ctx,self.source,plan,self.root/"q",self.root,lambda _:None)
            self.assertIsNone(result[plan["receptors"][0]["target_id"]]["second"])
            self.assertEqual(call.call_count,len(plan["receptors"]))
        def failed(*args):
            row,spec,round_no=args[2:5]
            facts=evidence(*args)
            facts["top1_rmsd"]=3.0 if round_no==1 else 1.0
            return facts
        with patch("science_modules.a06.quality_engine.prepare_compounds",return_value=[]), patch(
                "science_modules.a06.quality_engine.attempt",side_effect=failed) as call:
            result,_=run_engine(self.root,self.ctx,self.source,plan,self.root/"q",self.root,lambda _:None)
            self.assertEqual(result[plan["receptors"][0]["target_id"]]["first"]["top1_rmsd"],3.0)
            self.assertEqual(result[plan["receptors"][0]["target_id"]]["second"]["top1_rmsd"],1.0)
            self.assertEqual(call.call_count,len(plan["receptors"])+1)

    def test_publish_full_scope_no_scores_or_approval(self):
        request = self.authorization()
        old = deepcopy(self.f.load(self.sid))
        evidence = {r["target_id"]:{"first":{"error_zh":"隔离模拟工具无法准备"},
                     "second":None} for r in self.plan["receptors"]}
        compounds = [{"compound_id":r["compound_id"],"name_zh":"虚构","cid":r["cid"],
                      "state":"NA","reason_zh":"隔离模拟无三维","files":[]} for r in self.plan["compounds"]]
        binary=self.root/"environments/vina_1.2.7/vina_1.2.7_win.exe"
        binary.parent.mkdir(parents=True,exist_ok=True);binary.write_bytes(b"isolated fake tool")
        with patch("science_modules.a06.quality_flow.subprocess.run",
                   return_value=SimpleNamespace(returncode=0,stdout="AutoDock Vina v1.2.7")), \
             patch("science_modules.a06.quality_flow.run_engine",return_value=(evidence,compounds)):
            result = prepare_quality(self.f,self.sid,request,self.root,lambda _:None)
        self.assertTrue(result["summary"]["handoff_blocked"])
        self.assertEqual(result["summary"]["实际批量评分数"],0)
        self.assertEqual(len(result["tables"]["planned_pairs"]),
                         len(self.plan["compounds"])*len(self.plan["receptors"]))
        current=self.f.load(self.sid)
        self.assertEqual(old["reviews"],current["reviews"])
        self.assertEqual(current["current"].get("A06"),old["current"].get("A06"))
        self.assertFalse(self.f.approved(current,result["run_id"]))
        record=result["tables"]["quality_packet"][0]
        packet=read_json(verified_file(self.f.location(self.sid),record))
        self.assertFalse(packet["batch_docking_allowed"])
        self.assertEqual(old["current"]["A04"],current["current"]["A04"])

    def test_missing_and_metal_environment_do_not_pass(self):
        import gemmi
        pdb = ("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  "+chr(10)
               +"ATOM      2  C   ALA A   1       1.000   0.000   0.000  1.00 20.00           C  "+chr(10)
               +"HETATM    3 MG    MG B   2       0.000   0.000   1.000  1.00 20.00          MG  "+chr(10)+"END"+chr(10))
        st = gemmi.read_pdb_string(pdb)
        st.setup_entities()
        block = st.make_mmcif_document().sole_block()
        block.set_mmcif_category("_pdbx_unobs_or_zero_occ_atoms.", {
            "auth_asym_id":["A"],"auth_seq_id":["1"],"auth_comp_id":["ALA"],"auth_atom_id":["CB"]})
        facts = environment_audit(block.as_string(),{"chains":["A"],"altloc":None},
                                 {"center":[0,0,0],"size":[10,10,10]})
        self.assertFalse(facts["pocket_complete"])
        self.assertFalse(facts["environment_resolved"])
        self.assertEqual(facts["missing_pocket_atoms"][0]["atom"],"CB")
        self.assertEqual(facts["box_environment"][0]["residue"],"MG")

    def test_unconfirmed_prediction_is_reported_not_approved(self):
        plan = deepcopy(self.plan)
        row = plan["receptors"][0]
        spec = {k:v for k,v in row["first"].items() if not k.startswith("reference_")}
        spec["pocket"] = "p2rank"
        row["first"] = None;row["first_reason"] = "隔离第一遍无结构";row["second"] = spec
        evidence = {r["target_id"]:{"first":None,"second":None} for r in plan["receptors"]}
        evidence[row["target_id"]]["second"] = {
            "structure_id":spec["pdb_id"],"identity":{"target_id":row["target_id"],
            "uniprot":spec["uniprot"],"species":9606,"polymer_type":"Protein",
            "sequence_matches":True,"chains":spec["chains"]},"receptor_ready":True,
            "pocket_complete":True,"environment_resolved":True,
            "pocket":{"rank":1,"runs":[{"rank":"1"},{"rank":"1"}],
                      "mapped_indices":[],"confirmation":{},"pocket_key":"virtual"},
            "error_zh":"口袋待人工确认"}
        compounds=[{"compound_id":r["compound_id"],"name_zh":"虚构","cid":r["cid"],
                    "state":"ready","reason_zh":"","files":[]} for r in plan["compounds"]]
        prep, summary, tables = reports(self.ctx,plan,evidence,compounds)
        self.assertEqual(tables["receptor_diagnostics"][0]["质控状态"],"预测口袋待确认")
        self.assertTrue(summary["handoff_blocked"])
        self.assertEqual(summary["等待集中核查受体数"],1)
        self.assertEqual(prep["strict_count"],0)

    def test_presenter_uses_actual_round_reasons(self):
        from modulea.presenters.docking import present_a06_prep
        result={"summary":{"等待集中核查受体数":1},"tables":{
            "quality_packet":[{"path":"virtual"}],
            "receptor_diagnostics":[{"受体":"VIRTUAL","PPI顺序":1,"PDB":"1ABC","RMSD_A":3.0,
              "候选级别":"A","质控状态":"准备失败 / NA","第一遍":"Top-1重对接RMSD超过2Å",
              "第二遍":"未提供独立补救","结构限制":"通用环境说明"}]}}
        parts=present_a06_prep(result,{})
        self.assertIn("Top-1重对接RMSD超过2Å",str(parts.focus))
        self.assertIn("第一遍诊断",str(parts.table))
        self.assertIn("第二遍诊断",str(parts.table))

    def test_windows_target_directory_and_path_traversal(self):
        path = self.root / "receptors" / target_folder("HGNC:11998") / "first"
        path.mkdir(parents=True)
        self.assertTrue(path.is_dir())
        for bad in ("HGNC:../outside","../HGNC:1","HGNC:1:other"):
            with self.assertRaises(ValueError):
                target_folder(bad)

    def test_box_boundary(self):
        box={"center":[0,0,0],"size":[10,10,10]}
        self.assertTrue(inside_box([5,-5,0],box))
        self.assertFalse(inside_box([5.01,0,0],box))


if __name__ == "__main__":
    main()
