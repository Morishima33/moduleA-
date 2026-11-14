"""补救结果按稳定对象读取原执行与构象；下载指纹对应实际返回字节。"""
from copy import deepcopy
from hashlib import sha256
import json
import math
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import urlencode

from contracts import ContractError, fingerprint, require
from storage import read_json, verified_file
from .errors import ApiError, not_found

VERSION = 'ModuleA.rescue_evidence.1'
STATE_ZH = {'completed': '已评分', 'failed': '执行失败', 'NA': '准备NA'}


def same_file(left, right):
    """角色允许历史别名，路径、长度和SHA必须全部精确相同。"""
    return isinstance(left, dict) and isinstance(right, dict) and all(
        key in left and left[key] == right.get(key) for key in ('path', 'bytes', 'sha256'))


def checked_bytes(home, reference, registered):
    """只读登记原件并校验实际读取字节，避免Path核验后再开文件的竞态。"""
    require(any(same_file(reference, item) for item in registered), '执行证据或构象未登记')
    raw = verified_file(home, reference).read_bytes()
    require(len(raw) == reference['bytes'] and sha256(raw).hexdigest() == reference['sha256'],
            '证据下载读取期间原件校验失败')
    return raw


def load_bundle(app, sid, rid):
    """沿公开Workflow读取本运行，不借用current结果或其他研究的准备。"""
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    if rid not in manifest.get('runs', {}):
        raise not_found('本研究评分运行')
    home = workflow.location(sid)
    run = workflow.run(manifest, rid)
    result = workflow.result(manifest, rid)
    require(run.get('module_id') == 'A06' and run['config'].get('version') in
            ('A06.system_rescue.1', 'A06.system_rescue.2') and result, '该运行不是已归档补救结果')
    refs = result['tables'].get('scoring_packet', [])
    require(len(refs) == 1, '缺少唯一已登记评分事实包')
    packet = json.loads(checked_bytes(home, refs[0], result['files']))
    fixed = read_json(verified_file(home, run['inputs']['system_input_ref']))
    require(run['study_id'] == result['study_id'] == packet['study_id'] == fixed['study_id'] == sid
            and run['run_id'] == result['run_id'] == packet['run_id'] == rid
            and packet['schema_version'] == run['config']['version']
            and fixed.get('stage') == 'A06_INPUT'
            and fixed.get('binding', {}).get('batch_file') == run.get('batch_file')
            and fingerprint(packet['source_fixed']) == fingerprint(fixed['payload'])
            and fingerprint(packet['inputs']) == fingerprint(run['inputs'])
            and fingerprint(packet['summary']) == fingerprint(result['summary']),
            '补救证据研究、批次、固定输入或科学协议不同')
    keys = ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')
    require(fingerprint([{k: p.get(k) for k in keys} for p in packet['pairs']]) ==
            fingerprint([{k: p.get(k) for k in keys} for p in result['tables']['plan_scoring_pairs']]),
            '补救证据与本批完整评分表不同')
    return workflow, manifest, home, run, result, packet


def evidence_url(sid, rid, pair, input_key):
    """URL只含稳定对象和原固定输入，不暴露路径或可替换的组合序号。"""
    query = urlencode({'compound_id': pair['compound_id'], 'target_id': pair['target_id'],
                       'expected_input_key': input_key})
    return f'/api/v1/studies/{sid}/runs/{rid}/rescue-evidence/details?{query}'


def focus_matrix(view, compounds, targets):
    """服务端按固定顺序裁切展示格，原范围、评分和全批色标保持。"""
    matrix = view['table']
    for chosen, rows, key in ((compounds, matrix['rows'], 'compound_id'),
                              (targets, matrix['columns'], 'target_id')):
        require(isinstance(chosen, list) and all(isinstance(x, str) for x in chosen)
                and len(set(chosen)) == len(chosen)
                and set(chosen) <= {row[key] for row in rows}, '焦点筛选包含重复或未知稳定对象')
    ri = [i for i, row in enumerate(matrix['rows']) if row['compound_id'] in compounds]
    ci = [i for i, row in enumerate(matrix['columns']) if row['target_id'] in targets]
    return {'rows': [deepcopy(matrix['rows'][i]) for i in ri],
            'columns': [deepcopy(matrix['columns'][i]) for i in ci],
            'cells': [[deepcopy(matrix['cells'][i][j]) for j in ci] for i in ri]}


def _references(value):
    """只沿本运行明确绑定的文件引用追溯历史，不从目录或文件名搜寻成功。"""
    if isinstance(value, dict):
        if all(k in value for k in ('path', 'bytes', 'sha256')):
            yield value
        for child in value.values():
            yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _execution(bundle, fact, pair=None):
    """执行必须属于本批明确绑定的历史运行，状态与原分数精确对应。"""
    _, manifest, home, run, result, packet = bundle
    reference = fact.get('execution')
    registered = result['files']
    raw = checked_bytes(home, reference, registered)
    value = json.loads(raw)
    parts = PurePosixPath(reference['path']).parts
    require(len(parts) > 3 and parts[:2] == ('runs', 'A06'), '执行引用不是本批评分原件')
    origin_id = parts[2]
    origin_ref = manifest.get('runs', {}).get(origin_id, {}).get('run_file')
    require(origin_ref and (origin_id == run['run_id'] or any(
        same_file(origin_ref, ref) for ref in _references(run['inputs']))), '执行运行不在本批来源绑定中')
    origin = read_json(verified_file(home, origin_ref))
    require(origin.get('run_id') == origin_id and origin.get('study_id') == run['study_id']
            and origin.get('module_id') == 'A06' and origin.get('batch_file') == run.get('batch_file')
            and same_file(origin['inputs'].get('system_input_ref'), run['inputs']['system_input_ref'])
            and value.get('state') == fact['state']
            and fingerprint(value.get('score')) == fingerprint(fact.get('score')),
            '实际执行与本组合、批次或评分不同')
    # 同名或同分并不足以匹配；回到原运行自己的事实包，按稳定对象核对实际执行引用。
    owner = pair or fact
    origin_result_ref = manifest['runs'][origin_id].get('result_file')
    if origin_result_ref:
        origin_result = read_json(verified_file(home, origin_result_ref))
        refs = origin_result.get('tables', {}).get('scoring_packet', [])
        require(len(refs) == 1, '原执行运行缺少唯一评分事实包')
        origin_packet = json.loads(checked_bytes(home, refs[0], origin_result['files']))
        require(origin_packet.get('study_id') == run['study_id']
                and origin_packet.get('run_id') == origin_id, '原执行事实包归属不同')
        candidates = [p for p in origin_packet['pairs'] if p['compound_id'] == owner['compound_id']
                      and p['target_id'] == owner['target_id']]
        require(len(candidates) == 1, '原执行事实包没有唯一稳定对象组合')
        original_pair = candidates[0]
        candidates = [original_pair] if fact is owner else [r for r in original_pair.get('regions', [])
                                                        if r.get('region_id') == fact.get('region_id')]
        require(len(candidates) == 1 and same_file(candidates[0].get('execution'), reference)
                and candidates[0].get('state') == fact['state']
                and fingerprint(candidates[0].get('score')) == fingerprint(fact.get('score')),
                '执行引用不属于该稳定对象的原评分或区域')
    else:
        partial = run['inputs'].get('source_binding', {}).get('partial_recovery') or {}
        require(partial.get('run_id') == origin_id, '未发表执行没有本批明确检查点来源')
        expected = [(c['compound_id'], t['target_id']) for c in packet['source_fixed']['compounds']
                    for t in packet['source_fixed']['receptors']]
        ordinal = expected.index((owner['compound_id'], owner['target_id'])) + 1
        matches = []
        for checkpoint_ref in partial.get('checkpoint_refs', []):
            checkpoint = read_json(verified_file(home, checkpoint_ref))
            if checkpoint.get('key', '').startswith(f'pair_{ordinal:06d}_region_'):
                if same_file(checkpoint.get('payload', {}).get('execution'), reference):
                    matches.append(checkpoint)
        require(len(matches) == 1 and matches[0].get('run_id') == origin_id,
                '未发表执行没有对应稳定对象的已登记区域检查点')
    for item in value.get('files', []):
        checked_bytes(home, item, registered)
    return reference, raw, value, origin


def _top1(raw, score):
    """提取首个MODEL 1的精确原字节，拒绝换模式、缺尾或评分不符。"""
    chosen = []
    for line in raw.splitlines(keepends=True):
        if line.startswith(b'MODEL '):
            require(not chosen and line.split()[1:] == [b'1'], '原始第一构象不是唯一MODEL 1')
            chosen.append(line)
        elif chosen:
            chosen.append(line)
            if line.startswith(b'ENDMDL'):
                break
    require(chosen and chosen[-1].startswith(b'ENDMDL'), '原始MODEL 1不完整')
    scores = [float(line.split()[3]) for line in chosen if line.startswith(b'REMARK VINA RESULT:')]
    require(len(scores) == 1 and math.isfinite(scores[0]) and scores[0] == score,
            '原始MODEL 1评分与本组合不同')
    return b''.join(chosen)


def _artifacts(bundle, pair):
    """仅从该组合原执行构造只读下载；派生SHA按返回字节计算。"""
    _, _, home, run, result, packet = bundle
    ref, execution_raw, execution, origin = _execution(bundle, pair)
    artifacts = {'execution': (execution_raw, 'execution.json', 'application/json')}
    if pair['state'] != 'completed':
        return artifacts, ref, {'execution_run_id': origin['run_id']}
    require(execution.get('top_mode') == 1 and execution.get('returncode') == 0
            and execution.get('pose') in execution.get('files', []), '成功评分缺少原始Top-1执行证据')
    source = execution['pose']
    raw = checked_bytes(home, source, result['files'])
    top = _top1(raw, pair['score'])
    if pair.get('top1_pose'):
        require(checked_bytes(home, pair['top1_pose'], result['files']) == top,
                '已登记Top-1与实际执行MODEL 1不同')
    context = {'schema_version': VERSION, 'study_id': run['study_id'], 'run_id': run['run_id'],
               'compound_id': pair['compound_id'], 'target_id': pair['target_id'],
               'input_key': packet['summary']['input_key'], 'execution_run_id': origin['run_id'],
               'execution_sha256': ref['sha256'], 'source_pose_sha256': sha256(raw).hexdigest(),
               'source_pose_bytes': len(raw), 'top1_sha256': sha256(top).hexdigest(), 'top1_bytes': len(top),
               'top_mode': 1, 'score': pair['score'], 'unit': 'kcal/mol',
               'region_id': pair.get('region_id'), 'configuration': origin['config'],
               'read_only': True, 'scientific_results_changed': False,
               'source_zh': '来自已登记实际执行的MODEL 1原字节；沿用评分不计为本轮新增。'}
    artifacts.update(top1=(top, 'top1.pdbqt', 'chemical/x-pdbqt'),
                     source=(raw, 'original_poses.pdbqt', 'chemical/x-pdbqt'),
                     context=(json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8'),
                              'context.json', 'application/json'))
    return artifacts, ref, context


def _links(bundle, pair, artifacts, ref, *, region_id=None):
    """每个下载绑定原执行SHA与实际下载SHA，防止刷新后错取其他字节。"""
    run, packet = bundle[3], bundle[5]
    labels = {'execution': '原始执行证据', 'top1': 'Top-1原字节构象',
              'source': '原始全部模式构象', 'context': '构象来源与参数说明'}
    rows = []
    for kind, (raw, name, _) in artifacts.items():
        digest = sha256(raw).hexdigest()
        query = {'compound_id': pair['compound_id'], 'target_id': pair['target_id'],
                 'expected_input_key': packet['summary']['input_key'],
                 'expected_execution_sha256': ref['sha256'], 'expected_download_sha256': digest}
        if region_id is not None:
            query['region_id'] = region_id
        rows.append({'label_zh': labels[kind], 'name': name, 'sha256': digest, 'bytes': len(raw),
                     'url': f"/api/v1/studies/{run['study_id']}/runs/{run['run_id']}/rescue-evidence/{kind}?" + urlencode(query)})
    return rows


def read(app, req, sid, rid, kind):
    """GET仅读取归档；未知查询、陈旧绑定及损坏证据明确失败。"""
    fields = {'compound_id', 'target_id', 'expected_input_key'}
    if kind != 'details':
        fields |= {'expected_execution_sha256', 'expected_download_sha256'}
    if 'region_id' in req.query:
        fields.add('region_id')
    if set(req.query) != fields or any(len(v) != 1 for v in req.query.values()):
        raise ApiError(422, 'VALIDATION_FAILED', '证据查询字段错误，不接受路径或组合序号')
    try:
        bundle = load_bundle(app, sid, rid)
        workflow, manifest, _, run, _, packet = bundle
        if req.query1('expected_input_key') != packet['summary']['input_key']:
            raise ApiError(409, 'STALE_VERSION', '固定输入已改变，请刷新后下载')
        matches = [p for p in packet['pairs'] if p['compound_id'] == req.query1('compound_id')
                   and p['target_id'] == req.query1('target_id')]
        if len(matches) != 1:
            raise not_found('本批稳定对象组合')
        pair = matches[0]
        regions = pair.get('regions') or []
        require(isinstance(regions, list) and len({r['region_id'] for r in regions}) == len(regions),
                '区域记录重复或格式错误')
        region_id = req.query1('region_id')
        if region_id is not None:
            selected = [r for r in regions if r['region_id'] == region_id]
            if len(selected) != 1:
                raise not_found('本组合已登记区域')
            fact = selected[0]
            ref, raw, _, _ = _execution(bundle, fact, pair)
            artifacts, context = {'execution': (raw, 'execution.json', 'application/json')}, {}
        elif pair.get('execution'):
            artifacts, ref, context = _artifacts(bundle, pair)
        else:
            artifacts, ref, context = {}, None, {}
        if kind == 'details':
            shown = []
            for region in regions:
                region_ref, raw, _, _ = _execution(bundle, region, pair)
                selected = region['region_id'] == pair.get('region_id') and same_file(region_ref, pair.get('execution'))
                shown.append({**{k: deepcopy(region.get(k)) for k in ('region_id', 'state', 'score', 'reason_zh')},
                              'state_zh': STATE_ZH.get(region['state'], region['state']), 'selected': selected,
                              'downloads': _links(bundle, pair, {'execution': (raw, 'execution.json', 'application/json')},
                                                  region_ref, region_id=region['region_id'])})
            require(not regions or pair['state'] != 'completed' or sum(r['selected'] for r in shown) == 1,
                    '有效组合缺少唯一已登记选中区域')
            value = {'schema_version': VERSION, 'read_only': True, 'study_id': sid, 'run_id': rid,
                     'input_key': packet['summary']['input_key'], **{k: pair.get(k) for k in
                     ('compound_id', 'target_id', 'state', 'score')}, 'regions': shown,
                     'region_note_zh': '区域事实来自本批原始记录；局部失败不改变已归档组合评分。' if regions
                     else '原评分未登记区域明细，不推断或补造区域信息。',
                     'source_zh': context.get('source_zh', '已登记实际执行；未评分对象保留原原因。'),
                     'context': context, 'downloads': _links(bundle, pair, artifacts, ref) if artifacts else []}
        else:
            if kind not in artifacts:
                raise ApiError(409, 'GATE_BLOCKED', '本组合没有该类已核验构象证据')
            raw, name, mime = artifacts[kind]
            if req.query1('expected_execution_sha256') != ref['sha256'] or req.query1('expected_download_sha256') != sha256(raw).hexdigest():
                raise ApiError(409, 'STALE_VERSION', '执行或下载字节已改变，请刷新后下载')
            value = ('verified_download', raw, f'{rid}_{name}', mime, False)
        require(fingerprint(workflow.load(sid)) == fingerprint(manifest), '证据读取期间研究登记已改变')
        return value
    except (ContractError, KeyError, TypeError, ValueError, OSError) as error:
        raise ApiError(503, 'ARCHIVE_UNAVAILABLE', '无法完整核验本批执行证据：' + str(error)) from error


def focus(app, req, sid, rid):
    """焦点选择由后端校验与裁切，仅返回同批已有格子。"""
    if set(req.query) != {'expected_input_key', 'compounds', 'targets'} or any(len(v) != 1 for v in req.query.values()):
        raise ApiError(422, 'VALIDATION_FAILED', '焦点筛选查询字段错误')
    try:
        packet = load_bundle(app, sid, rid)[5]
        if req.query1('expected_input_key') != packet['summary']['input_key']:
            raise ApiError(409, 'STALE_VERSION', '焦点筛选来源已改变，请刷新')
        if packet['schema_version'] == 'A06.system_rescue.2':
            from science_modules.a06.system_rescue_display_v2 import build_view
        else:
            from science_modules.a06.system_rescue_display import build_view
        view = build_view(packet)
        for line in view['table']['cells']:
            for cell in line:
                cell['evidence_url'] = evidence_url(sid, rid, cell, packet['summary']['input_key'])
        matrix = focus_matrix(view, json.loads(req.query1('compounds')), json.loads(req.query1('targets')))
        return {'run_id': rid, 'input_key': packet['summary']['input_key'],
                'heatmap': matrix, 'score_range': view['score_range']}
    except (ContractError, ValueError, TypeError) as error:
        raise ApiError(422, 'VALIDATION_FAILED', str(error)) from error


def file_download(app, req, sid, key):
    """补救标准附件返回核验后的原字节；其他历史下载类型沿旧分派。"""
    rid, separator, index = key.rpartition('.')
    if not separator or not rid.startswith('run_') or not index.isdigit():
        return None
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    if rid not in manifest.get('runs', {}):
        return None
    run = workflow.run(manifest, rid)
    if run['config'].get('version') not in ('A06.system_rescue.1', 'A06.system_rescue.2'):
        return None
    if set(req.query) - {'inline', 'expected_sha256'} or any(len(v) != 1 for v in req.query.values()):
        raise ApiError(422, 'VALIDATION_FAILED', '补救附件查询字段错误')
    try:
        result = workflow.result(manifest, rid)
        files = (result or {}).get('files', [])
        if int(index) >= len(files):
            raise not_found('本运行已登记附件')
        record = files[int(index)]
        expected = req.query1('expected_sha256')
        if expected is not None and expected != record['sha256']:
            raise ApiError(409, 'STALE_VERSION', '附件登记已改变，请刷新后下载')
        raw = checked_bytes(workflow.location(sid), record, files)
        require(fingerprint(workflow.load(sid)) == fingerprint(manifest), '附件读取期间登记已改变')
        name = PurePosixPath(record['path']).name
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        return ('verified_download', raw, name, mime, req.query1('inline') == '1' and mime.startswith('image/'))
    except (ContractError, KeyError, TypeError, ValueError, OSError) as error:
        raise ApiError(503, 'ARCHIVE_UNAVAILABLE', '补救附件无法完整核验：' + str(error)) from error
