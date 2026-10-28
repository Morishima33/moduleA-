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


def scoring_readiness(app, req, sid):
    """GET只读正式评分闸门，不创建任务。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_scoring_readiness(sid)
    except ContractError as error:
        raise from_contract(str(error))
    if value['scoring_allowed'] and (app.tasks.active_for(sid) or app.settings.science_tools_root is None):
        reason = '请等待当前研究后台任务结束' if app.tasks.active_for(sid) else '本机未配置固定科学工具目录'
        value.update(scoring_allowed=False, execution_available=False, blockers=[reason], reason_zh=reason)
    return value


def review_packet(app, req, sid):
    """GET只读汇总人工整体复核材料，不写入或启动任务。"""
    try:
        return app.kernel.workflow().analysis_plan_a06_review_packet(sid)
    except ContractError as error:
        raise from_contract(str(error))


def export_review_packet(app, req, sid):
    """下载当前A06整体复核材料包JSON；下载前重新核验归档指纹。"""
    import json
    packet = review_packet(app, req, sid)
    return ("download", json.dumps(packet, ensure_ascii=False, indent=2).encode("utf-8"),
            f"{sid}_a06_review_packet.json", "application/json; charset=utf-8")


def review_gate(app, req, sid):
    """GET只读人工整体复核闸门，不保存决定。"""
    try:
        return app.kernel.workflow().analysis_plan_a06_review_gate(sid)
    except ContractError as error:
        raise from_contract(str(error))


def validate_scoring(app, req, sid):
    """POST只读预检正式评分请求，不提交评分任务。"""
    try:
        return app.kernel.workflow().validate_analysis_plan_a06_scoring_request(sid, req.json())
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


def info_v2(app, req, sid):
    """只读新版参考资格状态，不执行科学复算。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_reference_qualification_v2_info(sid)
    except ContractError as error:
        raise from_contract(str(error))
    if app.tasks.active_for(sid):
        value.update(enabled=False, reason_zh='请等待当前研究后台任务结束')
    return value


def prepare_v2(app, req, sid):
    """明确请求后在科学子进程复算并追加新版准备。"""
    body = req.json()
    try:
        result = app.kernel.workflow().validate_analysis_plan_a06_reference_qualification_v2(sid, body)
    except ContractError as error:
        raise from_contract(str(error))
    if result['repeated']:
        return {'run_id': result['run_id'], 'created': False, 'message_zh': '沿用已归档的参考资格准备'}, 200
    if app.settings.science_tools_root is None:
        raise ApiError(409, 'GATE_BLOCKED', '本机未配置固定科学工具目录')
    task, created = app.tasks.submit(sid, 'a06_plan_reference_qualification_v2', body['reviewer'].strip(), body)
    if not created:
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有后台任务')
    return {'task': task, 'created': True, 'message_zh': '已提交参考资格复算；不启动批量评分'}, 202
