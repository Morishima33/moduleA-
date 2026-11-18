"""评分执行、继承来源与固定MODEL 1的共用只读核验；API和完整包共用原规则。"""
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath

from contracts import fingerprint, require
from storage import read_json, verified_file
from .rescue_result_read import same_file, checked_bytes, bound_batch

VERSION = 'ModuleA.rescue_evidence.1'


def _references(value):
    """只沿本运行明确绑定的文件引用追溯历史，不从目录或文件名搜寻成功。"""
    if isinstance(value, dict):
        if all(k in value for k in ('path', 'bytes', 'sha256')):
            yield value
        for child in value.values():
            yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _checkpoint_attachments(manifest, origin, owner, ordinal, reference, checkpoint_ref, checkpoint, missing):
    """只从同一已登记区域检查点补齐该次执行的原附件。"""
    partial_run_id = origin['run_id']
    regions = [region for region in owner.get('regions', [])
               if same_file(region.get('execution'), reference)]
    require(len(regions) == 1, '恢复执行没有唯一的预定区域')
    region = regions[0]
    index = owner['regions'].index(region) + 1
    key = f'pair_{ordinal:06d}_region_{index:04d}'
    require(checkpoint_ref in manifest.get('analysis_plan_receptor_rescue_checkpoints', [])
            and checkpoint_ref['path'].startswith(f'runs/A06/{partial_run_id}/rescue_checkpoints/{key}/')
            and checkpoint.get('key') == key and checkpoint.get('study_id') == manifest['study_id']
            and checkpoint.get('schema_version') == origin['config']['version'] == 'A06.system_rescue.1'
            and checkpoint.get('config_hash') == origin.get('config_hash') == fingerprint(origin['config'])
            and checkpoint.get('human_review_written') is False and checkpoint['payload'] == region,
            '恢复附件没有绑定原研究、配置及预定区域的检查点')
    files = checkpoint.get('files', [])
    require(any(same_file(reference, item) for item in files), '检查点未登记同一实际执行')
    attempt = PurePosixPath(reference['path']).parent
    require(all(PurePosixPath(ref['path']).parent == attempt
                and any(same_file(ref, saved) for saved in files) for ref in missing),
            '执行附件未由本区域检查点登记')
    return [checkpoint_ref, *missing]


def _execution(bundle, fact, pair=None):
    """执行必须属于本批明确绑定的历史运行，状态与原分数精确对应。"""
    _, manifest, home, run, result, packet = bundle
    reference = fact.get('execution')
    registered = result['files']
    raw = checked_bytes(home, reference, registered)
    value = json.loads(raw)
    parts = PurePosixPath(reference['path']).parts
    require(len(parts) > 3 and parts[:2] == ('runs', 'A06'), '执行引用不是本批评分原件')
    origin_id = parts[2]
    origin_ref = manifest.get('runs', {}).get(origin_id, {}).get('run_file')
    require(origin_ref and (origin_id == run['run_id'] or any(
        same_file(origin_ref, ref) for ref in _references(run['inputs']))), '执行运行不在本批来源绑定中')
    origin = read_json(verified_file(home, origin_ref))
    require(origin.get('run_id') == origin_id and origin.get('study_id') == run['study_id']
            and origin.get('module_id') == 'A06'
            and same_file(bound_batch(home, manifest, origin), bound_batch(home, manifest, run))
            and same_file(origin['inputs'].get('system_input_ref'), run['inputs']['system_input_ref'])
            and value.get('state') == fact['state']
            and fingerprint(value.get('score')) == fingerprint(fact.get('score')),
            '实际执行与本组合、批次或评分不同')
    # 同名或同分并不足以匹配；回到原运行自己的事实包，按稳定对象核对实际执行引用。
    owner = pair or fact
    origin_result_ref = manifest['runs'][origin_id].get('result_file')
    additional = []
    if origin_result_ref:
        if origin_id == run['run_id']:
            # bundle 已绑定并核验当前运行的唯一评分包，同批每个区域共享这份原字节解析结果。
            origin_packet = packet
        else:
            origin_result = read_json(verified_file(home, origin_result_ref))
            refs = origin_result.get('tables', {}).get('scoring_packet', [])
            require(len(refs) == 1, '原执行运行缺少唯一评分事实包')
            origin_packet = json.loads(checked_bytes(home, refs[0], origin_result['files']))
        require(origin_packet.get('study_id') == run['study_id']
                and origin_packet.get('run_id') == origin_id, '原执行事实包归属不同')
        candidates = [p for p in origin_packet['pairs'] if p['compound_id'] == owner['compound_id']
                      and p['target_id'] == owner['target_id']]
        require(len(candidates) == 1, '原执行事实包没有唯一稳定对象组合')
        original_pair = candidates[0]
        candidates = [original_pair] if fact is owner else [r for r in original_pair.get('regions', [])
                                                        if r.get('region_id') == fact.get('region_id')]
        require(len(candidates) == 1 and same_file(candidates[0].get('execution'), reference)
                and candidates[0].get('state') == fact['state']
                and fingerprint(candidates[0].get('score')) == fingerprint(fact.get('score')),
                '执行引用不属于该稳定对象的原评分或区域')
    else:
        partial = run['inputs'].get('source_binding', {}).get('partial_recovery') or {}
        require(partial.get('run_id') == origin_id, '未发表执行没有本批明确检查点来源')
        expected = [(c['compound_id'], t['target_id']) for c in packet['source_fixed']['compounds']
                    for t in packet['source_fixed']['receptors']]
        ordinal = expected.index((owner['compound_id'], owner['target_id'])) + 1
        matches = []
        for checkpoint_ref in partial.get('checkpoint_refs', []):
            checkpoint = read_json(verified_file(home, checkpoint_ref))
            if checkpoint.get('key', '').startswith(f'pair_{ordinal:06d}_region_'):
                if same_file(checkpoint.get('payload', {}).get('execution'), reference):
                    matches.append((checkpoint_ref, checkpoint))
        require(len(matches) == 1 and matches[0][1].get('run_id') == origin_id,
                '未发表执行没有对应稳定对象的已登记区域检查点')
        missing = [item for item in value.get('files', [])
                   if not any(same_file(item, registered_ref) for registered_ref in registered)]
        if missing:
            require(partial.get('run_files') == manifest['runs'][origin_id], '恢复附件的原运行登记已改变')
            checkpoint_ref, checkpoint = matches[0]
            additional = _checkpoint_attachments(manifest, origin, owner, ordinal, reference,
                                                 checkpoint_ref, checkpoint, missing)
            registered = [*registered, *additional]
    for item in value.get('files', []):
        checked_bytes(home, item, registered)
    return reference, raw, value, origin, additional


def recovery_file_refs(bundle):
    """完整包保留所有采用区域独立登记的执行附件，含未选中的区域。"""
    _, _, _, run, _, packet = bundle
    partial = run['inputs'].get('source_binding', {}).get('partial_recovery') or {}
    origin_id = partial.get('run_id')
    if not origin_id:
        return []
    prefix = f'runs/A06/{origin_id}/'
    refs = []
    for pair in packet['pairs']:
        for region in pair.get('regions', []):
            if (region.get('execution') or {}).get('path', '').startswith(prefix):
                _, _, _, _, additional = _execution(bundle, region, pair)
                refs.extend(additional)
    return refs

def _top1(raw, score):
    """提取首个MODEL 1的精确原字节，拒绝换模式、缺尾或评分不符。"""
    chosen = []
    for line in raw.splitlines(keepends=True):
        if line.startswith(b'MODEL '):
            require(not chosen and line.split()[1:] == [b'1'], '原始第一构象不是唯一MODEL 1')
            chosen.append(line)
        elif chosen:
            chosen.append(line)
            if line.startswith(b'ENDMDL'):
                break
    require(chosen and chosen[-1].startswith(b'ENDMDL'), '原始MODEL 1不完整')
    scores = [float(line.split()[3]) for line in chosen if line.startswith(b'REMARK VINA RESULT:')]
    require(len(scores) == 1 and math.isfinite(scores[0]) and scores[0] == score,
            '原始MODEL 1评分与本组合不同')
    return b''.join(chosen)

def _score_source_note(packet, pair):
    """读取本批已登记代次，不按执行目录或累计补救类别推断本轮新增。"""
    if packet['schema_version'] == 'A06.system_rescue.1':
        require(pair.get('source_kind') in ('original', 'rescue'), '原补救评分缺少来源类别')
        reused = pair['source_kind'] == 'original'
    else:
        lookup = {(row['compound_id'], row['target_id']): row for row in packet['pairs']}
        require(len(lookup) == len(packet['pairs']), '补救评分包含重复稳定对象')
        groups = []
        for field in ('reused_pair_keys', 'new_pair_keys'):
            rows = packet.get(field)
            require(isinstance(rows, list) and all(isinstance(row, list) and len(row) == 2
                    and all(isinstance(value, str) and value for value in row) for row in rows),
                    '补救评分代次集合格式错误')
            keys = {tuple(row) for row in rows}
            require(len(keys) == len(rows) and keys <= set(lookup), '补救评分代次重复或包含未知组合')
            groups.append(keys)
        old, new = groups
        require(not old & new and all(lookup[key]['state'] == 'completed' for key in old)
                and all(lookup[key]['state'] in ('completed', 'failed') for key in new),
                '补救评分代次重叠或状态不同')
        require({key for key, row in lookup.items() if row['state'] == 'completed'} <= old | new,
                '有效评分缺少唯一的本轮或沿用代次')
        reused = (pair['compound_id'], pair['target_id']) in old
    note = '沿用已核验评分，不计为本轮新增。' if reused else '本轮新增评分。'
    return '来自已登记实际执行的MODEL 1原字节；' + note

def _artifacts(bundle, pair):
    """仅从该组合原执行构造只读下载；派生SHA按返回字节计算。"""
    _, _, home, run, result, packet = bundle
    ref, execution_raw, execution, origin, additional = _execution(bundle, pair)
    artifacts = {'execution': (execution_raw, 'execution.json', 'application/json')}
    if pair['state'] != 'completed':
        return artifacts, ref, {'execution_run_id': origin['run_id']}
    require(execution.get('top_mode') == 1 and execution.get('returncode') == 0
            and execution.get('pose') in execution.get('files', []), '成功评分缺少原始Top-1执行证据')
    source = execution['pose']
    raw = checked_bytes(home, source, [*result['files'], *additional])
    top = _top1(raw, pair['score'])
    if pair.get('top1_pose'):
        require(checked_bytes(home, pair['top1_pose'], result['files']) == top,
                '已登记Top-1与实际执行MODEL 1不同')
    context = {'schema_version': VERSION, 'study_id': run['study_id'], 'run_id': run['run_id'],
               'compound_id': pair['compound_id'], 'target_id': pair['target_id'],
               'input_key': packet['summary']['input_key'], 'execution_run_id': origin['run_id'],
               'execution_sha256': ref['sha256'], 'source_pose_sha256': sha256(raw).hexdigest(),
               'source_pose_bytes': len(raw), 'top1_sha256': sha256(top).hexdigest(), 'top1_bytes': len(top),
               'top_mode': 1, 'score': pair['score'], 'unit': 'kcal/mol',
               'region_id': pair.get('region_id'), 'configuration': origin['config'],
               'read_only': True, 'scientific_results_changed': False,
               'source_zh': _score_source_note(packet, pair)}
    artifacts.update(top1=(top, 'top1.pdbqt', 'chemical/x-pdbqt'),
                     source=(raw, 'original_poses.pdbqt', 'chemical/x-pdbqt'),
                     context=(json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8'),
                              'context.json', 'application/json'))
    return artifacts, ref, context
