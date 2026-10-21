"""显式一次授权后的串行接续；绑定检查不批准任何科研结果。"""
from contracts import require, safe_id
from storage import read_json, verified_file, new_id

SCHEMA = 'A06.connect_run.1'
FIELDS = {'expected_binding', 'expected_connection_id', 'expected_a06', 'request_id',
          'policy_version', 'reviewer', 'note', 'confirmed', 'reference_choices', 'continuation_version'}


def validate(workflow, sid, payload):
    """在连接前核对显式授权及本研究已批准名单，不依赖浏览器猜测状态。"""
    require(isinstance(payload, dict) and set(payload) == FIELDS, '连续执行请求字段不完整或含隐藏参数')
    require(payload['confirmed'] is True and payload['policy_version'] == 'A06.automatic.3',
            '请明确确认本次范围、来源补齐策略和连续执行')
    require(payload['continuation_version'] == SCHEMA, '连续执行版本不匹配，请刷新')
    require(all(isinstance(payload[k], str) and 0 < len(payload[k].strip()) <= 2000
                for k in ('reviewer', 'note')), '请填写实际执行确认人及说明')
    safe_id(payload['request_id'], 'auto')
    manifest, _ = workflow.automatic_binding(sid, payload['expected_binding'])
    workflow.validate_extended_scope(sid, manifest)
    require(not manifest.get('trashed'), '回收站研究只读')
    require(manifest['current'].get('A06') == payload['expected_a06'], '当前结果已改变，请刷新')
    connection = workflow.current_automatic_connection(manifest, payload['expected_binding'])
    require((connection['id'] if connection else None) == payload['expected_connection_id'],
            '连接版本已改变，请刷新')
    require(isinstance(payload['reference_choices'], list), '请明确提供共晶参考选择，可为空')
    if connection:
        from science_modules.a06.reference_candidates import validate_choices
        packet = read_json(verified_file(workflow.location(sid), connection['packet']))
        validate_choices(workflow.location(sid), packet, payload['reference_choices'])
    else:
        require(not payload['reference_choices'], '未连接时不能选择尚未核验的共晶参考')
    return manifest, connection


def run(workflow, sid, payload, connect, calculate, progress):
    """确认后补齐来源并交原执行接口；连接变更或异常不得跳过原科学校验。"""
    from science_modules.a06.compound_recovery import VERSION
    _, connection = validate(workflow, sid, payload)
    packet = read_json(verified_file(workflow.location(sid), connection['packet'])) if connection else None
    if (not packet or packet.get('compound_resolution_version') != VERSION
            or packet.get('summary', {}).get('exceptions', 0)):
        progress('已确认连续执行：正在连接并补齐资料，完成后自动进入计算')
        connection = connect(workflow, sid, {'expected_binding': payload['expected_binding'],
                             'connection_id': new_id('connection'), 'policy_version': payload['policy_version']}, progress)
    request = {k: v for k, v in payload.items() if k != 'continuation_version'}
    request['expected_connection_id'] = connection['id']
    # 原始确认载荷由后台任务归档；连接后的实际执行绑定由原Workflow再次校验及归档。
    workflow.validate_automatic_request(sid, request)
    progress('连接已完成：按本次明确授权接续准备、质控和对接，无需再次确认')
    return calculate(request)
