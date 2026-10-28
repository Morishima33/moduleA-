"""按归档证据复算并追加参考资格准备；保留历史及评分阻断。"""
from copy import deepcopy
from pathlib import Path
import shutil

from contracts import fingerprint, require, safe_id
from storage import file_record, read_json, verified_file, write_json, write_lock
from .plan_reference_context_v2 import derive_checked, derive_current
from .reference_preparation_contract import validate_request

VERSION = 'A06.plan_reference_preparation.2'
CONFIG = {'version': VERSION, 'reference_evidence_required': True,
          'batch_docking_allowed': False, 'automatic_approval': False,
          'execution_available': False, 'scored_pairs': 0, 'handoff_blocked': True}
INPUT_FIELDS = {'current_run', 'current_result', 'source_run', 'source_result',
                'source_packet', 'a06_plan_input', 'reference_review', 'reference_packet'}


def derive_archived(root, sid, inputs):
    """按固定路径和指纹复验旧准备、决定及参考，供发布和以后独立复算。"""
    home = Path(root) / 'studies' / sid
    require(set(inputs) == INPUT_FIELDS, '参考准备输入字段不一致')
    values = {key: read_json(verified_file(home, ref)) for key, ref in inputs.items()}
    current, result = values['current_run'], values['current_result']
    source, source_result = values['source_run'], values['source_result']
    review, packet = values['reference_review'], values['reference_packet']
    for run, result_value, key in ((current, result, 'current'), (source, source_result, 'source')):
        safe_id(run['run_id'], 'run')
        require(run['study_id'] == sid and run['module_id'] == 'A06_PREP' and
                result_value['study_id'] == sid and result_value['run_id'] == run['run_id'] and
                result_value['artifact_id'] == run['artifact_id'] and
                inputs[key + '_run']['path'] == f"runs/A06_PREP/{run['run_id']}/run.json" and
                inputs[key + '_result']['path'] == f"runs/A06_PREP/{run['run_id']}/result.json",
                '参考准备来源运行或结果归属不一致')
    require(source['config'].get('version') == 'A06.plan_preparation.2' and
            source['inputs']['a06_plan_input'] == inputs['a06_plan_input'] and
            source_result['tables'].get('preparation_packet') == [inputs['source_packet']] and
            current['parent_runs'] == source['parent_runs'] and
            current['parent_review_ids'] == source['parent_review_ids'], '参考准备来源批次不一致')
    version = current['config'].get('version')
    require(version in ('A06.plan_preparation.2', 'A06.plan_preparation.3'), '参考准备来源版本不支持')
    if version == 'A06.plan_preparation.2':
        require(current == source and result == source_result and
                inputs['current_run'] == inputs['source_run'] and
                inputs['current_result'] == inputs['source_result'], '原准备不是同一来源')
    else:
        require(current['inputs']['source_preparation_run'] == inputs['source_run'] and
                current['inputs']['source_preparation_result'] == inputs['source_result'] and
                current['inputs']['source_preparation_packet'] == inputs['source_packet'] and
                current['inputs']['a06_plan_input'] == inputs['a06_plan_input'], '口袋准备来源不一致')
    safe_id(review['review_id'], 'refreview')
    require(inputs['reference_review']['path'] ==
            f"decisions/analysis_plans/a06_reference_reviews/{review['review_id']}.json" and
            review['packet'] == inputs['reference_packet'], '参考决定路径或证据指纹不一致')
    data = {'current_run': current, 'current_result': result, 'source_run': source,
            'source_fact': values['source_packet'], 'source_packet_ref': inputs['source_packet'],
            'input_record': values['a06_plan_input']}
    return derive_checked(root, home, sid, data, review, packet, review['review_id'])


def validator(root, previous):
    """独立从运行固定输入复算摘要、矩阵及受体事实，旧版本交给原校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run.get('config', {}).get('version') != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        require(run['config'] == CONFIG and outcome == 'success' and anomalies == [], '参考准备配置或状态不一致')
        home = Path(root) / 'studies' / run['study_id']
        current = read_json(verified_file(home, run['inputs']['current_run']))
        require(run['parent_runs'] == current['parent_runs'] and
                run['parent_review_ids'] == current['parent_review_ids'], '参考准备上游与来源不一致')
        expected = derive_archived(root, run['study_id'], run['inputs'])
        refs = tables.get('preparation_packet', [])
        require(len(refs) == 1 and refs[0]['path'] ==
                f"runs/A06_PREP/{run['run_id']}/reference_qualification/packet.json", '参考准备事实包路径不一致')
        fact = read_json(verified_file(home, refs[0]))
        expected_tables = deepcopy(expected['tables'])
        expected_tables['preparation_packet'] = refs
        require(summary == expected['summary'] and tables == expected_tables and
                set(fact) == {'schema_version', 'study_id', 'inputs', 'receptors', 'files'} and
                fact['schema_version'] == VERSION and fact['study_id'] == run['study_id'] and
                fact['inputs'] == run['inputs'] and fact['receptors'] == expected['receptors'],
                '参考准备事实、摘要或矩阵与证据复算不一致')
        for ref in fact['files']:
            verified_file(home, ref)
        source_result = read_json(verified_file(home, run['inputs']['source_result']))
        current_result = read_json(verified_file(home, run['inputs']['current_result']))
        reference_packet = read_json(verified_file(home, run['inputs']['reference_packet']))
        required = list(run['inputs'].values()) + source_result['files'] + current_result['files'] + reference_packet['files']
        require(all(ref in fact['files'] for ref in required), '参考准备缺少来源或证据指纹')
        snapshot_paths = {r['path'] for r in fact['files'] if r['role'] == 'reference_qualification_code'}
        require(snapshot_paths == {f"runs/A06_PREP/{run['run_id']}/reference_qualification/code/{name}" for name in
                ('plan_reference_publication_v2.py', 'plan_reference_context_v2.py', 'plan_reference_qualification_v2.py')},
                '参考准备代码快照不完整')
    return check


def publish(workflow, sid, payload):
    """明确请求后在锁内复验并发布，不评分、不自动批准。"""
    from modulea.core.reference_preparation import _base, _review
    validate_request(payload)
    home = workflow.location(sid)
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        require(not manifest.get('trashed'), '回收站研究只读')
        for entry in manifest.get('analysis_plan_a06_reference_preparation_v2_records', []):
            old = read_json(verified_file(home, entry['decision']))
            if old['request']['request_id'] == payload['request_id']:
                require(old['study_id'] == sid and old['request_hash'] == fingerprint(payload), '请求编号已用于其他内容')
                require(manifest['current'].get('A06_PREP') == entry['run_id'] and
                        workflow.active(manifest, entry['run_id']), '参考准备已有后续版本，请刷新')
                current_input = workflow.analysis_plan_info(sid).get('a06_preparation_input')
                require(current_input and current_input['input_id'] == payload['expected_input_id'],
                        '准备输入或上游复核已更新，请刷新')
                result = workflow.result(manifest, entry['run_id'])
                require(result is not None, '参考准备尚未完整归档')
                return result
        data = _base(workflow, sid)
        require(data['current_run']['run_id'] == payload['expected_preparation_run_id'] and
                data['input_record']['input_id'] == payload['expected_input_id'], '准备或输入已更新，请刷新')
        record, packet, review_ref = _review(workflow, sid, data, payload['expected_review_id'])
        expected = derive_current(workflow, sid, payload['expected_review_id'])
        current_id = data['current_run']['run_id']
        source_id = data['source_run']['run_id']
        inputs = {'current_run': manifest['runs'][current_id]['run_file'],
                  'current_result': manifest['runs'][current_id]['result_file'],
                  'source_run': data['source_run_ref'], 'source_result': data['source_result_ref'],
                  'source_packet': data['source_packet_ref'], 'a06_plan_input': data['input_ref'],
                  'reference_review': review_ref, 'reference_packet': record['packet']}
        require(derive_archived(workflow.root, sid, inputs) == expected, '归档复算与当前准备不一致')
        run = workflow._begin(manifest, 'A06_PREP', inputs, CONFIG, '按已归档参考证据复算准备资格，不评分')
        folder = home / 'runs/A06_PREP' / run['run_id'] / 'reference_qualification'
        folder.mkdir(parents=True, exist_ok=False)
        snapshots = []
        for name in ('plan_reference_publication_v2.py', 'plan_reference_context_v2.py', 'plan_reference_qualification_v2.py'):
            destination = folder / 'code' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(__file__).parent / name, destination)
            snapshots.append(file_record(home, destination, 'reference_qualification_code'))
        refs = list(inputs.values()) + data['current_result']['files'] + data['source_result']['files'] + packet['files'] + snapshots
        refs = list({r['path']: r for r in refs}.values())
        fact = {'schema_version': VERSION, 'study_id': sid, 'inputs': inputs,
                'receptors': expected['receptors'], 'files': refs}
        write_json(folder / 'packet.json', fact)
        fact_ref = file_record(home, folder / 'packet.json', 'preparation_packet')
        tables = deepcopy(expected['tables'])
        tables['preparation_packet'] = [fact_ref]
        result = workflow._finish(manifest, run['run_id'], expected['summary'], tables, [], 'success', attachments=refs + [fact_ref])
        decision = {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'],
                    'request': deepcopy(payload), 'request_hash': fingerprint(payload)}
        path = home / 'decisions/analysis_plans/a06_reference_preparations_v2' / (run['run_id'] + '.json')
        write_json(path, decision)
        manifest.setdefault('analysis_plan_a06_reference_preparation_v2_records', []).append(
            {'decision': file_record(home, path, 'a06_reference_preparation_v2'), 'run_id': run['run_id']})
        workflow.save(manifest)
        return result
