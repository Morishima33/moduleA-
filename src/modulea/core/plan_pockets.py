"""新版A06口袋决定的只读上下文；运行和决定写入由Workflow公开入口完成。"""

from contracts import fingerprint, require
from storage import read_json, verified_file


def context(workflow, sid):
    """按manifest索引解析当前准备及原第二版证据，拒绝跨批次混用。"""
    manifest = workflow.load(sid)
    require(not manifest.get("trashed"), "回收站研究只读")
    current_id = manifest["current"].get("A06_PREP")
    require(current_id and workflow.active(manifest, current_id), "A06准备已更新或已失效，请刷新")
    current_run = workflow.run(manifest, current_id)
    version = current_run["config"].get("version")
    require(version in ("A06.plan_preparation.2", "A06.plan_preparation.3"), "当前准备版本不支持新版口袋核查")
    current_result = workflow.result(manifest, current_id)
    require(current_result is not None or version == "A06.plan_preparation.3", "当前准备尚未完整归档")
    if version == "A06.plan_preparation.3":
        source_ref = current_run["inputs"]["source_preparation_run"]
        source_run = read_json(verified_file(workflow.location(sid), source_ref))
        source_id = source_run["run_id"]
    else:
        source_run, source_id = current_run, current_id
    source_index = manifest["runs"].get(source_id)
    require(source_index and source_index.get("result_file"), "第二版准备来源缺失")
    source_run_ref = source_index["run_file"]
    source_result_ref = source_index["result_file"]
    source_run = workflow.run(manifest, source_id)
    require(source_run["study_id"] == sid and source_run["module_id"] == "A06_PREP" and
            source_run["config"].get("version") == "A06.plan_preparation.2", "口袋来源不是本研究第二版准备")
    source_result = workflow.result(manifest, source_id)
    refs = source_result["tables"].get("preparation_packet", [])
    require(len(refs) == 1 and refs[0]["path"] ==
            f"runs/A06_PREP/{source_id}/plan_preparation/packet.json", "口袋来源事实包归属不符")
    home = workflow.location(sid)
    source_fact = read_json(verified_file(home, refs[0]))
    input_ref = source_run["inputs"]["a06_plan_input"]
    input_record = read_json(verified_file(home, input_ref))
    current_input = workflow.analysis_plan_info(sid).get("a06_preparation_input")
    require(current_input and current_input == input_record, "准备输入或选择复核已更新，请刷新")
    require(source_fact["study_id"] == sid and source_fact["input_key"] == input_record["packet"]["input_key"] and
            current_run["parent_runs"] == source_run["parent_runs"] and
            current_run["parent_review_ids"] == source_run["parent_review_ids"], "口袋准备与当前输入批次不一致")
    if version == "A06.plan_preparation.3":
        require(current_run["inputs"]["source_preparation_run"] == source_run_ref and
                current_run["inputs"]["source_preparation_result"] == source_result_ref and
                current_run["inputs"]["source_preparation_packet"] == refs[0], "修订准备与原第二版指纹不一致")
    return {"manifest": manifest, "current_run": current_run, "current_result": current_result,
            "source_run": source_run, "source_result": source_result, "source_fact": source_fact,
            "source_run_ref": source_run_ref, "source_result_ref": source_result_ref,
            "source_packet_ref": refs[0], "input_ref": input_ref, "input_record": input_record}


def info(workflow, sid):
    """只读清单不联网或写入；旧研究及无准备运行时提供明确状态。"""
    manifest = workflow.load(sid)
    current = manifest["current"].get("A06_PREP")
    empty = {"supported": False, "enabled": False, "items": [], "execution_available": False,
             "reason_zh": "请先完成新版A06第二版准备，才能核查预测口袋"}
    if manifest.get("trashed"):
        return dict(empty, reason_zh="回收站研究只读")
    if not current or workflow.run(manifest, current)["config"].get("version") not in (
            "A06.plan_preparation.2", "A06.plan_preparation.3"):
        return empty
    data = context(workflow, sid)
    from science_modules.a06.plan_pockets import options
    items = options(workflow.location(sid), data["source_fact"])
    saved = None
    if data["current_result"] and data["current_run"]["inputs"].get("pocket_decision"):
        saved = read_json(verified_file(workflow.location(sid), data["current_run"]["inputs"]["pocket_decision"]))
    a00 = workflow.result(data["manifest"], data["input_record"]["packet"]["runs"]["A00"])["summary"]
    testing = data["manifest"].get("kind") == "contract_test" or a00.get("analysis_purpose") == "workflow_test"
    return {"supported": True, "enabled": True, "reason_zh": "确认仅采用预测位点作探索，不证明真实结合位点",
            "testing": testing, "study_label_zh": str(a00.get("formula", "")) + " · " + str(a00.get("disease", "")),
            "purpose_zh": "工作流测试研究；此处采用决定不作为真实研究结果" if testing else "当前研究的归档证据；位点采用仍须独立核查",
            "expected_input_id": data["input_record"]["input_id"],
            "expected_preparation_run_id": current,
            "source_preparation_run_id": data["source_run"]["run_id"],
            "items": items, "execution_available": False,
            "current_summary": data["current_result"]["summary"] if data["current_result"] else None,
            "saved_decisions": saved["request"]["decisions"] if saved else None,
            "previous_decision": data["current_run"]["inputs"].get("pocket_decision")}


def validate(workflow, sid, payload):
    """接口预检与重试幂等；最终发布仍在科学子进程再次核验。"""
    from science_modules.a06.plan_pockets import validate_request
    validate_request(payload)
    manifest = workflow.load(sid)
    require(not manifest.get("trashed"), "回收站研究只读")
    for entry in manifest.get("analysis_plan_a06_pocket_records", []):
        record = read_json(verified_file(workflow.location(sid), entry["decision"]))
        if record["request"]["request_id"] == payload["request_id"]:
            require(record["study_id"] == sid and record["request_hash"] == fingerprint(payload),
                    "口袋请求编号已用于其他内容，请刷新")
            current_input = workflow.analysis_plan_info(sid).get("a06_preparation_input")
            require(current_input and current_input["input_id"] == payload["expected_input_id"] and
                    manifest["current"].get("A06_PREP") == entry["run_id"] and workflow.active(manifest, entry["run_id"]),
                    "准备版本或输入已更新，请刷新")
            require(workflow.result(manifest, entry["run_id"]) is not None,
                    "上次核查未完整归档，请用新请求编号重试")
            return {"repeated": True, "run_id": entry["run_id"]}
    summary = info(workflow, sid)
    require(summary["enabled"] and summary["expected_input_id"] == payload["expected_input_id"] and
            summary["expected_preparation_run_id"] == payload["expected_preparation_run_id"],
            "准备版本或输入已更新，请刷新")
    require([r["target_id"] for r in payload["decisions"]] == [r["target_id"] for r in summary["items"]],
            "口袋决定未按顺序覆盖固定受体范围")
    for row, item in zip(payload["decisions"], summary["items"]):
        if row["pocket_key"] is not None:
            matches = [c for c in item["options"] if c["pocket_key"] == row["pocket_key"] and c["eligible"]]
            require(len(matches) == 1, "所选口袋不能唯一对应本受体的有效证据")
    return {"repeated": False}
