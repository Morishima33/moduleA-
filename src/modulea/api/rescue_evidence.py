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
from ..core.rescue_result_read import same_file, checked_bytes, load_rescue_result, bound_batch
from ..core.rescue_pose_evidence import _references, _execution, _top1, _score_source_note, _artifacts

VERSION = 'ModuleA.rescue_evidence.1'
STATE_ZH = {'completed': '已评分', 'failed': '执行失败', 'NA': '准备NA'}


def load_bundle(app, sid, rid):
    """沿公开Workflow读取本运行，不借用current结果或其他研究的准备。"""
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    if rid not in manifest.get('runs', {}):
        raise not_found('本研究评分运行')
    return load_rescue_result(workflow, manifest, sid, rid)


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
            ref, raw, _, _, _ = _execution(bundle, fact, pair)
            artifacts, context = {'execution': (raw, 'execution.json', 'application/json')}, {}
        elif pair.get('execution'):
            artifacts, ref, context = _artifacts(bundle, pair)
        else:
            artifacts, ref, context = {}, None, {}
        if kind == 'details':
            shown = []
            for region in regions:
                region_ref, raw, _, _, _ = _execution(bundle, region, pair)
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
