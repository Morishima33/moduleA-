"""A06两梯队方案第1版：只校验已批准名单和人工结构选择，不下载或计算。"""
from copy import deepcopy
from pathlib import Path
import re
from contracts import fingerprint, require
from docking_generic_prep import MIN_STRICT_RECEPTORS
from science_modules.a06.candidates import VERSION as GROUP_VERSION, build, checked

SCHEMA = "A06.two_tier.plan.1"
PARENTS = ("A00","A03","A03_SELECT","A04")
PLAN_FIELDS = {"compounds","receptors","package_id","pymol_executable"}
RECEPTOR_FIELDS = {"target","target_id","candidate_grade","scope","reason","pdb_id","chains","uniprot","pocket","altloc","reference_code","reference_chain","reference_sequence"}
COMPOUND_FIELDS = {"compound_id","status","reason","cid","protonation_policy"}

# A在前、B在后，各自沿用A04的Degree顺序；并列、失败和低位对象均不能漏掉。
def receptor_window(groups):
    require(groups.get("schema_version")==GROUP_VERSION,"两梯队候选版本不支持")
    a,b=checked(groups.get("group_a")),checked(groups.get("group_b"))
    full=checked(groups.get("degree_top15"))
    identities=[r["target_id"] for r in a+b]
    require(len(identities)==len(set(identities)) and set(identities)=={r["target_id"] for r in full},"两梯队有重复或漏掉前十五窗口对象")
    require(len({r["symbol"] for r in a+b})==len(identities),"受体标准基因名重复，不能交给以基因名定位的旧计算内核")
    rows=[]
    for grade,items in (("A",a),("B",b)):
        require(all(r.get("evidence_group")==grade for r in items),"候选证据级别与归档不一致")
        for row in items:
            rank=row.get("rank")
            require(isinstance(rank,int) and not isinstance(rank,bool) and rank>=1,"候选缺少A04第二轮Degree名次")
            rows.append({"symbol":row["symbol"],"target_id":row["target_id"],"candidate_grade":grade,
                         "ppi_order":rank,"screen_order":len(rows)+1,"degree":row["degree"],"bc":row["bc"],"cc":row["cc"]})
    require(groups.get("counts",{}).get("a")==len(a) and groups.get("counts",{}).get("b")==len(b),"候选数量与归档不一致")
    return rows

# 只读当前已批准版本；失效成分、撤回复核、跨研究资料均不能进入新方案。
def source_context(workflow,sid,manifest=None):
    manifest=manifest or workflow.load(sid)
    require(not manifest.get("trashed"),"回收站研究只读")
    parents={m:manifest["current"].get(m,"") for m in PARENTS}
    require(all(parents.values()) and all(workflow.approved(manifest,r) for r in parents.values()),"A00、A03、成分选择与A04须先通过；不能沿用失效成分")
    binding=workflow.candidate_binding(manifest)
    groups,record=workflow.candidate_record(manifest,binding)
    require(groups is not None,"请先生成当前A04的两梯队候选")
    expected=build(workflow.result(manifest,parents["A04"])["tables"])
    require(all(groups[k]==expected[k] for k in ("group_a","group_b","degree_top15","counts")),"候选归档与绑定A04第二轮不一致")
    purpose=workflow.result(manifest,parents["A00"])["summary"].get("analysis_purpose")
    require(purpose in ("formal_research","workflow_test"),"请明确登记用途，不能将历史资料默认为正式研究")
    ligands=workflow.result(manifest,parents["A03_SELECT"])["tables"].get("selected",[])
    require(isinstance(ligands,list) and ligands,"成分选择为空，不能建立对接方案")
    ids=[r.get("compound_id") for r in ligands]
    require(all(isinstance(x,str) and x for x in ids) and len(ids)==len(set(ids)),"成分稳定编号缺失或重复")
    reviews={m:workflow.latest_review(manifest,workflow.run(manifest,r)["artifact_id"])["review_id"] for m,r in parents.items()}
    refs={m:deepcopy(manifest["runs"][r]["result_file"]) for m,r in parents.items()}
    binding={"parent_runs":parents,"parent_review_ids":reviews,"candidate_record":deepcopy(record),"candidate_group_id":groups["group_id"],"source_results":refs,"analysis_purpose":purpose}
    return {**binding,"source_key":fingerprint(binding),"receptors":receptor_window(groups),
            "compounds":[{"compound_id":r["compound_id"],"name":r.get("name",""),"herbs":r.get("herbs","")} for r in ligands]}

# 空白结构和形态保持待填写；不预置CID、PDB、盒参数、质控通过或结合能。
def blank_plan(context):
    return {"compounds":[{"compound_id":r["compound_id"],"status":None,"reason":""} for r in context["compounds"]],
            "receptors":[{"target":r["symbol"],"target_id":r["target_id"],"candidate_grade":r["candidate_grade"],"scope":None,"reason":""} for r in context["receptors"]],
            "package_id":"","pymol_executable":""}

# 复用旧方案约束，仅将第一轮前十来源替换为已归档两梯队；A/B不自动通过质控。
def validate_plan(data,context):
    require(isinstance(data,dict) and set(data)==PLAN_FIELDS,"方案字段不完整或含未授权运行参数")
    receptors,compounds=data["receptors"],data["compounds"]
    require(isinstance(receptors,list) and all(isinstance(r,dict) for r in receptors),"受体方案必须逐项填写")
    require(isinstance(compounds,list) and all(isinstance(r,dict) for r in compounds),"成分方案必须逐项填写")
    expected=context["receptors"]
    require([r.get("target_id") for r in receptors]==[r["target_id"] for r in expected],"结构方案须按A/B顺序覆盖全部HGNC候选，不能漏掉不能计算的对象")
    for row,source in zip(receptors,expected):
        require(set(row)<=RECEPTOR_FIELDS,"受体方案含未授权字段，不能预填质控结果")
        require(row.get("target")==source["symbol"] and row.get("candidate_grade")==source["candidate_grade"],"受体名称或候选级别与来源不一致")
        require(row.get("scope") in ("strict","exploratory","unavailable") and isinstance(row.get("reason"),str) and row["reason"].strip(),"每个受体须明确结构范围和依据")
        if row["scope"]=="unavailable":
            continue
        require(isinstance(row.get("pdb_id"),str) and re.fullmatch(r"[0-9][A-Za-z0-9]{3}",row["pdb_id"]),"请填写有效PDB编号")
        chains=row.get("chains")
        require(isinstance(chains,list) and chains and all(isinstance(c,str) and re.fullmatch(r"[A-Za-z0-9]",c) for c in chains) and len(chains)==len(set(chains)),"请填写不重复的单字符作者链")
        require(isinstance(row.get("uniprot"),str) and re.fullmatch(r"[A-Z0-9]{6,10}",row["uniprot"]),"请明确UniProt身份")
        require(row.get("pocket") in ("reference","p2rank") and "altloc" in row and row["altloc"] in (None,"A","B"),"口袋或替代构象选择未确认")
        if row["pocket"]=="reference":
            require(isinstance(row.get("reference_code"),str) and re.fullmatch(r"[A-Z0-9]{1,3}",row["reference_code"]) and isinstance(row.get("reference_chain"),str) and re.fullmatch(r"[A-Za-z0-9]",row["reference_chain"]) and re.fullmatch(r"-?\d+[A-Za-z]?",str(row.get("reference_sequence",""))),"请明确参考配体代码、作者链和残基编号")
        require(row["scope"]!="strict" or row["pocket"]=="reference","预测口袋不能作为严格重对接受体")
    require([r.get("compound_id") for r in compounds]==[r["compound_id"] for r in context["compounds"]],"配体方案与本次批准成分不同")
    for row in compounds:
        require(set(row)<=COMPOUND_FIELDS,"成分方案含未授权字段")
        require(row.get("status") in ("use","unavailable") and isinstance(row.get("reason"),str) and row["reason"].strip(),"每个成分须明确形态或暂停说明")
        if row["status"]=="use":
            require(re.fullmatch(r"[0-9]+",str(row.get("cid",""))) and int(row["cid"])>0 and row.get("protonation_policy")=="pubchem_3d_as_provided_no_pH_prediction","请明确CID和使用原始PubChem三维形态，不猜测电离状态")
    require(isinstance(data["package_id"],str) and re.fullmatch(r"D\d{3,}",data["package_id"]),"请明确任务包编号")
    require(isinstance(data["pymol_executable"],str) and Path(data["pymol_executable"]).is_file(),"请明确可用PyMOL程序")
    return deepcopy(data)

# 方案留存不批准A06_PREP，也不产生任何科学运行或执行授权。
def plan_metadata(context):
    return {"schema_version":SCHEMA,"source_key":context["source_key"],"analysis_purpose":context["analysis_purpose"],
            "parent_runs":deepcopy(context["parent_runs"]),"parent_review_ids":deepcopy(context["parent_review_ids"]),
            "candidate_record":deepcopy(context["candidate_record"]),"candidate_group_id":context["candidate_group_id"],
            "source_results":deepcopy(context["source_results"]),"minimum_strict_receptors":MIN_STRICT_RECEPTORS,
            "execution_allowed":False,"status":"pending_structure_preparation_and_independent_review"}
