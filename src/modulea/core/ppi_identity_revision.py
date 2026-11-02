"""获准PPI清单的同批独立新运行；真实原件锁外计算，锁内规范校验并保留历史。"""
from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from . import ppi_identity_scope as scopes, ppi_identity_probes as probes, system_execution as execution

VERSION = 'A04.plan_identity_revision.1'
REQUESTS = 'analysis_plan_ppi_identity_revision_requests'
RECEIPTS = 'analysis_plan_ppi_identity_revision_receipts'
FAILURES = 'analysis_plan_ppi_identity_revision_failures'
FIELDS = {'request_id', 'scope_request_id', 'probe_id', 'expected_a04', 'expected_input_hash', 'author', 'note', 'confirmed'}


def implementation_current(home, request, science):
    """每次计算前后逐件对照同一归档，避免计算期间源码变化被新配置掩盖。"""
    sources = science.implementation_files()
    require(len(request['implementation_files']) == len(sources), 'PPI修订实现清单不完整')
    for item, source in zip(request['implementation_files'], sources):
        require(verified_file(home, item).read_bytes() == source.read_bytes(), 'PPI实现已改变，旧请求不能换版本重试')


def read_request(w, m, ref):
    """不可变请求只绑定公开登记的原清单、完整补查及原PPI，不接受任意原件路径。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref)); body = value['request']
    require(ref in m.get(REQUESTS, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and body['confirmed'] is True
            and value['request_hash'] == fingerprint(body), 'PPI修订请求归属或确认无效')
    approved = scopes.read_record(w, m, value['scope_file']); probe = probes.read_record(w, m, value['probe_file'])
    probe_request = probes.read_request(w, m, probe['request_file'])
    require(body['scope_request_id'] == approved['request']['request_id'] and body['probe_id'] == probe['probe_id']
            and probe['state'] == 'complete' and probe_request['scope_file'] == value['scope_file']
            and body['expected_a04'] == approved['binding']['current']['A04']
            and body['expected_input_hash'] == fingerprint(approved['binding'])
            and value['binding'] == approved['binding'], 'PPI修订的精确范围、完整补查或原输入不同')
    for item in value['implementation_files']: verified_file(home, item)
    return value


def read_receipt(w, m, ref):
    """回执必须指向真实新网络运行，不把决定登记或失败尝试当已发布。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref)); request = read_request(w, m, value['request_file'])
    run = w.run(m, value['run_id'])
    require(ref in m.get(RECEIPTS, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and run['config'].get('version') == 'A04.plan_network.2'
            and run['inputs']['identity_revision_request'] == value['request_file']
            and run['inputs']['ppi_identity_scope'] == request['scope_file']
            and run['inputs']['ppi_identity_probes'] == request['probe_file']
            and run['batch_file'] == request['binding']['batch_file']
            and value['result_file'] == m['runs'][value['run_id']]['result_file'], 'PPI修订回执与实际新运行不同')
    return value


def validate_body(body):
    """精确字段和显式确认，不接受客户端参数、路径、通过标记或替代对象。"""
    require(isinstance(body, dict) and set(body) == FIELDS, 'PPI修订字段错误，不接受参数、路径、URL或通过覆盖')
    for key, prefix in (('request_id', 'ppirevisionreq'), ('scope_request_id', 'ppiscopereq'), ('probe_id', 'ppiprobe'), ('expected_a04', 'run')):
        safe_id(body[key], prefix)
    require(body['confirmed'] is True and all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 2000
            for key in ('author', 'note')), '请填写PPI修订人员和依据并明确确认')


def register_request(w, sid, body):
    """先锁内登记完整补查与实现版本，再允许锁外新网络获取；同编号重试不覆盖历史。"""
    validate_body(body)
    from science_modules.a04 import plan_identity_network as science
    with write_lock(w.root):
        m = w.load(sid); scopes.guard(w, m); home = w.location(sid)
        for ref in m.get(REQUESTS, []):
            previous = read_request(w, m, ref)
            if previous['request']['request_id'] == body['request_id']:
                require(previous['request'] == body, 'PPI修订请求号已用于其他内容')
                return previous, ref
        scope_ref, approved = probes.find_scope(w, m, body['scope_request_id']); binding = scopes.current_context(w, m)
        require(binding == approved['binding'] and body['expected_a04'] == binding['current']['A04']
                and body['expected_input_hash'] == fingerprint(binding), 'PPI修订原输入或明确范围已改变')
        found = [(ref, probes.read_record(w, m, ref)) for ref in m.get(probes.INDEX, [])]
        matched = [(ref, value) for ref, value in found if value['probe_id'] == body['probe_id']]
        require(len(matched) == 1 and matched[0][1]['state'] == 'complete', 'PPI修订必须有逐编号完整成功补查，失败不能省略')
        probe_ref, probe = matched[0]
        require(probes.read_request(w, m, probe['request_file'])['scope_file'] == scope_ref, 'PPI补查来自另一明确范围')
        folder = home / 'decisions/analysis_plans/ppi_identity_revisions' / body['request_id']; folder.mkdir(parents=True, exist_ok=True)
        implementations = []
        for source in science.implementation_files():
            relative = source.relative_to(Path(science.__file__).parents[2])
            dest = folder / 'implementation' / relative; dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists(): require(dest.read_bytes() == source.read_bytes(), '原PPI修订请求实现已改变，不覆盖')
            else: dest.write_bytes(source.read_bytes())
            implementations.append(file_record(home, dest, 'ppi_identity_revision_implementation'))
        value = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body), 'request_hash': fingerprint(body),
                 'binding': binding, 'scope_file': deepcopy(scope_ref), 'probe_file': deepcopy(probe_ref),
                 'implementation_files': implementations, 'human_review_written': False}
        path = folder / 'request.json'
        if path.exists(): require(read_json(path) == value, '未完成的PPI修订请求不同')
        else: write_json(path, value)
        ref = file_record(home, path, 'ppi_identity_revision_request'); m.setdefault(REQUESTS, []).append(ref); w.save(m)
    return value, ref


def _publish(w, sid, body, *, opener=None):
    """同批发布独立A04第二版及最新完成事件；旧A04/A03/A05原件、批次和reviews保持。"""
    request, request_ref = register_request(w, sid, body); home = w.location(sid); binding = request['binding']
    m = w.load(sid)
    for ref in reversed(m.get(RECEIPTS, [])):
        old = read_receipt(w, m, ref)
        if old['request_file'] == request_ref:
            require(m['current'].get('A04') == old['run_id'] and execution.is_active(w, m, w.run(m, old['run_id'])), 'PPI已发布运行失效，不能沿用原修订回执')
            return dict(old, file=deepcopy(ref), created=False)
    require(scopes.current_context(w, m) == binding, 'PPI修订原输入已改变')
    from science_modules.a04 import plan_identity_network as science
    implementation_current(home, request, science)
    approved = scopes.read_record(w, m, request['scope_file']); probe = probes.read_record(w, m, request['probe_file'])
    a03 = binding['current']['A03']; parents = {'A03': a03}; parent_snapshot = execution.parent_records(w, m, parents)
    plan_record = read_json(verified_file(home, binding['plan_file'])); plan = plan_record['plan']
    config = science.configuration(plan, binding['plan_id'])
    implementation_current(home, request, science)
    folder = home / 'decisions/analysis_plans/ppi_identity_revisions' / body['request_id'] / 'attempts' / new_id('attempt')
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / 'request.json', {'request_file': request_ref, 'scope_file': request['scope_file'], 'probe_file': request['probe_file'], 'config': config})
    def evidence(value):
        """完整成功响应在任何后续计算前先留原件。"""
        write_json(folder / 'network.json', value)
    targets = w.result(m, a03)['tables']['intersection_targets']
    source = science.fetch_network(targets, read_json(verified_file(home, binding['source_file'])), probe['probes'],
        verified_file(home, binding['mapping_file']).read_bytes(), approved['scope'], plan, opener=opener, evidence=evidence)
    path = folder / 'source.json'; write_json(path, source); source_ref = file_record(home, path, 'ppi_identity_network_source')
    inputs = {'study_id': sid, 'bound_a00': binding['current']['A00'], 'analysis_plan_id': binding['plan_id'],
              'analysis_plan_file': deepcopy(binding['plan_file']), 'analysis_parameter_hash': binding['parameter_hash'],
              'parent_result': deepcopy(binding['run_files']['A03']['result_file']), 'original_ppi_run': deepcopy(binding['run_files']['A04']['run_file']),
              'original_ppi_source': deepcopy(binding['source_file']), 'source_file': source_ref,
              'ppi_identity_scope': deepcopy(request['scope_file']), 'ppi_identity_probes': deepcopy(request['probe_file']), 'identity_revision_request': deepcopy(request_ref)}
    summary, tables = science.facts(w, m, inputs)
    with write_lock(w.root):
        m = w.load(sid); require(scopes.current_context(w, m) == binding
            and execution.parent_records(w, m, parents) == parent_snapshot, 'PPI计算期间输入、人工意见或真实父回执已改变')
        require(config == science.configuration(plan, binding['plan_id']), 'PPI计算期间实现已改变')
        implementation_current(home, request, science)
        run = execution.begin(w, m, 'A04', inputs, config, body['note'], binding['batch_file'], parents)
        anomalies = [scopes.NOTICE]; outcome = 'success' if summary['参与节点数'] else 'empty'
        canonical = execution.validation.canonical_validator(w.root, 'A04'); require(callable(canonical), 'PPI新规范验证器未接通')
        canonical(run, summary, tables, anomalies, outcome)
        sources = [binding['batch_file'], binding['plan_file'], binding['source_file'], binding['mapping_file'],
                   request_ref, request['scope_file'], request['probe_file'], source_ref,
                   *run['parent_validation_records'].values(), *request['implementation_files'],
                   file_record(home, folder / 'request.json', 'ppi_identity_revision_attempt'), file_record(home, folder / 'network.json', 'ppi_identity_new_network')]
        w._finish(m, run['run_id'], summary, tables, anomalies, outcome, sources=sources)
        event = {'schema_version': execution.VERSION, 'study_id': sid, 'batch_id': read_json(verified_file(home, binding['batch_file']))['batch_id'],
                 'stage': 'A04', 'state': 'completed', 'batch_file': deepcopy(binding['batch_file']), 'request': deepcopy(body),
                 'run_id': run['run_id'], 'result_file': deepcopy(m['runs'][run['run_id']]['result_file']), 'human_review_written': False, 'created_at': now()}
        event_path = folder / 'system_event.json'; write_json(event_path, event); m.setdefault(execution.EVENTS, []).append(file_record(home, event_path, 'system_batch_event'))
        receipt = {'schema_version': VERSION, 'study_id': sid, 'request_file': deepcopy(request_ref), 'run_id': run['run_id'],
                   'result_file': deepcopy(m['runs'][run['run_id']]['result_file']), 'human_review_written': False, 'created_at': now()}
        receipt_path = folder / 'receipt.json'; write_json(receipt_path, receipt); ref = file_record(home, receipt_path, 'ppi_identity_revision_receipt')
        m.setdefault(RECEIPTS, []).append(ref); w.save(m)
    return dict(receipt, file=ref, created=True)


def publish(w, sid, body, *, opener=None):
    """失败如实保留已登记请求和尝试，原结果不被占位运行替换。"""
    try: return _publish(w, sid, body, opener=opener)
    except Exception as error:
        if isinstance(body, dict) and set(body) == FIELDS:
            with write_lock(w.root):
                m = w.load(sid); home = w.location(sid)
                refs = [ref for ref in m.get(REQUESTS, []) if read_request(w, m, ref)['request'] == body]
                if refs and not m.get('trashed'):
                    folder = verified_file(home, refs[0]).parent; paths = sorted((folder / 'attempts').rglob('*')) if (folder / 'attempts').exists() else []
                    for path in (home / 'runs/A04').glob('*/run.json'):
                        orphan = read_json(path)
                        if orphan['run_id'] not in m['runs'] and orphan.get('inputs', {}).get('identity_revision_request') == refs[0]:
                            paths.extend(sorted(path.parent.rglob('*')))
                    value = {'schema_version': VERSION, 'study_id': sid, 'request_file': refs[0], 'state': 'failed',
                             'error_type': type(error).__name__, 'error_zh': str(error), 'human_review_written': False,
                             'files': [file_record(home, path, 'ppi_identity_revision_failure_evidence') for path in paths if path.is_file()]}
                    path = folder / (new_id('failure') + '.json'); write_json(path, value); m.setdefault(FAILURES, []).append(file_record(home, path, 'ppi_identity_revision_failure')); w.save(m)
        raise
