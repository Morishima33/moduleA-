"""名称修订的明确版本目录、同批矩阵与附件；只读不绘图，写请求只排原重任务。"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import urlencode

from contracts import ContractError, fingerprint, require, safe_id
from ..core import rescue_presentations as core
from ..core.rescue_result_read import load_rescue_result
from ..core.rescue_presentation_read import matches_current as _matches
from ..core.read_evidence import current_evidence, read_call
from .errors import ApiError, not_found
from .rescue_evidence import evidence_url, focus_matrix


@contextmanager
def _errors():
    """明确查询错误保留原状态，损坏或归属不明的原件统一阻断。"""
    try:
        yield
    except (ContractError, OSError, KeyError, TypeError, ValueError) as error:
        raise ApiError(503, 'ARCHIVE_UNAVAILABLE', '名称修订原件无法完整核验：' + str(error)) from error


def _query(req, required, optional=()):
    """只接受明确单值，不接路径、覆盖名称、评分或重复版本字段。"""
    if not required <= set(req.query) or set(req.query) - required - set(optional) or any(
            not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str)
            for value in req.query.values()):
        raise ApiError(422, 'VALIDATION_FAILED', '名称修订查询字段缺失、重复或越界')


def _base(app, sid, rid):
    """运行必须实际登记在本研究，不能从目录或current代替指定运行。"""
    w = app.kernel.read_workflow();m = w.load(sid)
    if rid not in m.get('runs', {}):raise not_found('本研究评分运行')
    run = w.run(m, rid)
    require(run.get('module_id') == 'A06' and run.get('config', {}).get('version') in
            ('A06.system_rescue.1', 'A06.system_rescue.2'), '本运行不支持补救名称修订')
    return w, m


def _status(w, m, sid, rid, font_path):
    """生成资格仍用原完整状态规则；历史查看不因当前暂停而丢失原件。"""
    try:
        current, basis, bundle, source = read_call(core._context, w, sid, rid)
        require(fingerprint(current) == fingerprint(m), '名称修订读取期间研究登记改变')
        bound, _ = core._binding(w, m, basis, source, font_path=font_path)
        return bound, bundle, [row['reason_zh'] for row in bound['names']['blockers']]
    except (ContractError, OSError, KeyError, ValueError, TypeError) as error:
        return None, None, [str(error)]


def _records(w, m, sid, rid):
    """只深入核本运行修订；原回执先核SHA，不能靠文件名猜版本。"""
    values, ids = [], set()
    for ref in m.get(core.INDEX, []):
        header = core._read(w, sid, ref)
        if header.get('run_id') != rid:continue
        value = w.read_rescue_presentation(sid, ref)
        require(value['revision_id'] not in ids, '同一名称修订编号重复登记')
        ids.add(value['revision_id']);values.append(value)
    return values




def _descriptor(sid, rid, record, matches):
    """链接固定回执SHA与原input_key，后来的修订不改变既有URL。"""
    ref = record['file']
    return {'revision_id': record['revision_id'], 'receipt_sha256': ref['sha256'],
            'created_at': record['created_at'], 'input_key': record['input_key'], 'matches_input': matches,
            'view_url': f'/api/v1/studies/{sid}/runs/{rid}/rescue-presentations/{record["revision_id"]}?' +
                urlencode({'expected_revision_sha256': ref['sha256'], 'expected_input_key': record['input_key']})}


def directory(app, req, sid, rid):
    """只读版本目录；新生成资格与当前/历史修订分别表示，不自动排队。"""
    _query(req, set(), {'include_current'})
    include_current = req.query1('include_current')
    if include_current not in (None, '1'):
        raise ApiError(422, 'VALIDATION_FAILED', '当前图表读取参数错误')
    return read_directory(app, sid, rid, include_current=include_current == '1')


def _matching_page_cache(workflow, manifest, snapshot):
    """仅使用当前请求已核验、同一登记版本且未进入回收站的视图缓存。"""
    if snapshot is None or manifest.get('trashed'):
        return None
    display, view, _ = snapshot
    evidence = current_evidence(workflow.root)
    if (evidence is not None and evidence.study_id == manifest.get('study_id')
            and getattr(display, '_request_view_cache_scope', None) is evidence
            and view and view.get('manifest') == dict(manifest, trashed=False)):
        return display._request_view_cache
    return None


def read_directory(app, sid, rid, *, include_current=False, page_snapshot=None):
    """工作台和独立目录共用同一只读核验。"""
    with _errors():
        w, m = _base(app, sid, rid)
        shared = _matching_page_cache(w, m, page_snapshot)
        if shared is not None:
            w._view_cache = shared
        bound, bundle, blockers = _status(w, m, sid, rid, app.settings.font_regular)
        history, current = [], None
        current_record = current_request = None
        for record in _records(w, m, sid, rid):
            request = core._read_request(w, m, record['request_file'])
            record['input_key'] = request['binding']['source']['basis']['input_key']
            item = _descriptor(sid, rid, record, _matches(w, m, record, bound))
            history.append(item)
            if item['matches_input']:
                current = item
                current_record, current_request = record, request
        if app.tasks.active_for(sid):blockers.append('本研究已有活动任务，请等待完成')
        if current:blockers.append('本批已有适用的名称图表修订，可直接查看或下载')
        reply = {'schema_version': core.VERSION, 'run_id': rid, 'enabled': bool(bound and not blockers),
                 'blockers_zh': blockers, 'expected_input_hash': fingerprint(bound) if bound else None,
                 'translation_missing_ids': bound['names']['missing_ids'] if bound else [],
                 'current': current, 'history': history, 'read_only': True}
        if include_current:
            reply['current_view'] = None
            if current_record is not None:
                selected = _selection(w, m, sid, rid, current_record, current_request, bundle)
                selected['matches_input'] = True
                reply['current_view'] = _view(selected, sid, rid, current['revision_id'], current['input_key'])
        require(fingerprint(w.load(sid)) == fingerprint(m), '名称修订目录读取期间登记改变')
        return reply


def select(app, req, sid, rid, revision_id):
    """内部读取统一选择一个已登记修订；不把客户端提供的路径或内容当证据。"""
    try:safe_id(revision_id, 'rescueview')
    except ContractError as error:raise ApiError(422, 'VALIDATION_FAILED', str(error)) from error
    w, m = _base(app, sid, rid)
    chosen = next((value for value in _records(w, m, sid, rid) if value['revision_id'] == revision_id), None)
    if chosen is None:raise not_found('本运行已登记名称修订')
    if req.query1('expected_revision_sha256') != chosen['file']['sha256']:
        raise ApiError(409, 'STALE_VERSION', '名称修订回执已改变，请刷新')
    request = core._read_request(w, m, chosen['request_file']);bound = request['binding']
    if req.query1('expected_input_key') != bound['source']['basis']['input_key']:
        raise ApiError(409, 'STALE_VERSION', '名称修订固定输入已改变，请刷新')
    current, bundle, _ = _status(w, m, sid, rid, app.settings.font_regular)
    result = _selection(w, m, sid, rid, chosen, request, bundle)
    result['matches_input'] = _matches(w, m, chosen, current)
    require(fingerprint(w.load(sid)) == fingerprint(m), '名称修订读取期间登记改变')
    return result


def _selection(w, m, sid, rid, record, request, bundle):
    bound = request['binding']
    if bundle is None:
        bundle = load_rescue_result(w, m, sid, rid)
    require(bundle[4]['tables']['scoring_packet'][0] == bound['source']['scoring_packet'], '名称修订与指定评分包不同')
    saved = next(ref for ref in record['files'] if ref['role'] == 'a06_rescue_display_view')
    return {'workflow': w, 'manifest': m, 'home': w.location(sid), 'record': record,
            'request': request, 'binding': bound, 'bundle': bundle, 'view': core._read(w, sid, saved)}


def _revision(selection, matches=False):
    """目录与验收包共享同一回执、名称范围及原输入说明。"""
    record, bound = selection['record'], selection['binding']
    return {'revision_id': record['revision_id'], 'receipt_sha256': record['file']['sha256'],
            'input_key': bound['source']['basis']['input_key'], 'input_hash': record['input_hash'],
            'matches_input': matches, 'name_counts': deepcopy(selection['view']['name_counts']),
            'allowed_original_name_ids': deepcopy(bound['names']['allowed_original_name_ids'])}


def view(app, req, sid, rid, revision_id):
    """同修订矩阵、焦点URL、图和验收下载统一绑定，分数与原英文来源保持。"""
    _query(req, {'expected_revision_sha256', 'expected_input_key'})
    with _errors():
        selected = select(app, req, sid, rid, revision_id)
        return _view(selected, sid, rid, revision_id, req.query1('expected_input_key'))


def _view(selected, sid, rid, revision_id, input_key):
    """显式版本和目录中的当前版本使用同一个矩阵与链接构建规则。"""
    result = deepcopy(selected['view']);packet = selected['bundle'][-1]
    result['presentation_revision'] = _revision(selected, selected['matches_input'])
    tokens = {'expected_revision_sha256': selected['record']['file']['sha256'], 'expected_input_key': input_key}
    base = f'/api/v1/studies/{sid}/runs/{rid}/rescue-presentations/{revision_id}'
    result.update(input_key=tokens['expected_input_key'], focus_url=base + '/focus?' + urlencode(tokens),
        acceptance_url=f'/api/v1/studies/{sid}/runs/{rid}/acceptance?' + urlencode(dict(tokens, revision_id=revision_id)),
        downloads=[], figures=[], summary_rows=[], receptor_preparation=[])
    for matrix in (result['table'], result['heatmap']):
        for line in matrix['cells']:
            for cell in line:cell['evidence_url'] = evidence_url(sid, rid, cell, tokens['expected_input_key'])
    result['heatmap'] = focus_matrix(result, result['initial_focus']['compound_ids'], result['initial_focus']['target_ids'])
    from .system_rescue_view import COUNTS, COUNTS_V2, preparation_rows
    counts = COUNTS_V2 if packet['schema_version'] == 'A06.system_rescue.2' else COUNTS
    result['summary_rows'] = [{'label_zh': label, 'text': str(packet['summary'][key])}
                              for key, label in counts if packet['summary'].get(key) is not None]
    result['receptor_preparation'] = preparation_rows(selected['bundle'][4])
    for index, ref in enumerate(selected['record']['files']):
        url = base + '/files/' + str(index) + '?' + urlencode(dict(tokens, expected_sha256=ref['sha256']))
        name = PurePosixPath(ref['path']).name
        link = dict(label_zh=name, name=name, url=url, bytes=ref['bytes'], sha256=ref['sha256'])
        result['downloads'].append(link)
        if ref['role'] in ('plot_a06_rescue_full_png', 'plot_a06_rescue_focus_png'):
            result['figures'].append(dict(link, image_url=url + '&inline=1', role=ref['role']))
    return result


def focus(app, req, sid, rid, revision_id):
    """裁切只用本修订已核验的原格子，不新算阈值或改变名称。"""
    _query(req, {'expected_revision_sha256', 'expected_input_key', 'compounds', 'targets'})
    with _errors():
        selected = select(app, req, sid, rid, revision_id)
        try:
            matrix = focus_matrix(selected['view'], json.loads(req.query1('compounds')), json.loads(req.query1('targets')))
        except (ContractError, ValueError, TypeError) as error:raise ApiError(422, 'VALIDATION_FAILED', str(error)) from error
        for line in matrix['cells']:
            for cell in line:cell['evidence_url'] = evidence_url(sid, rid, cell, req.query1('expected_input_key'))
        return {'run_id': rid, 'revision_id': revision_id, 'receipt_sha256': selected['record']['file']['sha256'],
                'input_key': req.query1('expected_input_key'), 'heatmap': matrix, 'score_range': selected['view']['score_range']}


def download(app, req, sid, rid, revision_id, index):
    """附件只返回该回执中的精确字节；路径、字体与其它修订不能由查询替换。"""
    _query(req, {'expected_revision_sha256', 'expected_input_key', 'expected_sha256'}, {'inline'})
    if req.query1('inline') not in (None, '1'):raise ApiError(422, 'VALIDATION_FAILED', '内联读取参数错误')
    with _errors():
        selected = select(app, req, sid, rid, revision_id)
        files = selected['record']['files']
        if not isinstance(index, str) or not index.isdigit() or int(index) >= len(files):raise not_found('本修订附件')
        ref = files[int(index)]
        if req.query1('expected_sha256') != ref['sha256']:raise ApiError(409, 'STALE_VERSION', '名称图表附件已改变，请刷新')
        path = core._verify(selected['workflow'], sid, ref);raw = path.read_bytes()
        require(len(raw) == ref['bytes'] and sha256(raw).hexdigest() == ref['sha256'], '名称附件读取期间原件变化')
        require(fingerprint(selected['workflow'].load(sid)) == fingerprint(selected['manifest']), '名称附件读取期间登记改变')
        name = PurePosixPath(ref['path']).name;mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        return ('verified_download', raw, name, mime, req.query1('inline') == '1')


def submit(app, req, sid, rid):
    """这里只排队已有技术重任务；不接受新的专名许可或任何科学结果覆盖。"""
    body = req.json()
    try:core._confirmed(body, core.FIELDS, 'request_id', 'rescuereq')
    except (ContractError, KeyError, TypeError) as error:raise ApiError(422, 'VALIDATION_FAILED', str(error)) from error
    if body['expected_run_id'] != rid:raise ApiError(409, 'STALE_VERSION', '本次图表修订运行已改变')
    if app.tasks.active_for(sid):raise ApiError(409, 'TASK_BUSY', '本研究已有活动任务，请等待完成')
    w = app.kernel.workflow()
    try:core._validate(w, sid, body, app.settings.font_regular)
    except (ContractError, KeyError, OSError, ValueError, TypeError) as error:
        raise ApiError(409, 'GATE_BLOCKED', str(error)) from error
    task, created = app.tasks.submit(sid, 'plan_rescue_presentation', body['author'], {'stage': 'publish', 'request': body})
    if not created:raise ApiError(409, 'TASK_BUSY', '本研究已有活动任务，请等待完成')
    return {'task': task, 'created': True, 'message_zh': '本批名称图表已排队，未改变评分或科研复核。'}, 202
