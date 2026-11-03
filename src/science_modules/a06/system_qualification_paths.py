"""目录技术补执行后的新资格规范，完整复核原准备与真实新工具回执。"""
from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require
from storage import read_json, verified_file
from . import receptor_path_repair as repair, system_qualification_incremental as previous

VERSION = 'A06.system_qualification_paths.1'


# 新配置保留实际旧方案参数和冻结资格门槛，另记录本次技术修复协议。
def configuration(original):
    return dict(deepcopy(original['config']), version=VERSION, receptor_path_repair_protocol=repair.VERSION)


# 完整规范核验原资格，不接受仅含路径或客户端给出的结果。
def source(root, sid, inputs):
    home = Path(root) / 'studies' / sid
    run = read_json(verified_file(home, inputs['source_qualification_run']))
    result = read_json(verified_file(home, inputs['source_qualification_result']))
    require(run['study_id'] == result['study_id'] == sid and run['run_id'] == result['run_id']
            and run['module_id'] == 'A06_PREP' and run['config']['version'] == previous.VERSION,
            '路径修订要求实际同研究原系统资格')

    def reject(*_):
        require(False, '路径修订原资格协议不能回退')

    previous.validator(root, reject)(run, result['summary'], result['tables'], result['anomalies'], result['outcome'])
    return run, result


# 从原资格指向的原准备事实和本次目录回执重建完整名单、资格与NA。
def facts(home, original, inputs):
    require(inputs['source_preparation_fact'] == original['inputs']['source_preparation_fact']
            and inputs['system_input_ref'] == original['inputs']['system_input_ref'],
            '技术修订原准备或固定范围绑定不同')
    fixed, packet, (repaired, qualified, decisions) = repair.read_packet(home, inputs['path_repair_packet'])
    session = read_json(verified_file(home, packet['session']))
    require(session['binding']['source_preparation_fact'] == inputs['source_preparation_fact'],
            '技术修订回执引用其他准备')
    request = read_json(verified_file(home, inputs['path_repair_request']))
    require(request['schema_version'] == VERSION and request['human_review_written'] is False
            and request['study_id'] == original['study_id'] and request['batch_file'] == original['batch_file']
            and request['request_hash'] == fingerprint(request['request'])
            and request['source_qualification_run'] == inputs['source_qualification_run']
            and request['source_qualification_result'] == inputs['source_qualification_result']
            and request['request']['expected_preparation_run_id'] == original['run_id']
            and request['request']['expected_result_sha256'] == inputs['source_qualification_result']['sha256']
            and request['request']['batch_id'] == session['binding']['batch_id']
            and Path(inputs['path_repair_packet']['path']).parent.name == request['request']['request_id'],
            '技术修订请求、原资格或批次不同')
    checked, summary, tables = previous.reports(fixed, repaired, original['run_id'])
    require(checked == qualified and tables['system_qualification_decisions'] == decisions,
            '技术补执行资格复算不同')
    summary.update(science_version=VERSION, path_repair_attempts=len(packet['patches']),
                   message_zh='已按原固定名单补执行目录故障，并重新核验严格/探索/NA；尚未评分或人工批准')
    qualified_fact = {'schema_version': VERSION, 'study_id': original['study_id'],
                      'input_key': fixed['input_key'], 'human_review_written': False,
                      'source_preparation_run_id': original['run_id'],
                      'source_preparation_fact': inputs['source_preparation_fact'],
                      'path_repair_packet': inputs['path_repair_packet'], 'configuration': configuration(original),
                      'compounds': repaired['compounds'], 'receptors': qualified, 'decisions': decisions}
    refs = [inputs['path_repair_packet'], packet['session'], *session['implementations']]
    for ref in packet['patches']:
        patch = read_json(verified_file(home, ref))
        refs.extend([ref, *patch['files']])
    return request, qualified_fact, summary, tables, refs


# 发表和历史核验都从已签入文件重建，不运行工具。
def validator(root, fallback):
    def check(run, summary, tables, anomalies, outcome):
        if run.get('config', {}).get('version') != VERSION:
            return fallback(run, summary, tables, anomalies, outcome)
        inputs = run['inputs']
        home = Path(root) / 'studies' / run['study_id']
        original, _ = source(root, run['study_id'], inputs)
        request, fact, expected, rows, _ = facts(home, original, inputs)
        require(run['config'] == configuration(original) and run['batch_file'] == original['batch_file']
                and run['parent_runs'] == original['parent_runs'] and run['parent_review_ids'] == {}
                and run['execution_protocol'] == 'ModuleA.system_execution.1'
                and run['parent_validation_records'] == request['parent_validation_records']
                and inputs['analysis_plan_file'] == original['inputs']['analysis_plan_file']
                and inputs['analysis_parameter_hash'] == original['inputs']['analysis_parameter_hash'],
                '技术修订不是原同批方案及真实系统依赖')
        ref = inputs['qualification_fact']
        require(read_json(verified_file(home, ref)) == fact, '路径技术修订资格归档与原证据不同')
        rows['preparation_packet'] = [ref]
        require(fingerprint([expected, rows]) == fingerprint([summary, tables])
                and not anomalies and outcome == 'success', '路径技术修订摘要、矩阵或异常不同')
    return check
