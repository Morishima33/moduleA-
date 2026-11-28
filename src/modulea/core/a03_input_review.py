"""集中核验绑定两侧原件、剩余清单和用户在 A03 提交的决定。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contracts import ContractError, fingerprint, require
from storage import file_record, new_id, read_json, verified_file, write_json, write_lock
from workflow import Workflow
from . import system_execution

PREVIEWS = 'analysis_plan_a03_input_previews'
DECISIONS = 'analysis_plan_a03_input_decisions'
VERSION = 'ModuleA.a03_input_review.1'
VERSIONS = {'A01': 'A01.a03_input_review.1', 'A02': 'A02.a03_input_review.1'}
MODULES = tuple(VERSIONS)
NOTICE = '仅限本批流程测试。用户明确暂不采用所列未决身份，保留原件、证据和限制。'


def snapshot(w, m):
    """固定决定所依赖的最小范围，任何一侧更新均须重新核验清单。"""
    require(not m.get('trashed'), '回收站研究只读')
    current = {k: m['current'].get(k) for k in ('A00', *MODULES)}
    require(all(current.values()) and w.approved(m, current['A00']), '请先完成登记及两侧原件准备')
    plans = w._analysis_plan_records(m)
    require(plans and plans[-1]['expected_a00'] == current['A00'] and
            plans[-1]['plan']['mode'] == 'personalized', '当前方案不适用集中核验')
    plan = plans[-1]
    reviews = {}
    for key, rid in current.items():
        review = w.latest_review(m, w.run(m, rid)['artifact_id'])
        require(not review or review['decision'] == 'approved', f'{key} 已暂存或退回，请先处理原决定')
        reviews[key] = review['review_id'] if review else None
    return {'current': current, 'plan_id': plan['plan_id'], 'reviews': reviews,
            'staging': {k:m.get(k) for k in ('current_system_component_sources', 'current_source_staging')},
            'manual_disease_sources': m.get('analysis_plan_system_manual_source_records', []),
            'runs': {k:m['runs'][rid] for k,rid in current.items()}}


def calculate(w, m, bound, batch_ref):
    from science_modules.a01 import system_source_binding
    from science_modules.a02 import system_normalization_collection

    sid = m['study_id']
    home = w.location(sid)
    a01 = w.run(m, bound['current']['A01'])
    require(a01['config']['version'] == system_source_binding.PUBLICATION and
            a01['inputs']['analysis_plan_id'] == bound['plan_id'] and w.active(m, a01['run_id']),
            'A01 未形成当前方案有效三库结果')
    batch, plan = system_execution.require_batch(w, m, batch_ref)
    a02 = w.run(m, bound['current']['A02'])
    normalized = a02['config']['version'] == system_normalization_collection.PARALLEL_VERSION
    require(batch.get('foundation_stage') == 'A02' and
            (a02.get('batch_file') == batch_ref if normalized else
             batch['initial_binding']['current']['A02'] == bound['current']['A02']) and
            plan['plan_id'] == bound['plan_id'] and batch['mapping'] == a01['inputs']['mapping'],
            '疾病原件批次、方案或两侧映射证据不一致')

    def formula():
        inputs = a01['inputs']
        result = w.result(m, a01['run_id'])
        values = system_source_binding.facts(home, inputs)
        require(fingerprint(values) == fingerprint((result['summary'], result['tables'], result['anomalies'])),
                'A01 与原件重建不一致')
        require(not values[0]['完整性待核项数'], '请先补齐 A01 三库完整性证据')
        return inputs, values, result['sources']

    def disease():
        if normalized:
            require(w.active(m, a02['run_id']), '当前疾病标准化版本已失效')
            result = w.result(m, a02['run_id'])
            values = system_normalization_collection.facts(
                home, a02['inputs'], system_normalization_collection.PARALLEL_VERSION, review_preview=True)
            return a02['inputs'], values, result['sources']
        inputs, _, summary, tables, anomalies, sources = system_normalization_collection.compute(
            w, m, batch, plan, batch_ref, review_preview=True)
        return inputs, (summary, tables, anomalies), sources

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(formula), pool.submit(disease)
        return {'A01':one.result(), 'A02':two.result()}


def evidence(calculated):
    one, two = calculated['A01'][1], calculated['A02'][1]
    return {'A01':one[1]['identity_decisions'], 'A02':two[1]['identity_issues'],
            'scope': [r for r in two[1]['scope_system_decisions'] if r['action'] == 'deferred']}


def current(w, m):
    if not m.get(PREVIEWS):
        return None
    try:
        bound = snapshot(w, m)
    except ContractError:
        return None
    home = w.location(m['study_id'])
    for ref in reversed(m[PREVIEWS]):
        value = read_json(verified_file(home, ref))
        if value['binding'] == bound:
            return dict(value, token=ref['sha256'])
    return None


def prepare(w, sid):
    m = w.load(sid)
    bound = snapshot(w, m)
    if current(w, m):
        return True
    home = w.location(sid)
    disease_run = w.run(m, bound['current']['A02'])
    for ref in reversed(m.get(system_execution.BATCHES, [])):
        row = read_json(verified_file(home, ref))
        if (row.get('foundation_stage') == 'A02' and row['request']['expected_plan_id'] == bound['plan_id'] and
                (row['initial_binding']['current'].get('A02') == bound['current']['A02'] or
                 disease_run.get('batch_file') == ref)):
            break
    else:
        return False
    calculated = calculate(w, m, bound, ref)
    issues = evidence(calculated)
    if not issues['A01'] and not issues['A02']:
        return False
    purpose = w.result(m, bound['current']['A00'])['summary']['analysis_purpose']
    value = {'version':VERSION, 'binding':bound, 'batch':ref, 'issues':issues, 'purpose':purpose,
             'available_targets': {k:calculated[k][1][0]['标准化基因数'] for k in MODULES}}
    with write_lock(w.root):
        latest = w.load(sid)
        require(snapshot(w, latest) == bound, '生成清单期间输入已改变')
        path = home / 'decisions' / 'a03_input_reviews' / (new_id('inputpreview') + '.json')
        write_json(path, value)
        latest.setdefault(PREVIEWS, []).append(file_record(home, path, 'a03_input_review_preview'))
        w.save(latest)
    return True


def validate(w, sid, body):
    require(isinstance(body, dict) and set(body) == {'token', 'reviewer', 'note', 'omit', 'confirmed'},
            '集中核验请求格式错误')
    require(body['confirmed'] is True and all(isinstance(body[k], str) and 0 < len(body[k].strip()) <= 2000
            for k in ('reviewer', 'note')), '请填写核验人和依据后明确确认')
    preview = current(w, w.load(sid))
    require(preview and body['token'] == preview['token'], '核验清单已改变，请刷新 A03')
    require(preview['purpose'] == 'workflow_test', '正式研究仍须补齐身份依据')
    require(isinstance(body['omit'], list) and body['omit'] == [k for k in MODULES if preview['issues'][k]],
            '每侧仍有未决身份，请明确确认清单内暂不采用的范围')
    return preview


def accepted_values(home, module, inputs, receipt):
    from science_modules.a01 import system_source_binding
    from science_modules.a02 import system_normalization_collection

    raw = inputs['science_input']
    if module == 'A01':
        summary, tables, anomalies = system_source_binding.facts(home, raw)
        require(not summary['完整性待核项数'], '三库资料完整性问题仍阻断')
    else:
        summary, tables, anomalies = system_normalization_collection.facts(
            home, raw, system_normalization_collection.PARALLEL_VERSION, review_preview=True)
    return apply_decision(module, (summary,tables,anomalies), receipt)


def apply_decision(module, values, receipt):
    from copy import deepcopy
    summary, tables, anomalies = deepcopy(values)
    table, key = ('identity_decisions', 'issue_key') if module == 'A01' else ('identity_issues', 'issue_id')
    require(summary['analysis_purpose'] == 'workflow_test' and
            fingerprint(tables[table]) == fingerprint(receipt['preview']['issues'][module]),
            '复算发现身份问题清单变化，请重新核验')
    require(receipt['request']['omit'] == [k for k in MODULES if receipt['preview']['issues'][k]],
            '核验凭证没有准确确认全部暂不采用的范围')
    if module == 'A02':
        deferred = [r for r in tables['scope_system_decisions'] if r['action'] == 'deferred']
        require(fingerprint(deferred) == fingerprint(receipt['preview']['issues']['scope']), '疾病范围已改变')
    tables[table] = [dict(row, decision='本批流程测试暂不采用') for row in tables[table]]
    tables['identity_exception_scope'] = [
        {'module_id':module, 'issue_id':row[key], 'action':'omit_from_this_test_only',
         'reason_zh':receipt['request']['note'], 'notice_zh':NOTICE} for row in tables[table]]
    summary.update(handoff_blocked=False, candidate_only=False, identity_limitations_zh=[NOTICE],
                   identity_exception_protocol=VERSION, **{'身份问题处理':'本批流程测试经明确核验暂不采用'})
    if module == 'A01':
        summary.update({'本批未处理身份组数':0,'明确暂不采用身份组数':len(tables[table])})
    return summary, tables, list(anomalies) + [NOTICE]


def is_active(w, m, run):
    try:
        ref = run['inputs']['a03_input_review']
        require(ref in m.get(DECISIONS, []), '集中核验决定未登记')
        receipt = read_json(verified_file(w.location(m['study_id']), ref))
        bound = receipt['preview']['binding']
        original = dict(m, current={**m['current'], **bound['current']})
        require(snapshot(w, original) == bound, '集中核验原输入已改变')
        staging, _ = system_execution.source_for(w, m, bound['plan_id'])
        return staging == receipt['science_inputs']['A01']['staging_file']
    except ContractError:
        return False


def validator(root, module, fallback):
    def check(run, summary, tables, anomalies, outcome):
        if run['config']['version'] != VERSIONS[module]:
            return fallback(run, summary, tables, anomalies, outcome)
        inputs = run['inputs']
        home = Path(root) / 'studies' / run['study_id']
        receipt = read_json(verified_file(home, inputs['a03_input_review']))
        require(receipt['version'] == VERSION and receipt['study_id'] == run['study_id'] and
                receipt['preview']['binding']['plan_id'] == inputs['analysis_plan_id'] and
                receipt['preview']['binding']['current']['A00'] == run['parent_runs']['A00'] and
                receipt['science_inputs'][module] == inputs['science_input'] and
                receipt['request']['confirmed'] is True, '集中核验凭证与复算不符')
        require(fingerprint((summary, tables, anomalies)) == fingerprint(accepted_values(home, module, inputs, receipt)),
                '集中核验结果与原件复算不一致')
        require(outcome == ('success' if summary['标准化基因数'] else 'empty'), '复算结果状态错误')
    return check


def run(w, sid, body, *, progress):
    from science_modules.plan_stages_contract import info

    m = w.load(sid)
    home = w.location(sid)
    receipt_ref = receipt = None
    for ref in reversed(m.get(DECISIONS, [])):
        saved = read_json(verified_file(home, ref))
        if saved['request'] == body:
            receipt_ref = ref
            receipt = saved
            break
    if receipt_ref is None:
        preview = validate(w, sid, body)
        progress('用当前原件并行复算 A01、A02')
        calculated = calculate(w, m, preview['binding'], preview['batch'])
        require(fingerprint(evidence(calculated)) == fingerprint(preview['issues']), '待核问题已改变，请重新核验')
        receipt = {'version':VERSION, 'study_id':sid, 'request':body, 'preview':preview,
                   'science_inputs':{k:calculated[k][0] for k in MODULES}}
        with write_lock(w.root):
            validate(w, sid, body)
            m = w.load(sid)
            path = home / 'decisions' / 'a03_input_reviews' / (new_id('inputreview') + '.json')
            write_json(path, receipt)
            receipt_ref = file_record(home, path, 'a03_input_review_decision')
            m.setdefault(DECISIONS, []).append(receipt_ref)
            for module in MODULES:
                raw, _, sources = calculated[module]
                inputs = {'analysis_plan_id':preview['binding']['plan_id'], 'science_input':raw,
                          'a03_input_review':receipt_ref, 'mapping':raw['mapping']}
                values = apply_decision(module, calculated[module][1], receipt)
                run = Workflow._begin(w, m, module, inputs, {'version':VERSIONS[module]}, body['note'])
                w._finish(m, run['run_id'], *values, 'success' if values[0]['标准化基因数'] else 'empty',
                          sources=sources + [receipt_ref])
            w.save(m)
    m = w.load(sid)
    original = dict(m, current={**m['current'], **receipt['preview']['binding']['current']})
    require(snapshot(w, original) == receipt['preview']['binding'], '核验后原件、方案或决定已改变')
    entries = {}
    for module in MODULES:
        rid = m['current'][module]
        item = w.run(m, rid)
        require(item['inputs'].get('a03_input_review') == receipt_ref, '核验后上游已更新')
        latest = w.latest_review(m, item['artifact_id'])
        require(not latest or w.approved(m, rid), '核验后已有新的暂存或退回决定')
        entries[module] = {'run_id':rid, 'expected_review':latest['review_id'] if latest else None,
                           'action':'preserve' if latest else 'decide', 'decision':'approved',
                           'note':body['note'] + '（A03 集中核验 ' + body['token'] + '）'}
    if any(entry['action'] == 'decide' for entry in entries.values()):
        w.review_a01_a02(sid, entries, body['reviewer'])
    stage = info(w, sid)
    require(stage['expected_plan_id'] == receipt['preview']['binding']['plan_id'], '核验后方案已改变')
    a03 = next(item for item in stage['stages'] if item['stage'] == 'A03')
    if a03['active'] and not a03['enabled']:
        original_a03 = w.run(m, a03['current_run'])
        if all(original_a03['parent_runs'][k] == entries[k]['run_id'] for k in MODULES):
            return 'A03 已有本批有效图表'
    require(a03['enabled'], '；'.join(a03['blockers']))
    request = {k:stage[k] for k in ('expected_a00', 'expected_plan_id', 'expected_input_hash')}
    result = w.execute_analysis_plan_stage(sid, dict(request, stage='A03', operator=body['reviewer'], confirmed=True,
        reason='依据 A03 集中核验决定复算并生成交集图表'), progress=progress)
    return 'A03 交集图表已归档 ' + result['run_id']
