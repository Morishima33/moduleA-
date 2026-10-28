"""复算同批参考准备并发布可人工复核版本；保留全部NA、历史和空评分。"""
from copy import deepcopy
from pathlib import Path
import shutil

from contracts import fingerprint, require
from storage import file_record, read_json, verified_file, write_json, write_lock
from modulea.core.reviewable_preparation import VERSION, SOURCE_VERSION, check
from .plan_reference_publication_v2 import validator as source_validator

CONFIG = {'version': VERSION, 'automatic_approval': False, 'batch_docking_allowed': False,
          'execution_available': False}


def derive(root, sid, inputs):
    """独立核验原准备的科学事实和来源后，仅改变人工可复核状态。"""
    require(set(inputs) == {'reference_preparation_run', 'reference_preparation_result'}, '可复核准备输入不一致')
    home = Path(root) / 'studies' / sid
    run, result = (read_json(verified_file(home, inputs[k])) for k in
                   ('reference_preparation_run', 'reference_preparation_result'))
    rid = run['run_id']
    require(run['study_id'] == sid and run['module_id'] == 'A06_PREP' and
            run['config'].get('version') == SOURCE_VERSION and result['study_id'] == sid and
            result['run_id'] == rid and result['artifact_id'] == run['artifact_id'] and
            inputs['reference_preparation_run']['path'] == f'runs/A06_PREP/{rid}/run.json' and
            inputs['reference_preparation_result']['path'] == f'runs/A06_PREP/{rid}/result.json',
            '可复核准备来源版本或归属不一致')
    source_validator(root, lambda *_: None)(run, result['summary'], result['tables'],
                                           result['anomalies'], result['outcome'])
    summary, tables = deepcopy(result['summary']), deepcopy(result['tables'])
    require(summary['ready_pairs'] > 0 and summary['scored_pairs'] == 0 and
            all(row['score'] is None for row in tables['planned_pairs']), '没有可用组合或准备已包含评分，不能开放人工复核')
    summary.update(handoff_blocked=False, execution_available=False, reviewable=True,
                   message_zh='同批资料已复验，待人工整体复核；未批准、未执行组合评分，NA保持')
    tables.pop('preparation_packet')
    return run, result, summary, tables


def validator(root, previous):
    """新版本完全复算；旧版本原样委托历史校验器。"""
    def validate(run, summary, tables, anomalies, outcome):
        if run.get('config', {}).get('version') != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        require(run['config'] == CONFIG and outcome == 'success' and anomalies == [], '可复核准备配置或状态不一致')
        old_run, old_result, expected_summary, expected_tables = derive(root, run['study_id'], run['inputs'])
        require(run['parent_runs'] == old_run['parent_runs'] and
                run['parent_review_ids'] == old_run['parent_review_ids'], '可复核准备上游不一致')
        home = Path(root) / 'studies' / run['study_id']
        refs = tables.get('preparation_packet', [])
        require(len(refs) == 1 and refs[0]['path'] ==
                f"runs/A06_PREP/{run['run_id']}/reviewable_preparation/packet.json", '可复核准备事实包路径不一致')
        fact = read_json(verified_file(home, refs[0]))
        expected_tables['preparation_packet'] = refs
        require(summary == expected_summary and tables == expected_tables and
                fact['schema_version'] == VERSION and fact['study_id'] == run['study_id'] and
                fact['inputs'] == run['inputs'], '可复核准备事实、摘要或矩阵不一致')
        for ref in fact['files']:
            verified_file(home, ref)
        required = list(run['inputs'].values()) + old_result['files']
        require(all(ref in fact['files'] for ref in required), '可复核准备未保留全部来源指纹')
    return validate


def publish(workflow, sid, payload):
    """锁内复验并追加新运行，不写入reviews、不启动A06评分。"""
    with write_lock(workflow.root):
        checked = check(workflow, sid, payload)
        manifest = workflow.load(sid)
        if checked['repeated']:
            return workflow.result(manifest, checked['run_id'])
        source_id = checked['run_id']
        source_index = manifest['runs'][source_id]
        inputs = {'reference_preparation_run': source_index['run_file'],
                  'reference_preparation_result': source_index['result_file']}
        _, source_result, summary, tables = derive(workflow.root, sid, inputs)
        run = workflow._begin(manifest, 'A06_PREP', inputs, CONFIG, '同批科学资料复验后进入人工整体复核；不批准或评分')
        home = workflow.location(sid)
        folder = home / 'runs/A06_PREP' / run['run_id'] / 'reviewable_preparation'
        folder.mkdir(parents=True, exist_ok=False)
        snapshot = folder / 'plan_reviewable_preparation.py'
        shutil.copyfile(Path(__file__), snapshot)
        refs = list(inputs.values()) + source_result['files'] + [file_record(home, snapshot, 'reviewable_preparation_code')]
        refs = list({ref['path']: ref for ref in refs}.values())
        fact = {'schema_version': VERSION, 'study_id': sid, 'inputs': inputs, 'files': refs}
        write_json(folder / 'packet.json', fact)
        fact_ref = file_record(home, folder / 'packet.json', 'preparation_packet')
        tables['preparation_packet'] = [fact_ref]
        result = workflow._finish(manifest, run['run_id'], summary, tables, [], 'success', attachments=refs + [fact_ref])
        decision = {'schema_version': VERSION, 'study_id': sid, 'run_id': run['run_id'],
                    'request': deepcopy(payload), 'request_hash': fingerprint(payload)}
        path = home / 'decisions/analysis_plans/a06_reviewable_preparations' / (run['run_id'] + '.json')
        write_json(path, decision)
        manifest.setdefault('analysis_plan_a06_reviewable_records', []).append(file_record(home, path, 'a06_reviewable_preparation'))
        workflow.save(manifest)
        return result
