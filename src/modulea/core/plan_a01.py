"""新方案A01任务的只读资格与严格请求校验；不在接口进程解析科学资料。"""
from contracts import require, safe_id
from storage import read_json, verified_file
from science_modules.analysis_protocol import VERSION

DATABASES = ("TCMSP", "HERB", "BATMAN")
FIELDS = {"expected_a00", "expected_a01", "expected_plan_id", "expected_staging", "reason"}


def info(workflow, sid):
    """读取当前登记、不可变草稿和原件索引，精确区分采集与发布的缺口。"""
    manifest = workflow.load(sid)
    a00 = manifest["current"].get("A00", "")
    a01 = manifest["current"].get("A01", "")
    intake = workflow.result(manifest, a00)["summary"] if a00 else {}
    supported = intake.get("analysis_plan_profile") == VERSION
    if not supported:
        reason = "历史固定研究不启用新方案A01"
        return {"supported": False, "protocol_version": "A01.plan_tasks.1",
                "acquire_enabled": False, "publish_enabled": False,
                "acquire_blockers": [reason], "publish_blockers": [reason],
                "expected_a00": a00, "expected_a01": a01, "expected_plan_id": "",
                "expected_staging": "", "parameter_hash": "", "parameters": {"ob_min": None, "dl_min": None},
                "missing_databases": [], "processed": False, "message_zh": reason}
    records = workflow._analysis_plan_records(manifest) if supported else []
    draft = records[-1] if records and records[-1]["expected_a00"] == a00 else None
    blockers = []
    if manifest.get("trashed"):
        blockers.append("回收站研究只读")
    if not a00 or not workflow.approved(manifest, a00):
        blockers.append("请先复核通过当前A00登记")
    if not draft:
        blockers.append("当前登记尚无有效方案草稿")
    home = workflow.location(sid)
    reference = manifest.get("current_component_uploads")
    staging = read_json(verified_file(home, reference)) if reference else None
    current = bool(staging and staging.get("study_id") == sid and staging.get("a00_run_id") == a00)
    slots = {row["database"]: row for row in staging.get("datasets", [])} if current else {}
    for slot in slots.values():
        verified_file(home, slot["source_record"])
        for item in slot["files"]:
            verified_file(home, item)
    missing = [db for db in DATABASES if db not in slots]
    publication = list(blockers)
    if missing:
        publication.append("请补齐三库原件：" + "、".join(missing))
    a02 = manifest["current"].get("A02")
    mapping = bool(a02 and workflow.run(manifest, a02).get("inputs", {}).get("mapping_file"))
    if not mapping and not all((workflow.root / "references" / name).is_file() for name in
                              ("hgnc_complete_set_20260913.json", "hgnc_complete_set_20260913.tsv")):
        publication.append("尚无共同HGNC身份依据，请先准备身份快照或完成A02标准化")
    inputs = workflow.run(manifest, a01).get("inputs", {}) if a01 else {}
    processed = bool(draft and current and inputs.get("analysis_plan_id") == draft["plan_id"]
                     and (inputs.get("staging_file") or {}).get("sha256") == reference["sha256"]
                     and workflow.active(manifest, a01))
    if processed:
        publication.append("本方案及本批原件已发布，请核查当前A01；新草稿或新原件可生成新版")
    parameters = draft["plan"]["parameters"] if draft else {}
    return {"supported": supported, "protocol_version": "A01.plan_tasks.1",
            "acquire_enabled": not blockers, "publish_enabled": not publication,
            "acquire_blockers": blockers, "publish_blockers": publication,
            "expected_a00": a00, "expected_a01": a01,
            "expected_plan_id": draft["plan_id"] if draft else "",
            "expected_staging": reference["sha256"] if reference else "",
            "parameter_hash": draft["plan"]["parameter_hash"] if draft else "",
            "parameters": {"ob_min": parameters.get("a01.ob_min"), "dl_min": parameters.get("a01.dl_min")},
            "missing_databases": missing, "processed": processed,
            "message_zh": "先获取或上传原件，再明确整理发布；缺库和身份未决仍阻断，结果须独立复核。自动全流程尚未接通。"}


def validate(workflow, sid, payload, action):
    """先拒绝隐藏覆盖和旧版本，再交由科学后台再次核验本批依赖。"""
    require(action in ("acquire", "publish"), "A01任务类型无效")
    fields = FIELDS | ({"databases"} if action == "acquire" else set())
    require(isinstance(payload, dict) and set(payload) == fields, "新方案A01请求字段不完整或含未支持选项")
    for key, prefix in (("expected_a00", "run"), ("expected_plan_id", "plan")):
        safe_id(payload[key], prefix)
    require(isinstance(payload["expected_a01"], str), "A01版本格式无效")
    if payload["expected_a01"]:
        safe_id(payload["expected_a01"], "run")
    require(isinstance(payload["expected_staging"], str), "来源指纹格式无效")
    require(isinstance(payload["reason"], str) and 0 < len(payload["reason"].strip()) <= 2000,
            "请填写本次操作依据，最多2000字")
    if action == "acquire":
        databases = payload["databases"]
        require(isinstance(databases, list) and databases and all(isinstance(db, str) for db in databases)
                and len(set(databases)) == len(databases) and set(databases) <= set(DATABASES), "采集数据库范围无效")
    value = info(workflow, sid)
    require(not workflow.load(sid).get("trashed"), "回收站研究只读")
    require(all(payload[key] == value[key] for key in FIELDS - {"reason"}), "A00、A01、方案或来源已改变，请刷新后重新提交")
    require(value[action + "_enabled"], "上游条件未就绪：" + "；".join(value[action + "_blockers"]))
    return value
