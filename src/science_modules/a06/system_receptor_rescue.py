"""同批受体探索补救：复用既定路线、保留原评分，并另存完整矩阵。"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil

from contracts import fingerprint, require
from storage import file_record, new_id, read_json, verified_file, write_json

from .automatic_coverage_rules import POLICY as COVERAGE_POLICY
from .system_scoring_paths import _scope as _SCORING_SCOPE

# 技术路径版本的冻结评分规范主体；只用于本次只读namespace绑定，原模块保持。
SCORING_READ_FACTORY = _SCORING_SCOPE['validator']


VERSION = 'A06.system_rescue.1'
POLICY = dict(deepcopy(COVERAGE_POLICY), version=VERSION,
              scope='current_preparation_unavailable_receptors_only',
              existing_scores='verify_and_retain_original_execution',
              compound_scope='retain_original_prepared_and_unavailable_records',
              cpu_per_pair=1)
CODE_NAMES = (
    'science_modules/a06/system_receptor_rescue.py',
    'science_modules/a06/system_rescue_display.py',
    'science_modules/a06/system_rescue_runtime.py',
    'science_modules/a06/automatic_coverage_prepare.py',
    'science_modules/a06/automatic_coverage_sources.py',
    'science_modules/a06/automatic_coverage_rules.py',
    'science_modules/a06/reference_sources.py',
    'science_modules/a06/trial_prepare.py',
    'science_modules/a06/trial_rules.py',
    'science_modules/a06/coverage_geometry.py',
    'science_modules/a06/quality_engine.py',
    'science_modules/a06/plan_score_pair.py',
    'science_modules/a06/plan_quality_engine_v2.py',
    'science_modules/a06/two_pass.py',
    'science_modules/a06/automatic_engine.py',
    'science_modules/a06/automatic_sources.py',
    'science_modules/a06/automatic_rules.py',
    'science_modules/a06/plan_scoring_inputs.py',
    'science_modules/a06/reference_rules.py',
    'science_modules/a06/matrix_palette.py',
    'docking_p2rank.py', 'docking_receptor.py', 'docking_redocking.py',
    'docking_top10_execute.py', 'tools/repair_a06_trial.py',
)


def _code_file(code, name):
    """科学模块按src相对路径保存，独立工具脚本按仓库相对路径保存。"""
    return code / name if name.startswith('tools/') else code / 'src' / name


def configuration(preparation, *, tools, repair_packages, runtime_signature=None):
    """固定实际工具、实现和既有修补依赖，重试遇到变化就拒绝。"""
    from .system_scoring import check_tools
    from .system_rescue_runtime import signature
    binary = check_tools(Path(tools))
    packages = Path(repair_packages)
    require(packages.is_dir(), '未配置已确认的有限侧链修补依赖')
    metadata = sorted(packages.glob('*.dist-info/METADATA'))
    require(metadata, '有限修补依赖缺少版本元数据')
    code = Path(__file__).resolve().parents[3]
    implementations = {name: hashlib.sha256(_code_file(code, name).read_bytes()).hexdigest()
                       for name in CODE_NAMES}
    return {'version': VERSION, 'policy': deepcopy(POLICY),
            'source_preparation_config': deepcopy(preparation['config']),
            'vina_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'implementation_sha256': implementations,
            'runtime_signature': deepcopy(runtime_signature) if runtime_signature is not None
                                 else signature(Path(tools), packages),
            'repair_metadata': {path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in metadata},
            'vina_parameters': deepcopy(preparation['config']['vina_parameters']),
            'cpu_per_pair': 1, 'timeout_seconds': 1800}


def source_data(workflow, manifest, preparation_run_id, scoring_run_id):
    """只从明确的同批原准备和评分取固定名单，回溯归档事实而不猜目录。"""
    home = workflow.location(manifest['study_id'])
    preparation = workflow.run(manifest, preparation_run_id)
    scoring = workflow.run(manifest, scoring_run_id)
    require(preparation['module_id'] == 'A06_PREP' and scoring['module_id'] == 'A06'
            and preparation['study_id'] == scoring['study_id'] == manifest['study_id']
            and scoring['parent_runs'].get('A06_PREP') == preparation_run_id,
            '补救来源准备、评分或研究不同')
    prepared = workflow.result(manifest, preparation_run_id)
    scored = workflow.result(manifest, scoring_run_id)
    require(prepared and scored, '补救来源尚未完整归档')
    fixed_record = read_json(verified_file(home, preparation['inputs']['system_input_ref']))
    fixed = fixed_record['payload']
    require(fixed_record['study_id'] == manifest['study_id']
            and fixed_record['stage'] == 'A06_INPUT'
            and fixed['input_key'] == prepared['summary']['input_key'] == scored['summary']['input_key'],
            '补救来源未绑定同一批固定范围')
    qualification = read_json(verified_file(home, prepared['tables']['preparation_packet'][0]))
    fact = qualification
    seen = set()
    while 'connection' not in fact:
        reference = fact.get('source_preparation_fact')
        require(reference and fingerprint(reference) not in seen, '原准备事实引用缺失或循环')
        seen.add(fingerprint(reference))
        fact = read_json(verified_file(home, reference))
    scoring_packet = read_json(verified_file(home, scored['tables']['scoring_packet'][0]))
    compound_ids = [row['compound_id'] for row in fixed['compounds']]
    target_ids = [row['target_id'] for row in fixed['receptors']]
    require(compound_ids == [row['compound_id'] for row in fact['compounds']]
            and target_ids == [row['target_id'] for row in qualification['receptors']],
            '原准备事实对象或次序与固定名单不同')
    pairs = scoring_packet['pairs']
    require([(row['compound_id'], row['target_id']) for row in pairs]
            == [(compound, target) for compound in compound_ids for target in target_ids],
            '原评分矩阵缺项、重复或次序不同')
    published = scored['tables']['plan_scoring_pairs']
    columns = ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')
    require(all(tuple(left.get(key) for key in columns) == tuple(right.get(key) for key in columns)
                for left, right in zip(pairs, published)) and len(pairs) == len(published),
            '原评分包与发布表不一致')
    targets = [row['target_id'] for row in prepared['tables']['receptor_preparation']
               if row['state'] != 'ready']
    return {'fixed': fixed, 'fact': fact, 'qualification': qualification,
            'preparation': preparation, 'preparation_result': prepared,
            'scoring': scoring, 'scoring_result': scored,
            'scoring_packet': scoring_packet, 'targets': targets}


def execution_folder(path):
    """先建立父目录，再沿项目既有短路径适配传给原生结构工具。"""
    from .plan_quality_engine_v2 import tool_path
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return Path(tool_path(path)) if os.name == 'nt' else path


def archive_files(home, value):
    """复用既有文件引用提取，逐件核对重复引用的字节身份。"""
    from modulea.core.system_preparation_checkpoints import files
    rows = files(value)
    for reference in rows:
        verified_file(home, reference)
    return rows


def _source_uniprot(home, source, target_id):
    """优先采用原连接明确编号，缺失时回查同批已归档HGNC响应。"""
    row = next(row for row in source['fact']['connection']['receptors']
               if row['target_id'] == target_id)
    if row.get('uniprot'):
        return row['uniprot']
    candidates = row.get('candidates', [])
    if candidates:
        return candidates[0]['spec']['uniprot']
    from urllib.parse import unquote
    for reference in source['fact']['files']:
        if not reference['path'].endswith('_request.json'):
            continue
        request = read_json(verified_file(home, reference))
        if request.get('state') != 'success' or not unquote(request.get('url', '')).endswith(
                '/fetch/hgnc_id/' + target_id):
            continue
        docs = read_json(verified_file(home, request['file'])).get('response', {}).get('docs', [])
        require(len(docs) == 1 and docs[0].get('hgnc_id') == target_id
                and len(docs[0].get('uniprot_ids', [])) == 1, '原HGNC没有唯一稳定蛋白编号')
        return docs[0]['uniprot_ids'][0]
    require(False, '原批缺少可核对的HGNC—UniProt对应证据')


def _checkpoint(workflow, sid, run, key):
    """读取登记检查点，不以孤立目录或同名文件推断已完成。"""
    return workflow.read_analysis_plan_receptor_rescue_checkpoint(sid, run['run_id'], key)


def _save_checkpoint(workflow, sid, run, key, payload, files):
    """仅把当前运行已落盘的完整对象登记进现有研究索引。"""
    return workflow.append_analysis_plan_receptor_rescue_checkpoint(
        sid, run['run_id'], key, payload, files)


def _prepare_target(workflow, sid, run, source, original, folder, tools, repair_packages, progress):
    """保留原对象，按旧方案接续独立实验结构、有限修补和已发布模型。"""
    from . import automatic_coverage_prepare as rescue
    from .reference_sources import Fetcher, receptor_sources
    home = workflow.location(sid)
    target_id = original['target_id']
    key = 'receptor_' + target_id.replace(':', '_')
    saved = _checkpoint(workflow, sid, run, key)
    if saved and not saved[1]['payload'].get('retryable'):
        value = saved[1]['payload']
        if value['state'] == 'ready':
            _verify_prepared(home, value)
            progress('复用已核验补救受体：' + original['symbol'])
            return deepcopy(value)
        return deepcopy(value)
    expected_uniprot = _source_uniprot(home, source, target_id)
    connection = deepcopy(next(row for row in source['fact']['connection']['receptors']
                               if row['target_id'] == target_id))
    attempt = folder / new_id('attempt')
    native = execution_folder(attempt)
    code = Path(__file__).resolve().parents[3]
    try:
        if connection['state'] != 'connected':
            fetch = Fetcher(home, native / 'connection')
            connection = receptor_sources(original, fetch, progress)
        connection['uniprot'] = connection.get('uniprot') or expected_uniprot
        require(connection['uniprot'] == expected_uniprot, '补救来源与原人类蛋白稳定编号不同')
        value = rescue.prepare(workflow, sid, {'compounds': [], 'receptors': [connection]},
                               connection, native / 'preparation', Path(tools), Path(repair_packages),
                               code, run['run_id'], progress)
        if value['state'] == 'ready':
            require(value['selected_candidate']['spec']['uniprot'] == expected_uniprot,
                    '补救准备改变目标蛋白身份')
            _verify_prepared(home, value)
    except Exception as error:
        value = dict(original, state='NA', quality='待核查', reason_zh=str(error), attempts=[])
        write_json(native / 'failure.json', {'error_type': type(error).__name__, 'reason_zh': str(error)})
    value.update(target_id=target_id, symbol=original['symbol'], source_kind='rescue',
                 expected_uniprot=expected_uniprot)
    failures = str(value).lower()
    value['retryable'] = value['state'] != 'ready' and any(
        text in failures for text in ('timed out', 'timeout', 'urlopen error', 'http error 429',
                                     'http error 500', 'http error 502', 'http error 503', 'http error 504'))
    value['evidence_files'] = [file_record(home, path, 'rescue_preparation_evidence')
                               for path in attempt.rglob('*') if path.is_file()]
    write_json(native / 'result.json', value)
    files = [file_record(home, path, 'rescue_preparation_evidence')
             for path in attempt.rglob('*') if path.is_file()]
    _save_checkpoint(workflow, sid, run, key, value, files)
    return value


def _verify_prepared(home, receptor):
    """从原件重新核验有限修补和全部区域，不能只相信ready标记。"""
    from .automatic_coverage_prepare import check_exploration
    require(receptor['quality'] == '探索', '本次新增补救应保持探索用途')
    origin = receptor.get('origin') or receptor.get('selected_candidate')
    require(origin and origin['spec']['uniprot'] == receptor.get(
        'expected_uniprot', origin['spec']['uniprot']), '补救缺少原蛋白身份依据')
    regions, rejected = check_exploration(home, origin, receptor)
    require(regions == receptor['regions'] and rejected == receptor['rejected_regions'],
            '补救区域与原始结构、完整预测或环境依据不一致')
    archive_files(home, receptor)


def _scoring_config(run):
    """区域评分沿原固定Vina参数及单CPU执行，不从网页接收参数覆盖。"""
    return {key: deepcopy(run['config'][key])
            for key in ('vina_parameters', 'cpu_per_pair', 'timeout_seconds')}


def _top1_bytes(raw):
    """仅提取原始输出MODEL 1的原字节，禁止选取后续姿势。"""
    lines = raw.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith(b'MODEL ')]
    require(starts and lines[starts[0]].split()[1] == b'1', '原始姿势没有明确MODEL 1')
    first = starts[0]
    stop = next((index + 1 for index in range(first, len(lines))
                 if lines[index].startswith(b'ENDMDL')), None)
    require(stop is not None, '原始第一构象不完整')
    return b''.join(lines[first:stop])


def _attach_top1(home, folder, row, pose):
    """把评分选中的第一构象另存为下载附件，保留原全模式文件。"""
    raw = _top1_bytes(verified_file(home, pose).read_bytes())
    path = folder / 'top1.pdbqt'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, '已保存Top-1与实际计分姿势不同')
    else:
        path.write_bytes(raw)
    row.update(top1_pose=file_record(home, path, 'rescue_top1_pose'), original_pose=pose)


def _score_pair(workflow, sid, run, ordinal, compound, receptor, binary, folder, progress):
    """每个预定区域独立恢复和复算第一姿势，再按原规则选取区域最低值。"""
    from .plan_score_pair import execute, validate
    from .plan_scoring_inputs import ligand_record
    from .trial_rules import choose_score
    home = workflow.location(sid)
    config = _scoring_config(run)
    ligand = ligand_record(compound)
    facts = []
    for index, region in enumerate(receptor['regions'], 1):
        key = f'pair_{ordinal:06d}_region_{index:04d}'
        saved = _checkpoint(workflow, sid, run, key)
        if saved and not saved[1]['payload'].get('retryable'):
            reference = saved[1]['payload']['execution']
        else:
            progress(f'补算组合 {ordinal}，区域 {index}/{len(receptor["regions"])}')
            work = folder / f'pair_{ordinal:06d}' / f'region_{index:04d}' / new_id('attempt')
            reference = execute(home, work, binary, ligand, receptor['receptor'], region, config)
        value = validate(home, reference, binary, ligand, receptor['receptor'], region, config)
        fact = {'region_id': region['region_id'], 'state': value['state'], 'score': value['score'],
                'reason_zh': value['reason_zh'], 'execution': reference,
                'retryable': value.get('failure_kind') in ('timeout', 'launch_error')}
        if not saved or saved[1]['payload'].get('retryable'):
            _save_checkpoint(workflow, sid, run, key, fact, [reference, *value['files']])
        else:
            require(saved[1]['payload'] == fact, '区域检查点与实际命令、姿势不一致')
        facts.append(fact)
    best = choose_score(facts, receptor['mode'])
    row = {'compound_id': compound['compound_id'], 'target_id': receptor['target_id'],
           'state': 'completed' if best else 'failed', 'score': best['score'] if best else None,
           'quality': receptor['quality'], 'source_kind': 'rescue', 'regions': facts,
           'mode': receptor['mode'], 'region_id': best['region_id'] if best else None,
           'execution': best['execution'] if best else None,
           'partial_regions': bool(best and any(value['state'] != 'completed' for value in facts)),
           'reason_zh': '' if best else '全部预定区域均未形成有效评分，详见各区域原始执行证据'}
    if best:
        value = read_json(verified_file(home, best['execution']))
        _attach_top1(home, folder / f'pair_{ordinal:06d}', row, value['pose'])
    return row


def _table_rows(rows):
    """网页、CSV与完整矩阵共用同一组原始评分及缺失原因。"""
    keys = ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh', 'source_kind')
    labels = {'completed': '评分完成', 'NA': '准备NA', 'failed': '评分失败'}
    return [dict({key: row.get(key) for key in keys}, state_zh=labels[row['state']]) for row in rows]


def _summary(source, receptors, pairs):
    """分别统计原分、补算及剩余NA，不把探索补救累计为严格受体。"""
    scored = [row for row in pairs if row['state'] == 'completed']
    return {'science_version': VERSION, 'compound_count': len(source['fixed']['compounds']),
            'receptor_count': len(receptors), 'pair_count': len(pairs),
            'scored_pairs': len(scored), 'na_pairs': sum(row['state'] == 'NA' for row in pairs),
            'failed_pairs': sum(row['state'] == 'failed' for row in pairs),
            'strict_scored_pairs': sum(row['quality'] == '严格' for row in scored),
            'exploratory_scored_pairs': sum(row['quality'] == '探索' for row in scored),
            'strict_receptors': sum(row['state'] == 'ready' and row['quality'] == '严格' for row in receptors),
            'exploratory_receptors': sum(row['state'] == 'ready' and row['quality'] == '探索' for row in receptors),
            'rescue_target_count': len(source['targets']),
            'rescued_receptors': sum(row['target_id'] in source['targets'] and row['state'] == 'ready'
                                    for row in receptors),
            'reused_scored_pairs': sum(row['source_kind'] == 'original' for row in scored),
            'new_scored_pairs': sum(row['source_kind'] == 'rescue' for row in scored),
            'input_key': source['fixed']['input_key'],
            'analysis_parameter_hash': source['fixed']['analysis_parameter_hash'],
            'human_review_written': False, 'handoff_blocked': not scored,
            'message_zh': '按既定探索方案完成原失败受体的补救及补算；原有效评分沿用，新结果待独立复核'}


def _read_original(workflow, source):
    """复用前实际执行原生产规范，不以摘要计数冒充原构象核验。"""
    from modulea.core.read_archive import legacy_report_read_scope
    from modulea.core.read_evidence import read_evidence_scope
    from modulea.core.system_receptor_rescue import read_source_workflow
    reader = read_source_workflow(workflow)
    # 只读核验期间复用既有I/O适配；原规范、原件SHA、科学复算均照常，退出后不保留缓存。
    with read_evidence_scope(workflow.root, source['preparation']['study_id']) as evidence, \
            legacy_report_read_scope(workflow.root), reader.handoff_read_cache():
        for module, run, result in (
                ('A06_PREP', source['preparation'], source['preparation_result']),
                ('A06', source['scoring'], source['scoring_result'])):
            check = workflow.validators[module]
            if module == 'A06_PREP' and run['config'].get('version') == 'A06.system_qualification_paths.1':
                from .system_qualification_paths import validator as factory
            elif module == 'A06' and run['config'].get('version') == 'A06.system_scoring_paths.1':
                from .system_scoring_paths import validator as factory
            else:
                factory = None
            if factory is not None:
                def reject(*_):
                    """固定来源协议不能在只读校验时回退其他科学版本。"""
                    require(False, '补救原来源协议不符，不能回退')
                # 工厂原code与closure照用；私有namespace只绑定已白名单的只读I/O。
                bound_factory = evidence.bind(factory)
                if module == 'A06' and bound_factory is not factory:
                    bound_factory.__globals__['_scope'] = dict(
                        _SCORING_SCOPE, validator=evidence.bind(SCORING_READ_FACTORY))
                check = bound_factory(workflow.root, reject)
            check(run, result['summary'], result['tables'], result['anomalies'], result['outcome'])


def compute(workflow, sid, run, *, tools, repair_packages, progress):
    """同批补救和评分锁外执行，成功对象和区域通过已登记检查点恢复。"""
    home = workflow.location(sid)
    from .system_rescue_runtime import activate
    activate(Path(tools), Path(repair_packages))
    inputs = run['inputs']
    original_preparation = read_json(verified_file(home, inputs['source_preparation_run']))
    original_scoring = read_json(verified_file(home, inputs['source_scoring_run']))
    source = source_data(workflow, workflow.load(sid), original_preparation['run_id'], original_scoring['run_id'])
    require(run['config'] == configuration(source['preparation'], tools=tools, repair_packages=repair_packages),
            '补救参数、工具或实际实现已改变')
    progress('核验原准备、原评分及实际构象，保留已完成组合')
    _read_original(workflow, source)
    folder = home / 'runs/A06' / run['run_id'] / 'rescue'
    folder.mkdir(parents=True, exist_ok=True)
    from .system_scoring import check_tools
    executable = check_tools(Path(tools))
    binary = folder / 'software/vina.exe'
    binary.parent.mkdir(parents=True, exist_ok=True)
    if binary.exists():
        require(hashlib.sha256(binary.read_bytes()).hexdigest() == run['config']['vina_sha256'],
                '本批补算Vina字节已改变')
    else:
        shutil.copyfile(executable, binary)
    code = Path(__file__).resolve().parents[3]
    implementations = []
    for name, digest in run['config']['implementation_sha256'].items():
        path = _code_file(code, name)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, '补救实现已改变：' + name)
        target = folder / 'code' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            require(target.read_bytes() == path.read_bytes(), '原补救实现快照已改变')
        else:
            target.write_bytes(path.read_bytes())
        implementations.append(file_record(home, target, 'rescue_implementation'))
    original_rows = {row['target_id']: row for row in source['qualification']['receptors']}
    receptors = []
    for original in source['fixed']['receptors']:
        if original['target_id'] in source['targets']:
            progress('开始受体探索补救：' + original['symbol'])
            row = _prepare_target(workflow, sid, run, source, original,
                                  folder / 'receptors' / original['target_id'].replace(':', '_'),
                                  tools, repair_packages, progress)
        else:
            row = deepcopy(original_rows[original['target_id']])
            row['source_kind'] = 'original'
        receptors.append(row)
    fixed_compounds = {row['compound_id']: row for row in source['fixed']['compounds']}
    compounds = [dict(row, name=fixed_compounds[row['compound_id']].get('name', row['compound_id']))
                 for row in source['fact']['compounds']]
    lookup = {row['target_id']: row for row in receptors}
    original_pairs = {(row['compound_id'], row['target_id']): row
                      for row in source['scoring_packet']['pairs']}
    pairs = []
    for compound in compounds:
        for target in source['fixed']['receptors']:
            ordinal = len(pairs) + 1
            receptor = lookup[target['target_id']]
            baseline = original_pairs[(compound['compound_id'], receptor['target_id'])]
            if baseline['state'] == 'completed':
                row = dict(deepcopy(baseline), source_kind='original')
                value = read_json(verified_file(home, baseline['execution']))
                _attach_top1(home, folder / 'original_top1' / f'pair_{ordinal:06d}', row, value['pose'])
            elif receptor['target_id'] in source['targets'] and receptor['state'] == compound['state'] == 'ready':
                row = _score_pair(workflow, sid, run, ordinal, compound, receptor,
                                  binary, folder / 'scores', progress)
            else:
                causes = [item.get('reason_zh', '') for item in (compound, receptor) if item['state'] != 'ready']
                row = dict(deepcopy(baseline), state='NA', score=None, quality=receptor['quality'],
                           source_kind='rescue' if receptor['target_id'] in source['targets'] else 'original',
                           execution=None, reason_zh='；'.join(causes) or baseline['reason_zh'])
            pairs.append(row)
    stats = _summary(source, receptors, pairs)
    packet = {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'],
              'inputs': deepcopy(inputs), 'configuration': deepcopy(run['config']),
              'source_binding': deepcopy(inputs['source_binding']), 'source_fixed': deepcopy(source['fixed']),
              'compounds': compounds, 'receptors': receptors, 'pairs': pairs, 'summary': stats,
              'binary': file_record(home, binary, 'rescue_scoring_vina'),
              'implementation_files': implementations}
    from .system_rescue_display import export
    figures, attachments = export(home, packet, folder / 'display' / new_id('display'))
    packet['files'] = [file_record(home, path, 'rescue_evidence')
                       for path in folder.rglob('*') if path.is_file()]
    path = folder / 'packets' / (new_id('packet') + '.json')
    write_json(path, packet)
    reference = file_record(home, path, 'rescue_scoring_packet')
    preparation_rows = [{key: row.get(key) for key in ('target_id', 'symbol', 'state', 'quality', 'reason_zh', 'source_kind')}
                        for row in receptors]
    tables = {'scoring_packet': [reference], 'plan_scoring_pairs': _table_rows(pairs),
              'receptor_preparation': preparation_rows, 'rescue_summary': [stats]}
    sources = archive_files(home, source) + [inputs['rescue_request'], reference, *packet['files'], *attachments]
    return stats, tables, sources, figures


def _validate_new_pair(home, run, packet, ordinal, pair, compound, receptor):
    """逐区域重核实际命令、Top-1与预定盒子，拒绝跨对象或跨批次拼接。"""
    from .plan_score_pair import validate
    from .plan_scoring_inputs import ligand_record
    from .trial_rules import choose_score
    regions = receptor['regions']
    require(pair.get('mode') == receptor['mode']
            and [row['region_id'] for row in pair.get('regions', [])] == [row['region_id'] for row in regions],
            '同一受体的不同成分必须采用同一预定区域集合')
    binary = verified_file(home, packet['binary'])
    for index, (fact, region) in enumerate(zip(pair['regions'], regions), 1):
        reference = fact['execution']
        prefix = f'runs/A06/{run["run_id"]}/rescue/scores/pair_{ordinal:06d}/region_{index:04d}/'
        require(reference['path'].startswith(prefix) and reference['path'].endswith('/execution.json')
                and '/' not in reference['path'][len(prefix):-len('/execution.json')],
                '区域执行证据不属于当前组合或批次')
        value = validate(home, reference, binary, ligand_record(compound), receptor['receptor'],
                         region, _scoring_config(run))
        require((fact['state'], fact['score'], fact['reason_zh'])
                == (value['state'], value['score'], value['reason_zh']), '区域结果与实际Top-1不同')
    chosen = choose_score(pair['regions'], receptor['mode'])
    require(pair['state'] == ('completed' if chosen else 'failed')
            and pair['score'] == (chosen['score'] if chosen else None)
            and pair.get('execution') == (chosen['execution'] if chosen else None)
            and pair.get('region_id') == (chosen['region_id'] if chosen else None)
            and pair.get('partial_regions') == bool(chosen and any(row['state'] != 'completed'
                                                                  for row in pair['regions'])),
            '最终分数与预定区域的第一姿势最低值不一致')


def _validate_pose(home, run, pair):
    """下载文件必须来自本组合实际计分的第一模式，不能拼接其他组合的姿势。"""
    execution = read_json(verified_file(home, pair['execution']))
    require(pair.get('top1_pose') and pair.get('original_pose')
            and pair['original_pose'] == execution['pose']
            and pair['top1_pose']['path'].startswith(f'runs/A06/{run["run_id"]}/rescue/')
            and verified_file(home, pair['top1_pose']).read_bytes()
            == _top1_bytes(verified_file(home, pair['original_pose']).read_bytes()),
            '下载Top-1与实际计分构象不同')


def validate_packet(workflow, run, stats, tables, anomalies, outcome):
    """独立重建原分、补救准备、逐区域评分及完整矩阵，发布与复核共用。"""
    home = workflow.location(run['study_id'])
    m = workflow.load(run['study_id'])
    preparation = read_json(verified_file(home, run['inputs']['source_preparation_run']))
    scoring = read_json(verified_file(home, run['inputs']['source_scoring_run']))
    source = source_data(workflow, m, preparation['run_id'], scoring['run_id'])
    from modulea.core.system_receptor_rescue import _read_request, source_binding
    request = _read_request(workflow, m, run['inputs']['rescue_request'])
    expected_binding = source_binding(workflow, m, preparation['run_id'], scoring['run_id'])
    parent_review = workflow.latest_review(m, preparation['artifact_id'])
    require(request['binding'] == run['inputs']['source_binding'] == expected_binding
            and request['configuration'] == run['config']
            and request['request']['expected_preparation_run_id'] == preparation['run_id']
            and request['request']['expected_scoring_run_id'] == scoring['run_id']
            and run['inputs']['source_preparation_run'] == m['runs'][preparation['run_id']]['run_file']
            and run['inputs']['source_preparation_result'] == m['runs'][preparation['run_id']]['result_file']
            and run['inputs']['source_scoring_run'] == m['runs'][scoring['run_id']]['run_file']
            and run['inputs']['source_scoring_result'] == m['runs'][scoring['run_id']]['result_file']
            and run['parent_runs'] == {'A06_PREP': preparation['run_id']}
            and parent_review and parent_review['decision'] == 'approved'
            and run['parent_review_ids'] == {'A06_PREP': parent_review['review_id']},
            '补救未绑定已登记的明确请求、原来源及实际准备批准')
    _read_original(workflow, source)
    refs = tables.get('scoring_packet', [])
    require(len(refs) == 1 and refs[0]['path'].startswith(f'runs/A06/{run["run_id"]}/rescue/packets/'),
            '补救缺少本运行唯一事实包')
    packet = read_json(verified_file(home, refs[0]))
    require(packet['schema_version'] == VERSION and packet['study_id'] == run['study_id']
            and packet['run_id'] == run['run_id'] and packet['inputs'] == run['inputs']
            and packet['configuration'] == run['config']
            and packet['source_binding'] == run['inputs']['source_binding']
            and packet['source_fixed'] == source['fixed'], '补救事实与运行、原输入或配置不同')
    binary = packet['binary']
    require(binary['path'] == f'runs/A06/{run["run_id"]}/rescue/software/vina.exe'
            and binary['sha256'] == run['config']['vina_sha256'], '补算工具不是本批固定Vina')
    archive_files(home, packet)
    implementation = {row['path'].split('/rescue/code/', 1)[1]: row['sha256']
                      for row in packet['implementation_files']}
    require(implementation == run['config']['implementation_sha256'], '补救科学实现快照不完整或不同')
    compounds = {row['compound_id']: row for row in packet['compounds']}
    receptors = {row['target_id']: row for row in packet['receptors']}
    require([row['compound_id'] for row in packet['compounds']]
            == [row['compound_id'] for row in source['fixed']['compounds']]
            and [row['target_id'] for row in packet['receptors']]
            == [row['target_id'] for row in source['fixed']['receptors']], '补救改变固定对象或原顺序')
    for original in source['fact']['compounds']:
        row = compounds[original['compound_id']]
        require(all(row.get(key) == value for key, value in original.items()), '本轮受体补救改变原配体')
    prior_receptors = {row['target_id']: row for row in source['qualification']['receptors']}
    for row in packet['receptors']:
        if row['target_id'] not in source['targets']:
            require(all(row.get(key) == value for key, value in prior_receptors[row['target_id']].items()),
                    '本轮补救改变原准备可用的受体')
        else:
            require(row.get('source_kind') == 'rescue'
                    and row.get('expected_uniprot') == _source_uniprot(home, source, row['target_id']),
                    '补救目标身份与原始官方编号不同')
            if row['state'] == 'ready':
                _verify_prepared(home, row)
            else:
                require(row['state'] == 'NA' and row.get('reason_zh') and row.get('evidence_files'),
                        '补救未通过须保留真实尝试与具体原因')
    expected_order = [(compound['compound_id'], target['target_id'])
                      for compound in source['fixed']['compounds'] for target in source['fixed']['receptors']]
    require([(row['compound_id'], row['target_id']) for row in packet['pairs']] == expected_order,
            '补救完整矩阵缺项、重复或次序不同')
    original_pairs = {(row['compound_id'], row['target_id']): row for row in source['scoring_packet']['pairs']}
    for ordinal, pair in enumerate(packet['pairs'], 1):
        key = pair['compound_id'], pair['target_id']
        baseline = original_pairs[key]
        compound, receptor = compounds[key[0]], receptors[key[1]]
        if baseline['state'] == 'completed':
            require(pair.get('source_kind') == 'original'
                    and all(pair.get(name) == value for name, value in baseline.items()),
                    '原有效评分或其执行证据被改写')
        elif receptor['target_id'] in source['targets'] and compound['state'] == receptor['state'] == 'ready':
            require(pair['source_kind'] == 'rescue' and pair['quality'] == receptor['quality'],
                    '新增分数的补救来源或质量错误')
            _validate_new_pair(home, run, packet, ordinal, pair, compound, receptor)
        else:
            causes = [row.get('reason_zh', '') for row in (compound, receptor) if row['state'] != 'ready']
            require(pair['state'] == 'NA' and pair['score'] is None and pair.get('execution') is None
                    and pair['reason_zh'] == ('；'.join(causes) or baseline['reason_zh']),
                    '未准备成功的对象不得填入评分或丢失原因')
        if pair['state'] == 'completed':
            _validate_pose(home, run, pair)
    expected = _summary(source, packet['receptors'], packet['pairs'])
    preparation_rows = [{key: row.get(key) for key in ('target_id', 'symbol', 'state', 'quality', 'reason_zh', 'source_kind')}
                        for row in packet['receptors']]
    require(stats == packet['summary'] == expected and anomalies == []
            and outcome == ('success' if expected['scored_pairs'] else 'failed')
            and tables == {'scoring_packet': refs, 'plan_scoring_pairs': _table_rows(packet['pairs']),
                           'receptor_preparation': preparation_rows, 'rescue_summary': [expected]},
            '补救统计、网页表或完整矩阵与原始证据不同')
    return packet


def validator(root, previous):
    """仅新显式协议采用补救规范，所有旧协议沿原生产校验器。"""
    def check(run, stats, tables, anomalies, outcome):
        if run['config'].get('version') != VERSION:
            return previous(run, stats, tables, anomalies, outcome)
        from modulea.core.kernel import full_workflow
        workflow = full_workflow(Path(root))
        validate_packet(workflow, run, stats, tables, anomalies, outcome)
    return check
