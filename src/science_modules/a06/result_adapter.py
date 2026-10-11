"""为同源A06事实附加两梯队标签；不改评分、NA、姿势、RMSD或主要结论范围。"""
from copy import deepcopy
from contracts import require
from docking_contract import validate_generic_result, score_matrix_table

VERSION = "A06.two_tier.result_metadata.1"

# 此函数仅适配已存在的事实包，拒绝伪造遗漏对象或把旧病例评分移入新研究。
def attach_groups(result,context):
    validate_generic_result(result)
    require(result.get("analysis_purpose")==context["analysis_purpose"],"结果用途与登记不同，不能将流程测试改为正式研究")
    rows=context["receptors"]
    index={r["symbol"]:r for r in rows}
    require(len(index)==len(rows),"同源候选基因名重复")
    require([r["target"] for r in result["receptors"]]==[r["symbol"] for r in rows],"结果必须按本次A/B顺序覆盖全部候选")
    require([r["compound_id"] for r in result["compounds"]]==[r["compound_id"] for r in context["compounds"]],"结果成分与批准选择不一致")
    provenance=result.get("source_binding")
    require(provenance=={"source_key":context["source_key"],"parent_runs":context["parent_runs"],"candidate_record":context["candidate_record"]},"结果没有同源版本绑定，不能给历史评分补贴新级别")
    value=deepcopy(result)
    value["candidate_metadata_version"]=VERSION
    for row in value["receptors"]:
        source=index[row["target"]]
        require(row.get("target_id",source["target_id"])==source["target_id"],"结果HGNC身份与候选不同")
        require(row.get("candidate_grade",source["candidate_grade"])==source["candidate_grade"],"既有候选标签与来源冲突，不能静默改写")
        row.update(target_id=source["target_id"],candidate_grade=source["candidate_grade"])
    validate_generic_result(value)
    require(score_matrix_table(value)==score_matrix_table(result),"附加候选级别不能改变评分矩阵")
    return value

# 中文明细保持候选级别与真实结构质控两列，A组也可能质控失败并保留NA。
def candidate_quality_table(result):
    validate_generic_result(result)
    require(result.get("candidate_metadata_version")==VERSION,"缺少新版候选来源标签")
    require(all(r.get("candidate_grade") in ("A","B") and isinstance(r.get("target_id"),str) and r["target_id"].startswith("HGNC:") for r in result["receptors"]),"候选级别或HGNC标签不完整")
    return [{"梯队":"第一梯队" if r["candidate_grade"]=="A" else "第二梯队",
             "候选证据级别":r["candidate_grade"],"基因":r["target"],"HGNC":r["target_id"],
             "结构质控":r["qc_status"],"重对接RMSD（Å）":r["redocking_rmsd_A"],
             "结果解释范围":r["interpretation_scope"]} for r in result["receptors"]]
