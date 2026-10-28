"""可复核准备接口：只读资格或显式提交科学复验任务，不代签人工决定。"""
from contracts import ContractError
from .errors import ApiError, from_contract


def info(app, req, sid):
    """后台忙碌时不提供生成新准备操作。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_reviewable_info(sid)
    except ContractError as error:
        raise from_contract(str(error))
    if app.tasks.active_for(sid):
        value.update(enabled=False, reason_zh='请等待当前研究后台任务结束')
    return value


def publish(app, req, sid):
    """接口只做标准库预检，科学复算由隔离子进程再次检查。"""
    body = req.json()
    try:
        value = app.kernel.workflow().validate_analysis_plan_a06_reviewable(sid, body)
    except ContractError as error:
        raise from_contract(str(error))
    if value['repeated']:
        return {'run_id': value['run_id'], 'created': False, 'message_zh': '沿用已归档的可复核准备'}, 200
    if app.settings.science_tools_root is None:
        raise ApiError(409, 'GATE_BLOCKED', '本机未配置固定科学工具目录')
    task, created = app.tasks.submit(sid, 'a06_plan_reviewable_preparation', body['reviewer'].strip(), body)
    if not created:
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有后台任务')
    return {'task': task, 'created': True, 'message_zh': '已提交同批资料复验；完成后仍须人工整体复核，不启动评分'}, 202
