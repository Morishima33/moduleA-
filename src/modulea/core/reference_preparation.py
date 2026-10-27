"""新版A06参考证据绑定准备版本的只读预检与Workflow写入口。"""

from copy import deepcopy

from contracts import fingerprint, require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock

VERSION = "A06.plan_reference_preparation.1"
CONFIG = {"version": VERSION, "reference_evidence_required": True,
          "batch_docking_allowed": False, "automatic_approval": False,
          "execution_available": False, "scored_pairs": 0, "handoff_blocked": True}


def _base(workflow, sid):
    """读取当前第二或第三版准备，参考证据绑定只允许从当前版本派生。"""
    from .plan_pockets import context

    data = context(workflow, sid)
    require(data["current_run"]["config"].get("version") in
            ("A06.plan_preparation.2", "A06.plan_preparation.3"),
            "当前准备版本不支持参考证据绑定")
    return data


def _review(workflow, sid, data, review_id):
    """按当前准备指针查找并逐字节核验参考证据决定。"""
    home = workflow.location(sid)
    for entry in workflow.load(sid).get("analysis_plan_a06_reference_records", []):
        record = read_json(verified_file(home, entry["decision"]))
        if record.get("review_id") != review_id:
            continue
        require(record.get("study_id") == sid and
                record.get("expected_preparation_run_id") == data["current_run"]["run_id"],
                "参考核查不属于当前准备版本")
        packet = verified_file(home, record["packet"])
        return record, read_json(packet), entry["decision"]
    raise ValueError("未找到当前准备版本的参考证据核查")


def info(workflow, sid):
    """只读返回当前参考证据绑定状态；不自动创建新准备。"""
    manifest = workflow.load(sid)
    current = manifest.get("current", {}).get("A06_PREP")
    if not current:
        return {"supported": False, "enabled": False, "execution_available": False,
                "reason_zh": "请先完成新版A06准备"}
    run = workflow.run(manifest, current)
    if run["config"].get("version") == VERSION:
        result = workflow.result(manifest, current)
        return {"supported": True, "enabled": False, "execution_available": False,
                "expected_preparation_run_id": current,
                "state": "bound", "summary": result["summary"] if result else None,
                "reason_zh": "参考证据已绑定新版准备；仍待A06_PREP整体复核，未开放评分"}
    if run["config"].get("version") not in ("A06.plan_preparation.2", "A06.plan_preparation.3"):
        return {"supported": False, "enabled": False, "execution_available": False,
                "reason_zh": "当前准备版本不支持参考证据绑定"}
    data = _base(workflow, sid)
    reviews = []
    home = workflow.location(sid)
    for entry in manifest.get("analysis_plan_a06_reference_records", []):
        try:
            record = read_json(verified_file(home, entry["decision"]))
            if record.get("expected_preparation_run_id") == current:
                verified_file(home, record["packet"])
                reviews.append(record)
        except (ValueError, KeyError):
            continue
    return {"supported": True, "enabled": bool(reviews), "execution_available": False,
            "expected_input_id": data["input_record"]["input_id"],
            "expected_preparation_run_id": current,
            "source_preparation_run_id": data["source_run"]["run_id"],
            "reviews": reviews[-1:],
            "reason_zh": "选择并核查共晶参考后，可将证据绑定到新的准备版本；仍不启动批量评分" if reviews
            else "请先完成共晶参考选择与证据核查"}


def validate(workflow, sid, payload):
    """同源预检及重复请求检查，工具复核在后台再次执行。"""
    from science_modules.a06.reference_preparation_contract import validate_request

    validate_request(payload)
    data = _base(workflow, sid)
    require(payload["expected_input_id"] == data["input_record"]["input_id"] and
            payload["expected_preparation_run_id"] == data["current_run"]["run_id"],
            "准备版本或输入已更新，请刷新")
    record, packet, _ = _review(workflow, sid, data, payload["expected_review_id"])
    require(packet["summary"]["scored_pairs"] == 0 and packet["summary"]["handoff_blocked"] is True,
            "参考证据包已包含评分或解除阻断标记，不能绑定")
    for entry in workflow.load(sid).get("analysis_plan_a06_reference_preparation_records", []):
        old = read_json(verified_file(workflow.location(sid), entry["decision"]))
        if old["request"]["request_id"] == payload["request_id"]:
            require(old["request_hash"] == fingerprint(payload),
                    "参考准备请求编号已用于其他内容，请刷新")
            return {"repeated": True, "run_id": old["run_id"]}
    return {"repeated": False, "review_id": record["review_id"]}


def publish(workflow, sid, payload):
    """后台科学进程调用实际发布器；接口进程不导入科学依赖。"""
    from science_modules.a06.reference_preparation import publish as scientific_publish
    return scientific_publish(workflow, sid, payload)

def validator(root, previous):
    """复算参考绑定事实，其他准备版本沿用原校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("version") != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        home = __import__("pathlib").Path(root) / "studies" / run["study_id"]
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
        for ref in fact["files"] + [run["inputs"]["base_preparation_run"], run["inputs"]["reference_packet"]]:
            verified_file(home, ref)
        require(summary["reference_review_id"] == read_json(verified_file(home, run["inputs"]["reference_review"]))["review_id"] and
                summary["scored_pairs"] == 0 and summary["handoff_blocked"] is True,
                "参考准备摘要解除评分阻断或未绑定核查")
    return check
