"""新方案A06准备输入：固定成分与受体范围，失败项保留NA。"""

from copy import deepcopy

from contracts import fingerprint, require

VERSION = "A06.plan_preparation_input.1"


def build(study_id, runs, reviews, result_refs, selection_ref, selection_review_ref,
          plan_ref, selection, compounds):
    """只编制不可变准备输入；不下载结构、不运行Vina或宣布质控通过。"""
    require(isinstance(study_id, str) and isinstance(runs, dict) and isinstance(reviews, dict),
            "A06准备输入的研究或上游绑定缺失")
    require(set(runs) == {"A00", "A03", "A03_SELECT", "A04"}
            and set(reviews) == set(runs) and set(result_refs) == set(runs),
            "A06准备输入必须绑定完整上游")
    require(isinstance(selection, dict) and selection.get("network_run_id") == runs["A04"]
            and isinstance(selection.get("selected"), list), "A04受体选择与准备输入不一致")
    require(isinstance(compounds, list) and all(isinstance(row, dict) for row in compounds),
            "A03_SELECT成分选择不完整")
    compound_ids = [row.get("compound_id") for row in compounds]
    receptors = selection["selected"]
    receptor_ids = [row.get("target_id") for row in receptors]
    require(all(isinstance(item, str) and item for item in compound_ids + receptor_ids)
            and len(compound_ids) == len(set(compound_ids))
            and len(receptor_ids) == len(set(receptor_ids)), "准备范围含缺失或重复身份")
    symbols = [row.get("symbol") for row in receptors]
    require(all(isinstance(item, str) and item for item in symbols)
            and len(symbols) == len(set(symbols)), "准备受体的标准基因名缺失或重复")
    require(all(row.get("selection_order") == index for index, row in enumerate(receptors, 1)),
            "A04受体顺序与选择归档不一致")
    core = {"schema_version": VERSION, "study_id": study_id,
            "runs": deepcopy(runs), "reviews": deepcopy(reviews),
            "result_refs": deepcopy(result_refs), "a04_selection_ref": deepcopy(selection_ref),
            "a04_selection_review_ref": deepcopy(selection_review_ref), "plan_ref": deepcopy(plan_ref),
            "analysis_parameter_hash": selection["analysis_parameter_hash"],
            "compounds": deepcopy(compounds), "receptors": deepcopy(receptors)}
    pair_count = len(compounds) * len(receptors)
    return {**core, "input_key": fingerprint(core), "pair_count": pair_count,
            "structure_preparation_state": "pending" if pair_count else "empty_range",
            "execution_available": False}


def pair_statuses(packet, compound_statuses, receptor_statuses):
    """消费后续已核验的准备状态；按固定笛卡尔范围保留NA，不补低排名受体。"""
    require(isinstance(packet, dict) and packet.get("schema_version") == VERSION,
            "A06准备输入版本不一致")
    core = {key: value for key, value in packet.items() if key not in
            ("input_key", "pair_count", "structure_preparation_state", "execution_available")}
    require(packet.get("input_key") == fingerprint(core), "A06准备输入指纹不一致")
    compounds, receptors = packet["compounds"], packet["receptors"]
    require(packet.get("pair_count") == len(compounds) * len(receptors),
            "A06准备输入组合数量不一致")
    require(isinstance(compound_statuses, dict) and set(compound_statuses) ==
            {row["compound_id"] for row in compounds}, "配体准备状态未覆盖完整成分范围")
    require(isinstance(receptor_statuses, dict) and set(receptor_statuses) ==
            {row["target_id"] for row in receptors}, "受体准备状态未覆盖完整选择范围")
    for row in list(compound_statuses.values()) + list(receptor_statuses.values()):
        require(isinstance(row, dict) and row.get("state") in ("ready", "NA")
                and isinstance(row.get("reason_zh"), str)
                and (row["state"] == "ready" or bool(row["reason_zh"].strip())),
                "准备状态须逐项记录ready或带原因的NA")
    pairs = []
    for compound in compounds:
        for receptor in receptors:
            ligand = compound_statuses[compound["compound_id"]]
            target = receptor_statuses[receptor["target_id"]]
            reasons = [row["reason_zh"] for row in (ligand, target) if row["state"] == "NA"]
            pairs.append({"compound_id": compound["compound_id"], "target_id": receptor["target_id"],
                          "state": "NA" if reasons else "ready", "score": None,
                          "reason_zh": "；".join(reasons), "input_key": packet["input_key"]})
    require(len(pairs) == packet["pair_count"], "准备组合数量与绑定范围不一致")
    return pairs
