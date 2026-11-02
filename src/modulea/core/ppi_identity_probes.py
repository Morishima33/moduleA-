"""PPI获准精确编号的公开采集入口；只归档证据，不采用身份或发布新网络。"""
from copy import deepcopy
from collections import Counter
from pathlib import Path

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from . import ppi_identity_scope as scopes

VERSION = 'A04.plan_identity_probes.1'
REQUESTS = 'analysis_plan_ppi_identity_probe_requests'
INDEX = 'analysis_plan_ppi_identity_probe_records'
FIELDS = {'request_id', 'scope_request_id', 'expected_input_hash', 'author', 'note', 'confirmed'}


def find_scope(w, m, request_id):
    """仅选择本研究已公开登记的明确决定，不接受客户端路径或授权内容。"""
    values = [(ref, scopes.read_record(w, m, ref)) for ref in m.get(scopes.INDEX, [])]
    matches = [(ref, value) for ref, value in values if value['request']['request_id'] == request_id]
    require(len(matches) == 1, 'PPI明确清单未登记或不唯一')
    return matches[0]


def validate_request(w, sid, body):
    """后台共用严格预检；没有确认不得发送查询，输入不绑定A05结果。"""
    require(isinstance(body, dict) and set(body) == FIELDS, 'PPI补查字段错误，不接受URL、路径、编号或采用标记')
    safe_id(body['request_id'], 'ppiprobereq'); safe_id(body['scope_request_id'], 'ppiscopereq')
    require(body['confirmed'] is True and all(isinstance(body[k], str) and 0 < len(body[k].strip()) <= 2000
            for k in ('author', 'note')), '请填写补查人员及原因并明确确认')
    m = w.load(sid); binding = scopes.current_context(w, m); ref, scope = find_scope(w, m, body['scope_request_id'])
    require(binding == scope['binding'] and body['expected_input_hash'] == fingerprint(binding), 'PPI批准范围或当前输入已改变')
    return binding, ref, scope


def read_request(w, m, ref):
    """历史请求绑定原批准和归档实现，不因后续新网络替换而抹去。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref)); body = value['request']
    require(ref in m.get(REQUESTS, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and body['confirmed'] is True and value['request_hash'] == fingerprint(body)
            and value['human_review_written'] is False, 'PPI补查请求登记或确认错误')
    scope = scopes.read_record(w, m, value['scope_file'])
    require(scope['request']['request_id'] == body['scope_request_id'] and value['binding'] == scope['binding']
            and body['expected_input_hash'] == fingerprint(value['binding']), 'PPI补查原范围或输入指纹不同')
    for item in value['implementation_files']: verified_file(home, item)
    return value


def read_record(w, m, ref):
    """完整与部分失败分别核验；缺失查询不能作为已完成或身份已解决。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref))
    require(ref in m.get(INDEX, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False,
            'PPI补查回执协议或归属错误')
    request = read_request(w, m, value['request_file']); approved = scopes.read_record(w, m, request['scope_file'])
    require(value['state'] in ('complete', 'partial_failure') and value['expected_queries'] == len(approved['query_plan'])
            and value['successful_queries'] == len(value['probes'])
            and value['successful_queries'] + len(value['failures']) == value['expected_queries'], 'PPI补查回执缺查询或状态错误')
    for item in value['files']: verified_file(home, item)
    combined = [x['query'] for x in value['probes']] + [x['query'] for x in value['failures']]
    require(Counter(map(fingerprint, combined)) == Counter(map(fingerprint, approved['query_plan'])),
            'PPI补查成功及失败必须逐一覆盖原编号，不能重复或替换')
    from science_modules.a04.plan_identity_probes import checked_checkpoint
    checkpoints = [ref for ref in value['files'] if ref.get('role') == 'ppi_identity_query_checkpoint']
    require(len(checkpoints) == len(value['probes']), 'PPI成功原文断点缺失')
    binding_hash = fingerprint({'scope_file': request['scope_file'], 'binding': request['binding']})
    for probe, checkpoint in zip(value['probes'], checkpoints):
        require(checked_checkpoint(home, checkpoint, probe['query'], binding_hash) == probe,
                'PPI回执与逐请求原文不同')
    from science_modules.a04 import plan_identity as engine
    if value['state'] == 'complete':
        require(not value['failures'], 'PPI部分失败不能标为完整')
        targets = w.result(m, approved['binding']['current']['A03'])['tables']['intersection_targets']
        engine.checked_queries(targets, verified_file(home, approved['binding']['mapping_file']).read_bytes(), approved['scope'], value['probes'])
    else: require(value['failures'] and all(x['state'] == 'query_failed' for x in value['failures']), 'PPI部分失败缺少失败原因')
    return value


def execute(w, sid, body, *, opener=None, progress=None):
    """锁外逐查询保留原字节，显式重试只复用本请求成功断点，不改任何科学结果。"""
    binding, scope_ref, approved = validate_request(w, sid, body); home = w.location(sid)
    from science_modules.a04 import plan_identity_probes as science
    folder = home / 'decisions/analysis_plans/ppi_identity_probes' / body['request_id']
    with write_lock(w.root):
        m = w.load(sid); require(validate_request(w, sid, body)[0] == binding, 'PPI补查输入已改变')
        same = [ref for ref in m.get(REQUESTS, []) if read_request(w, m, ref)['request']['request_id'] == body['request_id']]
        if same:
            request_ref = same[0]; request = read_request(w, m, request_ref)
            require(request['request'] == body, 'PPI补查请求号已用于其他内容')
            for ref in reversed(m.get(INDEX, [])):
                old = read_record(w, m, ref)
                if old['request_file'] == request_ref and old['state'] == 'complete': return dict(old, file=ref, created=False)
            for item, source in zip(request['implementation_files'], (Path(__file__), Path(science.__file__))):
                require(verified_file(home, item).read_bytes() == source.read_bytes(), 'PPI补查实现已改变，旧请求不能换实现重试')
        else:
            folder.mkdir(parents=True, exist_ok=True); implementations = []
            for source in (Path(__file__), Path(science.__file__)):
                saved = folder / 'implementation' / source.name
                # 两个模块同名，按层级隔离，不能覆盖实现快照。
                saved = saved.parent / ('core_' if source == Path(__file__) else 'science_') / saved.name
                saved.parent.mkdir(parents=True, exist_ok=True)
                if saved.exists(): require(saved.read_bytes() == source.read_bytes(), 'PPI补查归档实现不同')
                else: saved.write_bytes(source.read_bytes())
                implementations.append(file_record(home, saved, 'ppi_identity_probe_implementation'))
            request = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body), 'request_hash': fingerprint(body),
                       'binding': binding, 'scope_file': deepcopy(scope_ref), 'implementation_files': implementations, 'human_review_written': False}
            target = folder / 'request.json'
            if target.exists(): require(read_json(target) == request, '未完成的PPI请求与原输入不同')
            else: write_json(target, request)
            request_ref = file_record(home, target, 'ppi_identity_probe_request'); m.setdefault(REQUESTS, []).append(request_ref); w.save(m)
    targets = w.result(m, binding['current']['A03'])['tables']['intersection_targets']
    result = science.execute(home, folder, targets, verified_file(home, binding['mapping_file']).read_bytes(),
                             approved['scope'], fingerprint({'scope_file': scope_ref, 'binding': binding}), opener=opener, progress=progress)
    with write_lock(w.root):
        m = w.load(sid); require(validate_request(w, sid, body)[0] == binding, 'PPI补查期间输入或人工意见已改变；原件保留，未放行')
        # 发表前再核验本请求归档实现；代码变化不能冒充旧实现产生的证据。
        for item, source in zip(request['implementation_files'], (Path(__file__), Path(science.__file__))):
            require(verified_file(home, item).read_bytes() == source.read_bytes(), 'PPI补查期间实现已改变')
        value = dict(result, study_id=sid, probe_id=new_id('ppiprobe'), request_file=deepcopy(request_ref),
                     human_review_written=False, scientific_results_changed=False, created_at=now(),
                     notice_zh='仅已归档官方编号原件；未采用身份、暂不采用对象或发布新PPI，仍需独立新协议复算。')
        target = folder / (value['probe_id'] + '.json'); write_json(target, value)
        ref = file_record(home, target, 'ppi_identity_probe_record'); m.setdefault(INDEX, []).append(ref); w.save(m)
    return dict(value, file=ref, created=True)
