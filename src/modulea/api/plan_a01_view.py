"""新方案A01显式任务接口；只读请求不采集，不发布，不代签。"""
from contracts import ContractError
from ..core import plan_a01
from .errors import ApiError, from_contract


def info(app, req, sid):
    """在研究资格上叠加一次实际后台状态快照。"""
    value = plan_a01.info(app.kernel.workflow(), sid)
    if app.tasks.active_for(sid):
        for action in ("acquire", "publish"):
            value[action + "_enabled"] = False
            value[action + "_blockers"].append("请等待当前研究后台任务结束")
    return value


def submit(app, req, sid, action):
    """严格版本校验后登记独立任务，科学依赖只在配置的子进程导入。"""
    payload = req.json()
    try:
        plan_a01.validate(app.kernel.workflow(), sid, payload, action)
    except ContractError as error:
        raise from_contract(str(error)) from error
    task, created = app.tasks.submit(sid, "a01_plan_" + action, "新方案A01", payload)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
    return {"task": task, "created": True,
            "message_zh": "已提交本方案来源获取；只暂存原件。" if action == "acquire" else "已提交本方案三库标准化；结果仍须独立复核。"}, 202
