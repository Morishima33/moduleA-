"""精确编号补查只读历史、严格显式任务和索引附件下载。"""
from contracts import ContractError
from ..core import component_identity_probes as core, component_identity_evidence as evidence
from .errors import ApiError, from_contract


def info(app, req, sid):
    """只读取正式回执，不联网、不重试。"""
    if req.query: raise ApiError(422, 'VALIDATION_FAILED', '补查入口不接受额外参数')
    try: value = core.info(app.kernel.read_workflow(), sid)
    except ContractError as error: raise from_contract(str(error)) from error
    value['busy'] = bool(app.tasks.active_for(sid))
    if value['busy']: value['enabled'] = False; value['blockers'].append('请等待当前研究任务结束')
    for row in value['records']:
        base = f'/api/v1/studies/{sid}/analysis-plan/component-identity-probes/{row["probe_id"]}/files/'
        row['downloads'] = [{'label_zh': '补查回执JSON', 'url': base + '0?expected_record_sha256=' + row['file']['sha256']}]
        labels = {'identity_probe_query': '官方查询记录', 'identity_probe_response': '官方响应原文', 'identity_probe_request': '本次明确请求'}
        row['downloads'] += [{'label_zh': labels.get(ref['role'], '已归档原件') + ' ' + str(i),
                'url': base + str(i) + '?expected_record_sha256=' + row['file']['sha256']}
                for i, ref in enumerate(row['files'], 1)]
    return value


def execute(app, req, sid):
    """HTTP只预检与排队，科学worker实际补查。"""
    if req.query: raise ApiError(422, 'VALIDATION_FAILED', '补查提交不接受额外参数')
    if app.tasks.active_for(sid): raise ApiError(409, 'GATE_BLOCKED', '请等待当前研究任务结束')
    try: body = core.validate_request(app.kernel.workflow(), sid, req.json())
    except ContractError as error: raise from_contract(str(error)) from error
    task, created = app.tasks.submit(sid, 'plan_component_identity_probe', body['author'], body)
    if not created: raise ApiError(409, 'GATE_BLOCKED', '本研究已有任务，请稍后明确重试')
    return {'task': task, 'created': True, 'request_id': body['request_id'], 'message_zh': '已提交官方精确编号补查；仅归档凭据，不采用身份或签署复核。'}, 202


def file(app, req, sid, probe_id, index):
    """只能下载本研究本回执登记的编号文件，指纹变化拒绝。"""
    if set(req.query) != {'expected_record_sha256'} or len(req.query['expected_record_sha256']) != 1 or len(index) > 9:
        raise ApiError(422, 'VALIDATION_FAILED', '补查附件字段错误，不接受路径或URL')
    w = app.kernel.read_workflow(); m = w.load(sid)
    try:
        rows = [(ref, core.read_record(w, m, ref)) for ref in m.get(core.INDEX, [])]
        found = next(((ref, row) for ref, row in rows if row['probe_id'] == probe_id), None)
        if not found: raise ApiError(404, 'NOT_FOUND', '本研究没有此补查回执')
        ref, row = found
        if ref['sha256'] != req.query1('expected_record_sha256'): raise ApiError(409, 'STALE_VERSION', '补查回执指纹不同，请刷新')
        files = [ref, *row['files']]; number = int(index)
        if number >= len(files): raise ApiError(404, 'NOT_FOUND', '本回执没有此附件')
        raw = evidence.read_bytes(w.location(sid), files[number])
    except ContractError as error: raise from_contract(str(error)) from error
    return 'download', raw, probe_id + '_' + str(number) + ('.json' if files[number]['path'].endswith('.json') else '.bin'), 'application/octet-stream'
