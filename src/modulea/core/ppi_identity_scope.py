"""PPI精确清单的公开决定登记；只用标准库，不计算网络、不迁移人工复核。"""
from copy import deepcopy
import csv
import hashlib
import io
import json

from contracts import ContractError, fingerprint, require, safe_id
from storage import file_record, read_json, verified_file, write_json, write_lock
from . import system_execution as execution

VERSION = 'A04.plan_identity_scope.1'
INDEX = 'analysis_plan_ppi_identity_scopes'
FIELDS = {'request_id', 'expected_a04', 'expected_input_hash', 'expected_proposal_sha256',
          'check_ids', 'omit_ids', 'author', 'note', 'user_decision', 'confirmed'}
NOTICE = '仅限本研究本批流程测试：先以原HGNC稳定编号补查；唯一且一致才可接入，其余获准清单子集暂不纳入PPI。原身份、原文和原因保留，A03及A05输入、STRING参数、结构质控、人工暂停和最终复核保持。'


def guard(w, m):
    """任何当前明确人工暂停或退回均阻断；批准清单不能取代它。"""
    require(not m.get('trashed'), '回收站研究只读')
    for rid in m['current'].values():
        review = w.latest_review(m, w.run(m, rid)['artifact_id'])
        require(not review or review['decision'] == 'approved', '已有明确人工暂存或退回，PPI补查不能放行')


def context(w, m, rid):
    """从原运行读取精确绑定；历史读取不依赖当前A05或最新方案草稿。"""
    run = w.run(m, rid); home = w.location(m['study_id'])
    require(run['module_id'] == 'A04' and run['config'].get('version') == 'A04.plan_network.1'
            and run.get('execution_protocol') == execution.VERSION, '仅支持原同批系统PPI第一版')
    batch, plan = execution.read_batch(w, m, run['batch_file'])
    a00 = batch['request']['expected_a00']; a03 = run['parent_runs']['A03']
    require(w.result(m, a00)['summary'].get('analysis_purpose') == 'workflow_test', 'PPI身份清单仅限流程测试')
    require(run['inputs']['analysis_plan_file'] == batch['plan_file']
            and run['inputs']['analysis_plan_id'] == plan['plan_id']
            and run['inputs']['analysis_parameter_hash'] == plan['plan']['parameter_hash']
            and run['inputs']['parent_result'] == m['runs'][a03]['result_file'], 'PPI原方案或原交集绑定不同')
    targets = w.result(m, a03)['tables']['intersection_targets']
    issues = w.result(m, rid)['tables']['identity_issues']
    require(issues and len({x['target_id'] for x in issues}) == len(issues), '原PPI没有完整唯一身份问题清单')
    mapping = batch['mapping']['mapping_file']; verified_file(home, mapping)
    source = run['inputs']['source_file']; verified_file(home, source)
    return {'study_id': m['study_id'], 'current': {'A00': a00, 'A03': a03, 'A04': rid},
            'run_files': {key: deepcopy(m['runs'][value]) for key, value in (('A00', a00), ('A03', a03), ('A04', rid))},
            'batch_file': deepcopy(run['batch_file']), 'plan_file': deepcopy(batch['plan_file']),
            'plan_id': plan['plan_id'], 'parameter_hash': plan['plan']['parameter_hash'],
            'mapping_file': deepcopy(mapping), 'source_file': deepcopy(source),
            'targets_hash': fingerprint(targets), 'issues': deepcopy(issues)}


def current_context(w, m):
    """登记及联网前核对当前原PPI，已换批或依赖失效不能沿用。"""
    guard(w, m); rid = m['current'].get('A04'); require(rid, '请先生成本批PPI原结果')
    value = context(w, m, rid); run = w.run(m, rid)
    execution.require_batch(w, m, run['batch_file'])
    require(execution.is_active(w, m, run)
            and all(m['current'].get(key) == item for key, item in value['current'].items()), '原PPI或同批真实依赖已改变')
    return value


def checked_proposal(w, m, binding, body, raw):
    """批准原提案逐件对照原问题、原响应和HGNC；不以文件存在冒充批准。"""
    require(isinstance(raw, bytes) and 0 < len(raw) <= 2 * 1024 * 1024
            and hashlib.sha256(raw).hexdigest() == body['expected_proposal_sha256'], 'PPI原提案字节或明确指纹不一致')
    try: value = json.loads(raw)
    except (ValueError, TypeError) as error: raise ContractError('PPI原提案不是完整JSON') from error
    require(isinstance(value, dict) and value.get('protocol') == 'ModuleA.ppi_identity_scope_proposal.1'
            and value.get('study_id') == m['study_id'] and value.get('analysis_purpose') == 'workflow_test'
            and value.get('a04_run_id') == binding['current']['A04']
            and value.get('a03_run_id') == binding['current']['A03']
            and value.get('batch_file') == binding['batch_file']
            and value.get('a04_run_files') == binding['run_files']['A04']
            and value.get('mapping_file_sha256') == binding['mapping_file']['sha256'], 'PPI原提案不属于同研究同批原运行')
    ids = sorted(x['target_id'] for x in binding['issues'])
    require(value.get('issue_ids') == ids and sorted(body['check_ids']) == ids
            and set(body['omit_ids']) <= set(ids), 'PPI精确问题清单不能遗漏或扩展')
    home = w.location(m['study_id']); targets = w.result(m, binding['current']['A03'])['tables']['intersection_targets']
    source = read_json(verified_file(home, binding['source_file']))
    mapping = json.loads(source['mapping']['response_text'])
    hgnc = {row['hgnc_id']: row for row in csv.DictReader(io.StringIO(
        verified_file(home, binding['mapping_file']).read_text(encoding='utf-8-sig')), delimiter='\t')}
    items = value.get('original_issues')
    require(isinstance(items, list) and len(items) == len(ids), 'PPI原提案缺少逐项原始证据')
    expected = {x['target_id']: x for x in binding['issues']}; seen = set()
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get('issue'), dict), 'PPI原问题记录格式错误')
        gid = item['issue'].get('target_id'); require(gid in expected and gid not in seen, 'PPI原问题重复或越界'); seen.add(gid)
        index = next(i for i, target in enumerate(targets) if target['target_id'] == gid)
        frozen = item.get('frozen_hgnc_fields')
        require(item['issue'] == expected[gid] and item.get('original_query_index') == index
                and item.get('string_responses') == [row for row in mapping if row['queryIndex'] == index]
                and isinstance(frozen, dict) and frozen.get('hgnc_id') == gid
                and frozen.get('symbol') == targets[index]['symbol']
                and all(hgnc[gid].get(key) == entry for key, entry in frozen.items()), 'PPI提案中的原问题、响应或HGNC不同')
    return value


def scope(binding, body):
    """只从已明确确认的内容派生范围，不调用旧病例默认授权。"""
    return {'study_id': binding['study_id'], 'a03_run': binding['current']['A03'],
            'decision': body['user_decision'], 'check_ids': deepcopy(body['check_ids']), 'omit_ids': deepcopy(body['omit_ids'])}


def read_record(w, m, ref):
    """标准库逐件核验历史批准、原提案及稳定编号计划；不联网或改变current。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref)); body = value['request']; binding = value['binding']
    require(ref in m.get(INDEX, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False
            and value['authority_kind'] == 'explicit_bound_test_decision'
            and body['confirmed'] is True and value['request_hash'] == fingerprint(body)
            and body['expected_input_hash'] == fingerprint(binding)
            and body['expected_a04'] == binding['current']['A04'], 'PPI清单登记归属、请求或确认无效')
    require(context(w, m, body['expected_a04']) == binding, 'PPI历史清单原输入已改变')
    checked_proposal(w, m, binding, body, verified_file(home, value['proposal_file']).read_bytes())
    for item in value['implementation_files']: verified_file(home, item)
    from science_modules.a04 import plan_identity as engine
    targets = w.result(m, binding['current']['A03'])['tables']['intersection_targets']
    require(value['scope'] == scope(binding, body) and value['query_plan'] == engine.queries(
        targets, verified_file(home, binding['mapping_file']).read_bytes(), value['scope']), 'PPI稳定编号计划与原HGNC或明确范围不同')
    return value


def info(w, sid):
    """只读返回原清单和登记状态；不解析网络，不隐式采用身份。"""
    m = w.load(sid); binding = None; blockers = []
    try: binding = current_context(w, m)
    except ContractError as error: blockers.append(str(error))
    return {'schema_version': VERSION, 'enabled': not blockers, 'blockers': blockers, 'binding': binding,
            'expected_a04': binding['current']['A04'] if binding else None,
            'expected_input_hash': fingerprint(binding) if binding else None,
            'history': [dict(read_record(w, m, ref), file=deepcopy(ref)) for ref in m.get(INDEX, [])],
            'notice_zh': NOTICE, 'queries_started_by_this_read': False, 'network_published_by_this_read': False}


def register(w, sid, body, proposal_bytes):
    """公开Workflow锁内登记实际决定和不可变原提案；不发布科学运行或签reviews。"""
    require(isinstance(body, dict) and set(body) == FIELDS, 'PPI决定字段错误，不接受参数、路径、URL或通过覆盖')
    safe_id(body['request_id'], 'ppiscopereq'); safe_id(body['expected_a04'], 'run')
    require(body['confirmed'] is True and all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 4000
            for key in ('author', 'note', 'user_decision')), '请登记真实用户决定、人员和原因并明确确认')
    for key in ('check_ids', 'omit_ids'):
        require(isinstance(body[key], list) and all(isinstance(x, str) for x in body[key])
                and len(body[key]) == len(set(body[key])), 'PPI补查及暂不采用清单格式错误或重复')
    with write_lock(w.root):
        m = w.load(sid); guard(w, m)
        for ref in m.get(INDEX, []):
            old = read_record(w, m, ref)
            if old['request']['request_id'] == body['request_id']:
                require(old['request'] == body and verified_file(w.location(sid), old['proposal_file']).read_bytes() == proposal_bytes,
                        'PPI决定请求号已用于其他内容')
                require(current_context(w, m) == old['binding'], 'PPI原输入已改变，历史决定不能继承')
                return dict(old, file=deepcopy(ref), created=False)
        binding = current_context(w, m)
        require(body['expected_a04'] == binding['current']['A04'] and body['expected_input_hash'] == fingerprint(binding), 'PPI输入已改变，请刷新')
        checked_proposal(w, m, binding, body, proposal_bytes)
        require(not any(read_record(w, m, ref)['binding'] == binding for ref in m.get(INDEX, [])), '该原PPI已登记明确清单，请复用原决定')
        from pathlib import Path
        from science_modules.a04 import plan_identity as engine
        import ppi_identity as original
        home = w.location(sid); folder = home / 'decisions/analysis_plans/ppi_identity_scopes' / body['request_id']
        targets = w.result(m, binding['current']['A03'])['tables']['intersection_targets']; approved = scope(binding, body)
        queries = engine.queries(targets, verified_file(home, binding['mapping_file']).read_bytes(), approved)
        folder.mkdir(parents=True, exist_ok=True); path = folder / 'approved_original_proposal.json'
        if path.exists(): require(path.read_bytes() == proposal_bytes, '原请求已归档不同提案，不能覆盖')
        else: path.write_bytes(proposal_bytes)
        implementations = []
        for source in (Path(__file__), Path(engine.__file__), Path(original.__file__)):
            dest = folder / 'implementation' / source.name; dest.parent.mkdir(exist_ok=True)
            if dest.exists(): require(dest.read_bytes() == source.read_bytes(), '原登记实现已改变，不能覆盖')
            else: dest.write_bytes(source.read_bytes())
            implementations.append(file_record(home, dest, 'ppi_identity_scope_implementation'))
        value = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body), 'request_hash': fingerprint(body),
                 'binding': binding, 'scope': approved, 'query_plan': queries, 'proposal_file': file_record(home, path, 'ppi_identity_original_proposal'),
                 'authority_kind': 'explicit_bound_test_decision', 'human_review_written': False,
                 'scientific_results_changed': False, 'notice_zh': NOTICE, 'implementation_files': implementations}
        target = folder / 'scope.json'
        if target.exists(): require(read_json(target) == value, '未完成的PPI登记与原内容不同')
        else: write_json(target, value)
        ref = file_record(home, target, 'ppi_identity_scope'); m.setdefault(INDEX, []).append(ref); w.save(m)
    return dict(value, file=ref, created=True)
