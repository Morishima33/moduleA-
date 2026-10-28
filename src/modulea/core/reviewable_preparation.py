"""A06可复核准备的只读资格与显式发布预检；不提交人工决定。"""
from contracts import fingerprint, require, safe_id
from storage import read_json, verified_file

VERSION = 'A06.plan_reviewable_preparation.1'
SOURCE_VERSION = 'A06.plan_reference_preparation.2'


def request(payload):
    """只接受版本绑定、请求编号及明确确认，不接受审批或执行参数。"""
    require(isinstance(payload, dict) and set(payload) == {
        'expected_preparation_run_id', 'expected_input_id', 'request_id',
        'reviewer', 'note', 'confirmed'}, '可复核准备字段不完整或含不支持选项')
    for key, prefix in (('expected_preparation_run_id', 'run'), ('expected_input_id', 'input'),
                        ('request_id', 'reviewprep')):
        safe_id(payload[key], prefix)
    require(payload['confirmed'] is True and all(isinstance(payload[k], str) and
        0 < len(payload[k].strip()) <= 2000 for k in ('reviewer', 'note')), '请填写准备核验人与依据并明确确认')


def check(workflow, sid, payload):
    """同编号同内容只回读原运行；上游、当前输入或后继版本改变均拒绝。"""
    from .reference_preparation import qualification
    request(payload)
    manifest = workflow.load(sid)
    require(not manifest.get('trashed'), '回收站研究只读')
    current = manifest.get('current', {}).get('A06_PREP')
    for ref in manifest.get('analysis_plan_a06_reviewable_records', []):
        old = read_json(verified_file(workflow.location(sid), ref))
        if old['request']['request_id'] != payload['request_id']:
            continue
        require(old['request_hash'] == fingerprint(payload), '请求编号已用于其他内容，请刷新')
        require(old['study_id'] == sid and old['run_id'] == current and
                workflow.active(manifest, current), '可复核准备已有后续版本或上游已更新，请刷新')
        value = workflow.analysis_plan_info(sid).get('a06_preparation_input')
        require(value and value['input_id'] == payload['expected_input_id'], '准备输入已更新，请刷新')
        require(workflow.result(manifest, current) is not None, '可复核准备尚未完整归档')
        return {'repeated': True, 'run_id': current}
    require(current == payload['expected_preparation_run_id'], '准备版本已更新，请刷新')
    run = workflow.run(manifest, current)
    require(run['config'].get('version') == SOURCE_VERSION, '当前准备版本不支持进入整体复核')
    value = qualification(workflow, sid)
    require(value.get('qualified'), '准备资料资格未通过，不能进入整体复核')
    require(value['summary']['ready_pairs'] > 0, '没有可用组合，不能进入整体复核；NA对象不得补位')
    record = workflow.analysis_plan_info(sid).get('a06_preparation_input')
    require(record and record['input_id'] == payload['expected_input_id'] and
            run['inputs']['a06_plan_input'] in manifest.get('analysis_plan_a06_input_records', []) and
            read_json(verified_file(workflow.location(sid), run['inputs']['a06_plan_input'])) == record,
            '准备输入或上游复核已更新，请刷新')
    return {'repeated': False, 'run_id': current}


def info(workflow, sid):
    """为网页提供可进入人工复核的资格，不把归档或确认等同审批。"""
    from .reference_preparation import qualification
    manifest = workflow.load(sid)
    current = manifest.get('current', {}).get('A06_PREP')
    base = {'supported': False, 'enabled': False, 'execution_available': False}
    if not current:
        return dict(base, reason_zh='请先完成新版参考准备')
    version = workflow.run(manifest, current)['config'].get('version')
    if version == VERSION:
        q = qualification(workflow, sid)
        return dict(base, supported=True, current_run_id=current,
                    state='published' if q.get('can_enter_review') else 'stale',
                    reason_zh='可复核准备已归档；请独立人工复核，通过后到新版评分区明确确认执行'
                    if q.get('can_enter_review') else q['reason_zh'])
    if version != SOURCE_VERSION:
        return dict(base, reason_zh='当前版本不支持进入整体复核')
    q = qualification(workflow, sid)
    record = workflow.analysis_plan_info(sid).get('a06_preparation_input')
    enabled = bool(q.get('qualified') and (q.get('summary') or {}).get('ready_pairs', 0) > 0 and record)
    return dict(base, supported=True, enabled=enabled, state='available' if enabled else 'blocked',
                current_run_id=current, expected_input_id=record['input_id'] if record else None,
                reason_zh='可在后台复验后生成待人工整体复核版本；不自动通过或评分' if enabled
                else '准备资料未通过、输入已失效或没有可用组合，不能进入整体复核')


def qualification(workflow, sid, manifest, run, base):
    """接口仅核验已科学复算的不可变准备，不在接口进程加载科学依赖。"""
    result = workflow.result(manifest, run['run_id'])
    blockers = []
    if manifest.get('trashed') or not workflow.active(manifest, run['run_id']):
        blockers.append('研究只读或准备上游复核已失效')
    try:
        require(result and result['outcome'] == 'success' and result['summary']['reviewable'] is True and
                result['summary']['handoff_blocked'] is False and result['summary']['scored_pairs'] == 0 and
                result['summary']['ready_pairs'] > 0, '可复核准备状态不一致')
        home = workflow.location(sid)
        fact = read_json(verified_file(home, result['tables']['preparation_packet'][0]))
        require(fact['schema_version'] == VERSION and fact['study_id'] == sid and
                fact['inputs'] == run['inputs'], '可复核准备事实归属不一致')
        for ref in fact['files'] + list(run['inputs'].values()):
            verified_file(home, ref)
        current_input = workflow.analysis_plan_info(sid).get('a06_preparation_input')
        source = read_json(verified_file(home, run['inputs']['reference_preparation_run']))
        require(current_input and current_input == read_json(verified_file(home, source['inputs']['a06_plan_input'])),
                '准备输入或上游复核已更新，请刷新')
        checked = len(fact['files'])
    except (ValueError, KeyError, TypeError) as error:
        blockers.append(str(error))
        checked = 0
    return dict(base, supported=True, enabled=True, current_run_id=run['run_id'],
                summary=result['summary'] if result else None, scored_pairs=0, checked_files=checked,
                qualified=not blockers, can_enter_review=not blockers, blockers=blockers,
                reason_zh='资料复验通过，可进行人工整体复核；资格核查不代替人工决定或执行确认' if not blockers else '；'.join(blockers))
