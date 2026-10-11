"""A06两遍规则与真实HTTP保存链隔离自测；不调用结构下载、准备、重对接或Vina。"""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import unittest,tempfile,threading,json,time,sys,base64
from contracts import ContractError
from modulea.core.two_pass_workflow import TwoPassWorkflow,preparation_context,selection_context
from modulea.config import Settings
from modulea.api.server import create_server
from intersection_flow import build,validate_selection
from science_modules.a06.plan_adapter import source_context
from science_modules.a06.two_pass_plan import blank,validate,row_check
from science_modules.a06.two_pass import POLICY,RESULT,VINA,confidence,pocket_key,assess_receptor,preparation,validate_result
from science_modules.a06.engine_adapter import run_stage
from science_modules.a04.selection import ranked,boundary_top

# 当前规则合成资料，既有成分选择生产验证器真实参与。
def fixture(root,selection=True,count=3):
 f=TwoPassWorkflow(root,{"A03_SELECT":validate_selection})
 sid=f.create({"formula":"虚构两遍方","herbs":"虚构药","disease":"虚构病","disease_scope":"契约测试","operator":"测试","species":9606,"analysis_purpose":"workflow_test"},kind="contract_test")
 f.review(sid,f.load(sid)["current"]["A00"],"approved","测试","虚构")
 payload={"components":[{"compound_id":c,"name":"虚构"+c} for c in ("C1","C2")],"memberships":[{"compound_id":c,"herb":"虚构药"} for c in ("C1","C2")],"compound_targets":[{"compound_id":c,"target_id":"HGNC:1","symbol":"VIRTUAL1","species":9606,"source_ref":"虚构"} for c in ("C1","C2")],"disease_targets":[{"target_id":"HGNC:1","symbol":"VIRTUAL1","species":9606,"source_ref":"虚构"}],"herbs":["虚构药"],"namespace":"HGNC","mapping_snapshot":"a"*64,"analysis_purpose":"workflow_test"}
 for mid in ("A01","A02","A03","A04"):
  inputs={"payload":payload} if mid=="A03" else {};summary={};tables={}
  if mid=="A03":_,summary,tables=build(payload)
  if mid=="A04":
   degree=ranked([{"target_id":"HGNC:"+str(i),"symbol":"VIRTUAL"+str(i),"degree":100-i if count<=20 or i<15 else 85,"bc":200-i,"cc":.4} for i in range(1,count+1)],"degree",True)
   tables={"degree_round2":degree,"degree_top10":boundary_top(degree,10,"degree"),"bc_cc_top15":degree[:2]};summary={"docking_candidate_source_pending":True}
  run=f.begin(sid,mid,inputs,{},"虚构");f.finish(sid,run["run_id"],summary,tables,[],"success");f.review(sid,run["run_id"],"approved","测试","虚构")
 f.generate_candidates(sid,{**f.candidate_binding(f.load(sid)),"group_id":"group_"+uuid4().hex,"reason":"虚构"})
 if selection:
  result=f.save_selection(sid,{**f.selection_binding(sid),"selected":["C1","C2"],"manual_supplements":{},"reviewer":"测试","reason":"合成身份核查","confirmed":True})
  f.review(sid,result["run_id"],"approved","测试","合成研究，不是科研结果")
 return f,sid

def exp(pdb="1ABC",pocket="reference"):
 s={"source_type":"experimental","pdb_id":pdb,"uniprot":"P12345","chains":["A"],"pocket":pocket,"altloc":None}
 if pocket=="reference":s.update(reference_code="ABC",reference_chain="A",reference_sequence="1")
 return s

def af():return {"source_type":"alphafold","model_id":"AF-P12345-F1","uniprot":"P12345","chains":["A"],"pocket":"p2rank","sequence_start":1,"sequence_end":3}
def evidence(row,spec,rmsd=1.0):
 e={"identity":{"target_id":row["target_id"],"uniprot":"P12345","species":9606,"polymer_type":"Protein","sequence_matches":True,"chains":["A"],"sequence_start":1,"sequence_end":3},"structure_id":spec.get("pdb_id",spec.get("model_id")),"pocket_complete":True,"environment_resolved":True,"receptor_ready":True,"top1_rmsd":rmsd,"pocket":{"rank":1,"runs":[{"residue_ids":"A_1 A_2 A_3"},{"residue_ids":"A_1 A_2 A_3"}],"mapped_indices":[0,1,2]},"confidence":{"plddt":[70,80,90],"pae":[[0,10,10],[10,0,10],[10,10,0]],"pocket_indices":[0,1,2]}}
 if spec["pocket"]=="reference":e["reference"]={k:spec[k] for k in ("reference_code","reference_chain","reference_sequence")}
 e["pocket"]["confirmation"]={"confirmed":True,"pocket_key":pocket_key(spec,e["pocket"]),"reviewer":"隔离口袋核验","note":"合成证据"}
 return e

def filled(ctx):
 p=blank(ctx);p["package_id"]="D900"
 for r in p["receptors"]:r["first"]=exp()
 for c in p["compounds"]:c.update(status="use",cid="1",reason="明确来源三维",protonation_policy="pubchem_3d_as_provided_no_pH_prediction")
 return p

class TwoPassRules(unittest.TestCase):
 def setUp(self):
  self.row={"target_id":"HGNC:1","symbol":"VIRTUAL1","candidate_grade":"A","first":exp(),"second":exp("2ABC","p2rank"),"first_reason":"","second_reason":"独立结构补救","unavailable":False,"reason":""}
 def test_confidence_boundary_and_both_directions(self):
  data=evidence(self.row,af())["confidence"];self.assertTrue(confidence(data)["passed"])
  for key in ("mean","minimum","reverse"):
   d=deepcopy(data)
   if key=="mean":d["plddt"]=[70,79.9,90]
   if key=="minimum":d["plddt"]=[69.9,90,90]
   if key=="reverse":d["pae"][2][0]=10.01
   self.assertFalse(confidence(d)["passed"])
 def test_missing_nonfinite_confidence_and_mapping(self):
  for d in ({},{"plddt":[80],"pae":[[0]],"pocket_indices":[0]},{"plddt":[float("nan"),90],"pae":[[0,0],[0,0]],"pocket_indices":[0,1]}):
   with self.assertRaises(ContractError):confidence(d)
 def test_strict_pass_skips_second_even_if_second_invalid(self):
  result=assess_receptor(self.row,{"first":evidence(self.row,self.row["first"],2.0),"second":{"invalid":True}})
  self.assertEqual((result["quality"],result["second"]["state"]),("严格","skipped"))
 def test_prediction_manual_confirmation_and_chain_reference_binding(self):
  for mode in ("missing","changed"):
   facts=evidence(self.row,self.row["second"])
   if mode=="missing":facts["pocket"].pop("confirmation")
   else:facts["pocket"]["confirmation"]["pocket_key"]="old"
   result=assess_receptor(self.row,{"first":evidence(self.row,self.row["first"],3),"second":facts})
   self.assertEqual(result["state"],"failed")
  for field in ("chains","reference"):
   facts=evidence(self.row,self.row["first"])
   if field=="chains":facts["identity"]["chains"]=["B"]
   else:facts["reference"]["reference_code"]="OTHER"
   result=assess_receptor(self.row,{"first":facts,"second":None})
   self.assertEqual(result["first"]["state"],"failed")
 def test_pending_first_does_not_start_second(self):
  result=assess_receptor(self.row,{"first":None,"second":evidence(self.row,self.row["second"])})
  self.assertEqual(result["state"],"pending")
 def test_failed_strict_independent_pocket_fallback(self):
  r=assess_receptor(self.row,{"first":evidence(self.row,self.row["first"],2.01),"second":evidence(self.row,self.row["second"])})
  self.assertEqual((r["first"]["state"],r["quality"],r["selected_round"]),("failed","探索",2));self.assertIsNone(r["second"]["rmsd"])
 def test_failed_same_structure_cannot_launder(self):
  self.row["second"]["pdb_id"]="1ABC"
  with self.assertRaises(ContractError):assess_receptor(self.row,{"first":evidence(self.row,self.row["first"],3),"second":evidence(self.row,self.row["second"])})
 def test_wrong_identity_species_missing_environment_fail(self):
  for k,v in (("target_id","HGNC:2"),("species",10090),("sequence_matches",False)):
   e=evidence(self.row,self.row["first"]);e["identity"][k]=v
   self.assertEqual(assess_receptor(self.row,{"first":e,"second":None})["first"]["state"],"failed")
  e=evidence(self.row,self.row["first"]);e["environment_resolved"]=False
  self.assertEqual(assess_receptor(self.row,{"first":e,"second":None})["first"]["state"],"failed")
 def test_prediction_twice_must_agree(self):
  e=evidence(self.row,self.row["second"]);e["pocket"]["runs"][1]["residue_ids"]="other"
  self.assertEqual(assess_receptor(self.row,{"first":evidence(self.row,self.row["first"],3),"second":e})["second"]["state"],"failed")
 def test_alphafold_confidence_range_and_pocket(self):
  self.row["first"]=None;self.row["first_reason"]="无实验结构";self.row["second"]=af()
  e=evidence(self.row,af());r=assess_receptor(self.row,{"first":None,"second":e});self.assertEqual(r["quality"],"探索")
  for change in ("missing","range","pocket","low"):
   d=deepcopy(e)
   if change=="missing":d.pop("confidence")
   if change=="range":d["identity"]["sequence_end"]=4
   if change=="pocket":d["confidence"]["pocket_indices"]=[1,2]
   if change=="low":d["confidence"]["plddt"][0]=60
   self.assertEqual(assess_receptor(self.row,{"first":None,"second":d})["second"]["state"],"failed")

class TwoPassWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix="a06_two_pass_");self.root=Path(self.tmp.name);self.f,self.sid=fixture(self.root);self.ctx=source_context(self.f,self.sid);self.p=filled(self.ctx)
 def tearDown(self):self.tmp.cleanup()
 def request(self):return {"expected_source":self.ctx["source_key"],"expected_plan_id":None,"plan_id":"plan_"+uuid4().hex,"confirmed_target_ids":[r["target_id"] for r in self.p["receptors"]],"reviewer":"测试","note":"合成方案，不执行","confirmed":True,"plan":deepcopy(self.p)}
 def test_empty_and_invalid_rows_not_bulk_allowed(self):
  p=blank(self.ctx);checks=self.f.check_two_pass(self.sid,{"expected_source":self.ctx["source_key"],"plan":p})["items"];self.assertTrue(all(not r["valid"] and not r["bulk_allowed"] for r in checks))
 def test_unavailable_only_individual_and_retains_pairs(self):
  row=self.p["receptors"][0];row.update(first=None,second=None,unavailable=True,reason="无合适来源")
  self.assertEqual(row_check(row,self.ctx["receptors"][0],self.ctx)["bulk_allowed"],False)
  self.assertTrue(validate(self.p,self.ctx,[r["target_id"] for r in self.p["receptors"]]))
 def test_plan_save_retry_version_and_no_approval_run(self):
  before=self.f.load(self.sid);req=self.request();data=self.f.save_two_pass(self.sid,req);self.assertFalse(data["execution_allowed"]);self.assertEqual(self.f.save_two_pass(self.sid,req),data)
  after=self.f.load(self.sid)
  for k in ("current","runs","reviews"):self.assertEqual(before[k],after[k])
  second=self.request();second["expected_plan_id"]=data["plan_id"];self.f.save_two_pass(self.sid,second);self.assertEqual(len(self.f.load(self.sid)["two_pass_plan_records"]),2)
  with self.assertRaises(ContractError):self.f.save_two_pass(self.sid,self.request())
 def test_missing_check_or_fake_metrics_execution_fields_rejected(self):
  for kind in ("confirmed","checks","rmsd","execution","shape"):
   req=self.request()
   if kind=="confirmed":req["confirmed"]=False
   if kind=="checks":req["confirmed_target_ids"].pop()
   if kind=="rmsd":req["plan"]["receptors"][0]["first"]["rmsd"]=1
   if kind=="execution":req["execute"]=True
   if kind=="shape":req["plan"]["compounds"][0]["protonation_policy"]="generated_3d"
   with self.assertRaises(ContractError):self.f.save_two_pass(self.sid,req)
 def test_cross_study_stale_reapproval_and_trash(self):
  _,other=fixture(self.root)
  with self.assertRaises(ContractError):self.f.save_two_pass(other,self.request())
  m=self.f.load(self.sid);rid=m["current"]["A03_SELECT"];review=self.ctx["parent_review_ids"]["A03_SELECT"];self.f.review(self.sid,rid,"approved","测试","新核查",review)
  with self.assertRaises(ContractError):self.f.save_two_pass(self.sid,self.request())
  m=self.f.load(self.sid);m["trashed"]=True;self.f.save(m)
  self.assertFalse(preparation_context(self.f,m)["enabled"])
 def test_source_sdf_archive_and_wrong_compound_rejected(self):
  payload={"expected_source":self.ctx["source_key"],"compound_id":"C1","cid":"1","name":"source.sdf","content_base64":base64.b64encode(b"original source SDF\n M  END\n$$$$\n").decode()}
  d=self.f.save_material(self.sid,payload);self.assertIn("待准备",d["state_zh"]);self.p["compounds"][0]["material_id"]=d["material_id"]
  self.assertTrue(validate(self.p,self.ctx,[r["target_id"] for r in self.p["receptors"]],self.f.materials(self.f.load(self.sid),self.ctx)))
  with self.assertRaises(ContractError):self.f.save_material(self.sid,{**payload,"compound_id":"OTHER"})
 def test_below_five_can_explore_and_all_combinations_retained(self):
  for r in self.p["receptors"]:r.update(first=None,first_reason="无实验结构",second=af(),second_reason="已有模型探索")
  ev={r["target_id"]:{"first":None,"second":evidence(r,af())} for r in self.p["receptors"]}
  prep=preparation(self.ctx,self.p,ev,[{"compound_id":"C1","state":"ready"},{"compound_id":"C2","state":"failed","reason_zh":"没有来源三维"}])
  self.assertFalse(prep["primary_conditions_met"]);self.assertEqual(prep["primary_targets"],[]);self.assertEqual(len(prep["planned_pairs"]),6);self.assertEqual(sum(r["state"]=="NA" for r in prep["planned_pairs"]),3)
  result={"schema_version":RESULT,"input_key":prep["input_key"],"vina_version":"1.2.7","source_key":self.ctx["source_key"],"analysis_purpose":"workflow_test","vina_parameters":VINA,"primary_targets":[],"pairs":[{**r,"state":"NA","score":None,"reason_zh":r["reason_zh"] or "隔离测试暂不计算"} for r in prep["planned_pairs"]]}
  self.assertTrue(validate_result(result,prep));result["pairs"].pop()
  with self.assertRaises(ContractError):validate_result(result,prep)

 def test_inputs_cache_top1_na_and_pose_integrity(self):
  from storage import file_record
  ev={r["target_id"]:{"first":evidence(r,exp()),"second":None} for r in self.p["receptors"]}
  cs=[{"compound_id":"C1","state":"ready"},{"compound_id":"C2","state":"ready"}]
  prep=preparation(self.ctx,self.p,ev,cs)
  result={"schema_version":RESULT,"input_key":prep["input_key"],"vina_version":"1.2.7","source_key":self.ctx["source_key"],"analysis_purpose":"workflow_test","vina_parameters":VINA,"primary_targets":[],"pairs":[{**r,"state":"NA","score":None,"reason_zh":"隔离测试不执行"} for r in prep["planned_pairs"]]}
  self.assertTrue(validate_result(result,prep))
  for kind in ("input","vina","na","top2","missing_pose"):
   bad=deepcopy(result)
   if kind=="input":bad["input_key"]="0"*64
   if kind=="vina":bad["vina_version"]="other"
   if kind=="na":bad["pairs"][0]["score"]=0
   if kind in ("top2","missing_pose"):bad["pairs"][0].update(state="completed",pose_rank=2 if kind=="top2" else 1,score=-7,pose_record={"path":"fake.pdbqt","bytes":5,"sha256":"a"*64})
   with self.assertRaises(ContractError):validate_result(bad,prep,self.root)
  path=self.root/"virtual.pdbqt";path.write_text("ISOLATED VIRTUAL POSE NOT A SCIENTIFIC RESULT")
  result["pairs"][0].update(state="completed",pose_rank=1,score=-7,pose_record=file_record(self.root,path,"isolated_pose"))
  self.assertTrue(validate_result(result,prep,self.root))
  path.write_text("tampered")
  with self.assertRaises(ContractError):validate_result(result,prep,self.root)
  changed=deepcopy(ev);changed["HGNC:1"]["first"]["top1_rmsd"]=1.2
  newer=preparation(self.ctx,self.p,changed,cs)
  self.assertNotEqual(prep["input_key"],newer["input_key"])
  with self.assertRaises(ContractError):validate_result(result,newer,self.root)
 def test_execution_guard_remains_closed(self):
  for stage in ("prepare","execute","deliver"):
   with self.assertRaises(ContractError):run_stage(stage,execution_allowed=True)
 def test_selection_save_pending_not_auto_approved(self):
  f,sid=fixture(self.root,selection=False);before=f.load(sid);result=f.save_selection(sid,{**f.selection_binding(sid),"selected":["C1"],"manual_supplements":{},"reviewer":"测试","reason":"明确虚构身份","confirmed":True})
  self.assertFalse(f.approved(f.load(sid),result["run_id"]));self.assertTrue(f.approved(f.load(sid),before["current"]["A04"]));self.assertEqual(selection_context(f,f.load(sid))["current_selected"],["C1"])
 def test_five_primary_follow_global_ppi_order_not_grade(self):
  ctx=deepcopy(self.ctx);ctx["receptors"]=[{"target_id":"HGNC:"+str(i),"symbol":"VIRTUAL"+str(i),"candidate_grade":"A" if i<3 else "B","ppi_order":7-i} for i in range(1,7)];p=filled(ctx);ev={r["target_id"]:{"first":evidence(r,exp()),"second":None} for r in p["receptors"]}
  prep=preparation(ctx,p,ev,[{"compound_id":"C1","state":"ready"},{"compound_id":"C2","state":"ready"}])
  self.assertEqual(prep["primary_targets"],["HGNC:6","HGNC:5","HGNC:4","HGNC:3","HGNC:2"]);self.assertTrue(prep["primary_conditions_met"])

# 真实HTTP与后台子进程只操作隔离研究；任务完成后再检查归档及审批。
class HttpTwoPass(unittest.TestCase):
 def test_background_plan_selection_and_security(self):
  with tempfile.TemporaryDirectory(prefix="a06_http_") as tmp:
   root=Path(tmp);f,sid=fixture(root);settings=Settings(data_root=root,runtime_dir=root/"runtime",science_python=sys.executable);server,app=create_server(settings,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base="http://127.0.0.1:"+str(server.server_port)
   def call(path,body=None,token=True):
    headers={"Origin":base,"Content-Type":"application/json"}
    if token:headers["X-ModuleA-Token"]=app.token
    with urlopen(Request(base+"/api/v1"+path,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=30) as res:return res.status,json.load(res)
   def wait(task):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
     _,v=call("/tasks/"+task["task_id"])
     if v["state"] not in ("queued","running"):break
     time.sleep(.1)
    self.assertEqual(v["state"],"succeeded",v)
   try:
    _,view=call("/studies/"+sid+"/modules/A06_PREP");info=view["docking_preparation"];ctx=info["context"];plan=filled(ctx)
    endpoint="/studies/"+sid+"/modules/A06_PREP/actions/two_pass_plan";payload={"expected_source":info["expected_source"],"expected_plan_id":None,"confirmed_target_ids":[r["target_id"] for r in plan["receptors"]],"reviewer":"隔离HTTP","note":"不执行","confirmed":True,"plan":plan}
    with self.assertRaises(HTTPError) as denial:call(endpoint,payload,False)
    self.assertEqual(denial.exception.code,403)
    with self.assertRaises(HTTPError) as denial:call(endpoint,{**payload,"expected_source":"old"})
    self.assertEqual(denial.exception.code,409)
    status,response=call(endpoint,payload);self.assertEqual(status,202);wait(response["task"])
    _,view=call("/studies/"+sid+"/modules/A06_PREP");self.assertIsNotNone(view["docking_preparation"]["latest"]);self.assertFalse(view["docking_preparation"]["execution_allowed"])
    self.assertNotIn("A06",f.load(sid)["current"]);self.assertNotIn("A06_PREP",f.load(sid)["current"])
    binding=f.selection_binding(sid);status,response=call("/studies/"+sid+"/modules/A03_SELECT/actions/selection",{**binding,"selected":["C1"],"manual_supplements":{},"reviewer":"测试","reason":"新选择","confirmed":True});wait(response["task"])
    self.assertFalse(f.approved(f.load(sid),f.load(sid)["current"]["A03_SELECT"]))
    _,view=call("/studies/"+sid+"/modules/A06_PREP");self.assertFalse(view["docking_preparation"]["enabled"])
   finally:server.shutdown();server.server_close();thread.join()
