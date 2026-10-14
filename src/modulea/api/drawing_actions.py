"""A06出图附件请求验证与后台调度；接口只依赖标准库。"""

from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from contracts import ContractError
from .errors import ApiError, from_contract


def action_workflow(app, study_id, payload):
    """提交前核验当前A06与只读边界，后台保存时再次核验。"""
    if app.tasks.active_for(study_id):
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
    workflow = app.kernel.workflow()
    try:
        workflow.artifact_source(study_id, payload.get("expected_a06", ""))
    except ContractError as error:
        raise from_contract(str(error))
    return workflow


def upload_figure(app, req, study_id):
    """受限multipart暂存原字节，完整解码与归档由后台完成。"""
    fields, files = req.multipart()
    if set(fields) != {"expected_a06", "caption", "pair_key"}:
        raise ApiError(422, "VALIDATION_FAILED", "图片上传字段不完整或含未知字段")
    workflow = action_workflow(app, study_id, fields)
    _, _, pairs = workflow.artifact_source(study_id, fields["expected_a06"])
    if fields["pair_key"] and fields["pair_key"] not in {p["pair_key"] for p in pairs}:
        raise ApiError(422, "VALIDATION_FAILED", "图片对应组合不存在")
    if not fields["caption"].strip() or len(fields["caption"]) > 2000:
        raise ApiError(422, "VALIDATION_FAILED", "请填写图片说明（最多2000字）")
    upload = files["upload"]
    if Path(upload["name"]).suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ApiError(422, "VALIDATION_FAILED", "请选择PNG/JPEG图片")
    queue = app.settings.runtime_dir / "upload_queue"
    queue.mkdir(parents=True, exist_ok=True)
    blob_name = "figure_" + uuid4().hex
    with (queue / blob_name).open("xb") as stream:
        stream.write(upload["data"])
    payload = dict(
        fields,
        name=upload["name"],
        blob_name=blob_name,
        blob_sha256=sha256(upload["data"]).hexdigest(),
    )
    task, created = app.tasks.submit(study_id, "a06_figure", "上传分子对接结果图片", payload)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，本次图片未归档")
    return {
        "task": task,
        "created": created,
        "message_zh": "图片已提交后台验证与保存。" + app._task_message(task),
    }, 202


def pair_task(app, req, study_id, kind):
    """按明确选择生成包或合集，未达本轮范围的组合不能自动加入。"""
    payload = req.json()
    if set(payload) != {"expected_a06", "pair_keys"}:
        raise ApiError(422, "VALIDATION_FAILED", "请只提交A06版本和所选组合")
    workflow = action_workflow(app, study_id, payload)
    try:
        workflow.validate_artifact_request(study_id, payload, ready=kind == "a06_pair_bundle")
    except ContractError as error:
        raise from_contract(str(error))
    payload["request_version"] = "A06.drawing.on_demand.2"
    task, created = app.tasks.submit(study_id, kind, "页面所选对接出图包", payload)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
    return {
        "task": task,
        "created": created,
        "message_zh": "所选组合已提交后台整理。" + app._task_message(task),
    }, 202
