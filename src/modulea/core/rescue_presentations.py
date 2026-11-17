"""补救名称许可与独立图表修订；沿原Workflow短锁追加，不修改科学结果或人工复核。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from contracts import ContractError, fingerprint, require, safe_id
from storage import new_id, now, within, write_json, write_lock
from .bounded_evidence import digest_file, file_record, read_verified_json, verified_file
from .read_evidence import current_evidence
from .rescue_name_basis import source_basis
from .rescue_presentation_names import checked_catalog, derive_names
from .rescue_result_read import load_rescue_result, same_file
from .rescue_presentation_validation import validate_files
from .native_execution import NativeWorkflow

VERSION = 'ModuleA.rescue_presentation.1'
NAME_VERSION = 'ModuleA.rescue_original_name_decision.1'
NAMES = 'analysis_plan_rescue_name_decisions'
REQUESTS = 'analysis_plan_rescue_presentation_requests'
CANDIDATES = 'analysis_plan_rescue_presentation_candidates'
INDEX = 'analysis_plan_rescue_presentation_records'
FIELDS = {'request_id', 'expected_run_id', 'expected_input_hash', 'author', 'note', 'confirmed'}
DECISION_FIELDS = {'decision_id', 'expected_run_id', 'expected_source_hash', 'author', 'note',
                   'confirmed', 'entries', 'user_evidence'}
CATALOG = Path(__file__).with_name('rescue_display_name_catalog.json')


def _read(w, sid, ref):
    """HTTP只读范围显式登记首尾证据，其余调用仍逐次核验原字节。"""
    reader = current_evidence(w.root)
    return reader.reader.read(w.location(sid), ref) if reader else read_verified_json(w.location(sid), ref)


def _verify(w, sid, ref):
    """归档代码、字体和原件也纳入HTTP退出证明，不只核JSON或图件。"""
    reader = current_evidence(w.root)
    return reader.reader.verify(w.location(sid), ref) if reader else verified_file(w.location(sid), ref)


def implementation():
    """只绑定本展示实际使用的现有实现；不改变原科学协议或工具。"""
    root = Path(__file__).resolve().parents[2]
    names = ('modulea/core/rescue_presentations.py', 'modulea/core/rescue_name_basis.py',
             'modulea/core/rescue_presentation_names.py', 'modulea/core/rescue_result_read.py',
             'modulea/core/rescue_presentation_validation.py', 'modulea/core/png_integrity.py',
             'modulea/core/kernel.py', 'modulea/tasks/rescue_presentation.py',
             'modulea/tasks/manager.py', 'modulea/tasks/worker.py', 'modulea/tasks/resource_runner.py',
             'modulea/tasks/compute_budget.py', 'modulea/tasks/process_identity.py',
             'science_modules/a06/system_rescue_presentation.py', 'science_modules/a06/system_rescue_display.py',
             'science_modules/a06/system_rescue_display_v2.py', 'science_modules/a06/matrix_palette.py',
             'science_modules/a07/plan_translations_v2.py')
    return {name: digest_file(root / name)[1] for name in names}


def _font(path):
    """字体由服务器配置或本机现有默认路径提供；请求只绑定字节，不接浏览器路径。"""
    path = Path(path) if path else Path('C:/Windows/Fonts/msyh.ttc')
    require(path.is_file(), '请配置可用中文绘图字体')
    size, digest = digest_file(path)
    return path, {'name': path.name, 'bytes': size, 'sha256': digest}


def _context(w, sid, rid):
    """真实完整评分及原状态规则是写修订的前提，不为尚运行科学批次追加manifest。"""
    safe_id(rid, 'run')
    m = w.load(sid)
    require(not m.get('trashed') and m['current'].get('A06') == rid
            and m['runs'].get(rid, {}).get('result_file'), '请等待当前本批科学评分完整归档后再修订')
    require(w.active(m, rid), '本批科学来源已失效或上游人工意见改变')
    basis = source_basis(w, m, sid, rid)
    bundle = load_rescue_result(w, m, sid, rid)
    packet = bundle[-1]
    # 新producer可能补展示name字段；身份和准备状态必须保持原资格，不能以译名补身份。
    keys = ('compound_id', 'state', 'cid')
    require(fingerprint([{k: row.get(k) for k in keys} for row in basis['prepared']]) ==
            fingerprint([{k: row.get(k) for k in keys} for row in packet['compounds']]),
            '本批评分成分身份或准备状态与名称原准备不同')
    source = dict(basis=deepcopy(basis['source']), evidence=deepcopy(basis['evidence']),
                  scoring_packet=deepcopy(bundle[4]['tables']['scoring_packet'][0]),
                  scoring_files=deepcopy(bundle[4]['files']), review_files=deepcopy(m.get('reviews', [])))
    return m, basis, bundle, source


def _without_review_files(records, source):
    """实际人工意见独立核对，不能将意见附件混作不可变名称身份来源。"""
    return [deepcopy(ref) for ref in records if not any(same_file(ref, review) for review in source['review_files'])]


def _immutable_source(source):
    """原专名许可绑定原运行/结果/输入/对象；科研暂停另由_context严格阻断。"""
    value = deepcopy(source)
    value['basis']['reviews'] = []
    value['evidence'] = _without_review_files(value['evidence'], source)
    value.pop('review_files')
    return value


def _comparable_binding(bound):
    """只剥离已经单独核验的人工意见引用，译名、原件、代码和许可全部保留。"""
    value = deepcopy(bound);source = bound['source']
    value['source'] = _immutable_source(source)
    value['name_basis']['source']['reviews'] = []
    value['name_basis']['evidence'] = _without_review_files(value['name_basis']['evidence'], source)
    for row in value['names']['names']:row['evidence'] = _without_review_files(row['evidence'], source)
    return value


def compatible_binding(w, m, archived, current):
    """复用原唯一首次通过兼容；暂存、退回后重批不能让旧修订自动复活。"""
    from .system_validation import same_binding_after_first_approval
    return same_binding_after_first_approval(w, m,
        {'immutable': _comparable_binding(archived), 'reviews': archived['source']['basis']['reviews']},
        {'immutable': _comparable_binding(current), 'reviews': current['source']['basis']['reviews']})


def _name_decision(w, m, ref):
    """原专名决定只能从本研究不可变登记读取；完整原问题与答复保留供审计。"""
    require(ref in m.get(NAMES, []), '本研究原专名许可未登记')
    value = _read(w, m['study_id'], ref)
    body = value['decision']
    _confirmed(body, DECISION_FIELDS, 'decision_id', 'rescuename')
    require(value.get('schema_version') == NAME_VERSION and value.get('study_id') == m['study_id']
            and value.get('decision_hash') == fingerprint(body)
            and value.get('source_hash') == fingerprint(value['source']) == body['expected_source_hash']
            and value['source']['basis']['run_id'] == body['expected_run_id']
            and body['confirmed'] is True and value.get('human_review_written') is False,
            '本研究原专名许可内容或来源不同')
    require(isinstance(body.get('entries'), list) and body['entries']
            and all(isinstance(row, dict) and set(row) ==
                    {'compound_id', 'source_identifier', 'source_name', 'name_scope'}
                    and row['name_scope'] == 'original_proper_name' for row in body['entries'])
            and len({row['compound_id'] for row in body['entries']}) == len(body['entries'])
            and value.get('allowed_original_name_ids') == sorted(row['compound_id'] for row in body['entries'])
            and value.get('counts_as_checked_chinese') is False, '原专名允许范围与实际决定清单不同')
    safe_id(body['decision_id'], 'rescuename')
    return value


def _binding(w, m, basis, source, *, font_path):
    """相同研究、运行、原件和明确决定才派生允许范围；无全局专名豁免。"""
    import json
    raw = CATALOG.read_bytes();catalog = json.loads(raw.decode('utf-8'));checked_catalog(catalog)
    refs, allowed = [], set()
    for ref in m.get(NAMES, []):
        decision = _name_decision(w, m, ref)
        if _immutable_source(decision['source']) == _immutable_source(source):
            refs.append(deepcopy(ref));allowed.update(decision['allowed_original_name_ids'])
    names = derive_names(basis, catalog, allowed_original_names=allowed)
    _, font = _font(font_path)
    bound = {'source': deepcopy(source), 'name_basis': deepcopy(basis), 'names': names,
             'catalog_sha256': sha256(raw).hexdigest(), 'implementation': implementation(),
             'font': font, 'name_decisions': refs, 'renderer_protocol': 'A06.system_rescue.display.3'}
    return bound, raw


def info(w, sid, rid, *, font_path=None):
    """只读候选和请求指纹；缺译、未发表或失效时给出原因，不登记许可或补图。"""
    blockers, bound, source = [], None, None
    try:
        m, basis, bundle, source = _context(w, sid, rid)
        bound, _ = _binding(w, m, basis, source, font_path=font_path)
        blockers.extend(row['reason_zh'] for row in bound['names']['blockers'])
    except (ContractError, OSError, KeyError, ValueError, TypeError) as error:
        blockers.append(str(error))
    return {'schema_version': VERSION, 'run_id': rid, 'enabled': bool(bound and not blockers),
            'blockers_zh': blockers, 'expected_source_hash': fingerprint(source) if source else None,
            'expected_input_hash': fingerprint(bound) if bound else None,
            'translation_missing_ids': bound['names']['missing_ids'] if bound else [],
            'names': deepcopy(bound['names']['names']) if bound else []}


def _confirmed(body, expected, id_field, prefix):
    """明确请求只接受固定字段，不能提供图片、得分、CID、路径或任意通过标记。"""
    require(isinstance(body, dict) and set(body) == expected, '名称修订请求字段不同')
    safe_id(body[id_field], prefix);safe_id(body['expected_run_id'], 'run')
    require(body['confirmed'] is True and all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 2000
            for key in ('author', 'note')), '请填写明确登记人及依据')


def register_name_decision(w, sid, body, *, check_task=None):
    """公开Workflow仅登记用户实际明确的原专名范围，不是科研批准，不变更任何NA。"""
    _confirmed(body, DECISION_FIELDS, 'decision_id', 'rescuename')
    require(isinstance(body['user_evidence'], dict) and set(body['user_evidence']) == {'source_id', 'question', 'answer'}
            and all(isinstance(value, str) and 0 < len(value.strip()) <= 8000
                    for value in body['user_evidence'].values()), '缺少原专名许可的实际问题、答复或来源')
    with write_lock(w.root):
        if check_task:check_task()
        m, basis, _, source = _context(w, sid, body['expected_run_id'])
        require(body['expected_source_hash'] == fingerprint(source), '原专名许可来源已改变')
        for ref in m.get(NAMES, []):
            old = _name_decision(w, m, ref)
            if old['decision']['decision_id'] == body['decision_id']:
                require(old['decision'] == body, '原专名决定编号已用于其他内容')
                return dict(old, file=deepcopy(ref), created=False)
        import json
        pending = derive_names(basis, json.loads(CATALOG.read_text('utf-8')))
        choices = {row['compound_id']: row for row in pending['names']
                   if row['translation_status'] == 'original_name_requires_user_decision'}
        rows = body['entries']
        require(isinstance(rows, list) and rows and all(isinstance(row, dict) and set(row) ==
                {'compound_id', 'source_identifier', 'source_name', 'name_scope'} for row in rows), '原专名许可清单错误')
        ids = [row['compound_id'] for row in rows]
        require(len(ids) == len(set(ids)), '原专名许可对象重复')
        for row in rows:
            expected = choices.get(row['compound_id'])
            require(expected and row['source_identifier'] == expected['identity']
                    and row['source_name'] == expected['source_name'] and row['name_scope'] == 'original_proper_name',
                    '原专名许可超出本批精确原身份或原名范围')
        value = {'schema_version': NAME_VERSION, 'study_id': sid, 'decision': deepcopy(body),
                 'decision_hash': fingerprint(body), 'source': source, 'source_hash': fingerprint(source),
                 'allowed_original_name_ids': sorted(ids), 'counts_as_checked_chinese': False,
                 'human_review_written': False, 'created_at': now()}
        # 文件落盘而索引保存前中断时，下次另存同body快照；旧未登记决定原样保留。
        path = within(w.location(sid), Path('decisions/analysis_plans/rescue_presentations/names') /
                      body['decision_id'] / new_id('rescuenameattempt') / 'decision.json')
        write_json(path, value)
        ref = file_record(w.location(sid), path, 'rescue_original_name_decision')
        m.setdefault(NAMES, []).append(ref);w.save(m)
    return dict(value, file=ref, created=True)


def _read_request(w, m, ref):
    """恢复只认本研究登记的明确请求及原实施/字体/词典字节，不凭目录成功猜测。"""
    require(ref in m.get(REQUESTS, []), '名称展示请求未登记')
    value = _read(w, m['study_id'], ref)
    body, bound = value['request'], value['binding']
    _confirmed(body, FIELDS, 'request_id', 'rescuereq')
    require(value.get('schema_version') == VERSION and value.get('study_id') == m['study_id']
            and value['request_hash'] == fingerprint(body) and body['expected_input_hash'] == fingerprint(bound)
            and body['expected_run_id'] == bound['source']['basis']['run_id'], '名称展示请求或来源指纹不同')
    home = w.location(m['study_id'])
    for item in value['implementation_files']:_verify(w, m['study_id'], item)
    require({row['source_path']: row['file']['sha256'] for row in value['implementation_sources']} == bound['implementation']
            and all(row['file'] in value['implementation_files'] for row in value['implementation_sources'])
            and value['catalog_file']['sha256'] == bound['catalog_sha256']
            and value['font_file']['sha256'] == bound['font']['sha256']
            and value['font_file']['bytes'] == bound['font']['bytes'], '名称展示实现、字体或词典归档不同')
    for item in (value['catalog_file'], value['font_file']):_verify(w, m['study_id'], item)
    for item in bound['name_decisions']:_name_decision(w, m, item)
    return value


def read_record(w, sid, ref):
    """历史按绑定原件读取，后来退回或current改变不删除旧修订、也不使其冒充当前。"""
    m = w.load(sid)
    require(ref in m.get(INDEX, []) or ref in m.get(CANDIDATES, []), '名称展示修订未登记')
    value = _read(w, sid, ref);request = _read_request(w, m, value['request_file']);bound = request['binding']
    safe_id(value['revision_id'], 'rescueview')
    require(value.get('schema_version') == VERSION and value.get('study_id') == sid
            and value.get('run_id') == bound['source']['basis']['run_id']
            and value.get('input_hash') == fingerprint(bound)
            and value.get('human_review_written') is False and value.get('scientific_results_changed') is False,
            '名称展示回执归属或绑定不同')
    home = w.location(sid)
    for rid, original in bound['source']['basis']['run_files'].items():
        require(m['runs'].get(rid) == original, '历史名称展示的原运行登记已改变')
    for item in [*bound['source']['evidence'], bound['source']['scoring_packet'], *bound['source']['scoring_files']]:
        _verify(w, sid, item)
    base = Path('runs/A06') / value['run_id'] / 'rescue/presentations' / value['revision_id']
    require(value['files'] and len({row['path'] for row in value['files']}) == len(value['files'])
            and all(Path(row['path']).parent == base for row in value['files']), '名称展示附件不属于同一修订')
    for item in value['files']:_verify(w, sid, item)
    packet = _read(w, sid, bound['source']['scoring_packet'])
    validate_files(home, packet, bound['names']['names'], bound['names']['allowed_original_name_ids'], value['files'])
    return dict(value, file=deepcopy(ref))


def _validate(w, sid, body, font_path):
    """每次恢复和发表都重核当前来源、意见、实现与字体；仅原请求可复用原候选。"""
    _confirmed(body, FIELDS, 'request_id', 'rescuereq')
    m, basis, bundle, source = _context(w, sid, body['expected_run_id'])
    bound, raw = _binding(w, m, basis, source, font_path=font_path)
    ref = None
    for item in m.get(REQUESTS, []):
        request = _read_request(w, m, item)
        if request['request']['request_id'] == body['request_id']:
            require(request['request'] == body and compatible_binding(w, m, request['binding'], bound),
                    '原名称请求编号、来源、许可、人工意见或实现已改变')
            bound = request['binding']
            ref = item
    require(body['expected_input_hash'] == fingerprint(bound), '名称展示来源、许可、实现或字体已改变')
    require(not bound['names']['missing_ids'], '本批名称仍缺译或缺少精确原专名许可')
    return m, bound, raw, bundle[-1], ref


def publish(w, sid, body, *, font_path=None, check_task=None):
    """原任务预算worker在锁外绘图，短锁复核后追加；候选完整恢复不重画，损坏阻断。"""
    with write_lock(w.root):
        if check_task:check_task()
        m, bound, raw, packet, request_ref = _validate(w, sid, body, font_path)
        home = w.location(sid)
        if request_ref:
            for ref in m.get(INDEX, []):
                value = read_record(w, sid, ref)
                if value['request_file'] == request_ref:return dict(value, created=False)
        folder = within(home, 'decisions/analysis_plans/rescue_presentations/requests/' + body['request_id'])
        if request_ref is None:
            # 未登记的中断残件不算完成；保留原快照，新尝试另目录，不覆盖或删除。
            archive = within(home, folder.relative_to(home) / 'preparations' / new_id('rescuepreparation'))
            archive.mkdir(parents=True, exist_ok=False)
            sources, files = [], []
            root = Path(__file__).resolve().parents[2]
            for name, digest in bound['implementation'].items():
                code = (root / name).read_bytes();require(sha256(code).hexdigest() == digest, '名称展示实现已改变')
                path = archive / 'implementation' / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(code)
                item = file_record(home, path, 'rescue_presentation_implementation');files.append(item)
                sources.append({'source_path': name, 'file': item})
            catalog = archive / 'catalog.json';catalog.write_bytes(raw)
            font, _ = _font(font_path);font_copy = archive / 'font' / bound['font']['name']
            font_copy.parent.mkdir();font_copy.write_bytes(font.read_bytes())
            require(digest_file(font_copy) == (bound['font']['bytes'], bound['font']['sha256']), '名称展示字体复制期间已改变')
            request = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body),
                'request_hash': fingerprint(body), 'binding': bound, 'implementation_files': files,
                'implementation_sources': sources, 'catalog_file': file_record(home, catalog, 'rescue_presentation_catalog'),
                'font_file': file_record(home, font_copy, 'rescue_presentation_font'), 'created_at': now()}
            path = archive / 'request.json';write_json(path, request)
            request_ref = file_record(home, path, 'rescue_presentation_request')
            m.setdefault(REQUESTS, []).append(request_ref);_read_request(w, m, request_ref);w.save(m)
        before = {key: deepcopy(m[key]) for key in ('current', 'runs', 'reviews')}
        candidate = None
        for ref in m.get(CANDIDATES, []):
            value = read_record(w, sid, ref)
            if value['request_file'] == request_ref:candidate = value
    try:
        if candidate is None:
            from science_modules.a06.system_rescue_presentation import export
            revision_id = new_id('rescueview')
            out = home / 'runs/A06' / body['expected_run_id'] / 'rescue/presentations' / revision_id
            request = _read_request(w, w.load(sid), request_ref)
            figures, attachments = export(home, packet, bound['names']['names'], out,
                allowed_original_names=bound['names']['allowed_original_name_ids'], font_path=home / request['font_file']['path'])
            validate_files(home, packet, bound['names']['names'], bound['names']['allowed_original_name_ids'], figures + attachments)
            candidate = {'schema_version': VERSION, 'study_id': sid, 'run_id': body['expected_run_id'],
                'revision_id': revision_id, 'request_file': deepcopy(request_ref), 'input_hash': fingerprint(bound),
                'files': figures + attachments, 'human_review_written': False, 'scientific_results_changed': False,
                'created_at': now()}
            with write_lock(w.root):
                if check_task:check_task()
                m, current, _, _, _ = _validate(w, sid, body, font_path)
                require(current == bound, '名称展示绘制期间来源已改变')
                path = folder / (revision_id + '.candidate.json');write_json(path, candidate)
                ref = file_record(home, path, 'rescue_presentation_candidate')
                m.setdefault(CANDIDATES, []).append(ref);w.save(m)
        with write_lock(w.root):
            if check_task:check_task()
            m, current, _, _, _ = _validate(w, sid, body, font_path)
            require(current == bound and all(m[key] == value for key, value in before.items()),
                    '名称展示发表前来源、运行或人工意见已改变')
            candidate_ref = next(ref for ref in m[CANDIDATES]
                                 if _read(w, sid, ref)['revision_id'] == candidate['revision_id'])
            candidate = read_record(w, sid, candidate_ref);candidate.pop('file')
            path = folder / 'receipt.json'
            if path.exists():require(read_verified_json(home, file_record(home, path, 'receipt')) == candidate,
                                     '已有名称回执内容不同，禁止覆盖')
            else:write_json(path, candidate)
            ref = file_record(home, path, 'rescue_presentation_receipt')
            if ref not in m.setdefault(INDEX, []):m[INDEX].append(ref)
            w.save(m)
        return dict(candidate, file=ref, created=True)
    except Exception as error:
        # 故障诊断另存，不在来源已变或取消后再改科学manifest，以免破坏正在接续的新任务。
        write_json(folder / (new_id('rescueviewfailure') + '.json'), {'schema_version': VERSION,
            'study_id': sid, 'request_file': request_ref, 'error_zh': str(error), 'created_at': now()})
        raise


class RescuePresentationMixin:
    """唯一公开写入口保留原Workflow的状态、存储和科学继承行为。"""
    def rescue_presentation_info(self, sid, rid, *, font_path=None):
        """只读检查本批修订资格，不生成或登记附件。"""
        return info(self, sid, rid, font_path=font_path)

    def register_rescue_original_name_decision(self, sid, body, *, check_task=None):
        """保存精确原专名决定，独立于科研复核。"""
        return register_name_decision(self, sid, body, check_task=check_task)

    def publish_rescue_presentation(self, sid, body, *, font_path=None, check_task=None):
        """在原任务预算内追加同批名称图表，保留原科学结果。"""
        return publish(self, sid, body, font_path=font_path, check_task=check_task)

    def read_rescue_presentation(self, sid, ref):
        """按明确登记读取当前或历史修订。"""
        return read_record(self, sid, ref)


class RescuePresentationWorkflow(RescuePresentationMixin, NativeWorkflow):
    """只增公开名称与图件方法，原_active/_begin/save及科学状态原样继承。"""
