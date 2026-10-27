"""新版预测口袋证据核查与决定契约；不联网、不运行准备或评分。"""

from copy import deepcopy
import re

from contracts import fingerprint, require, safe_id
from storage import verified_file
from .two_pass import pocket_key, assess_attempt

VERSION = "A06.plan_pocket_review.1"
PREPARATION_VERSION = "A06.plan_preparation.3"


def validate_request(payload):
    """客户端只能选已归档口袋，不接受科学状态、参数或任意文件。"""
    fields = {"request_id", "expected_input_id", "expected_preparation_run_id",
              "reviewer", "note", "confirmed", "decisions"}
    require(isinstance(payload, dict) and set(payload) == fields, "口袋核查字段不完整或含不支持选项")
    safe_id(payload["request_id"], "pocketreq")
    safe_id(payload["expected_input_id"], "input")
    safe_id(payload["expected_preparation_run_id"], "run")
    require(payload["confirmed"] is True, "请明确确认本次预测口袋采用决定")
    require(all(isinstance(payload[k], str) and 0 < len(payload[k].strip()) <= 2000
                for k in ("reviewer", "note")), "请填写实际核查人和依据")
    require(isinstance(payload["decisions"], list), "口袋决定必须为完整受体清单")
    for row in payload["decisions"]:
        require(isinstance(row, dict) and set(row) == {"target_id", "pocket_key"}, "口袋决定字段不合法")
        require(isinstance(row["target_id"], str) and re.fullmatch(r"HGNC:[0-9]+", row["target_id"]), "口袋受体身份无效")
        require(row["pocket_key"] is None or isinstance(row["pocket_key"], str)
                and re.fullmatch(r"[0-9a-f]{64}", row["pocket_key"]), "口袋证据键无效")
    return payload


def eligible_trace(home, trace, target, config):
    """将实际两次CSV、输入坐标、受体文件与口袋键逐项核对。"""
    from docking_p2rank import _prediction_rows
    from docking_formal import _input_atoms
    from .plan_quality_engine_v2 import prediction_box
    spec, ev = trace["candidate"]["spec"], trace["evidence"]
    require(spec.get("source_type") == "experimental" and spec.get("pocket") == "p2rank",
            "此入口仅采用已核查实验结构上的预测口袋")
    identity = ev.get("identity", {})
    require(identity.get("target_id") == target["target_id"] and
            identity.get("uniprot") == spec.get("uniprot") and
            identity.get("chains") == spec.get("chains") and
            identity.get("species") == 9606 and identity.get("polymer_type") == "Protein" and
            identity.get("sequence_matches") is True and ev.get("structure_id") == spec.get("pdb_id"),
            "口袋结构身份、链或人类序列未核对一致")
    require(ev.get("receptor_ready") is True and ev.get("pocket_complete") is True and
            ev.get("environment_resolved") is True, "受体准备、口袋完整性或环境尚未通过")
    _input_atoms(verified_file(home, ev["receptor"]).read_text("ascii"))
    verified_file(home, trace["candidate"]["cif"])
    predicted = ev.get("predicted_pocket", {})
    records = [ref for ref in predicted.get("files", []) if ref["role"] == "p2rank_prediction"]
    require(len(records) == 2, "口袋缺少两次原始预测文件")
    raw = [_prediction_rows(verified_file(home, ref))[0] for ref in records]
    keys = ("rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids")
    shared = {k: raw[0][k] for k in keys}
    require(int(shared["rank"]) == 1 and shared == {k: raw[1][k] for k in keys}, "两次首位口袋不一致")
    pocket = ev.get("pocket", {})
    require(pocket.get("rank") == 1 and pocket.get("runs") == [shared, shared] and
            pocket.get("mapped_indices") == sorted(shared["residue_ids"].split()) and
            pocket.get("pocket_key") == pocket_key(spec, pocket), "口袋事实与原始预测文件不一致")
    box = prediction_box(verified_file(home, predicted["input_pdb"]).read_text("ascii"),
                         shared, config["box_padding"])
    require(ev.get("box") == box, "口袋搜索盒与方案及输入坐标不一致")
    return {"pocket_key": pocket["pocket_key"], "pdb_id": spec["pdb_id"],
            "uniprot": spec["uniprot"], "chains": deepcopy(spec["chains"]),
            "prediction": shared, "mapped_residues": deepcopy(pocket["mapped_indices"]),
            "box": box, "prediction_files": deepcopy(records),
            "receptor_file": deepcopy(ev["receptor"]),
            "eligible": True, "reason_zh": "结构及两次首位预测证据一致；采用后仅作探索"}


def options(home, packet):
    """只读形成完整受体清单；不把资格检查保存为人工确认。"""
    items = []
    for row in packet["receptors"]:
        choices = []
        for trace in row["attempts"]:
            if trace.get("candidate", {}).get("spec", {}).get("pocket") != "p2rank":
                continue
            try:
                value = eligible_trace(home, trace, row, packet["config"])
            except (ValueError, KeyError, TypeError, IndexError) as error:
                value = {"pocket_key": trace.get("evidence", {}).get("pocket", {}).get("pocket_key"),
                         "pdb_id": trace["candidate"]["spec"].get("pdb_id"),
                         "eligible": False, "reason_zh": str(error)}
            choices.append(value)
        items.append({"target_id": row["target_id"], "symbol": row["symbol"],
                      "state": row["state"], "reason_zh": row["reason_zh"], "options": choices})
    return items


def validate_choices(home, source, payload):
    """决定须按原顺序覆盖全部受体，选择不能跨结构或补位。"""
    validate_request(payload)
    require([r["target_id"] for r in payload["decisions"]] ==
            [r["target_id"] for r in source["receptors"]], "口袋决定未按顺序覆盖固定受体范围")
    selected = {}
    for original, decision in zip(source["receptors"], payload["decisions"]):
        key = decision["pocket_key"]
        if key is None:
            continue
        matches = [trace for trace in original["attempts"]
                   if trace.get("evidence", {}).get("pocket", {}).get("pocket_key") == key]
        require(len(matches) == 1, "口袋键不能唯一对应此受体的归档结构")
        eligible_trace(home, matches[0], original, source["config"])
        selected[original["target_id"]] = matches[0]
    return selected


def derive(home, source, decision):
    """只修改被明确采用的预测口袋，失败和未选项原样保留。"""
    payload = decision["request"]
    require(decision["request_hash"] == fingerprint(payload), "口袋决定请求指纹不一致")
    selected = validate_choices(home, source, payload)
    output = deepcopy(source["receptors"])
    for original, row in zip(source["receptors"], output):
        trace = selected.get(row["target_id"])
        if trace is None:
            continue
        index = original["attempts"].index(trace)
        adopted = row["attempts"][index]
        pocket = adopted["evidence"]["pocket"]
        pocket["confirmation"] = {"confirmed": True, "pocket_key": pocket["pocket_key"],
            "reviewer": payload["reviewer"].strip(), "note": payload["note"].strip(),
            "decision_id": decision["decision_id"], "created_at": decision["created_at"]}
        assessment = assess_attempt(adopted["candidate"]["spec"], adopted["evidence"], row, 2)
        require(assessment["state"] == "ready" and assessment["quality"] == "探索", "所选口袋仍未满足探索准备规则")
        # 原第二版等待确认的提示保存在来源说明，避免修订事实同时标记ready和待确认。
        if adopted["evidence"].get("error_zh"):
            adopted["evidence"]["source_preparation_note_zh"] = adopted["evidence"].pop("error_zh")
        adopted["assessment"] = assessment
        row.update(state="ready", quality="探索", reason_zh=assessment["reason_zh"])
    return output
