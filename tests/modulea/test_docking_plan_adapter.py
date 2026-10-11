"""A06代码适配隔离自测：人工字段、两梯队、版本留存、缓存键及关闭执行。"""
from pathlib import Path
from copy import deepcopy
import json
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch
from modulea.core.docking_workflow import DockingWorkflow
from science_modules.a06.plan_adapter import source_context,blank_plan,validate_plan,receptor_window
from science_modules.a06.engine_adapter import pair_cache_key,run_stage
from science_modules.a06.result_adapter import attach_groups,candidate_quality_table
from science_modules.a06.candidates import build
from science_modules.a04.selection import ranked,boundary_top
from tests.test_docking_contract import sample
from contracts import ContractError
from storage import verified_file,read_json

# 虚构方剂/成分/研究，全部测试文件位于指定临时核查目录。
def fixture(root):
    flow=DockingWorkflow(root)
    sid=flow.create({"formula":"虚构两梯队方","herbs":"虚构药味","disease":"虚构病","disease_scope":"契约测试","operator":"测试","species":9606,"analysis_purpose":"workflow_test"},kind="contract_test")
    flow.review(sid,flow.load(sid)["current"]["A00"],"approved","测试","虚构")
    rows=[{"target_id":"HGNC:"+str(i),"symbol":symbol,"degree":31-i,"bc":100-i,"cc":0.4} for i,symbol in enumerate(("EGFR","PIK3CA","STAT3"),1)]
    degree=ranked(rows,"degree",True)
    for mid in ("A01","A02","A03","A03_SELECT","A04"):
        tables={"selected":[{"compound_id":"C001","name":"虚构一"},{"compound_id":"C002","name":"虚构二"}]} if mid=="A03_SELECT" else ({"degree_round2":degree,"degree_top10":boundary_top(degree,10,"degree"),"bc_cc_top15":degree[:2]} if mid=="A04" else {})
        run=flow.begin(sid,mid,{},{},"虚构上游")
        flow.finish(sid,run["run_id"],{},tables,[],"success")
        flow.review(sid,run["run_id"],"approved","测试","不作为科研结论")
    flow.generate_candidates(sid,{**flow.candidate_binding(flow.load(sid)),"group_id":"group_"+uuid4().hex,"reason":"虚构两梯队"})
    return flow,sid

# 明确传入虚构结构选择，文件仅证明字段路径校验，不代表真实PyMOL程序。
def filled(context,root):
    data=blank_plan(context)
    for row in data["receptors"]:
        row.update(scope="strict",reason="虚构结构字段测试",pdb_id="1ABC",chains=["A"],uniprot="P12345",pocket="reference",altloc=None,reference_code="ABC",reference_chain="A",reference_sequence="1")
    for row in data["compounds"]:
        row.update(status="use",reason="虚构形态字段测试",cid="1",protonation_policy="pubchem_3d_as_provided_no_pH_prediction")
    tool=root/"fake_pymol.exe";tool.write_text("非运行文件，仅测试路径",encoding="utf-8")
    data.update(package_id="D900",pymol_executable=str(tool))
    return data

class PlanAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="a06_adapter_")
        self.root=Path(self.tmp.name)
        self.flow,self.sid=fixture(self.root)
        self.context=source_context(self.flow,self.sid)
        self.plan=filled(self.context,self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self):
        return {"expected_source":self.context["source_key"],"expected_plan_id":None,"plan_id":"plan_"+uuid4().hex,"confirmed":True,"reviewer":"隔离测试","note":"只验证字段不计算","plan":deepcopy(self.plan)}

    def test_blank_fields_and_group_order(self):
        blank=blank_plan(self.context)
        self.assertTrue(all(r["scope"] is None for r in blank["receptors"]))
        self.assertTrue(all("cid" not in r for r in blank["compounds"]))
        self.assertEqual([r["candidate_grade"] for r in self.context["receptors"]],["A","A","B"])
        self.assertEqual([r["ppi_order"] for r in self.context["receptors"]],[1,2,3])
        self.assertNotIn("round1",self.context)
        with self.assertRaises(ContractError):validate_plan(blank,self.context)

    def test_plan_retains_unavailable_without_fake_box(self):
        self.plan["receptors"][0]={"target":"EGFR","target_id":"HGNC:1","candidate_grade":"A","scope":"unavailable","reason":"虚构：暂不采用"}
        normalized=validate_plan(self.plan,self.context)
        self.assertEqual(len(normalized["receptors"]),3)
        self.assertNotIn("pdb_id",normalized["receptors"][0])
        self.assertNotIn("center",normalized["receptors"][0])

    def test_missing_duplicate_identity_grade_and_computed_fields_rejected(self):
        mutations=[
            lambda p:p["receptors"].pop(),
            lambda p:p["receptors"].__setitem__(1,deepcopy(p["receptors"][0])),
            lambda p:p["receptors"][0].update(target="OTHER"),
            lambda p:p["receptors"][0].update(candidate_grade="B"),
            lambda p:p["receptors"][0].update(rmsd=0.1),
            lambda p:p.update(execute=True),
        ]
        for change in mutations:
            data=deepcopy(self.plan);change(data)
            with self.assertRaises(ContractError):validate_plan(data,self.context)

    def test_predicted_pocket_not_strict_and_shape_not_guessed(self):
        data=deepcopy(self.plan);data["receptors"][0]["pocket"]="p2rank"
        with self.assertRaisesRegex(ContractError,"预测口袋"):validate_plan(data,self.context)
        data["receptors"][0]["scope"]="exploratory"
        self.assertEqual(validate_plan(data,self.context)["receptors"][0]["scope"],"exploratory")
        data["compounds"][0]["protonation_policy"]="guess_pH"
        with self.assertRaisesRegex(ContractError,"电离"):validate_plan(data,self.context)

    def test_save_only_archive_retry_history_and_no_run(self):
        before=self.flow.load(self.sid)
        request=self.payload()
        data,record=self.flow.save_docking_plan(self.sid,request)
        self.assertFalse(data["execution_allowed"])
        self.assertEqual(data["analysis_purpose"],"workflow_test")
        self.assertEqual(data["minimum_strict_receptors"],5)
        self.assertEqual(read_json(verified_file(self.flow.location(self.sid),record)),data)
        self.assertEqual(self.flow.save_docking_plan(self.sid,request),(data,record))
        request2=self.payload();request2["expected_plan_id"]=data["plan_id"]
        new,_=self.flow.save_docking_plan(self.sid,request2)
        self.assertNotEqual(new["plan_id"],data["plan_id"])
        after=self.flow.load(self.sid)
        for key in ("current","runs","reviews"):self.assertEqual(before[key],after[key])
        self.assertEqual(len(after["docking_plan_records"]),2)

    def test_unconfirmed_empty_reviewer_extra_authorization_or_stale_rejected(self):
        changes=[{"confirmed":False},{"reviewer":""},{"expected_source":"old"},{"execution_allowed":True}]
        for change in changes:
            with self.assertRaises(ContractError):self.flow.save_docking_plan(self.sid,{**self.payload(),**change})
        first=self.payload();self.flow.save_docking_plan(self.sid,first)
        with self.assertRaisesRegex(ContractError,"方案已更新"):self.flow.save_docking_plan(self.sid,self.payload())

    def test_reapproved_source_changes_key_and_deactivates_old_plan(self):
        request=self.payload();self.flow.save_docking_plan(self.sid,request)
        manifest=self.flow.load(self.sid);selected=manifest["current"]["A03_SELECT"]
        review=self.context["parent_review_ids"]["A03_SELECT"]
        self.flow.review(self.sid,selected,"approved","测试","重新确认",review)
        current=source_context(self.flow,self.sid)
        self.assertNotEqual(current["source_key"],self.context["source_key"])
        self.assertIsNone(self.flow.current_docking_plan(self.flow.load(self.sid),current)[0])
        with self.assertRaisesRegex(ContractError,"已改变"):self.flow.save_docking_plan(self.sid,request)

    def test_new_group_same_members_invalidates_plan_binding(self):
        request=self.payload();self.flow.save_docking_plan(self.sid,request)
        binding=self.flow.candidate_binding(self.flow.load(self.sid))
        self.flow.generate_candidates(self.sid,{**binding,"group_id":"group_"+uuid4().hex,"reason":"虚构新分组记录"})
        context=source_context(self.flow,self.sid)
        self.assertEqual(context["receptors"],self.context["receptors"])
        self.assertNotEqual(context["source_key"],self.context["source_key"])
        with self.assertRaises(ContractError):self.flow.save_docking_plan(self.sid,request)

    def test_unapproved_stale_selection_and_trash_do_not_create_plan(self):
        manifest=self.flow.load(self.sid)
        rid=manifest["current"]["A03_SELECT"]
        self.flow.review(self.sid,rid,"pending","测试","暂存",self.context["parent_review_ids"]["A03_SELECT"])
        with self.assertRaises(ContractError):source_context(self.flow,self.sid)
        manifest=self.flow.load(self.sid);manifest["trashed"]=True;self.flow.save(manifest)
        with self.assertRaises(ContractError):source_context(self.flow,self.sid)
        self.assertNotIn("docking_plan_records",self.flow.load(self.sid))

    def test_cross_study_cannot_reuse_plan_source(self):
        _,other=fixture(self.root)
        with self.assertRaisesRegex(ContractError,"已改变"):self.flow.save_docking_plan(other,self.payload())

    def test_all_execution_stages_block_before_tools_even_flag_true(self):
        with patch("docking_automation_compute.prepare") as prepare,patch("docking_automation_compute.execute") as execute,patch("docking_automation_compute.deliver") as deliver:
            for stage in ("prepare","execute","deliver"):
                with self.assertRaisesRegex(ContractError,"入口未开放"):run_stage(stage,workflow=self.flow,execution_allowed=True)
            prepare.assert_not_called();execute.assert_not_called();deliver.assert_not_called()

    def test_pair_key_reuses_original_and_excludes_candidate_label(self):
        from docking_automation_compute import pair_key
        prep={"software":{"runtime":"虚构工具版本"}}
        receptor={"receptor_record":{"sha256":"a"*64},"pdb_id":"1ABC","chains":["A"],"box":{"center":[1,2,3],"size":[20,20,20]},"candidate_grade":"A"}
        ligand={"ligand_record":{"sha256":"b"*64},"identity":{"cid":"1"}}
        before=pair_cache_key(prep,receptor,ligand)
        self.assertEqual(before,pair_key(prep,receptor,ligand))
        receptor["candidate_grade"]="B"
        self.assertEqual(pair_cache_key(prep,receptor,ligand),before)
        receptor["box"]["size"][0]=21
        self.assertNotEqual(pair_cache_key(prep,receptor,ligand),before)

    def bound_result(self):
        result=sample()
        result["analysis_purpose"]=self.context["analysis_purpose"]
        result["source_binding"]={"source_key":self.context["source_key"],"parent_runs":self.context["parent_runs"],"candidate_record":self.context["candidate_record"]}
        return result

    def test_result_labels_leave_scores_qc_primary_and_na_unchanged(self):
        result=self.bound_result();before=deepcopy(result)
        annotated=attach_groups(result,self.context)
        self.assertEqual(result,before)
        self.assertEqual(annotated["completed_pairs"],before["completed_pairs"])
        self.assertEqual(annotated["failed_pairs"],before["failed_pairs"])
        self.assertEqual([r["primary_result"] for r in annotated["receptors"]],[r["primary_result"] for r in before["receptors"]])
        table=candidate_quality_table(annotated)
        self.assertEqual([r["候选证据级别"] for r in table],["A","A","B"])
        self.assertEqual([r["结构质控"] for r in table],["通过"]*3)

    def test_group_a_failed_stays_failed_and_na(self):
        result=self.bound_result()
        result["receptors"][0].update(center=None,size=None,redocking_rmsd_A=None,redocking_status="failed_not_computable",qc_status="失败",primary_result=False)
        failed=[r for r in result["completed_pairs"] if r["target"]=="EGFR"]
        result["completed_pairs"]=[r for r in result["completed_pairs"] if r["target"]!="EGFR"]
        result["failed_pairs"] += [{"compound_id":r["compound_id"],"target":r["target"],"reason":"虚构质控失败"} for r in failed]
        annotated=attach_groups(result,self.context)
        self.assertEqual(candidate_quality_table(annotated)[0]["候选证据级别"],"A")
        self.assertEqual(candidate_quality_table(annotated)[0]["结构质控"],"失败")
        self.assertFalse(annotated["receptors"][0]["primary_result"])

    def test_legacy_wrong_binding_missing_candidate_or_hgnc_rejected(self):
        for mutation in ("no_binding","wrong_source","missing","identity","grade","purpose"):
            result=self.bound_result()
            if mutation=="purpose":result["analysis_purpose"]="formal_research"
            if mutation=="no_binding":result.pop("source_binding")
            if mutation=="wrong_source":result["source_binding"]["source_key"]="other"
            if mutation=="missing":result["receptors"].pop()
            if mutation=="identity":result["receptors"][0]["target_id"]="HGNC:999"
            if mutation=="grade":result["receptors"][0]["candidate_grade"]="B"
            with self.assertRaises(ContractError):attach_groups(result,self.context)
