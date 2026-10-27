"""预测口袋决定生成第三版准备：复验原证据，不重新预测、准备或评分。"""

from copy import deepcopy
from pathlib import Path
import shutil

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from .plan_pockets import VERSION, PREPARATION_VERSION, validate_request, validate_choices, derive

CONFIG = {"version": PREPARATION_VERSION, "decision_version": VERSION,
          "batch_docking_allowed": False, "automatic_approval": False}
INPUT_FIELDS = {"a06_plan_input", "source_preparation_run", "source_preparation_result",
                "source_preparation_packet", "pocket_decision", "previous_preparation_run"}


def source_data(root, sid, inputs):
    """从归档复核第二版科学结果及其原始输入，不信任客户端状态。"""
    from .plan_preparation_v2 import validator as source_validator
    home = Path(root) / "studies" / sid
    require(set(inputs) == INPUT_FIELDS, "口袋准备输入字段不一致")
    source_run = read_json(verified_file(home, inputs["source_preparation_run"]))
    source_result = read_json(verified_file(home, inputs["source_preparation_result"]))
    safe_id(source_run["run_id"], "run")
    require(source_run["study_id"] == sid and source_run["module_id"] == "A06_PREP" and
            source_run["config"].get("version") == "A06.plan_preparation.2" and
            inputs["source_preparation_run"]["path"] == f"runs/A06_PREP/{source_run['run_id']}/run.json" and
            inputs["source_preparation_result"]["path"] == f"runs/A06_PREP/{source_run['run_id']}/result.json" and
            source_result["study_id"] == sid and source_result["run_id"] == source_run["run_id"] and
            source_result["artifact_id"] == source_run["artifact_id"], "口袋准备来源运行归属不一致")
    require(source_result["tables"].get("preparation_packet") == [inputs["source_preparation_packet"]] and
            source_run["inputs"]["a06_plan_input"] == inputs["a06_plan_input"], "口袋来源或方案文件指纹不一致")
    for ref in source_result["files"]:
        verified_file(home, ref)
    def unsupported(*args):
        raise ValueError("口袋准备来源版本不支持")
    source_validator(root, unsupported)(source_run, source_result["summary"], source_result["tables"],
                                        source_result["anomalies"], source_result["outcome"])
    source_fact = read_json(verified_file(home, inputs["source_preparation_packet"]))
    input_record = read_json(verified_file(home, inputs["a06_plan_input"]))
    decision = read_json(verified_file(home, inputs["pocket_decision"]))
    previous = read_json(verified_file(home, inputs["previous_preparation_run"]))
    require(previous["study_id"] == sid and previous["module_id"] == "A06_PREP" and
            previous["config"].get("version") in ("A06.plan_preparation.2", PREPARATION_VERSION) and
            previous["inputs"]["a06_plan_input"] == inputs["a06_plan_input"], "上一次准备不属于同批输入")
    if previous["config"]["version"] == "A06.plan_preparation.2":
        require(previous == source_run, "首次口袋核查来源不是原第二版准备")
    else:
        require(all(previous["inputs"][k] == inputs[k] for k in (
            "source_preparation_run", "source_preparation_result", "source_preparation_packet")),
            "修订口袋确认时来源批次已变化")
    require(decision["schema_version"] == VERSION and decision["study_id"] == sid and
            decision["source_preparation_run_id"] == source_run["run_id"] and
            decision["source_preparation_packet"] == inputs["source_preparation_packet"] and
            decision["source_preparation_result"] == inputs["source_preparation_result"] and
            decision["input_key"] == source_fact["input_key"] == input_record["packet"]["input_key"] and
            decision["request"]["expected_input_id"] == input_record["input_id"] and
            decision["request"]["expected_preparation_run_id"] == previous["run_id"],
            "口袋决定与研究、原始结构或准备批次不符")
    safe_id(decision["decision_id"], "pocketreview")
    require(inputs["pocket_decision"]["path"] ==
            f"decisions/analysis_plans/a06_pocket_reviews/{decision['decision_id']}.json", "口袋决定路径不一致")
    return source_run, source_result, source_fact, input_record, decision


def reports(home, source, input_packet, decision):
    """确认后的完整范围仍含NA、空评分和评分阻断。"""
    from .plan_preparation_v2 import reports as original_reports
    receptors = derive(home, source, decision)
    summary, tables = original_reports(input_packet, source["compounds"], receptors)
    summary.update(source_preparation_run_id=decision["source_preparation_run_id"],
                   adopted_pockets=sum(r["pocket_key"] is not None for r in decision["request"]["decisions"]),
                   message_zh="已归档本次预测口袋采用决定；探索准备仍待模块核查，未计算组合评分")
    return receptors, summary, tables


def validator(root, previous):
    """第三版逐件复核原第二版与决定，然后复算完整准备结果。"""
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("version") != PREPARATION_VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        require(run["config"] == CONFIG and outcome == "success" and anomalies == [], "第三版准备配置或结果不一致")
        home = Path(root) / "studies" / run["study_id"]
        source_run, source_result, source, input_record, decision = source_data(root, run["study_id"], run["inputs"])
        require(run["parent_runs"] == source_run["parent_runs"] and
                run["parent_review_ids"] == source_run["parent_review_ids"], "口袋准备上游或复核已变化")
        records = tables.get("preparation_packet", [])
        require(len(records) == 1 and records[0]["path"] ==
                f"runs/A06_PREP/{run['run_id']}/pocket_review/packet.json", "第三版准备事实包归属不符")
        fact = read_json(verified_file(home, records[0]))
        receptors, expected_summary, expected_tables = reports(home, source, input_record["packet"], decision)
        expected_tables["preparation_packet"] = records
        expected_tables["pocket_decision"] = [run["inputs"]["pocket_decision"]]
        require(summary == expected_summary and tables == expected_tables, "口袋准备摘要或组合与决定复算不一致")
        require(set(fact) == {"schema_version", "study_id", "input_key", "source_preparation_run_id",
                "decision", "compounds", "receptors", "files"} and
                fact["schema_version"] == PREPARATION_VERSION and fact["study_id"] == run["study_id"] and
                fact["input_key"] == source["input_key"] and
                fact["source_preparation_run_id"] == source_run["run_id"] and
                fact["decision"] == run["inputs"]["pocket_decision"] and
                fact["compounds"] == source["compounds"] and fact["receptors"] == receptors,
                "第三版准备事实与归档决定不一致")
        for ref in fact["files"]:
            verified_file(home, ref)
        require(all(ref in fact["files"] for ref in source_result["files"] + list(run["inputs"].values())),
                "第三版准备未完整保留来源和决定文件指纹")
    return check


def publish(workflow, sid, payload):
    """公开Workflow入口显式提交决定，锁内复核后追加科学运行。"""
    from modulea.core.plan_pockets import context
    from .plan_preparation_v2 import current_input
    validate_request(payload)
    request_hash = fingerprint(payload)
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        require(not manifest.get("trashed"), "回收站研究只读")
        for entry in manifest.get("analysis_plan_a06_pocket_records", []):
            old = read_json(verified_file(workflow.location(sid), entry["decision"]))
            require(old["study_id"] == sid and old["schema_version"] == VERSION, "口袋决定索引不一致")
            if old["request"]["request_id"] == payload["request_id"]:
                require(old["request_hash"] == request_hash, "口袋请求编号已用于其他内容，请刷新")
                current_input(workflow, sid, payload["expected_input_id"])
                require(manifest["current"].get("A06_PREP") == entry["run_id"] and workflow.active(manifest, entry["run_id"]),
                        "该口袋决定已有后续版本，请刷新")
                result = workflow.result(manifest, entry["run_id"])
                require(result is not None, "上次口袋核查未完整归档，请用新请求编号重试")
                return result
        data = context(workflow, sid)
        require(data["current_run"]["run_id"] == payload["expected_preparation_run_id"] and
                data["input_record"]["input_id"] == payload["expected_input_id"], "准备版本或输入已更新，请刷新")
        current_input(workflow, sid, payload["expected_input_id"])
        home = workflow.location(sid)
        validate_choices(home, data["source_fact"], payload)
        decision = {"schema_version": VERSION, "study_id": sid, "decision_id": new_id("pocketreview"),
                    "created_at": now(), "request": deepcopy(payload), "request_hash": request_hash,
                    "input_key": data["source_fact"]["input_key"],
                    "source_preparation_run_id": data["source_run"]["run_id"],
                    "source_preparation_packet": data["source_packet_ref"],
                    "source_preparation_result": data["source_result_ref"]}
        path = home / "decisions/analysis_plans/a06_pocket_reviews" / (decision["decision_id"] + ".json")
        write_json(path, decision)
        decision_ref = file_record(home, path, "a06_pocket_decision")
        inputs = {"a06_plan_input": data["input_ref"], "source_preparation_run": data["source_run_ref"],
                  "source_preparation_result": data["source_result_ref"], "source_preparation_packet": data["source_packet_ref"],
                  "pocket_decision": decision_ref,
                  "previous_preparation_run": manifest["runs"][payload["expected_preparation_run_id"]]["run_file"]}
        # 在建立新指针前重核原科学结果，缺证据不能通过确认补齐。
        source_data(workflow.root, sid, inputs)
        receptors, summary, tables = reports(home, data["source_fact"], data["input_record"]["packet"], decision)
        run = workflow._begin(manifest, "A06_PREP", inputs, CONFIG, "明确核查预测口袋，复用同批已归档准备，不评分")
        manifest.setdefault("analysis_plan_a06_pocket_records", []).append({"decision": decision_ref, "run_id": run["run_id"]})
        workflow.save(manifest)
        folder = home / "runs/A06_PREP" / run["run_id"] / "pocket_review"
        folder.mkdir(parents=True, exist_ok=False)
        code = Path(__file__).resolve().parent
        snapshots = []
        for name in ("plan_pockets.py", "plan_pocket_review.py"):
            target = folder / "code" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(code / name, target)
            snapshots.append(file_record(home, target, "pocket_review_code"))
        refs = data["source_result"]["files"] + list(inputs.values()) + snapshots
        refs = list({ref["path"]: ref for ref in refs}.values())
        fact = {"schema_version": PREPARATION_VERSION, "study_id": sid, "input_key": decision["input_key"],
                "source_preparation_run_id": data["source_run"]["run_id"], "decision": decision_ref,
                "compounds": data["source_fact"]["compounds"], "receptors": receptors, "files": refs}
        write_json(folder / "packet.json", fact)
        packet_ref = file_record(home, folder / "packet.json", "preparation_packet")
        tables["preparation_packet"] = [packet_ref]
        tables["pocket_decision"] = [decision_ref]
        result = workflow._finish(manifest, run["run_id"], summary, tables, [], "success", attachments=refs + [packet_ref])
        workflow.save(manifest)
        return result
