"""从当前研究的已归档准备及参考决定构造隔离资格复算输入。"""

from contracts import fingerprint, require
from storage import verified_file, read_json
from .plan_reference_qualification_v2 import derive


def derive_current(workflow, sid, review_id):
    """只读校验当前准备与参考证据；不写入运行、不批准、不评分。"""
    from modulea.core.reference_preparation import _base, _review
    from .plan_preparation_v2 import current_input, validator as original_validator
    from .plan_pocket_review import validator as pocket_validator
    from .reference_review_contract import validate_request

    data = _base(workflow, sid)
    home = workflow.location(sid)
    record, packet, _ = _review(workflow, sid, data, review_id)
    input_record = data['input_record']
    current_input(workflow, sid, input_record['input_id'])
    run, result = data['current_run'], data['current_result']
    require(result is not None and result.get('study_id') == sid and
            result.get('run_id') == run['run_id'] and result.get('artifact_id') == run['artifact_id'],
            '当前准备结果归属不一致')
    for ref in result['files']:
        verified_file(home, ref)
    def unsupported(*args):
        raise ValueError('准备版本不支持参考资格复算')
    verify = pocket_validator(workflow.root, original_validator(workflow.root, unsupported))
    verify(run, result['summary'], result['tables'], result['anomalies'], result['outcome'])
    request = record['request']
    validate_request(request)
    require(record['request_hash'] == fingerprint(request) and
            record['study_id'] == sid and record['review_id'] == review_id and
            record['expected_preparation_run_id'] == run['run_id'] and
            record['source_preparation_run_id'] == data['source_run']['run_id'] and
            record['source_preparation_packet'] == data['source_packet_ref'] and
            request['expected_input_id'] == input_record['input_id'] and
            request['expected_preparation_run_id'] == run['run_id'] and
            packet['request_id'] == request['request_id'] and packet['choices'] == request['choices'] and
            packet['summary'] == record['summary'] and packet['summary']['scored_pairs'] == 0 and
            packet['summary']['handoff_blocked'] is True,
            '参考决定、请求或证据与当前准备不一致')
    counts = packet['summary']
    require(counts['choice_count'] == len(packet['choices']) == len(packet['results']) and
            counts['ready_count'] == sum(row.get('state') == 'ready' for row in packet['results']) and
            counts['na_count'] == sum(row.get('state') == 'NA' for row in packet['results']) and
            counts['ready_count'] + counts['na_count'] == counts['choice_count'],
            '参考结果数量与核查摘要不一致')
    for ref in packet['files']:
        verified_file(home, ref)
    current_fact = read_json(verified_file(home, result['tables']['preparation_packet'][0]))
    source = data['source_fact']
    base = {'study_id': sid, 'input_id': input_record['input_id'],
            'run_id': data['source_run']['run_id'], 'current_run_id': run['run_id'],
            'input_key': source['input_key'], 'config': data['source_run']['config'],
            'connection': source['connection'], 'compounds': current_fact['compounds'],
            'receptors': current_fact['receptors']}
    return derive(home, input_record['packet'], base, packet)
