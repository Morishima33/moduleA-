"""新版A06正式评分前置预检：只读取固定归档，不执行评分或写入决定。"""
from contracts import fingerprint, require, safe_id
from storage import read_json, verified_file

VERSION = 'A06.scoring_gate.1'
PREPARATION_VERSION = 'A06.plan_reference_preparation.2'


def _source(workflow, sid, manifest, run):
    """从新版准备固定输入找回真实执行参数，不能读取绑定层空配置。"""
    study_dir = workflow.location(sid)
    inputs = run['inputs']
    source = read_json(verified_file(study_dir, inputs['source_run']))
    source_id = source['run_id']
    safe_id(source_id, 'run')
    require(source.get('study_id') == sid and source.get('module_id') == 'A06_PREP' and
            source.get('config', {}).get('version') == 'A06.plan_preparation.2' and
            manifest['runs'].get(source_id, {}).get('run_file') == inputs['source_run'] and
            manifest['runs'][source_id].get('result_file') == inputs['source_result'],
            '评分参数来源不属于本研究的固定准备版本')
    source_result = read_json(verified_file(study_dir, inputs['source_result']))
    fact = read_json(verified_file(study_dir, inputs['source_packet']))
    require(source_result.get('study_id') == sid and source_result.get('run_id') == source_id and
            source_result.get('outcome') == 'success' and
            source_result['tables'].get('preparation_packet') == [inputs['source_packet']] and
            fact.get('study_id') == sid and fact.get('config') == source['config'] and
            source.get('config_hash') == fingerprint(source['config']), '来源准备配置或证据指纹不一致')
    input_ref = inputs['a06_plan_input']
    require(source['inputs'].get('a06_plan_input') == input_ref and
            input_ref in manifest.get('analysis_plan_a06_input_records', []), '评分准备输入未登记在本研究')
    record = read_json(verified_file(study_dir, input_ref))
    packet = record['packet']
    require(record.get('study_id') == sid and packet.get('study_id') == sid and
            packet.get('input_key') == fact.get('input_key'), '评分准备输入归属或指纹不一致')
    plan = read_json(verified_file(study_dir, packet['plan_ref']))
    require(plan.get('study_id') == sid and
            plan['plan']['parameter_hash'] == packet['analysis_parameter_hash'], '评分来源方案不一致')
    parameters = source['config'].get('vina_parameters')
    require(isinstance(parameters, dict) and set(parameters) == {
        'scoring', 'exhaustiveness', 'num_modes', 'energy_range_kcal_mol', 'seed'}, '来源准备未记录完整评分参数')
    return source, record, packet, parameters


def validate(workflow, sid, payload):
    """核对请求、固定输入、上游复核和全NA状态，始终保持执行入口关闭。"""
    from .reference_preparation import scoring_readiness
    require(isinstance(payload, dict) and set(payload) == {
        'expected_preparation_run_id', 'reviewer', 'note', 'confirmed'}, '评分预检字段不完整或含不支持选项')
    safe_id(payload['expected_preparation_run_id'], 'run')
    require(payload['confirmed'] is True and all(isinstance(payload[key], str) and
            0 < len(payload[key].strip()) <= 2000 for key in ('reviewer', 'note')), '请明确评分预检人及依据')
    manifest = workflow.load(sid)
    require(not manifest.get('trashed'), '回收站研究不能进行评分预检')
    current = manifest.get('current', {}).get('A06_PREP')
    require(current == payload['expected_preparation_run_id'], '准备版本已更新，请刷新')
    run = workflow.run(manifest, current)
    require(run.get('study_id') == sid and run.get('module_id') == 'A06_PREP' and
            run.get('config', {}).get('version') == PREPARATION_VERSION, '当前准备版本不支持新版评分预检')
    result = workflow.result(manifest, current)
    require(result and result.get('outcome') == 'success', '当前准备尚未完整归档')
    source, input_record, packet, parameters = _source(workflow, sid, manifest, run)
    readiness = scoring_readiness(workflow, sid)
    blockers = list(readiness.get('blockers', []))
    if not workflow.active(manifest, current):
        blockers.append('准备或上游复核已失效')
    current_input = workflow.analysis_plan_info(sid).get('a06_preparation_input')
    if not current_input or current_input != input_record:
        blockers.append('准备输入或方案已更新，请重新核查')
    summary = result['summary']
    pairs = result['tables']['planned_pairs']
    require(len(pairs) == summary['pair_count'] == len(packet['compounds']) * len(packet['receptors']) and
            all(row.get('score') is None for row in pairs), '准备矩阵范围或空评分状态不一致')
    require(summary['ready_pairs'] == sum(row['state'] == 'ready' for row in pairs) and
            summary['na_pairs'] == sum(row['state'] == 'NA' for row in pairs) and
            summary['ready_pairs'] + summary['na_pairs'] == len(pairs), '可评分与NA组合数与准备矩阵不一致')
    if summary['ready_pairs'] == 0:
        blockers.append('当前没有可评分组合；NA对象不得补位或填零')
    review = workflow.latest_review(manifest, run['artifact_id'])
    # 固定执行器尚未接通；即使资料通过也不能以预检冒充批准或授权。
    blockers = list(dict.fromkeys(blockers + ['新版评分执行入口尚未接通']))
    require(workflow.load(sid) == manifest, '研究版本在预检期间已更新，请刷新')
    return {'protocol_version': VERSION, 'supported': True, 'read_only': True,
            'allowed': False, 'execution_available': False, 'current_run_id': current,
            'source_preparation_run_id': source['run_id'], 'input_id': input_record['input_id'],
            'input_key': packet['input_key'], 'analysis_parameter_hash': packet['analysis_parameter_hash'],
            'config_hash': source['config_hash'], 'input_hash': run['input_hash'],
            'latest_preparation_review_id': review['review_id'] if review else None,
            'pair_count': summary['pair_count'], 'ready_pairs': summary['ready_pairs'],
            'na_pairs': summary['na_pairs'], 'scoring_parameters': parameters,
            'box_padding': source['config']['box_padding'],
            'requested_rmsd_max_A': source['config']['requested_rmsd_max_A'],
            'blockers': blockers, 'reason_zh': '评分前置预检完成；未创建任务，正式复核和评分仍未开放'}
