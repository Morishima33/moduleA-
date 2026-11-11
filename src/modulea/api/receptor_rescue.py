"""受体探索补救的只读资格和严格任务入口，科学工具仅在后台运行。"""
from urllib.parse import urlsplit

from ..core import system_receptor_rescue as core
from .errors import ApiError


def info(app, req, sid):
    """按服务配置和当前来源列出可执行条件，不扫描科学工具依赖。"""
    if req.query or urlsplit(req.handler.path).query:
        raise ApiError(422, 'VALIDATION_FAILED', '受体补救资格入口不接受额外参数')
    value = core.info(app.kernel.read_workflow(), sid)
    value['busy'] = bool(app.tasks.active_for(sid))
    if value['busy']:
        value['enabled'] = False
        value['blockers'].append('请等待当前研究任务结束')
    if not app.settings.science_tools_root or not app.settings.science_repair_packages:
        value['enabled'] = False
        value['blockers'].append('本机尚未配置固定对接工具及有限修补依赖')
    return value


def execute(app, req, sid):
    """请求严格绑定原准备和原评分，队列不接受路径、名单或阈值覆盖。"""
    if req.query or urlsplit(req.handler.path).query:
        raise ApiError(422, 'VALIDATION_FAILED', '受体补救任务不接受额外参数')
    if app.tasks.active_for(sid):
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有任务，请等待结束')
    if not app.settings.science_tools_root or not app.settings.science_repair_packages:
        raise ApiError(409, 'GATE_BLOCKED', '未配置固定对接工具及有限修补依赖')
    body = req.json()
    core.validate_request(app.kernel.read_workflow(), sid, body)
    task, created = app.tasks.submit(sid, 'plan_system_receptor_rescue', body['author'], body)
    if not created:
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有任务')
    return {'task': task, 'created': True,
            'message_zh': '已提交当前失败受体的探索补救、补算和出图；新结果等待独立复核。'}, 202
