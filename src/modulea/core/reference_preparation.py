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


def qualification(workflow, sid):
    """只读复算新版准备是否具备进入人工整体复核的资料条件。"""
    manifest = workflow.load(sid)
    current = manifest.get("current", {}).get("A06_PREP")
    base = {"supported": False, "enabled": False, "qualified": False,
            "can_enter_review": False, "execution_available": False,
            "scored_pairs": None, "blockers": []}
    if not current:
        return dict(base, reason_zh="当前没有新版A06准备")
    run = workflow.run(manifest, current)
    if run.get("config", {}).get("version") != VERSION:
        return dict(base, reason_zh="当前准备尚未绑定共晶参考证据", current_run_id=current)
    result = workflow.result(manifest, current)
    value = dict(base, supported=True, enabled=True, current_run_id=current,
                 summary=result.get("summary") if result else None)
    blockers = value["blockers"]
    if manifest.get("trashed"):
        blockers.append("回收站研究只读")
    if not workflow.active(manifest, current):
        blockers.append("准备运行或上游复核已失效")
    if not result or result.get("outcome") != "success":
        blockers.append("新版准备尚未完整成功归档")
        return dict(value, reason_zh="；".join(blockers))
    summary = result.get("summary", {})
    value["scored_pairs"] = summary.get("scored_pairs")
    if summary.get("handoff_blocked") is not True:
        blockers.append("准备结果未保持handoff_blocked阻断")
    if summary.get("scored_pairs") != 0:
        blockers.append("准备结果已经包含评分组合")
    try:
        packet_ref = result["tables"]["preparation_packet"][0]
        fact = read_json(verified_file(workflow.location(sid), packet_ref))
        require(fact["schema_version"] == VERSION and fact["study_id"] == sid,
                "参考准备事实包版本或研究归属不一致")
        for ref in fact["files"] + [run["inputs"]["base_preparation_result"],
                                     run["inputs"]["reference_packet"],
                                     run["inputs"]["reference_review"]]:
            verified_file(workflow.location(sid), ref)
        review_packet = read_json(verified_file(workflow.location(sid), run["inputs"]["reference_packet"]))
        if review_packet.get("summary", {}).get("scored_pairs") != 0:
            blockers.append("参考核查包包含评分结果")
        if review_packet.get("summary", {}).get("handoff_blocked") is not True:
            blockers.append("参考核查包未保持阻断")
        base_result = read_json(verified_file(workflow.location(sid), run["inputs"]["base_preparation_result"]))
        if base_result.get("study_id") != sid or base_result.get("outcome") != "success":
            blockers.append("原准备结果归属或状态不一致")
        value["checked_files"] = len(fact["files"])
    except (ValueError, KeyError, TypeError) as error:
        blockers.append(str(error))
    qualified = not blockers
    return dict(value, qualified=qualified, can_enter_review=False,
                reason_zh="已核对归档完整性；当前版本仍阻断正式整体复核通过和评分" if qualified
                else "；".join(blockers))


def scoring_readiness(workflow, sid):
    """只读核对正式评分闸门；任何条件不足都保持不可执行。"""
    check = qualification(workflow, sid)
    value = {"supported": check["supported"], "enabled": check["supported"],
             "scoring_allowed": False, "execution_available": False,
             "current_run_id": check.get("current_run_id"),
             "blockers": list(check.get("blockers", [])),
             "reason_zh": "正式评分仍不可启动"}
    if not check["supported"]:
        value["blockers"].append("当前没有可核对的新版绑定准备")
        return value
    manifest = workflow.load(sid)
    current = manifest.get("current", {}).get("A06_PREP")
    if not workflow.approved(manifest, current):
        value["blockers"].append("A06_PREP尚未完成人工整体复核通过")
    summary = check.get("summary") or {}
    if summary.get("handoff_blocked") is True:
        value["blockers"].append("当前准备仍处于handoff_blocked阻断状态")
    if summary.get("scored_pairs") != 0:
        value["blockers"].append("当前准备已经包含评分组合，不能重复启动")
    value["blockers"].append("新版评分执行入口尚未接通")
    value["reason_zh"] = "；".join(value["blockers"])
    return value


def validate(workflow, sid, payload):
    """同源预检及重复请求检查，工具复核在后台再次执行。"""
    from science_modules.a06.reference_preparation_contract import validate_request

    validate_request(payload)
    manifest = workflow.load(sid)
    require(not manifest.get("trashed"), "回收站研究只读")
    for entry in manifest.get("analysis_plan_a06_reference_preparation_records", []):
        old = read_json(verified_file(workflow.location(sid), entry["decision"]))
        if old["request"]["request_id"] == payload["request_id"]:
            require(old["study_id"] == sid and old["request_hash"] == fingerprint(payload),
                    "参考准备请求编号已用于其他内容，请刷新")
            require(manifest["current"].get("A06_PREP") == entry["run_id"] and
                    workflow.active(manifest, entry["run_id"]) and
                    workflow.result(manifest, entry["run_id"]) is not None,
                    "参考准备已有后续版本或尚未完整归档，请刷新")
            current_input = workflow.analysis_plan_info(sid).get("a06_preparation_input")
            require(current_input and current_input["input_id"] == payload["expected_input_id"],
                    "准备输入或上游复核已更新，请刷新")
            return {"repeated": True, "run_id": entry["run_id"]}
    data = _base(workflow, sid)
    require(payload["expected_input_id"] == data["input_record"]["input_id"] and
            payload["expected_preparation_run_id"] == data["current_run"]["run_id"],
            "准备版本或输入已更新，请刷新")
    record, packet, _ = _review(workflow, sid, data, payload["expected_review_id"])
    require(packet["summary"]["scored_pairs"] == 0 and packet["summary"]["handoff_blocked"] is True,
            "参考证据包已包含评分或解除阻断标记，不能绑定")
    return {"repeated": False, "review_id": record["review_id"]}


def publish(workflow, sid, payload):
    """后台科学进程调用实际发布器；接口进程不导入科学依赖。"""
    from science_modules.a06.reference_preparation import publish as scientific_publish
    return scientific_publish(workflow, sid, payload)


def validate_v2(workflow, sid, payload):
    """只读预检新版本请求及幂等；科学子进程仍重新核验全部证据。"""
    from science_modules.a06.reference_preparation_contract import validate_request
    validate_request(payload)
    manifest = workflow.load(sid)
    require(not manifest.get('trashed'), '回收站研究只读')
    for entry in manifest.get('analysis_plan_a06_reference_preparation_v2_records', []):
        old = read_json(verified_file(workflow.location(sid), entry['decision']))
        if old['request']['request_id'] == payload['request_id']:
            require(old['study_id'] == sid and old['request_hash'] == fingerprint(payload), '请求编号已用于其他内容')
            require(manifest.get('current', {}).get('A06_PREP') == entry['run_id'] and
                    workflow.active(manifest, entry['run_id']) and workflow.result(manifest, entry['run_id']),
                    '参考准备已有后续版本或尚未完整归档，请刷新')
            current_input = workflow.analysis_plan_info(sid).get('a06_preparation_input')
            require(current_input and current_input['input_id'] == payload['expected_input_id'], '准备输入已更新，请刷新')
            return {'repeated': True, 'run_id': entry['run_id']}
    data = _base(workflow, sid)
    require(payload['expected_input_id'] == data['input_record']['input_id'] and
            payload['expected_preparation_run_id'] == data['current_run']['run_id'], '准备或输入已更新，请刷新')
    record, packet, _ = _review(workflow, sid, data, payload['expected_review_id'])
    require(packet['summary']['scored_pairs'] == 0 and packet['summary']['handoff_blocked'] is True,
            '参考证据包不符合评分阻断要求')
    return {'repeated': False, 'review_id': record['review_id']}


def info_v2(workflow, sid):
    """只读显示新版准备是否已经归档，不运行科学复算。"""
    manifest = workflow.load(sid)
    current = manifest.get('current', {}).get('A06_PREP')
    if current and workflow.run(manifest, current)['config'].get('version') == 'A06.plan_reference_preparation.2':
        result = workflow.result(manifest, current)
        active = workflow.active(manifest, current)
        return {'supported': True, 'enabled': False, 'state': 'bound' if result and active else 'stale',
                'expected_preparation_run_id': current, 'summary': result['summary'] if result else None,
                'execution_available': False, 'reason_zh': '参考资格已复算归档，评分仍关闭' if result and active else '准备已失效或未完整归档'}
    return info(workflow, sid)

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
