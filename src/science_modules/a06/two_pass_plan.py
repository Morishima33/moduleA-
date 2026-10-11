"""两遍方案输入版本：完整来源绑定，人工方案不能冒充科学计算事实。"""
from copy import deepcopy
import re
from contracts import require
from .two_pass import POLICY
from .plan_adapter import validate_plan as validate_legacy
SCHEMA="A06.two_pass.plan.1"

# 空白输入无默认结构、CID或科学成功状态，全部待用户核查。
def blank(context):
    return {"policy_version":POLICY,"package_id":"","pymol_executable":"",
      "compounds":[{"compound_id":r["compound_id"],"status":None,"reason":""} for r in context["compounds"]],
      "receptors":[{"target_id":r["target_id"],"symbol":r["symbol"],"candidate_grade":r["candidate_grade"],"first":None,"first_reason":"","second":None,"second_reason":"","unavailable":False,"reason":""} for r in context["receptors"]]}

# 实验结构完整字段继续交给既有输入约束，AlphaFold另设来源字段。
def validate_spec(spec,source,round_no,context):
    require(isinstance(spec,dict),"结构方案缺字段")
    require(spec.get("source_type") in ("experimental","alphafold"),"未知结构来源")
    if spec["source_type"]=="experimental":
        require(set(spec)<= {"source_type","pdb_id","chains","uniprot","pocket","altloc","reference_code","reference_chain","reference_sequence"},"结构方案含未授权计算字段")
        row={**{k:v for k,v in spec.items() if k!="source_type"},"target":source["symbol"],"target_id":source["target_id"],"candidate_grade":source["candidate_grade"],"scope":"strict" if spec.get("pocket")=="reference" else "exploratory","reason":"明确结构方案"}
        require(round_no==2 or spec.get("pocket")=="reference","第一遍须使用共晶参考配体")
        # 复用字段校验；工具占位仅用于该纯校验，不作为计划工具路径或执行对象。
        mini={"receptors":[source],"compounds":[]}
        import sys
        validate_legacy({"receptors":[row],"compounds":[],"package_id":"D000","pymol_executable":sys.executable},mini)
    else:
        require(round_no==2 and set(spec)=={"source_type","model_id","uniprot","chains","pocket","sequence_start","sequence_end"},"AlphaFold只允许第二遍且须完整模型范围")
        require(isinstance(spec.get("model_id"),str) and re.fullmatch(r"AF-[A-Z0-9]+-F[0-9]+",spec["model_id"]) and spec["model_id"].split("-")[1]==spec.get("uniprot"),"模型编号与UniProt不符")
        require(re.fullmatch(r"[A-Z0-9]{6,10}",str(spec.get("uniprot",""))) and spec.get("pocket")=="p2rank" and isinstance(spec.get("chains"),list) and len(spec["chains"])==1 and re.fullmatch(r"[A-Za-z0-9]",spec["chains"][0]),"模型身份或预测口袋字段不完整")
        require(all(isinstance(spec.get(k),int) and not isinstance(spec[k],bool) for k in ("sequence_start","sequence_end")) and 1<=spec["sequence_start"]<spec["sequence_end"],"模型序列范围不完整")
    return deepcopy(spec)

# 每行资格由后端校验；最终保存重新执行同一规则，前端不推算科学通过。
def row_check(row,source,context):
    try:
        require(set(row)=={"target_id","symbol","candidate_grade","first","first_reason","second","second_reason","unavailable","reason"},"受体方案含未授权字段")
        require(all(row[k]==source[k] for k in ("target_id","symbol","candidate_grade")),"受体身份或A/B标签与当前名单不符")
        require(isinstance(row["unavailable"],bool) and all(isinstance(row[k],str) and len(row[k])<=2000 for k in ("first_reason","second_reason","reason")),"方案说明格式无效")
        if row["unavailable"]:
            require(row["reason"].strip() and row["first"] is None and row["second"] is None,"无法计算项须说明原因且不能同时配置结构")
            return {"valid":True,"bulk_allowed":False,"reason_zh":"明确暂无法计算；需单项确认，组合保留NA"}
        require(row["first"] is not None or row["first_reason"].strip(),"第一遍缺结构或未提供原因")
        require(row["first"] is not None or row["second"] is not None,"两遍均缺结构，请补资料或明确暂无法计算")
        for key,number in (("first",1),("second",2)):
            if row[key] is not None:validate_spec(row[key],source,number,context)
        if row["second"] is not None:
            require(row["second_reason"].strip(),"请填写第二遍独立补救依据")
            require(row["first"] is None or row["first"].get("pdb_id")!=row["second"].get("pdb_id",row["second"].get("model_id")),"第二遍不能复用原失败结构切换口袋")
            require(row["first"] is None or row["first"]["uniprot"]==row["second"]["uniprot"],"两遍UniProt身份不同")
        return {"valid":True,"bulk_allowed":True,"reason_zh":"方案字段完整；仍待实际准备与质控"}
    except (ValueError,KeyError,TypeError) as error:return {"valid":False,"bulk_allowed":False,"reason_zh":str(error)}

# 配体只接受来源三维路线，上传SDF需绑定同一成分/CID并在后续独立验证。
def validate(plan,context,checked,materials=()):
    require(isinstance(plan,dict) and set(plan)=={"policy_version","package_id","pymol_executable","compounds","receptors"} and plan["policy_version"]==POLICY,"两遍方案版本或字段不符")
    receptors=plan["receptors"]
    require(isinstance(receptors,list) and all(isinstance(r,dict) for r in receptors) and [r.get("target_id") for r in receptors]==[r["target_id"] for r in context["receptors"]],"两遍方案须覆盖全部当前受体且不能重复")
    require(isinstance(checked,list) and all(isinstance(x,str) for x in checked) and len(set(checked))==len(checked) and set(checked)=={r["target_id"] for r in receptors},"须逐项确认完整受体名单；全选不代替保存")
    for row,source in zip(receptors,context["receptors"]):
        facts=row_check(row,source,context);require(facts["valid"],source["symbol"]+"："+facts["reason_zh"])
    compounds=plan["compounds"]
    require(isinstance(compounds,list) and all(isinstance(r,dict) for r in compounds) and [r.get("compound_id") for r in compounds]==[r["compound_id"] for r in context["compounds"]],"配体须覆盖当前已批准成分")
    for row in compounds:
        require(set(row)<={"compound_id","status","reason","cid","protonation_policy","material_id"} and row.get("status") in ("use","unavailable") and isinstance(row.get("reason"),str) and row["reason"].strip(),"配体状态或依据未明确")
        if row["status"]=="use":
            require(re.fullmatch(r"[0-9]+",str(row.get("cid",""))) and int(row["cid"])>0 and row.get("protonation_policy")=="pubchem_3d_as_provided_no_pH_prediction","配体只能使用明确CID的来源三维结构，不允许本地生成")
            if row.get("material_id"):require(any(m["material_id"]==row["material_id"] and m["compound_id"]==row["compound_id"] and str(m["cid"])==str(row["cid"]) and m["source_key"]==context["source_key"] for m in materials),"上传三维资料不属于当前成分或版本")
    require(isinstance(plan["package_id"],str) and re.fullmatch(r"D[0-9]{3,}",plan["package_id"]),"请填写稳定任务包编号")
    require(isinstance(plan["pymol_executable"],str),"工具字段格式错误")
    return deepcopy(plan)
