"""新版A06共晶参考选择的只读清单与Workflow写入口。"""

from copy import deepcopy

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock

VERSION = "A06.plan_reference_review.1"


def _context(workflow, sid):
    """只读取当前新版准备的第二版事实包，拒绝跨批次来源。"""
    from .plan_pockets import context

    data = context(workflow, sid)
    home = workflow.location(sid)
    return data, home


def info(workflow, sid):
    """从同批mmCIF列出可选共晶参考；GET不联网、不准备、不写入。"""
    empty = {"supported": False, "enabled": False, "items": [],
             "execution_available": False,
             "reason_zh": "请先完成新版A06准备，才能核查共晶参考"}
    manifest = workflow.load(sid)
    if manifest.get("trashed"):
        return dict(empty, reason_zh="回收站研究只读")
    current = manifest.get("current", {}).get("A06_PREP")
    if not current:
        return empty
    try:
        data, home = _context(workflow, sid)
        from science_modules.a06.reference_candidates import discover

        candidates = discover(home, data["source_fact"]["connection"])
    except (ValueError, KeyError, TypeError) as error:
        return dict(empty, enabled=False, supported=True, reason_zh=str(error),
                    expected_preparation_run_id=current)
    rows = []
    for target in data["source_fact"]["receptors"]:
        values = [deepcopy(row) for row in candidates if row["target_id"] == target["target_id"]]
        rows.append({"target_id": target["target_id"], "symbol": target["symbol"],
                     "state": target.get("state"), "options": values})
    saved = []
    for entry in manifest.get("analysis_plan_a06_reference_records", []):
        try:
            record = read_json(verified_file(home, entry["decision"]))
            verified_file(home, record["packet"])
            if record["study_id"] == sid and record["expected_preparation_run_id"] == current:
                saved.append(record)
        except (ValueError, KeyError):
            continue
    return {"supported": True, "enabled": True,
            "reason_zh": "共晶参考仅作为明确选择的结构证据，仍须实际准备与重对接质控",
            "expected_input_id": data["input_record"]["input_id"],
            "expected_preparation_run_id": current,
            "source_preparation_run_id": data["source_run"]["run_id"],
            "items": rows, "execution_available": False,
            "saved_reviews": saved[-1:]}


def validate(workflow, sid, payload):
    """核对请求编号、同批输入和候选稳定键；不运行科学工具。"""
    from science_modules.a06.reference_review_contract import validate_request
    validate_request(payload)
    data, home = _context(workflow, sid)
    require(payload["expected_preparation_run_id"] == data["current_run"]["run_id"],
            "准备版本已更新，请刷新")
    require(payload["expected_input_id"] == data["input_record"]["input_id"],
            "准备输入或上游复核已更新，请刷新")
    from science_modules.a06.reference_candidates import validate_choices

    validate_choices(home, data["source_fact"]["connection"], payload["choices"])
    for entry in workflow.load(sid).get("analysis_plan_a06_reference_records", []):
        record = read_json(verified_file(home, entry["decision"]))
        if record["request"]["request_id"] == payload["request_id"]:
            require(record["request_hash"] == fingerprint(payload),
                    "共晶参考请求编号已用于其他内容，请刷新")
            require(record["expected_preparation_run_id"] == data["current_run"]["run_id"],
                    "该请求已绑定其他准备版本")
            return {"repeated": True, "review_id": record["review_id"],
                    "summary": record["summary"]}
    return {"repeated": False}


def publish(workflow, sid, payload, packet):
    """锁内归档后台已完成的参考证据；不改变current或reviews。"""
    from science_modules.a06.reference_review_contract import validate_request
    validate_request(payload)
    request_hash = fingerprint(payload)
    data, home = _context(workflow, sid)
    require(payload["expected_preparation_run_id"] == data["current_run"]["run_id"] and
            payload["expected_input_id"] == data["input_record"]["input_id"],
            "准备版本或输入已更新，请重新核查")
    from science_modules.a06.reference_candidates import validate_choices

    validate_choices(home, data["source_fact"]["connection"], payload["choices"])
    folder = (home / packet["folder"]).resolve()
    require(folder.is_relative_to(home) and folder.is_dir(), "参考证据目录不属于当前研究")
    packet_path = folder / "packet.json"
    require(packet.get("folder") == packet_path.parent.relative_to(home).as_posix(),
            "参考证据包路径不一致")
    for ref in packet.get("files", []):
        verified_file(home, ref)
    for old_entry in workflow.load(sid).get("analysis_plan_a06_reference_records", []):
        old = read_json(verified_file(home, old_entry["decision"]))
        if old["request"]["request_id"] == payload["request_id"]:
            require(old["request_hash"] == request_hash, "共晶参考请求编号已用于其他内容")
            return {"review": old, "created": False}
    require(packet["schema_version"] == VERSION and packet["study_id"] == sid and
            packet["expected_preparation_run_id"] == data["current_run"]["run_id"] and
            packet["input_id"] == data["input_record"]["input_id"] and
            packet["choices"] == payload["choices"], "参考证据包与当前请求不一致")
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        current = manifest.get("current", {}).get("A06_PREP")
        require(current == data["current_run"]["run_id"] and workflow.active(manifest, current),
                "当前准备已更新或失效，请刷新")
        review = {"schema_version": VERSION, "study_id": sid, "review_id": new_id("refreview"),
                  "created_at": now(), "request": deepcopy(payload), "request_hash": request_hash,
                  "expected_preparation_run_id": current,
                  "source_preparation_run_id": data["source_run"]["run_id"],
                  "source_preparation_packet": data["source_packet_ref"],
                  "summary": packet["summary"], "packet": file_record(home, packet_path, "reference_review_packet"),
                  "state": "evidence_ready" if packet["summary"]["ready_count"] else "NA"}
        path = home / "decisions/analysis_plans/a06_reference_reviews" / (review["review_id"] + ".json")
        write_json(path, review)
        review_ref = file_record(home, path, "a06_reference_review")
        manifest.setdefault("analysis_plan_a06_reference_records", []).append(
            {"decision": review_ref, "run_id": current})
        workflow.save(manifest)
    return {"review": review, "created": True}
