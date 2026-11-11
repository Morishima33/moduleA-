"""明确受体补救的独立正常A06分支；原准备、评分及人工意见保持。"""
from copy import deepcopy
import csv
from hashlib import sha256
import io
from pathlib import Path
import re

from contracts import ContractError, check_result, encoded, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, within, write_json, write_lock
from .analysis_plans import AnalysisPlanWorkflow
from .read_archive import ReadResultMixin

VERSION = 'A06.system_rescue.1'
PREPARATION_VERSION = 'A06.system_qualification_paths.1'
SCORING_VERSION = 'A06.system_scoring_paths.1'
REQUESTS = 'analysis_plan_receptor_rescue_requests'
FAILURES = 'analysis_plan_receptor_rescue_failures'
CHECKPOINTS = 'analysis_plan_receptor_rescue_checkpoints'
PUBLICATIONS = 'analysis_plan_receptor_rescue_publications'
ARCHIVES = 'analysis_plan_receptor_rescue_publication_archives'
FIELDS = {'request_id', 'expected_preparation_run_id', 'expected_scoring_run_id',
          'expected_input_hash', 'author', 'note', 'confirmed'}
SOURCE_MODULES = ('A00', 'A01', 'A02', 'A03', 'A03_SELECT', 'A04', 'A05', 'A06_PREP')


def _body(body):
    """请求只包含精确来源和明确决定，不接受工具路径、名单或科学参数覆盖。"""
    require(isinstance(body, dict) and set(body) == FIELDS, '受体补救请求字段错误')
    safe_id(body['request_id'], 'rescue')
    for key in ('expected_preparation_run_id', 'expected_scoring_run_id'):
        safe_id(body[key], 'run')
    require(isinstance(body['expected_input_hash'], str)
            and re.fullmatch(r'[0-9a-f]{64}', body['expected_input_hash']), '受体补救来源指纹格式错误')
    require(body['confirmed'] is True, '请明确确认本批受体补救')
    require(all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 2000 for key in ('author', 'note')),
            '请填写补救登记人和依据')


def _review(workflow, manifest, run):
    """最新人工暂存或退回始终阻断；无意见不伪造批准。"""
    value = workflow.latest_review(manifest, run['artifact_id'])
    require(not value or value['decision'] == 'approved', '受体补救来源已有明确人工暂存或退回')
    return deepcopy(value)


def source_binding(workflow, manifest, prep_id, score_id):
    """固定实际来源链和最新意见；不把新建A06的当前指针纳入自身输入。"""
    from .read_evidence import read_evidence_scope
    reader = read_source_workflow(workflow)
    with read_evidence_scope(workflow.root, manifest['study_id']) as evidence, reader.handoff_read_cache():
        return evidence.call(_source_binding, reader, manifest, prep_id, score_id)


def read_source_workflow(workflow):
    """仅同一只读核验采用既有I/O适配，科学校验器及普通写入实例保持。"""
    return workflow if isinstance(workflow, ReadResultMixin) else _RescueReadWorkflow(workflow.root, workflow.validators)


def _source_binding(workflow, manifest, prep_id, score_id):
    """在同一次完整核验中复用内存读取，下一次保存仍重新校验字节。"""
    require(not manifest.get('trashed'), '回收站研究只读')
    home = workflow.location(manifest['study_id'])
    require(manifest['current'].get('A06_PREP') == prep_id, '原准备版本已改变')
    prep = workflow.run(manifest, prep_id)
    score = workflow.run(manifest, score_id)
    require(prep['module_id'] == 'A06_PREP' and prep['config'].get('version') == PREPARATION_VERSION
            and score['module_id'] == 'A06' and score['config'].get('version') == SCORING_VERSION,
            '受体补救只接受本批原技术修订准备及原评分')
    require(workflow.approved(manifest, prep_id), '原准备尚未实际人工复核通过或已失效')
    require(score['parent_runs'] == {'A06_PREP': prep_id}, '原评分不是同一准备来源')
    source_review = workflow.latest_review(manifest, prep['artifact_id'])
    if score.get('parent_review_ids'):
        require(score['parent_review_ids'] == {'A06_PREP': source_review['review_id']}, '原评分的准备批准已改变')
    plan_ref = prep['inputs'].get('analysis_plan_file')
    fixed_ref = prep['inputs'].get('system_input_ref')
    require(plan_ref and fixed_ref and plan_ref == score['inputs'].get('analysis_plan_file')
            and fixed_ref == score['inputs'].get('system_input_ref'), '原评分、准备的方案或固定输入不同')
    require(plan_ref in manifest.get('analysis_plan_records', []), '原方案未登记到本研究')
    plan = read_json(verified_file(home, plan_ref))
    require(plan['study_id'] == manifest['study_id']
            and plan['plan_id'] == prep['inputs'].get('analysis_plan_id') == score['inputs'].get('analysis_plan_id')
            and plan['plan']['parameter_hash'] == prep['inputs'].get('analysis_parameter_hash')
            == score['inputs'].get('analysis_parameter_hash'), '原方案身份或冻结参数不同')
    verified_file(home, fixed_ref)
    runs, files, reviews = {}, {}, {}
    for module in SOURCE_MODULES:
        rid = manifest['current'].get(module)
        if not rid:
            continue
        run = workflow.run(manifest, rid)
        require(run['module_id'] == module and workflow.active(manifest, rid), '补救上游已失效：' + module)
        result = workflow.result(manifest, rid)
        require(result and result['outcome'] != 'failed', '补救上游尚未完整成功：' + module)
        runs[module] = rid
        files[module] = deepcopy(manifest['runs'][rid])
        reviews[module] = _review(workflow, manifest, run)
    require(all(key in runs for key in ('A00', 'A01', 'A02', 'A03', 'A03_SELECT', 'A04', 'A06_PREP')),
            '原补救来源链不完整')
    score_result = workflow.result(manifest, score_id)
    require(score_result and score_result['outcome'] == 'success', '原评分尚未完整成功，不能替代为补救输入')
    for module, rid in score['parent_runs'].items():
        require(manifest['current'].get(module) == rid, '原评分的上游指针已改变')
    return {'study_id': manifest['study_id'], 'current': runs, 'run_files': files, 'latest_reviews': reviews,
            'source_preparation_run_id': prep_id, 'source_scoring_run_id': score_id,
            'source_scoring_files': deepcopy(manifest['runs'][score_id]), 'source_scoring_review': _review(workflow, manifest, score),
            'analysis_plan_file': deepcopy(plan_ref), 'analysis_plan_id': plan['plan_id'],
            'analysis_parameter_hash': plan['plan']['parameter_hash'], 'system_input_ref': deepcopy(fixed_ref), 'trashed': False}


def _read_request(workflow, manifest, ref):
    """历史请求从不可变原件核验；实际执行资格另对当前来源重核。"""
    require(ref in manifest.get(REQUESTS, []), '受体补救请求未登记')
    home = workflow.location(manifest['study_id'])
    value = read_json(verified_file(home, ref))
    _body(value['request'])
    require(value['schema_version'] == VERSION and value['study_id'] == manifest['study_id']
            and value['request_hash'] == fingerprint(value['request']) and value['human_review_written'] is False
            and value['input_hash'] == fingerprint(value['binding']) == value['request']['expected_input_hash'],
            '原补救请求、来源或明确决定不同')
    expected_path = 'decisions/A06_rescue/' + value['request']['request_id'] + '/request.json'
    require(ref['path'] == expected_path, '受体补救请求位置不同')
    for item in value['implementation_files']:
        verified_file(home, item)
    return value


def validate_request(workflow, sid, body):
    """供HTTP排队及科学worker共同预检；只核事实，不导入科学工具或写入。"""
    _body(body)
    manifest = workflow.load(sid)
    require(not manifest.get('trashed'), '回收站研究只读')
    current = manifest['current'].get('A06')
    existing, superseding, registered_request = None, None, False
    for ref in manifest.get(REQUESTS, []):
        value = _read_request(workflow, manifest, ref)
        if value['request']['request_id'] == body['request_id']:
            require(value['request'] == body, '受体补救请求编号已用于其他内容')
            registered_request = True
    if current:
        candidate = workflow.run(manifest, current)
        if candidate['config'].get('version') == VERSION:
            request = _read_request(workflow, manifest, candidate['inputs']['rescue_request'])
            _review(workflow, manifest, candidate)
            if request['request']['request_id'] == body['request_id']:
                require(request['request'] == body, '原受体补救请求内容不同')
                existing = candidate
            else:
                require(not registered_request and not manifest['runs'][current].get('result_file'),
                        '已登记的旧请求或已完成补救不能另开覆盖')
                require(all(body[key] == request['request'][key] for key in
                            ('expected_preparation_run_id', 'expected_scoring_run_id'))
                        and workflow.active(manifest, current), '新补救请求必须绑定同一原准备、原评分及有效来源')
                superseding = request
        else:
            require(current == body['expected_scoring_run_id'] and workflow.active(manifest, current), '当前原评分版本已改变或失效')
    require(existing is not None or superseding is not None or current == body['expected_scoring_run_id'], '原评分当前指针已经改变')
    bound = source_binding(workflow, manifest, body['expected_preparation_run_id'], body['expected_scoring_run_id'])
    require(fingerprint(bound) == body['expected_input_hash'], '受体补救来源、方案或人工意见已改变，请刷新')
    if existing:
        require(existing['inputs']['source_binding'] == bound and workflow.active(manifest, current), '原补救运行已失效')
    if superseding:
        require(superseding['binding'] == bound, '新补救请求不能更换原来源或绕过人工决定变化')
    return manifest, bound, existing


def info(workflow, sid):
    """只读原来源和当前补救状态，不执行质控、评分或生成复核。"""
    manifest = workflow.load(sid)
    prep_id, score_id = manifest['current'].get('A06_PREP'), manifest['current'].get('A06')
    current, request, blockers, bound = None, None, [], None
    try:
        if score_id:
            candidate = workflow.run(manifest, score_id)
            if candidate['config'].get('version') == VERSION:
                current = candidate
                request = _read_request(workflow, manifest, candidate['inputs']['rescue_request'])
                prep_id = request['request']['expected_preparation_run_id']
                score_id = request['request']['expected_scoring_run_id']
                _review(workflow, manifest, candidate)
        require(prep_id and score_id, '请先完成本批原准备及原评分')
        bound = source_binding(workflow, manifest, prep_id, score_id)
        if current:
            require(bound == request['binding'] and workflow.active(manifest, current['run_id']), '原受体补救输入已经失效')
    except (ContractError, OSError, KeyError, TypeError, ValueError) as error:
        blockers.append(str(error))
    state = 'blocked' if blockers else ('incomplete' if current else 'ready')
    if current and manifest['runs'][current['run_id']].get('result_file') and not blockers:
        workflow.result(manifest, current['run_id'])
        state = 'complete'
        blockers.append('本批受体补救已归档，请核对新A06结果')
    return {'schema_version': VERSION, 'enabled': bool(bound and not blockers), 'blockers': blockers,
            'expected_preparation_run_id': prep_id, 'expected_scoring_run_id': score_id,
            'expected_input_hash': fingerprint(bound) if bound else None,
            'current_run_id': current['run_id'] if current else None, 'state': state,
            'request': deepcopy(request['request']) if request else None}


def _execution_binding(workflow, config, tools, repair_packages):
    """同一未完成请求同时固定科学配置、外壳字节、解释器和服务器工具位置。"""
    code = Path(__file__).resolve().parents[3]
    names = ('src/modulea/core/system_receptor_rescue.py', 'src/modulea/core/read_evidence.py',
             'src/modulea/core/read_archive.py', 'tools/run_system_receptor_rescue.py')
    implementations = {name: sha256((code / name).read_bytes()).hexdigest() for name in names}
    return {'configuration': deepcopy(config), 'code_version': workflow.code_version,
            'environment_version': fingerprint(workflow.environment), 'implementation_sha256': implementations,
            'tools_root': str(Path(tools).resolve()), 'repair_packages': str(Path(repair_packages).resolve())}


def _immutable(path, value):
    """原请求和实现只写一次，重试必须完全一致。"""
    if path.exists():
        require(read_json(path) == value, '原受体补救档案内容不同，不能覆盖')
    else:
        write_json(path, value)


def _checkpoint_key(key):
    """内部对象键只能是明确类型及安全编号，不能成为任意文件路径。"""
    require(isinstance(key, str) and re.fullmatch(r'(?:source|receptor|pair)_[A-Za-z0-9_-]{1,150}', key),
            '受体补救检查点对象键错误')


def read_checkpoint(workflow, sid, run_id, key):
    """只认研究索引中的不可变检查点，完整校验本对象历次尝试与文件。"""
    _checkpoint_key(key)
    manifest = workflow.load(sid)
    run = workflow.run(manifest, run_id)
    require(run['module_id'] == 'A06' and run['config'].get('version') == VERSION, '检查点不是本补救运行')
    home = workflow.location(sid)
    previous = None
    for ref in manifest.get(CHECKPOINTS, []):
        value = read_json(verified_file(home, ref))
        require(value.get('schema_version') == VERSION and value.get('study_id') == sid, '补救检查点归属不同')
        if value.get('run_id') != run_id or value.get('key') != key:
            continue
        require(value.get('config_hash') == run['config_hash'] and isinstance(value.get('payload'), dict)
                and isinstance(value.get('files'), list) and value.get('human_review_written') is False,
                '补救检查点配置、内容或人工标记不同')
        prefix = f'runs/A06/{run_id}/rescue_checkpoints/{key}/'
        require(ref['path'].startswith(prefix) and value.get('previous') == (previous[0] if previous else None),
                '补救检查点未按本对象原尝试链登记')
        if previous:
            old = previous[1]['payload']
            require(old.get('state') not in ('ready', 'completed') and old.get('retryable') is True,
                    '已完成或不可重试的补救对象不能追加替换')
        for item in value['files']:
            verified_file(home, item)
        previous = (deepcopy(ref), value)
    return previous


def append_checkpoint(workflow, sid, run_id, key, payload, files):
    """短锁登记实际对象产物；成功只复用，明确临时失败允许另存下一次尝试。"""
    _checkpoint_key(key)
    require(isinstance(payload, dict) and isinstance(files, list), '补救检查点必须提供真实对象内容和文件清单')
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        run = workflow.run(manifest, run_id)
        require(run['module_id'] == 'A06' and run['config'].get('version') == VERSION
                and not manifest['runs'][run_id].get('result_file') and workflow.active(manifest, run_id),
                '只有当前有效未完成的补救运行可登记对象检查点')
        request = _read_request(workflow, manifest, run['inputs']['rescue_request'])
        validate_request(workflow, sid, request['request'])
        from science_modules.a06 import system_receptor_rescue as science
        execution = request['execution_binding']
        prep = workflow.run(manifest, request['request']['expected_preparation_run_id'])
        arguments = {'tools': Path(execution['tools_root']), 'repair_packages': Path(execution['repair_packages'])}
        # 区域评分只执行本批已复制且逐件核验的Vina；原准备工具在准备、恢复及最终发表时完整重核。
        # 此处继续重核实际科学实现和Vina，不为每个区域重复散列未参与评分的全部准备依赖。
        if key.startswith('pair_') and 'runtime_signature' in run['config']:
            arguments['runtime_signature'] = run['config']['runtime_signature']
        config = science.configuration(prep, **arguments)
        require(_execution_binding(workflow, config, execution['tools_root'], execution['repair_packages']) == execution,
                '登记检查点前补救工具、配置或代码已改变')
        home = workflow.location(sid)
        for ref in files:
            verified_file(home, ref)
        previous = read_checkpoint(workflow, sid, run_id, key)
        if previous:
            if previous[1]['payload'] == payload and previous[1]['files'] == files:
                return previous[0]
            old = previous[1]['payload']
            require(old.get('state') not in ('ready', 'completed') and old.get('retryable') is True,
                    '已完成或不可重试对象的原检查点不同，不能覆盖')
        # 未登记旧文件不能仅凭目录和自填JSON恢复为成功对象。
        orphan = home / 'runs/A06' / run_id / 'rescue_checkpoints' / (key + '.json')
        require(not orphan.exists(), '发现未登记的补救检查点，不能作为恢复凭据')
        folder = home / 'runs/A06' / run_id / 'rescue_checkpoints' / key
        registered = {ref['path'] for ref in manifest.get(CHECKPOINTS, [])}
        if folder.exists():
            require(all(path.relative_to(home).as_posix() in registered for path in folder.glob('*.json')),
                    '发现未登记的补救对象尝试，须保留并核查')
        value = {'schema_version': VERSION, 'study_id': sid, 'run_id': run_id, 'key': key,
                 'payload': deepcopy(payload), 'files': deepcopy(files), 'config_hash': run['config_hash'],
                 'previous': previous[0] if previous else None, 'human_review_written': False, 'created_at': now()}
        path = folder / (new_id('checkpoint') + '.json')
        write_json(path, value)
        ref = file_record(home, path, 'receptor_rescue_checkpoint')
        manifest.setdefault(CHECKPOINTS, []).append(ref)
        workflow.save(manifest)
        return ref


def _publication_candidate(workflow, manifest, run):
    """只恢复已登记的完整发表候选，不凭孤立result.json猜成功。"""
    home = workflow.location(manifest['study_id'])
    found = []
    for ref in manifest.get(PUBLICATIONS, []):
        value = read_json(verified_file(home, ref))
        require(value.get('schema_version') == VERSION and value.get('study_id') == manifest['study_id'],
                '补救发表候选归属不同')
        if value.get('run_id') != run['run_id']:
            continue
        prefix = f'runs/A06/{run["run_id"]}/publication_attempts/'
        require(ref['path'].startswith(prefix) and Path(ref['path']).name == 'candidate.json'
                and value['config_hash'] == run['config_hash'] and value['request'] == run['inputs']['rescue_request']
                and value.get('human_review_written') is False
                and value['payload_hash'] == fingerprint(value['payload']), '补救发表候选与原运行或请求不同')
        payload = value['payload']
        require(set(payload) == {'summary', 'tables', 'anomalies', 'outcome', 'sources', 'figures'}, '补救发表候选字段错误')
        order = value['table_order']
        require(isinstance(order, list) and len(order) == len(set(order)) and set(order) == set(payload['tables']),
                '补救发表候选缺少原表格顺序')
        payload['tables'] = {name: payload['tables'][name] for name in order}
        check_result(payload['summary'], payload['tables'], payload['anomalies'], payload['outcome'])
        for item in payload['sources'] + payload['figures']:
            verified_file(home, item)
        found.append((ref, payload))
    require(len(found) <= 1, '同一补救运行存在竞争发表候选')
    return found[0] if found else None


def _csv_bytes(rows):
    """按原_finish的确定性CSV序列化核对中断文件，不重解释科学值。"""
    columns = sorted({key for row in rows for key in row})
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode('utf-8-sig')


def _archive_partial_publication(workflow, manifest, run, candidate_ref, payload):
    """仅保全本新运行与已登记候选一致的派生文件，再交原_finish发表。"""
    home = workflow.location(manifest['study_id'])
    folder = within(home, f'runs/A06/{run["run_id"]}')
    require(run['config'].get('version') == VERSION and not manifest['runs'][run['run_id']].get('result_file'),
            '只能恢复本补救运行尚未发布的派生文件')
    # 已登记移动计划可逐文件完成；移动中断也不丢原件或跨目录猜测。
    for plan_ref in manifest.get(ARCHIVES, []):
        plan = read_json(verified_file(home, plan_ref))
        if plan['run_id'] != run['run_id']:
            continue
        require(plan['candidate'] == candidate_ref, '补救发表保全计划来源不同')
        archive_path = verified_file(home, plan_ref).parent / 'archive.json'
        require(archive_path.parent.is_relative_to(folder / 'publication_attempts')
                and Path(plan_ref['path']).name == 'archive_plan.json', '补救保全计划不属于本次新运行')
        if archive_path.exists():
            archived = read_json(archive_path)
            require(archived['candidate'] == candidate_ref and archived['plan'] == plan_ref, '补救保全完成记录不同')
            for item in archived['files']:
                verified_file(home, item)
            continue
        moved = []
        for item in plan['moves']:
            source = within(home, item['source']['path'])
            target = within(home, item['target'])
            require(source.parent == folder and target.is_relative_to(folder)
                    and target.parent == archive_path.parent / 'files', '补救保全路径越界')
            if target.exists():
                require(not source.exists(), '补救保全过程存在冲突原件')
                expected = dict(item['source'], path=item['target'])
                verified_file(home, expected)
            else:
                verified_file(home, item['source'])
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)
            moved.append(file_record(home, target, 'receptor_rescue_partial_publication'))
        write_json(archive_path, {'schema_version': VERSION, 'study_id': manifest['study_id'], 'run_id': run['run_id'],
                                  'candidate': candidate_ref, 'plan': plan_ref, 'files': moved,
                                  'human_review_written': False, 'created_at': plan['created_at']})
    expected = []
    for name, rows in payload['tables'].items():
        expected.append((name + ('.json' if isinstance(rows, dict) else '.csv'),
                         encoded(rows) if isinstance(rows, dict) else _csv_bytes(rows),
                         'structured_table' if isinstance(rows, dict) else 'table'))
    expected.extend((('anomalies.json', encoded(payload['anomalies']), 'anomalies'),
                     ('execution.json', None, 'execution'), ('result.json', None, 'result')))
    present = [(name, raw, role) for name, raw, role in expected if (folder / name).exists()]
    if not present:
        return
    require([row[0] for row in present] == [row[0] for row in expected[:len(present)]],
            '未完成发表文件次序不符合原_finish，不能作为中断恢复')
    table_refs = []
    for name, raw, role in present:
        path = within(folder, name)
        require(path.parent == folder and path.is_file(), '补救派生文件路径越界')
        if raw is not None:
            require(path.read_bytes() == raw, '补救未完成发表文件校验失败，不能归档掩盖损坏')
        elif name == 'execution.json':
            value = read_json(path)
            require(set(value) == {'started_at', 'finished_at', 'outcome'} and value['started_at'] == run['created_at']
                    and value['outcome'] == payload['outcome'] and isinstance(value['finished_at'], str),
                    '补救未完成执行记录不是原运行')
        else:
            value = read_json(path)
            meta = {key: run[key] for key in ('schema_version', 'study_id', 'run_id', 'module_id', 'artifact_id',
                    'parent_artifact_ids', 'input_hash', 'config_hash', 'code_version', 'environment_version')}
            require(all(value.get(key) == item for key, item in meta.items())
                    and all(value.get(key) == item for key, item in payload.items())
                    and value.get('kind') == manifest['kind']
                    and value.get('files') == payload['sources'] + payload['figures'] + table_refs,
                    '补救未完成结果不是已登记发表候选')
            for item in value['files']:
                verified_file(home, item)
        if name != 'result.json':
            table_refs.append(file_record(home, path, role))
    archive_folder = within(folder, 'publication_attempts/' + new_id('publication'))
    moves = [{'source': file_record(home, folder / name, 'receptor_rescue_partial_publication'),
              'target': (archive_folder / 'files' / name).relative_to(home).as_posix()} for name, _, _ in present]
    plan = {'schema_version': VERSION, 'study_id': manifest['study_id'], 'run_id': run['run_id'],
            'candidate': candidate_ref, 'moves': moves, 'human_review_written': False, 'created_at': now()}
    plan_path = archive_folder / 'archive_plan.json'
    write_json(plan_path, plan)
    manifest.setdefault(ARCHIVES, []).append(file_record(home, plan_path, 'receptor_rescue_publication_archive'))
    workflow.save(manifest)
    # 只处理刚登记的固定文件路径；所有字节已在移动前完整核对。
    return _archive_partial_publication(workflow, manifest, run, candidate_ref, payload)


def execute(workflow, sid, body, *, tools, repair_packages, progress=None):
    """使用正常A06父批准链；只恢复同请求、同输入及同工具的未完成运行。"""
    _body(body)
    notify = progress or (lambda _: None)
    with write_lock(workflow.root):
        manifest, bound, existing = validate_request(workflow, sid, body)
        if existing and manifest['runs'][existing['run_id']].get('result_file'):
            return workflow.result(manifest, existing['run_id'])
        require(tools is not None and Path(tools).is_dir() and repair_packages is not None and Path(repair_packages).is_dir(),
                '尚未配置固定对接工具和有限修补依赖')
        from science_modules.a06 import system_receptor_rescue as science
        prep = workflow.run(manifest, body['expected_preparation_run_id'])
        config = science.configuration(prep, tools=tools, repair_packages=repair_packages)
        require(config.get('version') == VERSION, '受体补救科学协议不同')
        execution = _execution_binding(workflow, config, tools, repair_packages)
        home = workflow.location(sid)
        folder = within(home, 'decisions/A06_rescue/' + body['request_id'])
        path = folder / 'request.json'
        if existing:
            request = _read_request(workflow, manifest, existing['inputs']['rescue_request'])
            require(request['execution_binding'] == execution and request['configuration'] == config
                    and existing['config'] == config and existing['code_version'] == workflow.code_version
                    and existing['environment_version'] == execution['environment_version'],
                    '未完成受体补救的工具、配置或代码已改变，请使用新明确请求')
            run = existing
        else:
            implementations = []
            code = Path(__file__).resolve().parents[3]
            for name, digest in execution['implementation_sha256'].items():
                target = folder / 'implementation' / name
                raw = (code / name).read_bytes()
                require(sha256(raw).hexdigest() == digest, '受体补救实现读取期间已改变')
                if target.exists():
                    require(target.read_bytes() == raw, '原补救实现不同，不覆盖旧字节')
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as stream:
                        stream.write(raw)
                implementations.append(file_record(home, target, 'receptor_rescue_implementation'))
            record = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body),
                      'request_hash': fingerprint(body), 'binding': bound, 'input_hash': fingerprint(bound),
                      'configuration': config, 'execution_binding': execution, 'implementation_files': implementations,
                      'human_review_written': False, 'created_at': now()}
            if path.exists():
                previous = read_json(path)
                require(all(previous.get(key) == value for key, value in record.items() if key != 'created_at'),
                        '原受体补救请求、工具或输入不同')
                record = previous
            _immutable(path, record)
            request_ref = file_record(home, path, 'receptor_rescue_request')
            if request_ref not in manifest.get(REQUESTS, []):
                manifest.setdefault(REQUESTS, []).append(request_ref)
            inputs = {key: deepcopy(prep['inputs'][key]) for key in ('study_id', 'bound_a00', 'analysis_plan_id',
                      'analysis_plan_file', 'analysis_parameter_hash', 'system_input_ref')}
            inputs.update(source_preparation_run=deepcopy(manifest['runs'][body['expected_preparation_run_id']]['run_file']),
                          source_preparation_result=deepcopy(manifest['runs'][body['expected_preparation_run_id']]['result_file']),
                          source_scoring_run=deepcopy(manifest['runs'][body['expected_scoring_run_id']]['run_file']),
                          source_scoring_result=deepcopy(manifest['runs'][body['expected_scoring_run_id']]['result_file']),
                          rescue_request=request_ref, source_binding=deepcopy(bound))
            run = workflow._begin(manifest, 'A06', inputs, config, body['note'])
            workflow.save(manifest)
        candidate = _publication_candidate(workflow, manifest, run)
    try:
        if candidate:
            candidate_ref, payload = candidate
            summary, tables, figures = payload['summary'], payload['tables'], payload['figures']
        else:
            summary, tables, sources, figures = science.compute(workflow, sid, run, tools=tools,
                                                              repair_packages=repair_packages, progress=notify)
        with write_lock(workflow.root):
            manifest, current_binding, existing = validate_request(workflow, sid, body)
            require(existing and existing['run_id'] == run['run_id'] and current_binding == bound,
                    '受体补救发表前当前运行或来源已改变')
            current_config = science.configuration(prep, tools=tools, repair_packages=repair_packages)
            require(_execution_binding(workflow, current_config, tools, repair_packages) == execution,
                    '受体补救执行期间工具、配置或代码已改变')
            outcome = 'success' if summary['scored_pairs'] else 'failed'
            workflow.validators['A06'](run, summary, tables, [], outcome)
            if not candidate:
                references = [run['inputs'][key] for key in ('source_preparation_run', 'source_preparation_result',
                              'source_scoring_run', 'source_scoring_result', 'system_input_ref', 'rescue_request')]
                payload = {'summary': summary, 'tables': tables, 'sources': references + list(sources),
                           'figures': list(figures), 'anomalies': [], 'outcome': outcome}
                record = {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'], 'payload': payload,
                          'payload_hash': fingerprint(payload), 'request': run['inputs']['rescue_request'],
                          'table_order': list(tables),
                          'config_hash': run['config_hash'], 'human_review_written': False, 'created_at': now()}
                run_folder = within(home, 'runs/A06/' + run['run_id'])
                path = within(run_folder, 'publication_attempts/' + new_id('publication') + '/candidate.json')
                write_json(path, record)
                candidate_ref = file_record(home, path, 'receptor_rescue_publication_candidate')
                manifest.setdefault(PUBLICATIONS, []).append(candidate_ref)
                workflow.save(manifest)
            _archive_partial_publication(workflow, manifest, run, candidate_ref, payload)
            result = workflow._finish(manifest, run['run_id'], summary, tables, [], outcome,
                                      sources=payload['sources'], figures=figures)
            workflow.save(manifest)
            return result
    except Exception as error:
        with write_lock(workflow.root):
            manifest = workflow.load(sid)
            failure = {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'],
                       'request': run['inputs']['rescue_request'], 'state': 'failed',
                       'error_type': type(error).__name__, 'error_zh': str(error),
                       'human_review_written': False, 'created_at': now()}
            path = folder / 'failures' / (new_id('attempt') + '.json')
            write_json(path, failure)
            manifest.setdefault(FAILURES, []).append(file_record(home, path, 'receptor_rescue_failure'))
            workflow.save(manifest)
        raise


class SystemReceptorRescueWorkflow(AnalysisPlanWorkflow):
    """仅新增补救协议使用附加来源绑定；冻结工作流及旧版本分派保持。"""

    def analysis_plan_receptor_rescue_info(self, study_id):
        """读取本批原来源、阻塞和同请求恢复状态。"""
        return info(self, study_id)

    def execute_analysis_plan_receptor_rescue(self, study_id, body, *, tools, repair_packages, progress=None):
        """按明确请求追加正常A06结果，不更换或批准准备。"""
        return execute(self, study_id, body, tools=tools, repair_packages=repair_packages, progress=progress)

    def append_analysis_plan_receptor_rescue_checkpoint(self, study_id, run_id, key, payload, files):
        """保存一个真实完成或失败对象，不覆盖已登记尝试。"""
        return append_checkpoint(self, study_id, run_id, key, payload, files)

    def read_analysis_plan_receptor_rescue_checkpoint(self, study_id, run_id, key):
        """读取本研究本运行的最新合法对象尝试；未登记文件不用于恢复。"""
        return read_checkpoint(self, study_id, run_id, key)

    def _active(self, manifest, run_id):
        """正常父批准链加上本请求来源；不依赖已被新A06替换的原评分当前指针。"""
        run = self.run(manifest, run_id)
        if run['config'].get('version') != VERSION:
            return super()._active(manifest, run_id)
        try:
            if not super()._active(manifest, run_id):
                return False
            request = _read_request(self, manifest, run['inputs']['rescue_request'])
            body = request['request']
            bound = source_binding(self, manifest, body['expected_preparation_run_id'], body['expected_scoring_run_id'])
            require(run['parent_runs'] == {'A06_PREP': body['expected_preparation_run_id']}
                    and run['inputs']['source_binding'] == request['binding'] == bound
                    and run['config'] == request['configuration'], '受体补救原父链、来源或请求不同')
            require(run['inputs']['source_preparation_run'] == bound['run_files']['A06_PREP']['run_file']
                    and run['inputs']['source_preparation_result'] == bound['run_files']['A06_PREP']['result_file']
                    and run['inputs']['source_scoring_run'] == bound['source_scoring_files']['run_file']
                    and run['inputs']['source_scoring_result'] == bound['source_scoring_files']['result_file']
                    and run['inputs']['system_input_ref'] == bound['system_input_ref'], '受体补救原件绑定不同')
            return True
        except (ContractError, OSError, KeyError, TypeError, ValueError):
            return False


class _RescueReadWorkflow(ReadResultMixin, SystemReceptorRescueWorkflow):
    """只用于补救来源与原生产规范的短只读核验，不提交计算或写入研究。"""
