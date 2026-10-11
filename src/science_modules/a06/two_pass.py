"""两遍受体核查纯规则：严格口径冻结，独立补救仅作探索，不调用科学工具。"""
from copy import deepcopy
import math,json,hashlib,re
from storage import verified_file
from contracts import require
POLICY = "A06.two_pass.policy.1"
PREP = "A06.two_pass.preparation.1"
RESULT = "A06.two_pass.result.1"
CONFIDENCE = {"mean_plddt":80.0,"min_plddt":70.0,"max_bidirectional_pae_A":10.0}
VINA_VERSION = "1.2.7"
VINA = {"scoring":"vina","exhaustiveness":8,"num_modes":9,"energy_range_kcal_mol":3,"seed":1}

# 从完整残基映射取首位口袋，不以全蛋白平均值掩盖低置信口袋。
def confidence(data):
    require(isinstance(data,dict),"缺少AlphaFold口袋置信度资料")
    scores,pae,indices=data.get("plddt"),data.get("pae"),data.get("pocket_indices")
    require(isinstance(scores,list) and scores and isinstance(pae,list) and len(pae)==len(scores),"置信度或PAE长度不一致")
    require(all(isinstance(row,list) and len(row)==len(scores) for row in pae),"PAE矩阵不完整")
    require(isinstance(indices,list) and len(indices)>=2 and all(isinstance(i,int) and not isinstance(i,bool) and 0<=i<len(scores) for i in indices) and len(set(indices))==len(indices),"口袋残基索引不完整或重复")
    require(all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=100 for v in scores),"pLDDT无效")
    require(all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for row in pae for v in row),"PAE无效")
    local=[scores[i] for i in indices];maximum=max(pae[i][j] for i in indices for j in indices if i!=j)
    facts={"mean_plddt":sum(local)/len(local),"min_plddt":min(local),"max_bidirectional_pae_A":maximum,"pocket_residues":len(indices)}
    facts["passed"]=facts["mean_plddt"]>=80 and facts["min_plddt"]>=70 and maximum<=10
    return facts

# 预测口袋确认必须绑定这份结构与两次原始预测，不沿用其他结构的人工签名。
def pocket_key(spec,pocket):
    data={"structure":spec,"rank":pocket.get("rank"),"runs":pocket.get("runs"),"mapped_indices":pocket.get("mapped_indices")}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

# 只评估已归档准备证据；客户端方案不能直接提供这些计算事实。
def assess_attempt(spec,evidence,target,round_no):
    output={"round":round_no,"state":"pending","quality":"待验证","source_type":spec.get("source_type") if spec else None,"structure_id":spec.get("pdb_id",spec.get("model_id","")) if spec else "","rmsd":None,"reason_zh":"尚未准备和验证"}
    if not spec:return {**output,"state":"unavailable","quality":"无法计算","reason_zh":"未提供结构方案"}
    if evidence is None:return output
    try:
        identity=evidence.get("identity",{})
        require(identity.get("target_id")==target["target_id"] and identity.get("uniprot")==spec["uniprot"] and identity.get("species")==9606 and identity.get("polymer_type")=="Protein" and identity.get("sequence_matches") is True and identity.get("chains")==spec["chains"],"蛋白身份、物种或序列不符")
        require(evidence.get("structure_id")==output["structure_id"],"准备证据不属于所选结构")
        require(evidence.get("pocket_complete") is True and evidence.get("environment_resolved") is True,"口袋不完整或必要环境尚未解决")
        require(evidence.get("receptor_ready") is True,"受体尚未成功准备")
        if spec["source_type"]=="alphafold":
            require(round_no==2 and spec["pocket"]=="p2rank","预测结构只用于第二遍探索")
            data=evidence.get("confidence",{})
            require(identity.get("sequence_start")==spec["sequence_start"] and identity.get("sequence_end")==spec["sequence_end"] and len(data.get("plddt",[]))==spec["sequence_end"]-spec["sequence_start"]+1,"模型序列范围与置信度记录不符")
            require(data.get("pocket_indices")==evidence.get("pocket",{}).get("mapped_indices"),"置信度残基不属于首位预测口袋")
            output["confidence"]=confidence(data)
            require(output["confidence"]["passed"],"AlphaFold口袋置信度未达到项目探索阈值")
        if spec["pocket"]=="reference":
            require(evidence.get("reference")=={k:spec[k] for k in ("reference_code","reference_chain","reference_sequence")},"重对接参考配体与方案不符")
            value=evidence.get("top1_rmsd")
            require(isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0,"缺少有效Top-1重对接RMSD")
            output["rmsd"]=value
            require(value<=2.0,"Top-1重对接RMSD超过2Å")
            return {**output,"state":"ready","quality":"严格","reason_zh":"当前结构严格质控通过"}
        require(round_no==2,"第一遍必须使用共晶参考配体")
        pocket=evidence.get("pocket",{})
        require(pocket.get("rank")==1 and isinstance(pocket.get("runs"),list) and len(pocket["runs"])==2 and pocket["runs"][0]==pocket["runs"][1] and pocket["runs"][0],"P2Rank首位口袋两次结果不一致或缺证据")
        decision=pocket.get("confirmation",{})
        require(decision.get("confirmed") is True and decision.get("pocket_key")==pocket_key(spec,pocket) and all(isinstance(decision.get(k),str) and decision[k].strip() for k in ("reviewer","note")),"预测口袋证据尚未人工确认，或确认绑定已失效")
        return {**output,"state":"ready","quality":"探索","reason_zh":"无可靠参考配体；重对接RMSD不适用"}
    except (ValueError,KeyError,TypeError) as error:
        return {**output,"state":"failed","quality":"无法计算","reason_zh":str(error)}

# 第一遍通过则不执行第二遍；失败结构不能切换口袋绕过失败。
def assess_receptor(row,evidence):
    first=assess_attempt(row.get("first"),evidence.get("first"),row,1)
    if first["state"]=="ready":second={"round":2,"state":"skipped","quality":"不适用","reason_zh":"第一遍已通过"}
    elif first["state"]=="pending":second={"round":2,"state":"pending","quality":"待验证","reason_zh":"等待第一遍结果"}
    else:
        require(not row.get("second") or not row.get("first") or row["second"].get("pdb_id",row["second"].get("model_id"))!=row["first"].get("pdb_id",row["first"].get("model_id")),"第二遍必须使用独立结构，不能切换原失败结构口袋")
        second=assess_attempt(row.get("second"),evidence.get("second"),row,2)
    chosen=first if first["state"]=="ready" else second
    return {"target_id":row["target_id"],"symbol":row["symbol"],"candidate_grade":row["candidate_grade"],"first":first,"second":second,"selected_round":chosen.get("round") if chosen.get("state")=="ready" else None,"state":chosen["state"],"quality":chosen["quality"]}

# 不足五严格受体仍可探索，但主要五名单保持空；全部组合都有状态。
def preparation(context,plan,evidence,compounds):
    require(set(evidence)=={r["target_id"] for r in context["receptors"]},"准备证据受体范围不符")
    require([r["compound_id"] for r in compounds]==[r["compound_id"] for r in context["compounds"]],"配体准备范围不符")
    require(plan.get("policy_version")==POLICY and [r["target_id"] for r in plan["receptors"]]==[r["target_id"] for r in context["receptors"]],"准备方案策略或受体顺序不符")
    require(all(r["symbol"]==s["symbol"] and r["candidate_grade"]==s["candidate_grade"] for r,s in zip(plan["receptors"],context["receptors"])),"准备不能改受体身份或候选标签")
    rows=[assess_receptor(row,evidence[row["target_id"]]) for row in plan["receptors"]]
    order={r["target_id"]:r["ppi_order"] for r in context["receptors"]}
    strict=sorted([r for r in rows if r["state"]=="ready" and r["quality"]=="严格"],key=lambda r:(order[r["target_id"]],r["target_id"]))
    ready={r["target_id"] for r in rows if r["state"]=="ready"}
    primary=[r["target_id"] for r in strict[:5]] if len(strict)>=5 else []
    snapshot={"context":context,"plan":plan,"evidence":evidence,"compounds":compounds,"policy":POLICY,"vina_version":VINA_VERSION,"vina_parameters":VINA}
    input_key=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    pairs=[]
    for c in compounds:
        for r in rows:
            passed=r["target_id"] in ready and c.get("state")=="ready"
            reasons=[]
            if c.get("state")!="ready":reasons.append(c.get("reason_zh") or "配体未通过来源三维准备")
            if r["target_id"] not in ready:
                original=next(x for x in plan["receptors"] if x["target_id"]==r["target_id"])
                reasons.append(original["reason"] if original.get("unavailable") else r["second"].get("reason_zh") or r["first"]["reason_zh"])
            pairs.append({"input_key":input_key,"compound_id":c["compound_id"],"target_id":r["target_id"],"state":"ready" if passed else "NA","reason_zh":"；".join(reasons)})
    return {"input_key":input_key,"vina_version":VINA_VERSION,"schema_version":PREP,"policy_version":POLICY,"source_key":context["source_key"],"analysis_purpose":context["analysis_purpose"],"receptors":rows,"compounds":deepcopy(compounds),"planned_pairs":pairs,"primary_targets":primary,"strict_count":len(strict),"primary_conditions_met":len(strict)>=5,"execution_allowed":False}

# 新结果契约明确全部组合覆盖；NA、Top-1及姿势文件校验仍不可放宽。
def validate_result(packet,prep,root=None):
    require(packet.get("schema_version")==RESULT and packet.get("source_key")==prep["source_key"] and packet.get("analysis_purpose")==prep["analysis_purpose"],"结果版本或来源不一致")
    require(packet.get("input_key")==prep["input_key"] and packet.get("vina_version")==VINA_VERSION,"结果准备输入或Vina版本不匹配，不能复用旧评分")
    require(packet.get("vina_parameters")==VINA and packet.get("primary_targets")==prep["primary_targets"],"参数或主要受体被改变")
    expected={(r["compound_id"],r["target_id"]):r for r in prep["planned_pairs"]}
    rows=packet.get("pairs")
    require(isinstance(rows,list) and len(rows)==len(expected),"结果必须覆盖全部计划组合")
    seen=set()
    for row in rows:
        key=(row.get("compound_id"),row.get("target_id"));require(key in expected and key not in seen,"重复或跨研究对接组合");seen.add(key)
        require(row.get("input_key")==prep["input_key"],"组合准备指纹不匹配")
        if row.get("state")=="completed":
            require(expected[key]["state"]=="ready" and row.get("pose_rank")==1,"失败对象不能产生评分，也不能改取第二姿势")
            score=row.get("score");pose=row.get("pose_record",{})
            require(isinstance(score,(int,float)) and not isinstance(score,bool) and math.isfinite(score),"对接评分无效")
            require(isinstance(pose.get("path"),str) and pose["path"] and isinstance(pose.get("bytes"),int) and pose["bytes"]>0 and isinstance(pose.get("sha256"),str) and re.fullmatch(r"[0-9a-f]{64}",pose["sha256"]),"姿势缺完整文件指纹")
            require(root is not None,"有效评分必须核验实际归档姿势文件")
            verified_file(root,pose)
        else:
            require(row.get("state")=="NA" and row.get("score") is None and isinstance(row.get("reason_zh"),str) and row["reason_zh"].strip(),"失败组合须保留NA与原因")
    return True
