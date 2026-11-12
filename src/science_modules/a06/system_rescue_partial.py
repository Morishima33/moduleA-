"""二版只读复用未发表一版的登记准备和完整区域组；孤立目录不作为恢复凭据。"""
from copy import deepcopy
import json
from pathlib import Path

from contracts import encoded, require
from storage import file_record, read_json, verified_file
from . import system_receptor_rescue as prior


def completed_pairs(home, run, checkpoints, compounds, receptors, fixed):
    """全部预定区域均有登记终态才重建成功组合，逐区域复核原命令和Top-1。"""
    from .plan_score_pair import validate
    from .plan_scoring_inputs import ligand_record
    from .trial_rules import choose_score
    by_key = {item['key']: (ref, item) for ref, item in checkpoints}
    by_target = {row['target_id']: row for row in receptors}
    binary = home / 'runs/A06' / run['run_id'] / 'rescue/software/vina.exe'
    output = []
    for ordinal, (compound, target) in enumerate(((c, t) for c in compounds for t in fixed['receptors']), 1):
        receptor = by_target[target['target_id']]
        if compound['state'] != 'ready' or receptor['state'] != 'ready' or not receptor.get('regions'):
            continue
        keys = [f'pair_{ordinal:06d}_region_{index:04d}' for index in range(1, len(receptor['regions']) + 1)]
        if not all(key in by_key and not by_key[key][1]['payload'].get('retryable') for key in keys):
            continue
        require(file_record(home, binary, 'scoring_vina')['sha256'] == run['config']['vina_sha256'],
                '未完成运行的原评分工具已改变')
        facts = []
        for index, (key, region) in enumerate(zip(keys, receptor['regions']), 1):
            fact = by_key[key][1]['payload']
            reference = fact['execution']
            prefix = f'runs/A06/{run["run_id"]}/rescue/scores/pair_{ordinal:06d}/region_{index:04d}/'
            require(reference['path'].startswith(prefix) and reference['path'].endswith('/execution.json')
                    and '/' not in reference['path'][len(prefix):-len('/execution.json')],
                    '恢复区域不是原组合的登记执行')
            actual = validate(home, reference, binary, ligand_record(compound), receptor['receptor'],
                              json.loads(encoded(region)), prior._scoring_config(run))
            expected = dict(region_id=region['region_id'], state=actual['state'], score=actual['score'],
                            reason_zh=actual['reason_zh'], execution=reference,
                            retryable=actual.get('failure_kind') in ('timeout', 'launch_error'))
            require(fact == expected, '旧区域检查点与原实际执行不同')
            facts.append(deepcopy(fact))
        best = choose_score(facts, receptor['mode'])
        if not best:
            continue
        execution = read_json(verified_file(home, best['execution']))
        top1 = home / 'runs/A06' / run['run_id'] / 'rescue/scores' / f'pair_{ordinal:06d}' / 'top1.pdbqt'
        # 附件只是已登记实际评分的确定性派生物；绝不靠它推断评分或采用第二姿势。
        require(top1.is_file() and top1.read_bytes() == prior._top1_bytes(verified_file(home, execution['pose']).read_bytes()),
                '已登记完整区域组的派生Top-1缺失或不同，保留原件待处理')
        output.append(dict(compound_id=compound['compound_id'], target_id=receptor['target_id'],
            state='completed', score=best['score'], quality=receptor['quality'], source_kind='rescue',
            regions=facts, mode=receptor['mode'], region_id=best['region_id'], execution=best['execution'],
            partial_regions=any(row['state'] != 'completed' for row in facts), reason_zh='',
            top1_pose=file_record(home, top1, 'rescue_top1_pose'), original_pose=execution['pose']))
    return output


def verify_identity(home, source, target, value):
    """未发表旧运行须重核对象键和原稳定身份，不能只信payload内部自洽。"""
    require(target['target_id'] in source['original_targets'], '恢复检查点不能覆盖原已可用受体')
    require(value.get('target_id') == target['target_id'] and value.get('symbol') == target['symbol']
            and value.get('source_kind') == 'rescue'
            and value.get('expected_uniprot') == prior._source_uniprot(home, source, target['target_id']),
            '恢复受体与原对象键、名称或官方稳定蛋白身份不同')
    require(value.get('state') in ('ready', 'NA'), '恢复受体状态不是旧补救协议的合法终态')


def restore(workflow, manifest, source, binding):
    """原始评分与原件不变，另列恢复事实；准备阶段与评分阶段的对象范围分开。"""
    from .system_receptor_rescue_v2 import verify_prepared
    partial = binding.get('partial_recovery')
    source['prepare_targets'] = list(source['targets'])
    source['recovered_pairs'] = []
    if not partial:
        return source
    home = workflow.location(manifest['study_id'])
    run = workflow.run(manifest, partial['run_id'])
    require(run['config']['version'] == prior.VERSION
            and partial['run_files'] == manifest['runs'][run['run_id']]
            and not partial['run_files'].get('result_file'), '恢复来源不是同批未发表一版')
    checkpoints = [(ref, read_json(verified_file(home, ref))) for ref in partial['checkpoint_refs']]
    latest = {item['key']: (ref, item) for ref, item in checkpoints}
    rows = {row['target_id']: deepcopy(row) for row in source['baseline_receptors']}
    for target in source['fixed']['receptors']:
        key = 'receptor_' + target['target_id'].replace(':', '_')
        if key not in latest:
            continue
        value = latest[key][1]['payload']
        verify_identity(home, source, target, value)
        if value['state'] == 'ready':
            verify_prepared(home, value)
        rows[target['target_id']] = deepcopy(value)
    source['baseline_receptors'] = [rows[row['target_id']] for row in source['fixed']['receptors']]
    source['prepare_targets'] = [row['target_id'] for row in source['baseline_receptors'] if row['state'] != 'ready']
    source['partial_run'] = run
    source['partial_recovery'] = partial
    source['recovered_pairs'] = completed_pairs(home, run, checkpoints, source['fact']['compounds'],
                                               source['baseline_receptors'], source['fixed'])
    return source
