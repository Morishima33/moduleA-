"""失败二版的只读恢复清点：逐件验证登记准备与区域，不把残件当作成功。"""
from copy import deepcopy
import re

from contracts import encoded, fingerprint, require
from . import bounded_evidence as io
from . import system_receptor_rescue_v2 as core


def difference_paths(expected, actual, prefix='binding', limit=32):
    """只列不同字段路径，不把整份依赖签名/个人路径重复拼进错误或长任务内存。"""
    paths = []
    def walk(left, right, name):
        if len(paths) >= limit:return
        if type(left) is not type(right):paths.append(name);return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:paths.append(name+'.'+str(key))
                else:walk(left[key],right[key],name+'.'+str(key))
                if len(paths)>=limit:return
        elif isinstance(left,list):
            if len(left)!=len(right):paths.append(name+'.length')
            else:
                for index,(a,b) in enumerate(zip(left,right)):walk(a,b,name+f'[{index}]')
        elif left != right:paths.append(name)
    walk(expected,actual,prefix)
    return paths


def preflight(adapter, workflow, sid, run_id, body, tools, repair_packages):
    """完整原资格、代码、工具和原请求先核对，inspect不写研究或调用评分。"""
    manifest, _, run = adapter.bind(core.validate_request)(workflow, sid, body)
    require(run and run['run_id'] == run_id and run['config']['version'] == core.VERSION,
            '只支持明确指定的当前失败/中断二版原运行，不新建科学批次')
    require(not manifest['runs'][run_id].get('result_file'), '二版已归档，不重复恢复')
    request = adapter.bind(core._read_request)(workflow, manifest, run['inputs']['rescue_request'])
    from science_modules.a06 import system_receptor_rescue_v2 as science
    prep = workflow.run(manifest, body['expected_preparation_run_id'])
    config = adapter.bind(science.configuration)(prep, tools=tools, repair_packages=repair_packages)
    execution = adapter.bind(core._execution_binding)(workflow, config, tools, repair_packages)
    differences = difference_paths(run['config'],config,'configuration')
    differences += difference_paths(request['execution_binding'],execution,'execution_binding')
    if run['code_version'] != workflow.code_version:differences.append('code_version')
    if run['environment_version'] != fingerprint(workflow.environment):differences.append('environment_version')
    require(not differences,'原二版绑定已改变，不能同批恢复；差异字段：'+'、'.join(differences[:32]))
    return manifest, run


def catalog(adapter, workflow, sid, run):
    """单遍验证完整登记链和所有证据，只保留对象到最新引用的紧凑索引。"""
    manifest = workflow.load(sid)
    home = workflow.location(sid)
    latest, states = {}, {}
    for ref in manifest.get(core.CHECKPOINTS, []):
        value = io.read_verified_json(home, ref)
        require(value.get('schema_version') == core.VERSION and value.get('study_id') == sid,
                '恢复检查点研究或协议不同')
        if value.get('run_id') != run['run_id']:continue
        key = value.get('key')
        core.frozen._checkpoint_key(key)
        require(value.get('config_hash') == run['config_hash'] and value.get('human_review_written') is False
                and isinstance(value.get('payload'), dict) and isinstance(value.get('files'), list)
                and value.get('previous') == latest.get(key)
                and ref['path'].startswith(f'runs/A06/{run["run_id"]}/rescue_checkpoints/{key}/'),
                '恢复检查点配置、对象、路径或原链不同')
        if key in states:
            state, retryable = states[key]
            require(state not in ('ready', 'completed') and retryable is True, '成功或稳定NA对象不能被后续替换')
        for original in value['files']:io.verified_file(home, original)
        latest[key] = deepcopy(ref)
        states[key] = value['payload'].get('state'), value['payload'].get('retryable')
    require(fingerprint(workflow.load(sid)) == fingerprint(manifest), '恢复清点期间登记改变')
    return latest


def inventory(adapter, workflow, sid, run):
    """复用原科学验证器逐区域核命令和MODEL1；只返回计数及需计算对象，绝不执行Vina。"""
    import json
    from science_modules.a06 import system_receptor_rescue_v2 as science
    from science_modules.a06.system_rescue_partial import verify_identity
    from science_modules.a06.plan_score_pair import validate
    from science_modules.a06.plan_scoring_inputs import ligand_record
    from science_modules.a06.trial_rules import choose_score
    home = workflow.location(sid)
    manifest = workflow.load(sid)
    source = adapter.bind(science.source_data)(workflow, manifest,
                run['inputs']['source_binding']['source_preparation_run_id'],
                run['inputs']['source_binding']['baseline_run_id'])
    # 原来源生产规范仍执行，不以目录或摘要计数代替。
    adapter.bind(science._read_baseline)(workflow, source)
    refs = catalog(adapter, workflow, sid, run)
    receptors = {r['target_id']: deepcopy(r) for r in source['baseline_receptors']}
    restored_preparations = []
    for target in source['fixed']['receptors']:
        key = 'receptor_' + target['target_id'].replace(':', '_')
        if key not in refs:continue
        value = io.read_verified_json(home, refs[key])['payload']
        adapter.bind(verify_identity)(home, source, target, value)
        if value['state'] == 'ready':
            adapter.bind(science.validate_source_use)(home, source, value,
                adapter.bind(science._source_catalog)(workflow, sid, run, target['target_id']))
            adapter.bind(science.verify_prepared)(home, value)
            restored_preparations.append(target['target_id'])
        receptors[target['target_id']] = value
    compounds = source.get('baseline_packet', {}).get('compounds') or source['fact']['compounds']
    allowed_regions = {f'pair_{ordinal:06d}_region_{index:04d}'
        for ordinal,(_,target) in enumerate(((c,t) for c in compounds for t in source['fixed']['receptors']),1)
        for index,_ in enumerate(receptors[target['target_id']].get('regions',[]),1)}
    require(all(key in allowed_regions for key in refs if key.startswith('pair_')),
            '登记区域对象超出固定组合或本受体预定区域')
    original = {(p['compound_id'], p['target_id']):p for p in adapter.bind(science.effective_pairs)(source)}
    binary = home/'runs/A06'/run['run_id']/'rescue/software/vina.exe'
    needed, terminal, na, complete, partial = [], [], [], [], []
    successful_regions = failed_regions = 0
    for ordinal, (compound, target) in enumerate(((c, t) for c in compounds for t in source['fixed']['receptors']), 1):
        pair_id = dict(compound_id=compound['compound_id'], target_id=target['target_id'], ordinal=ordinal)
        if original[(compound['compound_id'], target['target_id'])]['state'] == 'completed':
            terminal.append(pair_id);continue
        receptor = receptors[target['target_id']]
        if compound['state'] != 'ready':
            na.append(dict(pair_id, reason_zh=compound.get('reason_zh','原配体不可用')));continue
        if receptor['state'] != 'ready':
            preparation_key = 'receptor_' + target['target_id'].replace(':', '_')
            if preparation_key in refs and receptor.get('retryable') is not True:
                na.append(dict(pair_id,reason_zh=receptor.get('reason_zh','受体准备稳定NA')))
            else:
                needed.append(dict(pair_id, stage='preparation', reason_zh=receptor.get('reason_zh','受体仍待准备')))
            continue
        facts = []
        for index, region in enumerate(receptor.get('regions', []), 1):
            key = f'pair_{ordinal:06d}_region_{index:04d}'
            if key not in refs:
                needed.append(dict(pair_id, stage='scoring', region_id=region['region_id']));continue
            fact = io.read_verified_json(home, refs[key])['payload']
            prefix = f'runs/A06/{run["run_id"]}/rescue/scores/pair_{ordinal:06d}/region_{index:04d}/'
            require(fact['execution']['path'].startswith(prefix)
                    and re.fullmatch(r'attempt_[0-9a-f]{32}/execution.json',fact['execution']['path'][len(prefix):]),
                    '区域执行不是本运行、本组合和本预定区域')
            require(io.file_record(home,binary,'vina')['sha256'] == run['config']['vina_sha256'], '本批Vina字节改变')
            actual = adapter.bind(validate)(home,fact['execution'],binary,ligand_record(compound),
                       receptor['receptor'],json.loads(encoded(region)),
                       {k:run['config'][k] for k in ('vina_parameters','cpu_per_pair','timeout_seconds')})
            expected = dict(region_id=region['region_id'],state=actual['state'],score=actual['score'],
                reason_zh=actual['reason_zh'],execution=fact['execution'],
                retryable=actual.get('failure_kind') in ('timeout','launch_error'))
            require(fact == expected, '登记区域与实际命令、分数或MODEL1不同')
            if fact.get('retryable'):
                needed.append(dict(pair_id,stage='scoring',region_id=region['region_id'],reason_zh=fact['reason_zh']))
            else:
                facts.append(fact)
                successful_regions += fact['state'] == 'completed'
                failed_regions += fact['state'] == 'failed'
        if len(facts) == len(receptor.get('regions', [])) and facts:
            best = choose_score(facts, receptor['mode'])
            complete.append(dict(pair_id,state='completed' if best else 'failed',
                selected_region_id=best['region_id'] if best else None,
                score=best['score'] if best else None))
        elif facts:partial.append(dict(pair_id,registered_terminal_regions=len(facts)))
    require(fingerprint(workflow.load(sid)) == fingerprint(manifest), '恢复清点期间登记改变')
    return {'schema_version':'ModuleA.rescue_recovery_inventory.1','study_id':sid,'run_id':run['run_id'],
            'read_only':True,'scientific_computation_performed':False,'human_review_written':False,
            'registered_preparations_reused':restored_preparations,'baseline_completed_pairs':terminal,
            'registered_complete_groups':complete,'registered_partial_groups':partial,'ligand_na':na,
            'registered_successful_regions':successful_regions,'registered_failed_regions':failed_regions,
            'remaining':needed,'checkpoint_objects':len(refs),
            'note_zh':'成功登记区域逐个复用；完整区域组无需重算。部分组只计算缺失/明确可重试区域。'
                      '未登记残件不计成功，Top-1派生附件缺失可由原完整区域复核后恢复，不产生新坐标。'}
