"""新版A06参考证据绑定准备版本；沿用原准备事实，不运行评分。"""

from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require
from storage import file_record, now, read_json, verified_file, write_json, write_lock

VERSION = "A06.plan_reference_preparation.1"
CONFIG = {"version": VERSION, "reference_evidence_required": True,
          "batch_docking_allowed": False, "automatic_approval": False,
          "execution_available": False, "scored_pairs": 0, "handoff_blocked": True}


def publish(workflow, sid, payload):
    """锁内生成新准备版本，保留当前准备、参考包和逐件指纹。"""
    from modulea.core.reference_preparation import _base, _review
    from .reference_preparation_contract import validate_request

    validate_request(payload)
    data = _base(workflow, sid)
    home = workflow.location(sid)
    record, packet, review_ref = _review(workflow, sid, data, payload["expected_review_id"])
    require(payload["expected_input_id"] == data["input_record"]["input_id"] and
            payload["expected_preparation_run_id"] == data["current_run"]["run_id"],
            "准备版本或输入已更新，请重新绑定")
    require(packet["summary"]["scored_pairs"] == 0 and packet["summary"]["handoff_blocked"] is True,
            "参考证据包不符合评分阻断要求")
    manifest = workflow.load(sid)
    for entry in manifest.get("analysis_plan_a06_reference_preparation_records", []):
        old = read_json(verified_file(home, entry["decision"]))
        if old["request"]["request_id"] == payload["request_id"]:
            require(old.get("request_hash") == fingerprint(payload),
                    "参考准备请求编号已用于其他内容")
            return workflow.result(manifest, old["run_id"])
    base_run = data["current_run"]
    base_result = workflow.result(manifest, base_run["run_id"])
    require(base_result is not None, "当前准备尚未完整归档")
    inputs = {"base_preparation_run": manifest["runs"][base_run["run_id"]]["run_file"],
              "base_preparation_result": manifest["runs"][base_run["run_id"]]["result_file"],
              "reference_review": review_ref, "reference_packet": record["packet"],
              "a06_plan_input": data["input_ref"]}
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        require(manifest["current"].get("A06_PREP") == base_run["run_id"] and
                workflow.active(manifest, base_run["run_id"]), "当前准备已更新，请刷新")
        run = workflow._begin(manifest, "A06_PREP", inputs, CONFIG,
                              "将已核查共晶参考绑定新版准备资格；不评分")
        folder = home / "runs/A06_PREP" / run["run_id"] / "reference_preparation"
        folder.mkdir(parents=True, exist_ok=False)
        code_path = folder / "code" / "reference_preparation.py"
        code_path.parent.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).resolve()
        code_path.write_bytes(source.read_bytes())
        code_ref = file_record(home, code_path, "reference_preparation_code")
        fact = {"schema_version": VERSION, "study_id": sid,
                "base_preparation_run_id": base_run["run_id"],
                "base_preparation_result": inputs["base_preparation_result"],
                "reference_review": review_ref, "reference_packet": record["packet"],
                "input_id": data["input_record"]["input_id"],
                "files": [code_ref] + base_result["files"] + packet["files"] + [record["packet"]]}
        packet_path = folder / "packet.json"
        write_json(packet_path, fact)
        packet_ref = file_record(home, packet_path, "preparation_packet")
        summary = deepcopy(base_result["summary"])
        summary.update(reference_review_id=record["review_id"],
                       reference_ready_count=packet["summary"]["ready_count"],
                       reference_na_count=packet["summary"]["na_count"],
                       execution_available=False, scored_pairs=0, handoff_blocked=True,
                       message_zh="已绑定共晶参考证据；A06_PREP整体复核和批量评分仍关闭")
        tables = {"preparation_packet": [packet_ref], "reference_review": [review_ref],
                  "base_preparation": [inputs["base_preparation_result"]]}
        result = workflow._finish(manifest, run["run_id"], summary, tables, [], "success",
                                  attachments=fact["files"] + [packet_ref])
        decision = {"schema_version": VERSION, "study_id": sid, "run_id": run["run_id"],
                    "request": deepcopy(payload), "request_hash": fingerprint(payload),
                    "reference_review": review_ref,
                    "created_at": now()}
        decision_path = home / "decisions/analysis_plans/a06_reference_preparations" / (run["run_id"] + ".json")
        write_json(decision_path, decision)
        decision_ref = file_record(home, decision_path, "a06_reference_preparation")
        manifest.setdefault("analysis_plan_a06_reference_preparation_records", []).append(
            {"decision": decision_ref, "run_id": run["run_id"]})
        workflow.save(manifest)
        return result


def validator(root, previous):
    """复算参考绑定事实，其他准备版本沿用原校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("version") != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        require(run["config"] == CONFIG and outcome == "success" and anomalies == [],
                "参考准备版本配置或结果状态不一致")
        fact_ref = tables.get("preparation_packet", [])
        require(len(fact_ref) == 1 and fact_ref[0]["path"] ==
                f"runs/A06_PREP/{run['run_id']}/reference_preparation/packet.json",
                "参考准备事实包路径不属于当前运行")
        fact = read_json(verified_file(home, fact_ref[0]))
        require(fact["schema_version"] == VERSION and fact["study_id"] == run["study_id"] and
                fact["base_preparation_result"] == run["inputs"]["base_preparation_result"] and
                fact["reference_review"] == run["inputs"]["reference_review"],
                "参考准备事实与输入指纹不一致")
        for ref in fact["files"] + [run["inputs"]["base_preparation_run"],
                                     run["inputs"]["reference_packet"]]:
            verified_file(home, ref)
        review = read_json(verified_file(home, run["inputs"]["reference_review"]))
        review_packet = read_json(verified_file(home, run["inputs"]["reference_packet"]))
        require(summary["reference_review_id"] == review["review_id"] and
                review_packet["summary"]["scored_pairs"] == 0 and
                review_packet["summary"]["handoff_blocked"] is True and
                summary["scored_pairs"] == 0 and summary["handoff_blocked"] is True,
                "参考准备摘要解除评分阻断或未绑定核查")
    return check
