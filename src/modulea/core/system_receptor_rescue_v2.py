"""第二轮受体补救的明确正常A06交接；第一轮实现、结果和人工复核保持。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import FunctionType

from contracts import ContractError, fingerprint, require
from storage import file_record, now, read_json, verified_file, within, write_json, write_lock
from . import system_receptor_rescue as frozen
from . import receptor_source_packages as packages

VERSION = 'A06.system_rescue.2'
REQUESTS = 'analysis_plan_receptor_rescue_v2_requests'
FAILURES = 'analysis_plan_receptor_rescue_v2_failures'
CHECKPOINTS = 'analysis_plan_receptor_rescue_v2_checkpoints'
PUBLICATIONS = 'analysis_plan_receptor_rescue_v2_publications'
ARCHIVES = 'analysis_plan_receptor_rescue_v2_publication_archives'
BASELINES = {frozen.SCORING_VERSION, frozen.VERSION}


def partial_recovery(workflow, manifest, prep_id, score_id, original_binding):
    """确定性选择同来源最新未发表第一轮，并核对完整登记链；不依赖其current指针。"""
    home = workflow.location(manifest['study_id'])
    candidates = []
    for run_id, files in manifest['runs'].items():
        if files.get('result_file'):
            continue
        run = workflow.run(manifest, run_id)
        if run['module_id'] != 'A06' or run['config'].get('version') != frozen.VERSION:
            continue
        request = frozen._read_request(workflow, manifest, run['inputs']['rescue_request'])
        if (request['request']['expected_preparation_run_id'], request['request']['expected_scoring_run_id']) == (prep_id, score_id):
            candidates.append((run['created_at'], run_id, run, request))
    if not candidates:
        return None
    _, run_id, run, request = max(candidates, key=lambda row: (row[0], row[1]))
    frozen._review(workflow, manifest, run)
    prep = workflow.run(manifest, prep_id)
    review = workflow.latest_review(manifest, prep['artifact_id'])
    require(request['binding'] == run['inputs']['source_binding'] == original_binding
            and request['configuration'] == run['config'] and run['config_hash'] == fingerprint(run['config'])
            and run['input_hash'] == fingerprint({'inputs': run['inputs'], 'parents': run['parent_artifact_ids']})
            and run['parent_runs'] == {'A06_PREP': prep_id}
            and review and review['decision'] == 'approved'
            and run['parent_review_ids'] == {'A06_PREP': review['review_id']}
            and run['parent_artifact_ids'] == [prep['artifact_id']]
            and run['inputs']['source_preparation_run'] == manifest['runs'][prep_id]['run_file']
            and run['inputs']['source_preparation_result'] == manifest['runs'][prep_id]['result_file']
            and run['inputs']['source_scoring_run'] == manifest['runs'][score_id]['run_file']
            and run['inputs']['source_scoring_result'] == manifest['runs'][score_id]['result_file']
            and run['inputs']['system_input_ref'] == original_binding['system_input_ref'],
            '未完成第一轮的原来源、配置、父批准或请求已改变')
    checkpoints, previous = [], {}
    for ref in manifest.get(frozen.CHECKPOINTS, []):
        value = read_json(verified_file(home, ref))
        if value.get('run_id') != run_id:
            continue
        key = value.get('key')
        frozen._checkpoint_key(key)
        require(value.get('schema_version') == frozen.VERSION and value.get('study_id') == manifest['study_id']
                and value.get('config_hash') == run['config_hash'] and value.get('human_review_written') is False
                and isinstance(value.get('payload'), dict) and isinstance(value.get('files'), list)
                and ref['path'].startswith(f'runs/A06/{run_id}/rescue_checkpoints/{key}/')
                and value.get('previous') == (previous[key][0] if key in previous else None),
                '未完成第一轮检查点的归属、对象或配置不同')
        if key in previous:
            old = previous[key][1]['payload']
            require(old.get('state') not in ('ready', 'completed') and old.get('retryable') is True,
                    '第一轮已成功或稳定NA对象不能在历史链中被替换')
        for evidence in value['files']:
            verified_file(home, evidence)
        checkpoints.append(deepcopy(ref))
        previous[key] = (ref, value)
    # 按冻结读取器相同的previous/成功不可覆盖规则单遍核验；孤立目录不参与恢复。
    return {'run_id': run_id, 'run_files': deepcopy(manifest['runs'][run_id]), 'checkpoint_refs': checkpoints}


def source_binding(workflow, manifest, prep_id, score_id):
    """固定基线及原评分身份，排除后来新A06指针，仅加入本来源的已登记官方包。"""
    baseline = workflow.run(manifest, score_id)
    require(baseline['module_id'] == 'A06' and baseline['config'].get('version') in BASELINES,
            '第二轮补救基线必须为原路径评分或完整第一轮补救')
    require(baseline['parent_runs'] == {'A06_PREP': prep_id}, '第二轮基线的原准备不同')
    baseline_result = workflow.result(manifest, score_id)
    require(baseline_result and baseline_result['outcome'] == 'success', '第二轮来源评分尚未完整成功')
    original_id = score_id
    if baseline['config']['version'] == frozen.VERSION:
        request = frozen._read_request(workflow, manifest, baseline['inputs']['rescue_request'])
        require(request['request']['expected_preparation_run_id'] == prep_id,
                '第一轮基线不是同一原准备')
        original_id = request['request']['expected_scoring_run_id']
    base = frozen.source_binding(workflow, manifest, prep_id, original_id)
    if baseline['config']['version'] == frozen.VERSION:
        require(baseline['inputs']['source_binding'] == request['binding'] == base,
                '第一轮基线原绑定已经改变')
    prep = workflow.run(manifest, prep_id)
    require(baseline['inputs']['system_input_ref'] == prep['inputs']['system_input_ref']
            and baseline['inputs']['analysis_plan_file'] == prep['inputs']['analysis_plan_file'],
            '第二轮基线改变了原固定范围或方案')
    bound = {'original': base, 'baseline_run_id': score_id,
             'baseline_files': deepcopy(manifest['runs'][score_id]),
             'baseline_review': frozen._review(workflow, manifest, baseline),
             'baseline_original_scoring_run_id': original_id,
             'source_preparation_run_id': prep_id, 'study_id': manifest['study_id'],
             'partial_recovery': partial_recovery(workflow, manifest, prep_id, score_id, base)
                 if baseline['config']['version'] == frozen.SCORING_VERSION else None,
             'official_source_packages': packages.for_baseline(workflow.location(manifest['study_id']), manifest,
                                                               prep_id, score_id)}
    return bound


def _read_request(workflow, manifest, ref):
    """第二版确认只读取自己的不可变登记，不把第一版请求静默升级。"""
    require(ref in manifest.get(REQUESTS, []), '第二轮受体补救请求未登记')
    value = read_json(verified_file(workflow.location(manifest['study_id']), ref))
    frozen._body(value['request'])
    require(value['schema_version'] == VERSION and value['study_id'] == manifest['study_id']
            and value['human_review_written'] is False and value['request_hash'] == fingerprint(value['request'])
            and value['input_hash'] == fingerprint(value['binding']) == value['request']['expected_input_hash']
            and ref['path'] == 'decisions/A06_rescue_v2/' + value['request']['request_id'] + '/request.json',
            '第二轮补救确认、指纹或归属不同')
    for item in value['implementation_files']:
        verified_file(workflow.location(manifest['study_id']), item)
    return value


def validate_request(workflow, sid, body):
    """允许完整第一轮后明确新请求；未完成运行只按精确原绑定恢复或另开。"""
    frozen._body(body)
    manifest = workflow.load(sid)
    require(not manifest.get('trashed'), '回收站研究只读')
    require(manifest['current'].get('A06_PREP') == body['expected_preparation_run_id'],
            '第二轮原准备已改变，请刷新后重新读取资格')
    current_id = manifest['current'].get('A06')
    require(current_id, '尚无原评分基线')
    current = workflow.run(manifest, current_id)
    known = False
    for key, reader in ((REQUESTS, _read_request), (frozen.REQUESTS, frozen._read_request)):
        for ref in manifest.get(key, []):
            value = reader(workflow, manifest, ref)
            if value['request']['request_id'] == body['request_id']:
                require(key == REQUESTS and value['request'] == body, '请求编号已被原补救内容使用')
                known = True
    existing = None
    if current['config'].get('version') == VERSION:
        previous = _read_request(workflow, manifest, current['inputs']['rescue_request'])
        frozen._review(workflow, manifest, current)
        if previous['request'] == body:
            existing = current
        else:
            require(not known and not manifest['runs'][current_id].get('result_file')
                    and workflow.active(manifest, current_id)
                    and all(previous['request'][key] == body[key] for key in
                            ('expected_preparation_run_id', 'expected_scoring_run_id')),
                    '第二轮已有不同或完整结果，不能覆盖')
    elif current['config'].get('version') == frozen.VERSION and not manifest['runs'][current_id].get('result_file'):
        previous = frozen._read_request(workflow, manifest, current['inputs']['rescue_request'])
        require(not known and workflow.active(manifest, current_id)
                and all(previous['request'][key] == body[key] for key in
                        ('expected_preparation_run_id', 'expected_scoring_run_id')),
                '另开第二轮必须绑定中断第一轮相同的原准备及原评分')
    else:
        require(current_id == body['expected_scoring_run_id'] and workflow.active(manifest, current_id),
                '第二轮来源当前评分已改变或失效')
    bound = source_binding(workflow, manifest, body['expected_preparation_run_id'], body['expected_scoring_run_id'])
    require(fingerprint(bound) == body['expected_input_hash'], '第二轮来源、官方包或人工意见已改变，请刷新')
    if existing:
        require(existing['inputs']['source_binding'] == bound and workflow.active(manifest, current_id),
                '第二轮运行的原来源已失效')
    return manifest, bound, existing


def info(workflow, sid):
    """读取第二轮当前资格；从完整第一轮或明确中断来源建立输入，不执行科学工具。"""
    manifest = workflow.load(sid)
    prep_id, score_id = manifest['current'].get('A06_PREP'), manifest['current'].get('A06')
    current, request, bound, blockers = None, None, None, []
    try:
        require(prep_id and score_id, '请先完成原准备及原评分')
        candidate = workflow.run(manifest, score_id)
        version = candidate['config'].get('version')
        if version == VERSION:
            current = candidate
            request = _read_request(workflow, manifest, candidate['inputs']['rescue_request'])
            score_id = request['request']['expected_scoring_run_id']
            prep_id = request['request']['expected_preparation_run_id']
            frozen._review(workflow, manifest, candidate)
        elif version == frozen.VERSION and not manifest['runs'][score_id].get('result_file'):
            old = frozen._read_request(workflow, manifest, candidate['inputs']['rescue_request'])
            require(workflow.active(manifest, score_id), '中断第一轮来源已失效')
            score_id = old['request']['expected_scoring_run_id']
        bound = source_binding(workflow, manifest, prep_id, score_id)
        if current:
            require(bound == request['binding'] and workflow.active(manifest, current['run_id']), '第二轮来源已失效')
    except (ContractError, OSError, KeyError, TypeError, ValueError) as error:
        blockers.append(str(error))
    state = 'blocked' if blockers else ('incomplete' if current else 'ready')
    if current and manifest['runs'][current['run_id']].get('result_file') and not blockers:
        workflow.result(manifest, current['run_id'])
        state = 'complete'
        blockers.append('第二轮受体补救已归档，等待独立复核')
    return {'schema_version': VERSION, 'enabled': bool(bound and not blockers), 'blockers': blockers,
            'expected_preparation_run_id': prep_id, 'expected_scoring_run_id': score_id,
            'expected_input_hash': fingerprint(bound) if bound else None, 'state': state,
            'current_run_id': current['run_id'] if current else None,
            'request': deepcopy(request['request']) if request else None}


def _execution_binding(workflow, config, tools, repair_packages):
    """固定独立第二轮与复用第一轮的真实代码；现有实现只读。"""
    code = Path(__file__).resolve().parents[3]
    names = ('src/modulea/core/system_receptor_rescue_v2.py', 'src/modulea/core/receptor_source_packages.py',
             'src/modulea/core/system_receptor_rescue.py', 'src/modulea/core/read_evidence.py',
             'src/modulea/core/read_archive.py', 'tools/run_system_receptor_rescue_v2.py')
    return {'configuration': deepcopy(config), 'code_version': workflow.code_version,
            'environment_version': fingerprint(workflow.environment),
            'implementation_sha256': {name: sha256((code / name).read_bytes()).hexdigest() for name in names},
            'tools_root': str(Path(tools).resolve()), 'repair_packages': str(Path(repair_packages).resolve())}


# 仅把无科学行为变化的不可变归档实现接入新版本私有namespace，原模块globals不修改。
_scope = dict(vars(frozen), VERSION=VERSION, REQUESTS=REQUESTS, FAILURES=FAILURES, CHECKPOINTS=CHECKPOINTS,
              PUBLICATIONS=PUBLICATIONS, ARCHIVES=ARCHIVES, _read_request=_read_request)
for _name in ('read_checkpoint', '_publication_candidate', '_archive_partial_publication'):
    _source = getattr(frozen, _name)
    _scope[_name] = FunctionType(_source.__code__, _scope, _name, _source.__defaults__, _source.__closure__)
read_checkpoint = _scope['read_checkpoint']


def append_checkpoint(workflow, sid, run_id, key, payload, files):
    """第二轮对象使用独立登记链；真实工具及来源重核后才短锁发表。"""
    frozen._checkpoint_key(key)
    require(isinstance(payload, dict) and isinstance(files, list), '第二轮检查点内容或文件清单错误')
    with write_lock(workflow.root):
        m = workflow.load(sid)
        run = workflow.run(m, run_id)
        require(run['config'].get('version') == VERSION and not m['runs'][run_id].get('result_file')
                and workflow.active(m, run_id), '第二轮检查点只能写入当前有效未完成运行')
        request = _read_request(workflow, m, run['inputs']['rescue_request'])
        validate_request(workflow, sid, request['request'])
        from science_modules.a06 import system_receptor_rescue_v2 as science
        execution = request['execution_binding']
        arguments = {'tools': Path(execution['tools_root']), 'repair_packages': Path(execution['repair_packages'])}
        if key.startswith('pair_') and 'runtime_signature' in run['config']:
            arguments['runtime_signature'] = run['config']['runtime_signature']
        prep = workflow.run(m, request['request']['expected_preparation_run_id'])
        config = science.configuration(prep, **arguments)
        require(_execution_binding(workflow, config, execution['tools_root'], execution['repair_packages']) == execution,
                '第二轮检查点的代码、工具或配置已改变')
        home = workflow.location(sid)
        for item in files:
            verified_file(home, item)
        previous = read_checkpoint(workflow, sid, run_id, key)
        if previous:
            if previous[1]['payload'] == payload and previous[1]['files'] == files:
                return previous[0]
            old = previous[1]['payload']
            require(old.get('state') not in ('ready', 'completed') and old.get('retryable') is True,
                    '第二轮已完成或稳定NA对象不能覆盖')
        folder = within(home, f'runs/A06/{run_id}/rescue_checkpoints/{key}')
        registered = {ref['path'] for ref in m.get(CHECKPOINTS, [])}
        require(not folder.exists() or all(path.relative_to(home).as_posix() in registered for path in folder.glob('*.json')),
                '第二轮存在未登记的检查点，不能借用')
        value = {'schema_version': VERSION, 'study_id': sid, 'run_id': run_id, 'key': key,
                 'payload': deepcopy(payload), 'files': deepcopy(files), 'config_hash': run['config_hash'],
                 'previous': previous[0] if previous else None, 'human_review_written': False, 'created_at': now()}
        path = folder / (frozen.new_id('checkpoint') + '.json')
        write_json(path, value)
        ref = file_record(home, path, 'receptor_rescue_v2_checkpoint')
        m.setdefault(CHECKPOINTS, []).append(ref)
        workflow.save(m)
        return ref


def execute(workflow, sid, body, *, tools, repair_packages, progress=None):
    """正常父批准链追加第二轮A06，精确恢复与归档保全复用原实现。"""
    frozen._body(body)
    notify = progress or (lambda _: None)
    with write_lock(workflow.root):
        m, bound, existing = validate_request(workflow, sid, body)
        if existing and m['runs'][existing['run_id']].get('result_file'):
            return workflow.result(m, existing['run_id'])
        require(tools is not None and Path(tools).is_dir() and repair_packages is not None and Path(repair_packages).is_dir(),
                '第二轮未配置固定工具或有限修补依赖')
        from science_modules.a06 import system_receptor_rescue_v2 as science
        prep = workflow.run(m, body['expected_preparation_run_id'])
        config = science.configuration(prep, tools=tools, repair_packages=repair_packages)
        require(config['version'] == VERSION, '第二轮科学协议错误')
        execution = _execution_binding(workflow, config, tools, repair_packages)
        home = workflow.location(sid)
        folder = within(home, 'decisions/A06_rescue_v2/' + body['request_id'])
        if existing:
            request = _read_request(workflow, m, existing['inputs']['rescue_request'])
            require(request['execution_binding'] == execution and existing['config'] == config
                    and existing['code_version'] == workflow.code_version
                    and existing['environment_version'] == fingerprint(workflow.environment),
                    '第二轮原代码、工具或配置已改变，请另行明确请求')
            run = existing
        else:
            snapshots = []
            code = Path(__file__).resolve().parents[3]
            for name, digest in execution['implementation_sha256'].items():
                raw = (code / name).read_bytes()
                require(sha256(raw).hexdigest() == digest, '第二轮实现读取期间已改变')
                target = folder / 'implementation' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    require(target.read_bytes() == raw, '第二轮实现已有不同原字节')
                else:
                    with target.open('xb') as stream:
                        stream.write(raw)
                snapshots.append(file_record(home, target, 'receptor_rescue_v2_implementation'))
            value = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body), 'request_hash': fingerprint(body),
                     'binding': bound, 'input_hash': fingerprint(bound), 'configuration': config,
                     'execution_binding': execution, 'implementation_files': snapshots,
                     'human_review_written': False, 'created_at': now()}
            path = folder / 'request.json'
            if path.exists():
                old = read_json(path)
                require(all(old.get(key) == value[key] for key in value if key != 'created_at'), '原第二轮请求内容不同')
                value = old
            frozen._immutable(path, value)
            ref = file_record(home, path, 'receptor_rescue_v2_request')
            m.setdefault(REQUESTS, []).append(ref)
            inputs = {key: deepcopy(prep['inputs'][key]) for key in ('study_id', 'bound_a00', 'analysis_plan_id',
                      'analysis_plan_file', 'analysis_parameter_hash', 'system_input_ref')}
            inputs.update(source_preparation_run=deepcopy(m['runs'][body['expected_preparation_run_id']]['run_file']),
                          source_preparation_result=deepcopy(m['runs'][body['expected_preparation_run_id']]['result_file']),
                          source_scoring_run=deepcopy(m['runs'][body['expected_scoring_run_id']]['run_file']),
                          source_scoring_result=deepcopy(m['runs'][body['expected_scoring_run_id']]['result_file']),
                          rescue_request=ref, source_binding=deepcopy(bound),
                          official_source_packages=deepcopy(bound['official_source_packages']))
            run = workflow._begin(m, 'A06', inputs, config, body['note'])
            workflow.save(m)
        candidate = _scope['_publication_candidate'](workflow, m, run)
    try:
        if candidate:
            candidate_ref, payload = candidate
            summary, tables, figures = payload['summary'], payload['tables'], payload['figures']
        else:
            summary, tables, sources, figures = science.compute(workflow, sid, run, tools=tools,
                                                              repair_packages=repair_packages, progress=notify)
        with write_lock(workflow.root):
            m, current_bound, active = validate_request(workflow, sid, body)
            require(active and active['run_id'] == run['run_id'] and current_bound == bound, '第二轮发表前来源已改变')
            current_config = science.configuration(prep, tools=tools, repair_packages=repair_packages)
            require(_execution_binding(workflow, current_config, tools, repair_packages) == execution,
                    '第二轮发表前工具或代码已改变')
            outcome = 'success' if summary['scored_pairs'] else 'failed'
            workflow.validators['A06'](run, summary, tables, [], outcome)
            if not candidate:
                refs = [run['inputs'][key] for key in ('source_preparation_run', 'source_preparation_result',
                        'source_scoring_run', 'source_scoring_result', 'system_input_ref', 'rescue_request')]
                payload = {'summary': summary, 'tables': tables, 'sources': refs + list(sources),
                           'figures': list(figures), 'anomalies': [], 'outcome': outcome}
                record = {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'], 'payload': payload,
                          'payload_hash': fingerprint(payload), 'request': run['inputs']['rescue_request'],
                          'table_order': list(tables), 'config_hash': run['config_hash'],
                          'human_review_written': False, 'created_at': now()}
                path = within(home, f'runs/A06/{run["run_id"]}/publication_attempts/{frozen.new_id("publication")}/candidate.json')
                write_json(path, record)
                candidate_ref = file_record(home, path, 'receptor_rescue_v2_publication_candidate')
                m.setdefault(PUBLICATIONS, []).append(candidate_ref)
                workflow.save(m)
            _scope['_archive_partial_publication'](workflow, m, run, candidate_ref, payload)
            result = workflow._finish(m, run['run_id'], summary, tables, [], outcome, sources=payload['sources'], figures=figures)
            workflow.save(m)
            return result
    except Exception as error:
        with write_lock(workflow.root):
            m = workflow.load(sid)
            path = folder / 'failures' / (frozen.new_id('attempt') + '.json')
            write_json(path, {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'],
                'request': run['inputs']['rescue_request'], 'state': 'failed', 'error_type': type(error).__name__,
                'error_zh': str(error), 'human_review_written': False, 'created_at': now()})
            m.setdefault(FAILURES, []).append(file_record(home, path, 'receptor_rescue_v2_failure'))
            workflow.save(m)
        raise


class SystemReceptorRescueV2Workflow(frozen.SystemReceptorRescueWorkflow):
    """第二轮明确分派，未匹配版本继续冻结第一轮和原工作流。"""
    def analysis_plan_receptor_rescue_v2_info(self, study_id):
        return info(self, study_id)

    def execute_analysis_plan_receptor_rescue_v2(self, study_id, body, *, tools, repair_packages, progress=None):
        return execute(self, study_id, body, tools=tools, repair_packages=repair_packages, progress=progress)

    def register_analysis_plan_receptor_source_package(self, study_id, body, staging, artifacts):
        return packages.register(self, study_id, body, staging, artifacts)

    def append_analysis_plan_receptor_rescue_v2_checkpoint(self, study_id, run_id, key, payload, files):
        return append_checkpoint(self, study_id, run_id, key, payload, files)

    def read_analysis_plan_receptor_rescue_v2_checkpoint(self, study_id, run_id, key):
        return read_checkpoint(self, study_id, run_id, key)

    def append_analysis_plan_receptor_rescue_checkpoint(self, study_id, run_id, key, payload, files):
        run = self.run(self.load(study_id), run_id)
        if run['config'].get('version') == VERSION:
            return append_checkpoint(self, study_id, run_id, key, payload, files)
        return super().append_analysis_plan_receptor_rescue_checkpoint(study_id, run_id, key, payload, files)

    def read_analysis_plan_receptor_rescue_checkpoint(self, study_id, run_id, key):
        run = self.run(self.load(study_id), run_id)
        if run['config'].get('version') == VERSION:
            return read_checkpoint(self, study_id, run_id, key)
        return super().read_analysis_plan_receptor_rescue_checkpoint(study_id, run_id, key)

    def _active(self, manifest, run_id):
        run = self.run(manifest, run_id)
        if run['config'].get('version') != VERSION:
            return super()._active(manifest, run_id)
        try:
            if not super()._active(manifest, run_id):
                return False
            request = _read_request(self, manifest, run['inputs']['rescue_request'])
            body = request['request']
            bound = source_binding(self, manifest, body['expected_preparation_run_id'], body['expected_scoring_run_id'])
            require(bound == request['binding'] == run['inputs']['source_binding']
                    and request['configuration'] == run['config']
                    and run['parent_runs'] == {'A06_PREP': body['expected_preparation_run_id']}
                    and run['inputs']['source_scoring_run'] == bound['baseline_files']['run_file']
                    and run['inputs']['source_scoring_result'] == bound['baseline_files']['result_file']
                    and run['inputs']['official_source_packages'] == bound['official_source_packages'],
                    '第二轮绑定、原准备或官方来源不同')
            return True
        except (ContractError, OSError, KeyError, ValueError, TypeError):
            return False
