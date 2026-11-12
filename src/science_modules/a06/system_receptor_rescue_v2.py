"""受体补救二版：复用已核验官方原件和整条成功结果，只补仍缺失的受体。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import FunctionType

from contracts import ContractError, encoded, fingerprint, require
from storage import file_record, new_id, now, read_json, verified_file, write_json
from . import system_receptor_rescue as prior

VERSION = 'A06.system_rescue.2'
POLICY = dict(deepcopy(prior.POLICY), version=VERSION,
              existing_scores='retain_entire_validated_completed_pair',
              official_source_reuse='registered_exact_url_bytes_and_original_http_provenance')
CODE_NAMES = prior.CODE_NAMES + (
    'science_modules/a06/system_receptor_rescue_v2.py',
    'science_modules/a06/system_rescue_display_v2.py',
    'science_modules/a06/system_rescue_partial.py',
    'modulea/core/receptor_source_packages.py',
)


def configuration(preparation, *, tools, repair_packages, runtime_signature=None):
    """原工具和科学阈值保持，单独固定二版及其归档来源校验实现。"""
    value = prior.configuration(preparation, tools=tools, repair_packages=repair_packages,
                                runtime_signature=runtime_signature)
    code = Path(__file__).resolve().parents[3]
    value.update(version=VERSION, policy=deepcopy(POLICY))
    value['implementation_sha256'] = {
        name: hashlib.sha256(prior._code_file(code, name).read_bytes()).hexdigest() for name in CODE_NAMES}
    return value


def verify_prepared(home, receptor):
    """完整重建科学依据后按项目JSON规范比较，容许元组保存后成为列表。"""
    from .automatic_coverage_prepare import check_exploration
    require(receptor['quality'] == '探索', '本轮新增补救应保持探索用途')
    origin = receptor.get('origin') or receptor.get('selected_candidate')
    require(origin and origin['spec']['uniprot'] == receptor.get(
        'expected_uniprot', origin['spec']['uniprot']), '补救缺少原蛋白身份依据')
    regions, rejected = check_exploration(home, origin, receptor)
    require(fingerprint(regions) == fingerprint(receptor['regions'])
            and fingerprint(rejected) == fingerprint(receptor['rejected_regions']),
            '补救区域与原始结构、完整预测或环境依据不一致')
    prior.archive_files(home, receptor)


def score_pair(workflow, sid, run, ordinal, compound, receptor, binary, folder, progress):
    """在执行边界使用归档的同一JSON表示；区域、数值、次序和原对象保持。"""
    canonical = json.loads(encoded(receptor))
    return prior._score_pair(workflow, sid, run, ordinal, compound, canonical, binary, folder, progress)


def source_data(workflow, manifest, preparation_run_id, scoring_run_id):
    """区分原始准备/评分与补救基线，后者不能冒充原严格评分协议。"""
    home = workflow.location(manifest['study_id'])
    baseline = workflow.run(manifest, scoring_run_id)
    version = baseline['config'].get('version')
    require(version in ('A06.system_scoring_paths.1', prior.VERSION), '不支持的补救二版评分基线')
    original_id = scoring_run_id
    if version == prior.VERSION:
        ref = baseline['inputs']['source_scoring_run']
        original = read_json(verified_file(home, ref))
        original_id = original['run_id']
        require(ref == manifest['runs'][original_id]['run_file'], '原评分不是本研究已登记原件')
    value = prior.source_data(workflow, manifest, preparation_run_id, original_id)
    result = workflow.result(manifest, scoring_run_id)
    require(result and result['outcome'] == 'success', '补救基线尚未完整成功')
    refs = result['tables'].get('scoring_packet', [])
    require(len(refs) == 1 and refs[0] in result['files'], '补救基线缺少唯一登记事实包')
    packet = read_json(verified_file(home, refs[0]))
    if version == prior.VERSION:
        require(packet['schema_version'] == prior.VERSION and packet['source_fixed'] == value['fixed'],
                '既有补救与原固定对象或协议不同')
        rows = packet['receptors']
    else:
        rows = value['qualification']['receptors']
    require([row['target_id'] for row in rows] == [row['target_id'] for row in value['fixed']['receptors']],
            '补救基线受体身份或顺序不同')
    value.update(baseline_scoring=baseline, baseline_result=result, baseline_packet=packet,
                 baseline_receptors=rows, original_targets=deepcopy(value['targets']))
    value['targets'] = [row['target_id'] for row in rows if row['state'] != 'ready']
    require(set(value['targets']) <= set(value['original_targets']), '原可用受体不能变为本轮补救对象')
    from modulea.core.system_receptor_rescue_v2 import source_binding
    from .system_rescue_partial import restore
    return restore(workflow, manifest, value, source_binding(workflow, manifest, preparation_run_id, scoring_run_id))


def effective_pairs(source):
    """原评分包保持原样，恢复的完整区域组另列并仅补其原缺失组合。"""
    lookup = {(row['compound_id'], row['target_id']): row for row in source.get('recovered_pairs', [])}
    return [lookup.get((row['compound_id'], row['target_id']), row)
            if row['state'] != 'completed' else row for row in source['baseline_packet']['pairs']]


def _read_baseline(workflow, source):
    """复用前完整执行基线原协议，不能从完成标记或自填摘要推断可信。"""
    baseline = source['baseline_scoring']
    if baseline['config'].get('version') == prior.VERSION:
        result = source['baseline_result']
        prior.validate_packet(workflow, baseline, result['summary'], result['tables'],
                              result['anomalies'], result['outcome'])
    else:
        prior._read_original(workflow, source)


def _source_catalog(workflow, sid, run, target_id):
    """仅采用本请求明确固定且属于当前受体的已登记官方来源包。"""
    from modulea.core.receptor_source_packages import read_record
    home, manifest = workflow.location(sid), workflow.load(sid)
    catalog = {}
    for ref in run['inputs'].get('official_source_packages', []):
        record = read_record(home, manifest, ref)
        if record['validated']['target_id'] != target_id:
            continue
        for row in record['responses']:
            key = row['url']
            if key in catalog:
                require(catalog[key]['file'] == row['file'], '同一官方URL登记了冲突原件')
            catalog[key] = dict(row, source_package=deepcopy(ref))
    return catalog


def archived_fetcher(home, folder, catalog):
    """按精确URL复用原件，单独记录复用时间，绝不伪造本次HTTP成功。"""
    from .automatic_coverage_sources import Fetcher

    class ArchivedOfficialFetcher(Fetcher):
        """本实例的来源目录固定；其余URL仍走原官方白名单及网络重试。"""
        def get(self, url, suffix='json'):
            """损坏或格式不符必须报错，不能用网络静默替换已固定的原件。"""
            item = catalog.get(url)
            if item is None:
                return super().get(url, suffix)
            require(item['url'] == url and suffix in ('json', 'cif'), '官方复用请求格式不同')
            request = read_json(verified_file(self.root, item['original_request']))
            require(request.get('state') == 'success' and request.get('status') == 200
                    and request.get('url') == url, '原官方请求未成功或URL不同')
            raw = verified_file(self.root, item['file']).read_bytes()
            require(all(request['file'][key] == item['file'][key] for key in ('bytes', 'sha256')),
                    '复用原件与原HTTP下载的字节不同')
            value = json.loads(raw) if suffix == 'json' else {}
            fact = dict(schema_version='ModuleA.archived_official_reuse.1', url=url,
                        reused_at=now(), original_downloaded_at=item['original_downloaded_at'],
                        original_request=item['original_request'], file=item['file'],
                        source_package=item.get('source_package'), new_http_request_performed=False)
            path = self.folder / (new_id('reuse') + '.json')
            write_json(path, fact)
            self.records.extend([item['file'], item['original_request'],
                                 file_record(self.root, path, 'archived_official_reuse')])
            return value, deepcopy(item['file'])

    return ArchivedOfficialFetcher(home, folder)


def _prior_experimental_exhausted(home, row):
    """只从已验证基线的实际分页审计确认实验路线已走完，不凭原因文字跳过。"""
    for ref in row.get('evidence_files', []):
        if not Path(ref['path']).name.startswith('inspection_') or not ref['path'].endswith('.json'):
            continue
        evidence = read_json(verified_file(home, ref))
        if evidence.get('target_id') == row['target_id'] and evidence.get('exhausted') is True:
            return True
    return False


def _official_sequence(home, connection, uniprot, fetch, *, previous=None):
    """优先复用原连接逐字节核实的官方序列；没有才按原稳定编号补查。"""
    reference = connection.get('official_sequence_file')
    if not reference:
        registered = (previous or {}).get('evidence_files', [])
        candidates = []
        for item in registered:
            if not item['path'].endswith('_request.json'):
                continue
            request = read_json(verified_file(home, item))
            if request.get('url') != 'https://rest.uniprot.org/uniprotkb/' + uniprot + '.json' \
                    or request.get('state') != 'success' or request.get('status') != 200:
                continue
            original = request.get('file')
            require(original and any(all(ref.get(key) == original.get(key) for key in ('path', 'bytes', 'sha256'))
                                     for ref in registered), '旧官方序列响应没有登记在同批对象依据中')
            document = read_json(verified_file(home, original))
            candidates.append((document, original))
        if candidates:
            require(all((row[0]['primaryAccession'], row[0]['organism']['taxonId'], row[0]['sequence']['value'])
                        == (candidates[0][0]['primaryAccession'], candidates[0][0]['organism']['taxonId'],
                            candidates[0][0]['sequence']['value']) for row in candidates),
                    '同批成功官方序列存在身份或序列冲突')
            official, reference = candidates[-1]
            connection = dict(connection, official_sequence=official)
    if reference:
        official = read_json(verified_file(home, reference))
        require(official == connection.get('official_sequence'), '原连接官方序列声明与原件不同')
    else:
        official, reference = fetch.get('https://rest.uniprot.org/uniprotkb/' + uniprot + '.json')
    require(official['primaryAccession'] == uniprot and official['organism']['taxonId'] == 9606,
            '补救官方序列身份或物种不同')
    return official, reference


def validate_source_use(home, source, row, catalog):
    """准备产物绑定本次精确模型原件；不能换成同蛋白另一版本的自洽结构。"""
    previous = next(value for value in source['baseline_receptors'] if value['target_id'] == row['target_id'])
    baseline = source.get('partial_run') or source['baseline_scoring']
    claimed = row.get('prior_experimental_run_id')
    if claimed is not None:
        require(catalog and baseline['config']['version'] == prior.VERSION
                and claimed == baseline['run_id'] and previous['state'] != 'ready'
                and _prior_experimental_exhausted(home, previous),
                '不能凭声明跳过原实验结构路线，须有同批已完成分页审计')
    origin = row.get('origin') or row.get('selected_candidate')
    require(origin, '补救准备缺少实际结构来源')
    if not catalog or origin['spec']['source_type'] != 'alphafold':
        return
    metadata_url = 'https://alphafold.ebi.ac.uk/api/prediction/' + row['expected_uniprot']
    require(metadata_url in catalog, '本次官方模型元数据未在明确来源包登记')
    metadata_ref = catalog[metadata_url]['file']
    metadata = read_json(verified_file(home, metadata_ref))
    exact = [info for info in metadata if info.get('uniprotAccession') == row['expected_uniprot']]
    require(len(exact) == 1, '本次来源包没有唯一目标模型')
    info = exact[0]
    require(info['cifUrl'] in catalog and info['paeDocUrl'] in catalog,
            '本次来源包缺少同版模型或PAE精确地址')
    require(origin.get('model_metadata_file') == metadata_ref and origin.get('model_metadata') == info
            and origin.get('cif') == catalog[info['cifUrl']]['file']
            and origin.get('pae_file') == catalog[info['paeDocUrl']]['file'],
            '实际准备模型、PAE或元数据不是本请求登记的精确原件')


def prepare_target(workflow, sid, run, source, original, folder, tools, repair_packages, progress):
    """成功对象只恢复；身份不足单列NA，完整旧路线失败后可补用同版官方原件。"""
    from . import automatic_coverage_prepare as coverage
    home, target_id = workflow.location(sid), original['target_id']
    key = 'receptor_' + target_id.replace(':', '_')
    saved = prior._checkpoint(workflow, sid, run, key)
    if saved and not saved[1]['payload'].get('retryable'):
        value = deepcopy(saved[1]['payload'])
        if value['state'] == 'ready':
            validate_source_use(home, source, value, _source_catalog(workflow, sid, run, target_id))
            verify_prepared(home, value)
        return value
    folder = Path(folder)
    attempt = folder / new_id('attempt')
    native = prior.execution_folder(attempt)
    try:
        expected = prior._source_uniprot(home, source, target_id)
    except ContractError as error:
        # 损坏原件仍抛出；只有可读原件确实不能给出唯一身份，才属于对象级NA。
        prior.archive_files(home, source.get('fact', {}))
        value = dict(original, state='NA', quality='待核查', reason_zh=str(error), attempts=[],
                     source_kind='rescue', expected_uniprot=None, retryable=False,
                     failure_stage='identity_verification')
        write_json(native / 'identity_failure.json', {'target_id': target_id,
                   'reason_zh': str(error), 'failure_stage': 'identity_verification'})
    else:
        catalog = _source_catalog(workflow, sid, run, target_id)
        connection = deepcopy(next(row for row in source['fact']['connection']['receptors']
                                   if row['target_id'] == target_id))
        previous = next(row for row in source['baseline_receptors'] if row['target_id'] == target_id)
        code = Path(__file__).resolve().parents[3]
        try:
            fetch = archived_fetcher(home, native / 'archived_official_reuse', catalog)
            route_run = source.get('partial_run') or source['baseline_scoring']
            if catalog and route_run['config']['version'] == prior.VERSION \
                    and previous['state'] != 'ready' and _prior_experimental_exhausted(home, previous):
                # 基线已实际走完同批实验候选；只补先前因传输缺失而未能准备的官方模型。
                official, official_ref = _official_sequence(home, connection, expected, fetch, previous=previous)
                origin = coverage.published_model(original, expected, official, fetch)
                origin['official_sequence_file'] = official_ref
                require(origin['spec']['uniprot'] == expected, '归档模型改变原蛋白身份')
                progress('复用同版官方原件补救：' + original['symbol'])
                value = coverage.explore(home, original, origin, native / 'preparation',
                                         Path(tools), Path(repair_packages), code)
                value.update(selected_candidate=deepcopy(value['origin']), evidence=deepcopy(value),
                             attempts=[{'candidate': origin}],
                             prior_experimental_run_id=route_run['run_id'])
            else:
                # 新来源的普通全路线仍执行原prepare；仅私有函数namespace绑定本次Fetcher。
                def fetch_factory(root, path):
                    """不改变冻结模块globals，仅为本次调用提供已登记原件。"""
                    return archived_fetcher(root, path, catalog)
                scope = dict(coverage.prepare.__globals__, Fetcher=fetch_factory)
                prepared = FunctionType(coverage.prepare.__code__, scope, coverage.prepare.__name__,
                                        coverage.prepare.__defaults__, coverage.prepare.__closure__)
                connection['uniprot'] = connection.get('uniprot') or expected
                require(connection['uniprot'] == expected, '原连接UniProt与稳定编号不同')
                if connection['state'] != 'connected':
                    from .reference_sources import receptor_sources
                    connection = receptor_sources(original, fetch, progress)
                    require(connection['uniprot'] == expected, '重新连接改变原蛋白身份')
                value = prepared(workflow, sid, {'compounds': [], 'receptors': [connection]},
                                 connection, native / 'preparation', Path(tools), Path(repair_packages),
                                 code, run['run_id'], progress)
            value.update(target_id=target_id, symbol=original['symbol'], source_kind='rescue',
                         expected_uniprot=expected)
            if value['state'] == 'ready':
                validate_source_use(home, source, value, catalog)
                verify_prepared(home, value)
        except Exception as error:
            value = dict(original, state='NA', quality='待核查', reason_zh=str(error), attempts=[],
                         source_kind='rescue', expected_uniprot=expected)
            write_json(native / 'failure.json', {'error_type': type(error).__name__, 'reason_zh': str(error)})
        failures = str(value).lower()
        value['retryable'] = value['state'] != 'ready' and any(text in failures for text in (
            'timed out', 'timeout', 'urlopen error', 'http error 429', 'http error 500',
            'http error 502', 'http error 503', 'http error 504'))
    value['evidence_files'] = [file_record(home, path, 'rescue_preparation_evidence')
                               for path in attempt.rglob('*') if path.is_file()]
    require(value['evidence_files'], '补救必须保留真实执行或身份核查依据')
    write_json(native / 'result.json', value)
    files = [file_record(home, path, 'rescue_preparation_evidence') for path in attempt.rglob('*') if path.is_file()]
    prior._save_checkpoint(workflow, sid, run, key, value, files)
    return value


def merge_pairs(workflow, sid, run, source, compounds, receptors, binary, folder, progress):
    """整条保留既有完成结果；只对本轮补救且准备成功的缺失组合实际计算。"""
    lookup = {row['target_id']: row for row in receptors}
    baselines = {(row['compound_id'], row['target_id']): row for row in effective_pairs(source)}
    pairs, reused, fresh = [], [], []
    for compound in compounds:
        for target in source['fixed']['receptors']:
            ordinal = len(pairs) + 1
            receptor = lookup[target['target_id']]
            key = compound['compound_id'], receptor['target_id']
            baseline = baselines[key]
            if baseline['state'] == 'completed':
                row = deepcopy(baseline)
                reused.append(list(key))
            elif key[1] not in source['targets']:
                # 已准备受体的旧失败仍是实际执行失败，不能重写成准备NA或丢失原始执行。
                row = deepcopy(baseline)
            elif key[1] in source['targets'] and compound['state'] == receptor['state'] == 'ready':
                row = score_pair(workflow, sid, run, ordinal, compound, receptor, binary, folder, progress)
                fresh.append(list(key))
            else:
                causes = [item.get('reason_zh', '') for item in (compound, receptor) if item['state'] != 'ready']
                row = dict(deepcopy(baseline), state='NA', score=None, quality=receptor['quality'],
                           source_kind=baseline.get('source_kind', 'original'), execution=None,
                           reason_zh='；'.join(causes) or baseline['reason_zh'])
            pairs.append(row)
    return pairs, reused, fresh


def summary(source, receptors, pairs, reused, fresh):
    """本轮增量、沿用结果和累计探索结果分别计数，不把旧代次改称本轮新增。"""
    # 原始评分协议没有source_kind；只为计数补默认值，原组合对象仍逐字段保持。
    counted = [dict(row, source_kind=row.get('source_kind', 'original')) for row in pairs]
    stats = prior._summary(source, receptors, counted)
    newly_scored = {tuple(row) for row in fresh}
    completed = [row for row in pairs if row['state'] == 'completed']
    stats.update(science_version=VERSION, reused_scored_pairs=len(reused), baseline_scored_pairs=len(reused),
                 new_scored_pairs=sum((row['compound_id'], row['target_id']) in newly_scored for row in completed),
                 cumulative_rescue_scored_pairs=sum(row.get('source_kind') == 'rescue' for row in completed),
                 cumulative_rescue_target_count=len(source['original_targets']),
                 ready_receptors_total=sum(row['state'] == 'ready' for row in receptors),
                 cumulative_rescued_receptors=sum(row['target_id'] in source['original_targets']
                     and row['state'] == 'ready' for row in receptors),
                 message_zh='复用已核验官方原件补救剩余受体；既有成功结果完整保留，新结果待独立复核')
    prepared = source.get('prepare_targets', source['targets'])
    stats.update(rescue_target_count=len(prepared),
                 rescued_receptors=sum(row['target_id'] in prepared and row['state'] == 'ready' for row in receptors),
                 reused_prepared_receptors=sum(row['target_id'] in source['original_targets']
                     and row['target_id'] not in prepared and row['state'] == 'ready' for row in receptors))
    return stats


def compute(workflow, sid, run, *, tools, repair_packages, progress):
    """独立二版只追加缺失计算和图件，原件、既有评分及人工记录保持。"""
    from .system_rescue_runtime import activate
    from .system_scoring import check_tools
    activate(Path(tools), Path(repair_packages))
    home, inputs = workflow.location(sid), run['inputs']
    prep = read_json(verified_file(home, inputs['source_preparation_run']))
    baseline = read_json(verified_file(home, inputs['source_scoring_run']))
    source = source_data(workflow, workflow.load(sid), prep['run_id'], baseline['run_id'])
    require(run['config'] == configuration(prep, tools=tools, repair_packages=repair_packages),
            '补救二版配置、实际依赖或源码已改变')
    progress('核验既有准备、完整评分和实际构象；成功对象不重算')
    _read_baseline(workflow, source)
    folder = home / 'runs/A06' / run['run_id'] / 'rescue'
    folder.mkdir(parents=True, exist_ok=True)
    binary = folder / 'software/vina.exe'
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists():
        shutil.copyfile(check_tools(Path(tools)), binary)
    require(hashlib.sha256(binary.read_bytes()).hexdigest() == run['config']['vina_sha256'], '补算Vina字节不同')
    implementations, code = [], Path(__file__).resolve().parents[3]
    for name, digest in run['config']['implementation_sha256'].items():
        original = prior._code_file(code, name)
        raw = original.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == digest, '本轮实现已改变：' + name)
        target = folder / 'code' / name
        if target.exists():
            require(target.read_bytes() == raw, '已保存实现快照不同')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        implementations.append(file_record(home, target, 'rescue_implementation'))
    previous = {row['target_id']: row for row in source['baseline_receptors']}
    receptors = [prepare_target(workflow, sid, run, source, original,
                    folder / 'receptors' / original['target_id'].replace(':', '_'), tools, repair_packages, progress)
                 if original['target_id'] in source.get('prepare_targets', source['targets']) else deepcopy(previous[original['target_id']])
                 for original in source['fixed']['receptors']]
    if baseline['config']['version'] == prior.VERSION:
        compounds = deepcopy(source['baseline_packet']['compounds'])
    else:
        names = {row['compound_id']: row.get('name', row['compound_id']) for row in source['fixed']['compounds']}
        compounds = [dict(deepcopy(row), name=names[row['compound_id']]) for row in source['fact']['compounds']]
    pairs, reused, fresh = merge_pairs(workflow, sid, run, source, compounds, receptors,
                                       binary, folder / 'scores', progress)
    stats = summary(source, receptors, pairs, reused, fresh)
    packet = dict(schema_version=VERSION, study_id=sid, run_id=run['run_id'], inputs=deepcopy(inputs),
                  configuration=deepcopy(run['config']), source_binding=deepcopy(inputs['source_binding']),
                  source_fixed=deepcopy(source['fixed']), compounds=compounds, receptors=receptors,
                  pairs=pairs, summary=stats, reused_pair_keys=reused, new_pair_keys=fresh,
                  binary=file_record(home, binary, 'rescue_scoring_vina'), implementation_files=implementations)
    from .system_rescue_display_v2 import export
    figures, attachments = export(home, packet, folder / 'display' / new_id('display'))
    packet['files'] = [file_record(home, path, 'rescue_evidence') for path in folder.rglob('*') if path.is_file()]
    path = folder / 'packets' / (new_id('packet') + '.json')
    write_json(path, packet)
    ref = file_record(home, path, 'rescue_scoring_packet')
    prepared_rows = [{key: row.get(key) for key in ('target_id', 'symbol', 'state', 'quality', 'reason_zh', 'source_kind')}
                     for row in receptors]
    tables = dict(scoring_packet=[ref], plan_scoring_pairs=prior._table_rows(pairs),
                  receptor_preparation=prepared_rows, rescue_summary=[stats])
    sources = prior.archive_files(home, source) + prior.archive_files(home, pairs) \
              + [inputs['rescue_request'], *inputs.get('official_source_packages', []), ref, *packet['files'], *attachments]
    return stats, tables, sources, figures


def validate_packet(workflow, run, stats, tables, anomalies, outcome):
    """重新核对基线、归档来源、每个新增区域及整个矩阵，禁止跨代次拼接。"""
    from modulea.core.system_receptor_rescue_v2 import _read_request, source_binding
    home, m = workflow.location(run['study_id']), workflow.load(run['study_id'])
    prep = read_json(verified_file(home, run['inputs']['source_preparation_run']))
    baseline = read_json(verified_file(home, run['inputs']['source_scoring_run']))
    source = source_data(workflow, m, prep['run_id'], baseline['run_id'])
    request = _read_request(workflow, m, run['inputs']['rescue_request'])
    bound = source_binding(workflow, m, prep['run_id'], baseline['run_id'])
    parent_review = workflow.latest_review(m, prep['artifact_id'])
    require(run['config']['version'] == VERSION and request['binding'] == run['inputs']['source_binding'] == bound
            and run['config'] == request['configuration'] and parent_review and parent_review['decision'] == 'approved'
            and run['parent_runs'] == {'A06_PREP': prep['run_id']}
            and run['parent_review_ids'] == {'A06_PREP': parent_review['review_id']}
            and run['inputs']['source_preparation_run'] == m['runs'][prep['run_id']]['run_file']
            and run['inputs']['source_preparation_result'] == m['runs'][prep['run_id']]['result_file']
            and run['inputs']['source_scoring_run'] == m['runs'][baseline['run_id']]['run_file']
            and run['inputs']['source_scoring_result'] == m['runs'][baseline['run_id']]['result_file']
            and run['inputs'].get('official_source_packages', []) == bound['official_source_packages'],
            '补救二版请求、来源、配置或原准备批准不同')
    _read_baseline(workflow, source)
    refs = tables.get('scoring_packet', [])
    prefix = f'runs/A06/{run["run_id"]}/rescue/'
    require(len(refs) == 1 and refs[0]['path'].startswith(prefix + 'packets/'), '二版缺少本运行唯一事实包')
    packet = read_json(verified_file(home, refs[0]))
    require(packet['schema_version'] == VERSION and packet['study_id'] == run['study_id']
            and packet['run_id'] == run['run_id'] and packet['inputs'] == run['inputs']
            and packet['source_fixed'] == source['fixed'] and packet['configuration'] == run['config']
            and packet['source_binding'] == bound, '二版事实与原范围、配置或请求不同')
    prior.archive_files(home, packet)
    require(packet['binary']['path'] == prefix + 'software/vina.exe'
            and packet['binary']['sha256'] == run['config']['vina_sha256'], '二版不是本批固定工具')
    actual = {ref['path'].split('/rescue/code/', 1)[1]: ref['sha256'] for ref in packet['implementation_files']}
    require(actual == run['config']['implementation_sha256'], '二版实现快照不同或缺失')
    prior_compounds = source['baseline_packet'].get('compounds', source['fact']['compounds'])
    require([row['compound_id'] for row in packet['compounds']]
            == [row['compound_id'] for row in source['fixed']['compounds']], '二版成分名单或次序不同')
    for before, row in zip(prior_compounds, packet['compounds']):
        require(all(row.get(key) == value for key, value in before.items()), '受体补救改变原配体')
    require([row['target_id'] for row in packet['receptors']]
            == [row['target_id'] for row in source['fixed']['receptors']], '二版受体名单或次序不同')
    previous = {row['target_id']: row for row in source['baseline_receptors']}
    for row in packet['receptors']:
        if row['target_id'] not in source.get('prepare_targets', source['targets']):
            require(row == previous[row['target_id']], '二版改变已准备成功的受体')
            continue
        catalog = _source_catalog(workflow, run['study_id'], run, row['target_id'])
        try:
            expected = prior._source_uniprot(home, source, row['target_id'])
        except ContractError as error:
            prior.archive_files(home, source['fact'])
            require(row['state'] == 'NA' and row.get('expected_uniprot') is None
                    and row.get('failure_stage') == 'identity_verification' and row['reason_zh'] == str(error),
                    '身份不足不能冒充已核验或使用其他蛋白')
        else:
            require(row.get('expected_uniprot') == expected and row.get('source_kind') == 'rescue',
                    '二版目标稳定身份不同')
            if row['state'] == 'ready':
                validate_source_use(home, source, row, catalog)
                verify_prepared(home, row)
            else:
                require(row['state'] == 'NA' and row.get('reason_zh') and row.get('evidence_files'),
                        '补救NA必须保留实际证据与原因')
    compounds = {row['compound_id']: row for row in packet['compounds']}
    receptors = {row['target_id']: row for row in packet['receptors']}
    baselines = {(row['compound_id'], row['target_id']): row for row in effective_pairs(source)}
    order = [(row['compound_id'], col['target_id']) for row in source['fixed']['compounds']
             for col in source['fixed']['receptors']]
    require([(row['compound_id'], row['target_id']) for row in packet['pairs']] == order, '二版矩阵缺项、重复或次序不同')
    reused, fresh = [], []
    for ordinal, pair in enumerate(packet['pairs'], 1):
        key = pair['compound_id'], pair['target_id']
        before = baselines[key]
        compound, receptor = compounds[key[0]], receptors[key[1]]
        if before['state'] == 'completed':
            require(pair == before, '继承成功组合必须逐字段完整保持')
            reused.append(list(key))
        elif key[1] not in source['targets']:
            require(pair == before, '非本轮受体的既有NA或失败执行必须完整保持')
        elif key[1] in source['targets'] and compound['state'] == receptor['state'] == 'ready':
            require(pair.get('source_kind') == 'rescue' and pair['quality'] == receptor['quality'], '本轮新增评分类别不同')
            prior._validate_new_pair(home, run, packet, ordinal, pair, compound, receptor)
            if pair['state'] == 'completed':
                prior._validate_pose(home, run, pair)
            fresh.append(list(key))
        else:
            causes = [item.get('reason_zh', '') for item in (compound, receptor) if item['state'] != 'ready']
            require(pair['state'] == 'NA' and pair['score'] is None and pair.get('execution') is None
                    and pair['reason_zh'] == ('；'.join(causes) or before['reason_zh']), '未就绪组合含评分或丢失原因')
    require(packet['reused_pair_keys'] == reused and packet['new_pair_keys'] == fresh, '评分代次或实际计算对象不同')
    expected = summary(source, packet['receptors'], packet['pairs'], reused, fresh)
    prepared_rows = [{key: row.get(key) for key in ('target_id', 'symbol', 'state', 'quality', 'reason_zh', 'source_kind')}
                     for row in packet['receptors']]
    require(stats == packet['summary'] == expected and anomalies == []
            and outcome == ('success' if expected['scored_pairs'] else 'failed')
            and tables == dict(scoring_packet=refs, plan_scoring_pairs=prior._table_rows(packet['pairs']),
                               receptor_preparation=prepared_rows, rescue_summary=[expected]),
            '二版统计、表格或逐项状态与实际证据不同')
    return packet


def validator(root, previous):
    """仅新显式二版采用新规范；所有历史协议继续调用原校验器。"""
    def check(run, stats, tables, anomalies, outcome):
        """按运行自身固定版本校验，不随当前页面或新请求升级旧结果。"""
        if run['config'].get('version') != VERSION:
            return previous(run, stats, tables, anomalies, outcome)
        from modulea.core.kernel import full_workflow
        return validate_packet(full_workflow(Path(root)), run, stats, tables, anomalies, outcome)
    return check
