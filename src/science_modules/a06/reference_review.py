"""新版A06共晶参考选择的科学复核；只准备明确选择，不计算研究组合。"""

from copy import deepcopy
import shutil
from pathlib import Path

from contracts import require
from storage import file_record, write_json
from .reference_candidates import validate_choices
from .plan_reference_evidence import prepare_selected, validate_ready, VERSION as EVIDENCE_VERSION
from .reference_review_contract import validate_request

VERSION = "A06.plan_reference_review.1"


def run(workflow, sid, payload, tools, progress):
    """从当前准备事实包复核选择，结果以独立证据包追加归档。"""
    from modulea.core.plan_pockets import context

    validate_request(payload)
    data = context(workflow, sid)
    require(payload["expected_preparation_run_id"] == data["current_run"]["run_id"] and
            payload["expected_input_id"] == data["input_record"]["input_id"],
            "准备版本或输入已更新，请刷新")
    home = workflow.location(sid)
    connection = data["source_fact"]["connection"]
    validate_choices(home, connection, payload["choices"])
    config = data["source_run"]["config"]
    require(config.get("version") == "A06.plan_preparation.2", "参考复核来源不是第二版准备")
    folder = home / "runs/A06_PREP" / data["current_run"]["run_id"] / "reference_review" / payload["request_id"]
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    for index, choice in enumerate(payload["choices"], 1):
        progress("复核共晶参考：" + choice["target_id"])
        target = folder / (str(index) + "_" + choice["target_id"].replace(":", "_"))
        result = prepare_selected(home, connection, choice, target, tools, config, progress)
        if result["state"] == "ready":
            validate_ready(home, connection, result, config)
        results.append(result)
    code_root = Path(__file__).resolve().parent
    for name in ("reference_review.py", "reference_review_contract.py", "plan_reference_evidence.py",
                 "reference_candidates.py", "reference_prepare.py"):
        target = folder / "code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(code_root / name, target)
    files = [file_record(home, path, "reference_review_code")
             for path in (folder / "code").rglob("*") if path.is_file()]
    for result in results:
        files.extend(result.get("evidence", {}).get("files", []))
    files = list({item["path"]: item for item in files}.values())
    summary = {"choice_count": len(results),
               "ready_count": sum(r["state"] == "ready" for r in results),
               "na_count": sum(r["state"] != "ready" for r in results),
               "scored_pairs": 0, "execution_available": False,
               "handoff_blocked": True,
               "message_zh": "共晶参考证据已独立核查；尚未纳入批量评分或模块批准"}
    packet = {"schema_version": VERSION, "evidence_version": EVIDENCE_VERSION,
              "study_id": sid, "input_id": data["input_record"]["input_id"],
              "expected_preparation_run_id": data["current_run"]["run_id"],
              "source_preparation_run_id": data["source_run"]["run_id"],
              "request_id": payload["request_id"], "choices": deepcopy(payload["choices"]),
              "config": config, "results": results, "summary": summary,
              "folder": folder.relative_to(home).as_posix(), "files": files}
    packet_path = folder / "packet.json"
    write_json(packet_path, packet)
    packet["files"] = files
    write_json(packet_path, packet, replace=True)
    result = workflow.publish_analysis_plan_a06_reference_review(sid, payload, packet)
    result["summary"] = summary
    return result
