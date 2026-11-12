"""受体补救二版的独立资格与执行地址；第一版原请求始终沿原协议恢复。"""
from urllib.parse import urlsplit

from ..core import system_receptor_rescue as first
from ..core import system_receptor_rescue_v2 as core
from .errors import ApiError


def info(app, req, sid):
    """活动第一版仍返回其确切原请求；完成后才提供明确二版补救资格。"""
    if req.query or urlsplit(req.handler.path).query:
        raise ApiError(422, 'VALIDATION_FAILED', '受体补救资格入口不接受额外参数')
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    current_id = manifest['current'].get('A06')
    current = workflow.run(manifest, current_id) if current_id else None
    unfinished_first = bool(current and current['config'].get('version') == first.VERSION
                            and not manifest['runs'][current_id].get('result_file'))
    value = first.info(workflow, sid) if unfinished_first else core.info(workflow, sid)
    value['busy'] = bool(app.tasks.active_for(sid))
    if value['busy']:
        value['enabled'] = False
        value['blockers'].append('请等待当前研究任务结束')
    if not app.settings.science_tools_root or not app.settings.science_repair_packages:
        value['enabled'] = False
        value['blockers'].append('本机尚未配置固定对接工具及有限修补依赖')
    return value


def execute(app, req, sid):
    """仅新明确二版请求进入二版预算worker，不接收文件路径或科学参数。"""
    if req.query or urlsplit(req.handler.path).query:
        raise ApiError(422, 'VALIDATION_FAILED', '受体补救任务不接受额外参数')
    if app.tasks.active_for(sid):
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有任务，请等待结束')
    if not app.settings.science_tools_root or not app.settings.science_repair_packages:
        raise ApiError(409, 'GATE_BLOCKED', '未配置固定对接工具及有限修补依赖')
    body = req.json()
    core.validate_request(app.kernel.read_workflow(), sid, body)
    task, created = app.tasks.submit(sid, 'plan_system_receptor_rescue_v2', body['author'], body)
    if not created:
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有任务')
    return {'task': task, 'created': True,
            'message_zh': '已提交剩余受体补救；沿用已核验成功对象，新结果等待独立复核。'}, 202
