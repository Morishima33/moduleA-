"""显式恢复第三版中断批次：离线重核准备原件，仅计算未落盘区域，不改变科学规则。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
from unittest.mock import patch
import json
import urllib.error

from contracts import require, fingerprint
from storage import file_record, read_json, verified_file, write_json, new_id
from .reference_rules import VERSION, POLICY
from .trial_compute import score_region as execute_region


def source_cache(home):
    """只索引本研究原始请求；使用时复验原件指纹，不把失败请求当成功。"""
    cache = {}
    for path in home.rglob('*_request.json'):
        fact = read_json(path)
        if fact.get('state') == 'success' and fact.get('file'):
            cache.setdefault(fact['url'], []).append(fact['file'])
    return cache


def cached_get(cache):
    """恢复准备期间禁止联网；不存在已成功归档的URL时明确失败。"""
    def get(self, url, suffix='json'):
        require(url in cache, '恢复缺少已归档的官方响应：' + url)
        records = cache[url]
        prefix = self.folder.relative_to(self.root).as_posix() + '/' if getattr(self,'folder',None) else ''
        same_attempt = [r for r in records if prefix and r['path'].replace('\\','/').startswith(prefix)]
        require(not prefix or bool(same_attempt), '本轮原始请求没有成功响应，不借用其他批次补入候选：'+url)
        records = same_attempt if prefix else records
        raw = verified_file(self.root, records[-1]).read_bytes()
        self.records.append(records[-1])
        return (json.loads(raw) if suffix == 'json' else raw), records[-1]
    return get


def cached_candidate(root, row, origin, folder, tools, repair_packages, code):
    """重建原准备字段，区域和环境仍由冻结check_exploration从实际原件重算。"""
    from .trial_prepare import prediction_rows, regions_from_predictions, coordinates
    from .trial_rules import partitions
    spec = origin['spec']
    repair = read_json(folder/'repair_evidence.json')
    require(read_json(folder/'meeko_execution.json')['returncode'] == 0, '原Meeko准备未成功')
    protein = folder/'repaired_protein.pdb'
    predictions = sorted(folder.glob('p2rank_*/*_predictions.csv'))
    if spec['pocket'] == 'reference':
        from docking_top10_execute import _box_from_lines
        regions = [dict(_box_from_lines((folder/'reference_coordinates.pdb').read_text('ascii')), region_id='fixed_site')]
        mode, rejected = 'fixed_site', []
    else:
        require(len(predictions) == 2 and prediction_rows(predictions[0]) == prediction_rows(predictions[1]), '原两次预测未完整或不一致')
        regions, rejected = regions_from_predictions(protein.read_text('ascii'), prediction_rows(predictions[0]))
        mode = 'predicted_sites'
        if not regions:
            mode, regions = 'partitioned_blind', partitions(coordinates(protein.read_text('ascii')))
    return dict(state='ready', spec=spec, structure_id=spec.get('pdb_id',spec.get('model_id')),
        receptor=file_record(root,folder/(row['symbol']+'.pdbqt'),'trial_receptor'), regions=regions, mode=mode,
        reused=False, repair=repair, source=origin['source_file'], rejected_predictions=rejected,
        environment=origin.get('environment_audit',{}), confidence=origin.get('confidence_facts'),
        history_quality_zh='未通过原严格验证；仅试算', history_rmsd_A=origin.get('top1_rmsd'),
        processing_zh='中断恢复：复验原有限修补、双次预测、实际坐标、环境及既定区域；未重新准备或降低质控。')


def recover_prepare(workflow, sid, connection, row, folder, tools, packages, code, authorization, progress, cache):
    """重放已落盘失败顺序及首个合格候选，禁止新增结构选择或重新运行准备工具。"""
    from . import automatic_coverage_prepare as previous
    from . import trial_prepare, automatic_coverage_sources
    require(not connection.get('reference_choices'), '此恢复入口只支持未核定共晶参考的探索批次')
    if (folder/'final_failure.json').is_file():
        return dict(row,state='NA',quality='未通过',reason_zh='已完成本轮实验候选及预测模型补救；仍有未解决条件，详见逐项依据',attempts=read_json(folder/'final_failure.json')['attempts'])
    clean = deepcopy(row)
    for origin in clean.get('candidates',[]):
        origin['spec'] = {k:v for k,v in origin['spec'].items() if not k.startswith('reference_')}
        origin['spec']['pocket'] = 'p2rank'
        origin.pop('reference_audit',None)
    def explore(root, current, origin, destination, *args):
        failed = folder/('failure_' + destination.name.split('_')[-1]+'.json')
        if failed.is_file():
            fact = read_json(failed)
            require(fact['candidate']['spec'] == origin['spec'] and fact['candidate']['cif'] == origin['cif'], '中断候选顺序或原件不一致')
            raise ValueError(fact['reason_zh'])
        return previous.explore(root,current,origin,destination,*args)
    def preserve(path, data):
        # 原失败记录保留；重放中新产生的检索诊断单独追加。
        if not path.exists():
            diagnostic = folder.parents[2]/'recovery'/'replay_diagnostics'/row['target_id'].replace(':','_')/(new_id('diagnostic')+'_'+path.name)
            write_json(diagnostic,data)
    replay = FunctionType(previous.prepare.__code__,dict(vars(previous),explore=explore,write_json=preserve))
    with patch.object(automatic_coverage_sources.Fetcher,'get',cached_get(cache)), patch.object(trial_prepare,'candidate',cached_candidate):
        result = replay(workflow,sid,connection,clean,folder,tools,packages,code,authorization,progress)
    require(result['state'] == 'ready', '无法从原件恢复已准备受体，不自动改为新的失败结果：'+str(result.get('attempts',[])[-1:])[-300:])
    return result


def recover_region(root, folder, binary, compound, receptor, region):
    """已有区域执行必须匹配实际输入和姿势；中断未落盘目录另存后重新执行该区域。"""
    from .trial_rules import VINA
    from docking_top10_execute import _vina_arguments
    from docking_redocking import _poses
    work = folder/'scores'/compound['compound_id']/receptor['target_id'].replace(':','_')/region['region_id']
    path = work/'execution.json'
    ligand = next(r for r in compound['files'] if r['role']=='prepared_ligand')
    config = dict(compound=ligand,receptor=receptor['receptor'],region=region,
        version=__import__('science_modules.a06.trial_rules',fromlist=['VERSION']).VERSION,vina=VINA,
        executable_sha256=file_record(root,binary,'vina')['sha256'])
    command = _vina_arguments(binary,verified_file(root,receptor['receptor']),verified_file(root,ligand),region,work/'poses.pdbqt')+['--cpu','2']
    if path.is_file():
        fact = read_json(path)
        # 准备器内存使用tuple，JSON归档恢复为list；以归档表示比较，科学输入指纹仍须完全一致。
        normalized = json.loads(json.dumps(config))
        require(fact['config'] == normalized and fact['input_key'] == fingerprint(config) and fact['command'] == command, '已完成区域与当前输入不一致，禁止复用')
        if fact['state']=='completed':
            pose = _poses(verified_file(root,fact['pose']).read_text('ascii'))[0]
            require(fact['returncode']==0 and fact['score']==pose['score_kcal_mol'], '已有原始姿势评分不一致')
        return fact
    if work.exists():
        target = folder/'recovery'/'interrupted_regions'/new_id('region')
        require(work.resolve().is_relative_to(folder.resolve()) and target.resolve().is_relative_to(folder.resolve()), '恢复路径越界')
        target.parent.mkdir(parents=True,exist_ok=True)
        work.rename(target)
    return execute_region(root,folder,binary,compound,receptor,region)


def run(workflow, sid, payload, tools, code, progress, packages):
    """复用本研究原执行授权和同一未完成运行；最后仍走原公开完成校验。"""
    from .reference_engine import draw_matrix, score_pair
    from .quality_engine import target_folder
    manifest,bound,connection_row = workflow.validate_automatic_request(sid,payload)
    batch = workflow.automatic_record(manifest,payload['request_id'])
    require(batch and batch['state']=='running' and manifest['current']['A06']==batch['run_id'], '只能恢复当前中断未完成批次')
    root = workflow.location(sid); info = workflow.run(manifest,batch['run_id'])
    require(info['config']['schema_version']==VERSION and manifest['runs'][info['run_id']]['result_file'] is None, '已完成批次不能续写')
    authorization = read_json(verified_file(root,batch['authorization']))
    require(authorization['request']==payload and authorization['binding']['runs']==info['parent_runs'] and authorization['binding']['reviews']==info['parent_review_ids'], '原授权或批准已变更')
    folder = root/'runs/A06'/info['run_id']/'automatic'
    checkpoint=folder/'recovery/prepared.json'
    connection=read_json(verified_file(root,connection_row['packet']))
    require(not payload['reference_choices'], '恢复不能修改原参考位点选择')
    if checkpoint.is_file():
        prepared=read_json(checkpoint);compounds,receptors=prepared['compounds'],prepared['receptors']
    else:
        cache=source_cache(root);compounds=[];receptors=[]
        for row in connection['compounds']:
            fact=read_json(folder/'quality/ligands'/(row['compound_id']+'_quality.json'))
            for record in fact['files']:verified_file(root,record)
            compounds.append(dict(row,**{k:v for k,v in fact.items() if k not in row},state=fact['state']))
        for row in connection['receptors']:
            progress('恢复准备原件：'+row['symbol'])
            saved=folder/'recovery/preparation'/(target_folder(row['target_id'])+'.json')
            if saved.exists():
                recovered=read_json(saved)
                require(recovered['target_id']==row['target_id'], '准备断点身份不同')
            else:
                recovered=recover_prepare(workflow,sid,connection,row,folder/'quality/receptors'/target_folder(row['target_id']),tools,packages,code,payload['request_id'],progress,cache)
                write_json(saved,recovered)
            receptors.append(recovered)
        write_json(checkpoint,dict(compounds=compounds,receptors=receptors))
    binary=folder/'software/vina_1.2.7.exe'
    require(file_record(root,binary,'vina')['sha256']==read_json(folder/'software/runtime.json')['source_executable_sha256'],'原Vina工具指纹不一致')
    pairs=[]
    for compound in compounds:
        for receptor in receptors:
            row=dict(compound_id=compound['compound_id'],target_id=receptor['target_id'],state='NA',score=None,quality=receptor['quality'],reason_zh='')
            if compound['state']!='ready' or receptor['state']!='ready':
                row['state']='failed' if compound['state']=='failed' or receptor['state']=='failed' else 'NA'
                row['reason_zh']='；'.join(r.get('reason_zh','') for r in (compound,receptor) if r['state']!='ready')
            else:
                progress(f"续算 {len(pairs)+1}/{len(compounds)*len(receptors)}：{receptor['symbol']}")
                with patch('science_modules.a06.trial_compute.score_region',recover_region):
                    # recover_region在缺失时调用冻结原函数，避免替换函数递归。
                    row.update(score_pair(root,folder,binary,compound,receptor))
            pairs.append(row)
            saved = folder/'recovery'/f'pair_{len(pairs):06d}.json'
            if saved.exists():
                require(read_json(saved) == json.loads(json.dumps(row)), '本次恢复与已保存组合不一致')
            else:
                write_json(saved,row)
            progress(f"已保存组合 {len(pairs)}/{len(compounds)*len(receptors)}：{receptor['symbol']}")
    strict=[r['target_id'] for r in receptors if r['state']=='ready' and r['quality']=='严格'];primary=strict[:5] if len(strict)>=5 else []
    summary=dict(science_version=VERSION,成分数=len(compounds),受体数=len(receptors),计划组合数=len(pairs),成功组合数=sum(x['state']=='completed' for x in pairs),失败组合数=sum(x['state']=='failed' for x in pairs),NA组合数=sum(x['state']=='NA' for x in pairs),严格受体数=len(strict),探索受体数=sum(x['state']=='ready' and x['quality']=='探索' for x in receptors),主要受体数=len(primary),handoff_blocked=not any(x['state']=='completed' for x in pairs),interpretation_scope='strict_and_exploratory_separate',automatic_scientific_approval=False)
    packet=dict(schema_version=VERSION,study_id=sid,id=payload['request_id'],run_id=info['run_id'],connection=info['inputs']['automatic_connection'],authorization=info['inputs']['automatic_authorization'],policy=POLICY,runtime=read_json(folder/'software/runtime.json')['runtime'],compounds=compounds,receptors=receptors,pairs=pairs,summary=summary,primary_targets=primary,executable=file_record(root,binary,'automatic_vina'))
    from modulea.core.automatic_experience import automatic_names
    draw_matrix(packet,folder/'display',automatic_names(workflow,manifest,packet,info['parent_runs']['A03']))
    write_json(folder/'packet.json',packet);record=file_record(root,folder/'packet.json','automatic_packet')
    files=list({r['path']:r for r in connection['files']+list(info['inputs'].values())+[file_record(root,p,'automatic_evidence') for p in folder.rglob('*') if p.is_file()]}.values())
    tables=dict(automatic_packet=[record],pairs=[{k:r[k] for k in ('compound_id','target_id','state','score','quality','reason_zh')} for r in pairs],receptor_setup=[{'基因':r['symbol'],'HGNC':r['target_id'],'质控':r['quality'],'状态':r['state'],'PDB':r.get('selected_candidate',{}).get('spec',{}).get('pdb_id',r.get('selected_candidate',{}).get('spec',{}).get('model_id','')),'原因':r['reason_zh']} for r in receptors])
    return workflow.finish_automatic(sid,payload,info['run_id'],record,summary,tables,files)
