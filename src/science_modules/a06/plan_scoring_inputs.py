"""独立从评分固定归档重建科学输入；不读当前指针、不下载或改变准备。"""
from pathlib import Path

from contracts import fingerprint, require, safe_id
from storage import read_json, verified_file
from modulea.core.plan_scoring import VERSION, PREPARATION_VERSION, INPUT_FIELDS, configuration, request
from .plan_reviewable_preparation import validator as preparation_validator


def derive(root, sid, inputs):
    """复算准备证据并绑定其真实人工批准、来源配置和执行授权。"""
    require(set(inputs) == INPUT_FIELDS, '评分固定输入字段不一致')
    home = Path(root) / 'studies' / sid
    values = {key: read_json(verified_file(home, ref)) for key, ref in inputs.items()}
    prep, result, review = (values[k] for k in ('preparation_run', 'preparation_result', 'preparation_review'))
    safe_id(prep['run_id'], 'run')
    require(prep['study_id'] == sid and prep['module_id'] == 'A06_PREP' and
            prep['config'].get('version') == PREPARATION_VERSION and result['study_id'] == sid and
            result['run_id'] == prep['run_id'] and result['artifact_id'] == prep['artifact_id'] and
            inputs['preparation_run']['path'] == f"runs/A06_PREP/{prep['run_id']}/run.json" and
            inputs['preparation_result']['path'] == f"runs/A06_PREP/{prep['run_id']}/result.json",
            '评分来源准备版本、路径或归属不一致')
    preparation_validator(root, lambda *_: None)(prep, result['summary'], result['tables'], result['anomalies'], result['outcome'])
    safe_id(review['review_id'], 'review')
    require(review['study_id'] == sid and review['run_id'] == prep['run_id'] and
            review['artifact_id'] == prep['artifact_id'] and review['decision'] == 'approved' and
            review['config_hash'] == prep['config_hash'] and review['result_hash'] == inputs['preparation_result']['sha256'] and
            inputs['preparation_review']['path'] == f"reviews/{review['review_id']}.json",
            '评分缺少同一准备的明确人工批准')
    reference_run = read_json(verified_file(home, prep['inputs']['reference_preparation_run']))
    source = read_json(verified_file(home, reference_run['inputs']['source_run']))
    source_fact = read_json(verified_file(home, reference_run['inputs']['source_packet']))
    reference_result = read_json(verified_file(home, prep['inputs']['reference_preparation_result']))
    fact = read_json(verified_file(home, reference_result['tables']['preparation_packet'][0]))
    record = values['a06_plan_input']
    require(inputs['a06_plan_input'] == reference_run['inputs']['a06_plan_input'] and
            record['study_id'] == sid and record['packet']['study_id'] == sid,
            '评分固定准备输入不一致')
    authorization = values['authorization']
    request(authorization['request'])
    body = authorization['request']
    require(authorization['schema_version'] == VERSION and authorization['study_id'] == sid and
            authorization['request_hash'] == fingerprint(body) and
            body['expected_preparation_run_id'] == prep['run_id'] and
            body['expected_preparation_review_id'] == review['review_id'] and
            body['expected_input_id'] == record['input_id'], '评分执行授权未绑定当前归档资料')
    safe_id(authorization['authorization_id'], 'scoreauth')
    require(inputs['authorization']['path'] ==
            f"decisions/analysis_plans/a06_scoring/{authorization['authorization_id']}.json", '评分授权路径不一致')
    config = configuration({'parameters': source['config']['vina_parameters'], 'source': source, 'packet': record['packet']})
    require(authorization['configuration'] == config, '评分实际参数与来源配置不一致')
    compounds, receptors = source_fact['compounds'], fact['receptors']
    require([r['compound_id'] for r in compounds] == [r['compound_id'] for r in record['packet']['compounds']] and
            [r['target_id'] for r in receptors] == [r['target_id'] for r in record['packet']['receptors']],
            '评分对象顺序与固定输入不一致')
    return {'preparation': prep, 'preparation_result': result, 'review': review,
            'input_record': record, 'configuration': config, 'compounds': compounds, 'receptors': receptors,
            'planned_pairs': result['tables']['planned_pairs']}


def ligand_record(row):
    """只接受该已准备成分唯一的实际PDBQT，不生成构象或借用其他成分。"""
    records = [ref for ref in row.get('files', []) if ref['role'] == 'prepared_ligand']
    require(row['state'] == 'ready' and len(records) == 1, '可评分成分缺少唯一的准备配体')
    return records[0]


def receptor_evidence(row):
    """严格参考采用已复验参考证据；探索采用明确确认过的唯一准备证据。"""
    require(row['state'] == 'ready' and row['quality'] in ('严格', '探索'), '受体未通过本批准备')
    reference = row.get('reference_evidence')
    if reference:
        require(reference['state'] == 'ready' and reference['quality'] == '严格' and
                reference['choice']['target_id'] == row['target_id'], '参考受体证据归属不一致')
        return reference['evidence']
    accepted = [a for a in row.get('attempts', []) if a.get('assessment', {}).get('state') == 'ready']
    require(len(accepted) == 1, '准备受体不能唯一定位已通过的搜索盒和文件')
    return accepted[0]['evidence']
