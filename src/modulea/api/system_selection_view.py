"""读取当前系统A04的已归档最终名单；不替代执行前完整规范校验。"""
from contracts import fingerprint, require, safe_id
from storage import read_json, verified_file
from ..core import system_decisions, system_execution
from ..presenters.system_selection import present


def _record(workflow, manifest, ref):
    """展示只核验已登记原件及内容指纹；不重新展开所有科学来源或授予资格。"""
    home = workflow.location(manifest['study_id'])
    value = read_json(verified_file(home, ref))
    require(value.get('schema_version') == system_decisions.VERSION
        and value.get('study_id') == manifest['study_id'] and value.get('state') == 'completed'
        and value.get('stage') in system_decisions.STAGES
        and value.get('authority_kind') == 'system_validation' and value.get('human_review_written') is False,
        '最终名单归档的研究、协议或决定类型无效')
    safe_id(value['decision_id'], 'systemdecision')
    require(value['request']['batch_id'] == value['batch_id'] and value['request']['stage'] == value['stage']
        and value['request_hash'] == fingerprint(value['request'])
        and value['input_hash'] == fingerprint(value['binding'])
        and value['payload_hash'] == fingerprint(value['payload']), '最终名单归档指纹不一致')
    return value


def context(workflow, manifest, run, *, historical=False):
    """只显示本研究当前网络的同批名单，不借用其他版本或恢复旧人工表单。"""
    if (historical or not run or run.get('module_id') != 'A04'
            or run.get('execution_protocol') != system_execution.VERSION
            or manifest['current'].get('A04') != run['run_id']):
        return None
    require(run['study_id'] == manifest['study_id'], '最终名单不能跨研究展示')
    batch_ref = run['batch_file']
    require(batch_ref in manifest.get(system_execution.BATCHES, []), '当前网络系统批次未登记')
    batch = read_json(verified_file(workflow.location(manifest['study_id']), batch_ref))
    require(batch.get('schema_version') == system_execution.VERSION and batch.get('study_id') == manifest['study_id']
        and batch.get('human_review_written') is False, '当前网络系统批次归属无效')
    matches = {}
    for ref in manifest.get(system_decisions.INDEX, []):
        value = _record(workflow, manifest, ref)
        if value['batch_id'] == batch['batch_id']:
            require(value['binding']['batch_file'] == batch_ref, '最终名单批次原件不一致')
            matches[value['stage']] = (ref, value)
    if 'A04_SELECTION' not in matches:
        return present()
    selection_ref, selection = matches['A04_SELECTION']
    binding = selection['binding']
    if (binding['parent_runs'].get('A04') != run['run_id']
            or binding['parent_files'].get('A04') != manifest['runs'][run['run_id']]):
        return present(source_changed=True)
    payload = selection['payload']
    require(payload['network_run_id'] == run['run_id'] and type(payload['actual_count']) is int
        and type(payload['requested_count']) is int and payload['requested_count'] > 0
        and payload['actual_count'] == len(payload['selected'])
        and [row['selection_order'] for row in payload['selected']] == list(range(1, len(payload['selected']) + 1))
        and len({row['target_id'] for row in payload['selected']}) == len(payload['selected']), '最终名单身份、顺序或数量不一致')
    fixed = matches.get('A06_INPUT', (None, None))[1]
    if fixed is not None:
        packet = fixed['payload']
        require(fixed['binding']['parent_runs'].get('A04') == run['run_id']
            and fixed['binding']['parent_files'].get('A04') == manifest['runs'][run['run_id']]
            and fixed['binding'].get('selection_ref') == selection_ref
            and packet['a04_system_selection_ref'] == selection_ref and packet['receptors'] == payload['selected']
            and packet['human_reviews'] == {} and packet['human_review_written'] is False
            and packet['pair_count'] == len(packet['compounds']) * len(packet['receptors']), '固定输入与本批最终名单不一致')
    return present(selection, fixed)
