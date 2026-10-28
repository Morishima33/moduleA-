"""新方案A05接口只做标准库预检和任务分派，不在HTTP运行R。"""
from pathlib import Path
from contracts import ContractError
from ..core import plan_a05
from .errors import ApiError, from_contract


def execution_blocker(settings, active):
    """只检查配置文件存在；固定版本由科学R进程实际验证。"""
    if active:
        return "请等待当前研究后台任务结束"
    if not settings.science_rscript or not Path(settings.science_rscript).is_file():
        return "本机尚未配置有效固定R工具，请核对science_rscript"
    return None


def info(app, req, sid):
    """执行资格同时反映当前任务和服务器R配置，不在网页猜测。"""
    value = plan_a05.info(app.kernel.workflow(), sid)
    reason = execution_blocker(app.settings, app.tasks.active_for(sid))
    if reason:
        value["enabled"] = False
        value["blockers"].append(reason)
    return value


def submit(app, req, sid):
    """明确操作后提交新协议任务；无缺依赖静默降级。"""
    body = req.json()
    try:
        plan_a05.validate(app.kernel.workflow(), sid, body)
    except ContractError as error:
        raise from_contract(str(error)) from error
    reason = execution_blocker(app.settings, app.tasks.active_for(sid))
    if reason:
        raise ApiError(409, "GATE_BLOCKED", reason)
    task, created = app.tasks.submit(sid, "a05_plan_enrichment", "新方案A05", body)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
    return {"task": task, "created": True, "message_zh": "已提交本方案A05富集，统计及完整表归档后仍须独立复核。"}, 202
