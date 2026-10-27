"""新版A06共晶参考清单与明确核查任务接口。"""

from contracts import ContractError
from .errors import ApiError, from_contract


def info(app, req, sid):
    """GET只读取同批准备候选和证据决定。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_reference_info(sid)
    except ContractError as error:
        raise from_contract(str(error))
    if app.tasks.active_for(sid):
        value.update(enabled=False, reason_zh="请等待当前研究后台任务结束")
    return value


def review(app, req, sid):
    """显式POST提交选择；空清单可归档为明确不采用参考，仍不评分。"""
    body = req.json()
    try:
        result = app.kernel.workflow().validate_analysis_plan_a06_reference_request(sid, body)
    except ContractError as error:
        raise from_contract(str(error))
    if result["repeated"]:
        return {"review_id": result["review_id"], "created": False,
                "summary": result["summary"], "message_zh": "该共晶参考核查已归档，沿用原证据"}, 200
    if app.settings.science_tools_root is None:
        raise ApiError(409, "GATE_BLOCKED", "本机未配置固定科学工具目录")
    task, created = app.tasks.submit(sid, "a06_plan_reference_review", body["reviewer"].strip(), body)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
    return {"task": task, "created": True,
            "message_zh": "共晶参考选择已提交复核；结果只追加证据，不批准A06或启动批量评分"}, 202
