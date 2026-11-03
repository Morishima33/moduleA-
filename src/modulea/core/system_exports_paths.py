"""系统批次同源导出公开桥接；只追加图表/Excel档案，不改科学运行或人工复核。"""
from copy import deepcopy
from pathlib import Path

from contracts import ContractError, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from . import system_validation, system_decisions
from . import system_exports_v2 as legacy

VERSION = 'A06.system_exports.3'
REQUESTS = 'analysis_plan_repaired_export_requests'
INDEX = 'analysis_plan_repaired_export_records'
CANDIDATES = 'analysis_plan_repaired_export_candidates'
FAILURES = 'analysis_plan_repaired_export_failures'
FIELDS = {'request_id', 'expected_module', 'expected_run_id', 'expected_input_hash', 'author', 'note', 'confirmed'}
SCORING = ('A06.system_scoring_paths.1',)
PREPARATION = ('A06.system_qualification_paths.1',)


def guard(w, m):
    """生成只对当前可写研究；明确人工暂存和退回不被导出操作绕过。"""
    require(not m.get('trashed'), '回收站只读，可读取已归档文件，不能新生成导出')
    for rid in m['current'].values():
        review = w.latest_review(m, w.run(m, rid)['artifact_id'])
        require(not review or review['decision'] == 'approved', '研究已有明确人工暂存或退回，不能新生成导出')


def context(w, m):
    """只取本批有效系统评分，或无可评分组合的全NA准备；不借用旧批评分。"""
    guard(w, m); sid = m['study_id']; rid = m['current'].get('A06')
    if not rid or w.run(m, rid)['config'].get('version') not in SCORING or not w.active(m, rid) or not w.result(m, rid):
        rid = m['current'].get('A06_PREP')
    require(rid, '请先形成本批系统评分或全NA准备结果')
    run = w.run(m, rid); result = w.result(m, rid)
    require(run.get('execution_protocol') == 'ModuleA.system_execution.1' and run['config'].get('version') in SCORING + PREPARATION
            and w.active(m, rid) and result is not None and result['outcome'] != 'failed', '本批系统结果尚未完整归档或已失效')
    ref = run['inputs']['system_input_ref']; fixed = system_decisions.read_record(w, m, ref)
    require(fixed['stage'] == 'A06_INPUT' and system_decisions.active(w, m, fixed)
            and fixed['binding']['batch_file'] == run['batch_file'] and fixed['payload']['input_key'] == result['summary']['input_key'], '系统导出固定范围或来源批次不同')
    if run['config']['version'] in PREPARATION:
        require(result['tables']['planned_pairs'] and all(row['state'] == 'NA' and row['score'] is None and row['reason_zh']
                for row in result['tables']['planned_pairs']), '本批仍有可评分组合，请完成评分后导出评分矩阵')
    _, _, _, dependency = system_validation.binding(w, sid, rid)
    return {'study_id': sid, 'module_id': run['module_id'], 'run_id': rid, 'run_files': deepcopy(m['runs'][rid]),
            'fixed_file': deepcopy(ref), 'input_key': fixed['payload']['input_key'], 'dependency_binding': dependency}


def read_request(w, m, ref):
    """历史导出绑定原运行、完整依赖及固定范围，来源更新不抹掉旧档案。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref)); body = value['request']; binding = value['binding']
    require(ref in m.get(REQUESTS, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False
            and value['request_hash'] == fingerprint(body) and body['confirmed'] is True
            and body['expected_run_id'] == binding['run_id'] and body['expected_module'] == binding['module_id']
            and body['expected_input_hash'] == fingerprint(binding), '系统导出请求归属、范围或明确确认错误')
    require(m['runs'].get(binding['run_id']) == binding['run_files'], '导出原运行文件登记已改变')
    for item in binding['run_files'].values(): verified_file(home, item)
    for run_id, files in binding['dependency_binding']['dependency_files'].items():
        require(m['runs'].get(run_id) == files, '导出历史依赖的登记已改变')
        for item in files.values():
            if item: verified_file(home, item)
    fixed = system_decisions.read_record(w, m, binding['fixed_file'])
    require(fixed['stage'] == 'A06_INPUT' and fixed['payload']['input_key'] == binding['input_key'], '导出原固定对象不同')
    for item in value['implementation_files']: verified_file(home, item)
    return value


def read_candidate(w, m, ref):
    """只有manifest登记的成功检查点可复用；未登记的临时文件不能自证其完整性。"""
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref)); request = read_request(w, m, value['request_file'])
    require(ref in m.get(CANDIDATES, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False
            and value['source_run_id'] == request['binding']['run_id']
            and value['input_key'] == request['binding']['input_key'] and len(value['files']) == 6
            and set(value['formats']) == {'heatmap_png', 'heatmap_svg', 'full_heatmap_png', 'full_heatmap_svg', 'csv', 'xlsx'}, '系统导出回执与本批原件不同')
    verified_file(home, value['view_file'])
    require(fingerprint(read_json(verified_file(home, value['view_file']))) == value['view_hash'], '系统导出视图指纹不同')
    require(len({fingerprint(item) for item in value['files']}) == 6
            and {fingerprint(item) for item in value['formats'].values()} == {fingerprint(item) for item in value['files']}, '系统导出格式与文件清单不同')
    prefix = 'decisions/analysis_plans/repaired_system_exports/' + request['request']['request_id'] + '/attempts/'
    require(all(item['path'].startswith(prefix) for item in [value['view_file'], *value['files']]), '系统导出文件不属于原明确请求')
    for item in value['files']: verified_file(home, item)
    return value


def read_record(w, m, ref):
    """已发表导出必须引用真实成功检查点，历史读取不改变科学状态。"""
    value = read_json(verified_file(w.location(m['study_id']), ref))
    require(ref in m.get(INDEX, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id'], '系统导出回执归属或协议错误')
    candidate = read_candidate(w, m, value['candidate_file'])
    require(all(value[key] == item for key, item in candidate.items()), '系统导出回执与已登记成功检查点不同')
    safe_id(value['export_id'], 'systemexport')
    return value


def info(w, sid):
    """GET只读资格与既有文件；没有后台生成、自动续做或新科学计算。"""
    m = w.load(sid); binding = None; blockers = []
    try: binding = context(w, m)
    except ContractError as error: blockers.append(str(error))
    history = [dict(read_record(w, m, ref), file=deepcopy(ref)) for ref in m.get(INDEX, [])]
    current = next((row for row in reversed(history) if row['schema_version'] == VERSION and binding and read_request(w, m, row['request_file'])['binding'] == binding), None)
    return {'schema_version': VERSION, 'enabled': not blockers, 'blockers': blockers,
            'expected_module': binding['module_id'] if binding else None,
            'expected_run_id': binding['run_id'] if binding else None,
            'expected_input_hash': fingerprint(binding) if binding else None,
            'current': current, 'history': history, 'message_zh': '只从本批归档数据生成Excel、CSV和图；不重算Vina、不改变范围、评分或人工复核。'}


def validate_request(w, sid, body):
    """HTTP及worker共用严格预检，不允许传入评分、文件路径或对象替换。"""
    require(isinstance(body, dict) and set(body) == FIELDS, '系统导出字段错误，不接受评分、路径、URL或对象覆盖')
    safe_id(body['request_id'], 'sysexportreq'); safe_id(body['expected_run_id'], 'run')
    require(body['expected_module'] in ('A06', 'A06_PREP') and body['confirmed'] is True
            and all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 2000 for key in ('author', 'note')), '请填写导出登记人及说明并明确确认')
    m = w.load(sid); binding = context(w, m)
    require(body['expected_module'] == binding['module_id'] and body['expected_run_id'] == binding['run_id']
            and body['expected_input_hash'] == fingerprint(binding), '系统导出输入或人工意见已改变，请刷新')
    return binding


def execute(w, sid, body):
    """独立导出任务，完整成功原件可恢复；旧科学运行、报告及reviews不被改写。"""
    binding = validate_request(w, sid, body); home = w.location(sid)
    from science_modules.a06 import system_exports_paths as science
    implementations = [Path(__file__), Path(legacy.__file__), *science.implementation_files()]
    with write_lock(w.root):
        m = w.load(sid); require(validate_request(w, sid, body) == binding, '导出登记期间输入已改变')
        same = [(ref, read_request(w, m, ref)) for ref in m.get(REQUESTS, [])
                if read_request(w, m, ref)['request']['request_id'] == body['request_id']]
        folder = home / 'decisions/analysis_plans/repaired_system_exports' / body['request_id']
        if same:
            request_ref, request = same[0]; require(request['request'] == body, '导出请求号已用于其他内容')
            for ref in reversed(m.get(INDEX, [])):
                previous = read_record(w, m, ref)
                if previous['request_file'] == request_ref: return dict(previous, file=deepcopy(ref), created=False)
        else:
            saved = []
            for source in implementations:
                target = folder / 'implementation' / source.relative_to(Path(__file__).parents[2]); target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists(): require(target.read_bytes() == source.read_bytes(), '导出原请求实现不同，不覆盖')
                else: target.write_bytes(source.read_bytes())
                saved.append(file_record(home, target, 'system_export_implementation'))
            request = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body), 'request_hash': fingerprint(body),
                'binding': binding, 'implementation_files': saved, 'human_review_written': False, 'scientific_results_changed': False}
            path = folder / 'request.json'
            if path.exists(): require(read_json(path) == request, '未完成的导出请求与原输入不同')
            else: write_json(path, request)
            request_ref = file_record(home, path, 'system_export_request'); m.setdefault(REQUESTS, []).append(request_ref); w.save(m)
    try:
        for ref, source in zip(request['implementation_files'], implementations):
            require(verified_file(home, ref).read_bytes() == source.read_bytes(), '导出实现已改变，旧请求不能换实现重试')
        run = w.run(m, binding['run_id']); result = w.result(m, binding['run_id'])
        fixed = system_decisions.read_record(w, m, binding['fixed_file'])
        view = science.build_view(run, result, fixed['payload'])
        available = [(ref, read_candidate(w, m, ref)) for ref in m.get(CANDIDATES, [])
                     if read_candidate(w, m, ref)['request_file'] == request_ref]
        if available:
            candidate_ref, candidate = available[-1]
            require(candidate['request_file'] == request_ref and candidate['view_hash'] == fingerprint(view), '导出恢复原件不属于本输入')
            for ref in [candidate['view_file'], *candidate['files']]: verified_file(home, ref)
            science.validate_files(view, {key: verified_file(home, ref) for key, ref in candidate['formats'].items()})
        else:
            attempt = folder / 'attempts' / new_id('exportattempt'); attempt.mkdir(parents=True, exist_ok=False)
            view_path = attempt / 'view.json'; write_json(view_path, view)
            produced = science.export(view, attempt)
            formats = {key: file_record(home, path, 'system_export_' + key) for key, path in produced.items()}
            candidate = {'schema_version': VERSION, 'study_id': sid, 'request_file': request_ref,
                'view_file': file_record(home, view_path, 'system_export_view'), 'view_hash': fingerprint(view),
                'formats': formats, 'files': list(formats.values()), 'source_module': binding['module_id'],
                'source_run_id': binding['run_id'], 'input_key': binding['input_key'],
                'human_review_written': False, 'scientific_results_changed': False}
            with write_lock(w.root):
                current = w.load(sid); require(validate_request(w, sid, body) == binding, '导出完成前输入或人工意见已改变，原文件保留')
                path = attempt / 'candidate.json'; write_json(path, candidate)
                candidate_ref = file_record(home, path, 'system_export_candidate')
                current.setdefault(CANDIDATES, []).append(candidate_ref); w.save(current)
        with write_lock(w.root):
            m = w.load(sid); require(validate_request(w, sid, body) == binding, '导出期间输入或人工意见改变，原件保留，未发表')
            for ref, source in zip(request['implementation_files'], implementations):
                require(verified_file(home, ref).read_bytes() == source.read_bytes(), '导出期间实现改变，原件保留')
            # 同一明确请求即使被并发调用，也只发表一份不可覆盖的回执。
            for previous_ref in reversed(m.get(INDEX, [])):
                previous = read_record(w, m, previous_ref)
                if previous['request_file'] == request_ref:
                    return dict(previous, file=deepcopy(previous_ref), created=False)
            value = dict(candidate, export_id=new_id('systemexport'), candidate_file=deepcopy(candidate_ref), created_at=now())
            path = folder / 'records' / (value['export_id'] + '.json'); write_json(path, value); ref = file_record(home, path, 'system_export_record')
            m.setdefault(INDEX, []).append(ref); w.save(m)
        return dict(value, file=ref, created=True)
    except Exception as error:
        with write_lock(w.root):
            m = w.load(sid)
            if not m.get('trashed'):
                value = {'schema_version': VERSION, 'study_id': sid, 'request_file': request_ref, 'state': 'failed',
                    'error_type': type(error).__name__, 'error_zh': str(error), 'human_review_written': False,
                    'files': [file_record(home, path, 'system_export_failure_evidence') for path in sorted((folder / 'attempts').rglob('*')) if path.is_file()]}
                path = folder / (new_id('failure') + '.json'); write_json(path, value)
                m.setdefault(FAILURES, []).append(file_record(home, path, 'system_export_failure')); w.save(m)
        raise
