"""新版本参考证据资格复算：仅同批严格参考可更新对应受体，不执行评分。"""

from copy import deepcopy

from contracts import require
from .reference_candidates import validate_choices
from .plan_reference_evidence import validate_ready
from .plan_preparation_v2 import reports

VERSION = "A06.plan_reference_qualification.2"


def derive(home, input_packet, base_fact, reference_packet):
    """复验明确选择与实际证据；调用方须从已验签归档构造base_fact。"""
    require(reference_packet.get("schema_version") == "A06.plan_reference_review.1",
            "参考核查版本不支持")
    require(isinstance(base_fact.get("study_id"), str) and base_fact["study_id"] and
            reference_packet.get("study_id") == base_fact["study_id"] == input_packet.get("study_id"),
            "参考证据与准备输入不属于同一研究")
    require(isinstance(base_fact.get("run_id"), str) and base_fact["run_id"] and
            reference_packet.get("source_preparation_run_id") == base_fact["run_id"],
            "参考证据与原准备运行不一致")
    require(isinstance(base_fact.get("current_run_id"), str) and base_fact["current_run_id"] and
            reference_packet.get("expected_preparation_run_id") == base_fact["current_run_id"],
            "参考证据与当前准备版本不一致")
    require(isinstance(input_packet.get("input_key"), str) and input_packet["input_key"] and
            base_fact.get("input_key") == input_packet["input_key"], "准备事实与输入指纹不一致")
    require(reference_packet.get("config") == base_fact.get("config"), "参考证据参数与来源准备不一致")
    require(isinstance(base_fact.get("input_id"), str) and base_fact["input_id"] and
            reference_packet.get("input_id") == base_fact["input_id"], "参考证据与固定输入不一致")
    connection = base_fact["connection"]
    choices = reference_packet["choices"]
    validate_choices(home, connection, choices)
    values = reference_packet["results"]
    require(len(values) == len(choices) and
            all(result.get("choice") == choice for result, choice in zip(values, choices)),
            "参考结果与明确选择不一致")
    targets = [r["target_id"] for r in base_fact["receptors"]]
    require(targets == [r["target_id"] for r in input_packet["receptors"]] and
            len(targets) == len(set(targets)), "受体范围与固定输入不一致")
    compounds = [r["compound_id"] for r in base_fact["compounds"]]
    require(compounds == [r["compound_id"] for r in input_packet["compounds"]] and
            len(compounds) == len(set(compounds)), "成分范围与固定输入不一致")
    receptors = deepcopy(base_fact["receptors"])
    by_id = {r["target_id"]: r for r in receptors}
    reference_results = []
    for choice, result in zip(choices, values):
        row = by_id.get(choice["target_id"])
        require(row is not None, "参考选择不属于固定受体范围")
        if result.get("state") == "ready":
            assessment = validate_ready(home, connection, result, base_fact["config"])
            require(assessment["state"] == "ready" and assessment["quality"] == "严格",
                    "参考证据未通过严格复验")
            row.update(state="ready", quality="严格", reason_zh=assessment["reason_zh"])
            row["reference_evidence"] = deepcopy(result)
            reference_results.append({"target_id": row["target_id"], "state": "ready",
                                      "reason_zh": assessment["reason_zh"]})
        else:
            require(result.get("state") == "NA" and isinstance(result.get("reason_zh"), str)
                    and result["reason_zh"].strip(), "失败参考必须保留NA及原因")
            reference_results.append({"target_id": row["target_id"], "state": "NA",
                                      "reason_zh": result["reason_zh"]})
    summary, tables = reports(input_packet, base_fact["compounds"], receptors)
    summary.update(reference_ready_count=sum(r["state"] == "ready" for r in reference_results),
                   reference_na_count=sum(r["state"] == "NA" for r in reference_results),
                   execution_available=False, scored_pairs=0, handoff_blocked=True,
                   message_zh="参考证据复算完成；组合评分及正式批准仍未开放")
    tables["reference_qualification"] = reference_results
    return {"schema_version": VERSION, "receptors": receptors, "summary": summary, "tables": tables}
