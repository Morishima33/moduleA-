"""新版A06参考证据绑定准备版本的接口。"""

from contracts import ContractError
from .errors import ApiError, from_contract


def info(app, req, sid):
    """GET只读当前绑定状态，不创建准备版本。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_reference_preparation_info(sid)
    except ContractError as error:
        raise from_contract(str(error))
    if app.tasks.active_for(sid):
        value.update(enabled=False, reason_zh="请等待当前研究后台任务结束")
    return value


def qualification(app, req, sid):
    """GET只复算归档指纹和阻断规则，不提交复核或启动任务。"""
    try:
        return app.kernel.workflow().analysis_plan_a06_reference_qualification(sid)
    except ContractError as error:
        raise from_contract(str(error))


def prepare(app, req, sid):
    """提交显式绑定请求；后台只重建准备证据，不运行评分。"""
    body = req.json()
    try:
        result = app.kernel.workflow().validate_analysis_plan_a06_reference_preparation_request(sid, body)
    except ContractError as error:
        raise from_contract(str(error))
    if result["repeated"]:
        return {"run_id": result["run_id"], "created": False,
                "message_zh": "参考证据已绑定新版准备，沿用原准备版本"}, 200
    if app.settings.science_tools_root is None:
        raise ApiError(409, "GATE_BLOCKED", "本机未配置固定科学工具目录")
    task, created = app.tasks.submit(sid, "a06_plan_reference_preparation", body["reviewer"].strip(), body)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
    return {"task": task, "created": True,
            "message_zh": "参考证据绑定任务已提交；新版准备仍待整体复核，未启动批量评分"}, 202
