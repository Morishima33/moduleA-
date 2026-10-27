"""新版口袋清单与明确核查任务；接口不生成科学准备结果。"""

from contracts import ContractError
from .errors import ApiError, from_contract


def info(app, req, sid):
    """GET只返回当前研究已归档证据和可采用项。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_pocket_info(sid)
    except ContractError as error:
        raise from_contract(str(error)) from error
    busy = bool(app.tasks.active_for(sid))
    if busy:
        value.update(enabled=False, reason_zh="请等待当前研究后台任务结束")
    return value


def review(app, req, sid):
    """显式POST提交科学后台复验；重复已归档请求只读返回原运行。"""
    body = req.json()
    try:
        result = app.kernel.workflow().validate_analysis_plan_a06_pocket_request(sid, body)
    except ContractError as error:
        raise from_contract(str(error)) from error
    if result["repeated"]:
        return {"run_id": result["run_id"], "created": False,
                "message_zh": "该口袋决定已归档，沿用原准备修订"}, 200
    if app.settings.science_tools_root is None:
        raise ApiError(409, "GATE_BLOCKED", "本机未配置固定科学工具目录")
    task, created = app.tasks.submit(sid, "a06_plan_pocket_review", body["reviewer"].strip(), body)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
    return {"task": task, "created": True,
            "message_zh": "口袋决定已提交复验；复用归档准备，不重跑口袋预测或评分，不批准模块结果"}, 202
