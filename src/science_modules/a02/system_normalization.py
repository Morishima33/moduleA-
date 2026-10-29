"""一次明确系统批次的疾病侧标准化：原五库/HGNC算法，未决范围留因暂缓。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require
from storage import read_json,verified_file

VERSION='A02.system_normalization.1'


def configuration():
    return {'version':VERSION,'scope_policy':'direct_only_defer_unresolved',
        'score_filter':'none','mapping_rule':'HGNC.resolve.3','identity_policy':'block_unresolved',
        'source_profile':'A02.source_profile.3'}


def facts(home,inputs):
    """逐件核验批次原候选和五库原件，重新解析后才调用原标准化算法。"""
    from disease import CONFIG,organize,source_profile,validate_disease
    from hgnc import HgncMap
    from identity_sources import IdentityEvidence
    from mesh_identity import validate_mesh_identity
    from normalization import compute
    from source_identity import validate_source_identity
    from science_modules.analysis_protocol import checked_plan
    home=Path(home);batch=read_json(verified_file(home,inputs['system_batch_file']))
    require(batch['schema_version']=='ModuleA.system_execution.1' and batch['study_id']==inputs['study_id']
        and batch['human_review_written'] is False and batch['request']['confirmed'] is True
        and batch['request_hash']==fingerprint(batch['request']),'A02系统批次授权无效')
    initial=batch['initial_binding'];base_id=initial['current'].get('A02')
    require(base_id and inputs['base_result']==initial['run_files'][base_id]['result_file']
        and inputs['base_run']==initial['run_files'][base_id]['run_file'],'疾病候选不属于批次明确绑定的原始输入')
    plan=read_json(verified_file(home,inputs['analysis_plan_file']))
    require(inputs['analysis_plan_file']==batch['plan_file'] and plan['study_id']==inputs['study_id']
        and plan['plan_id']==inputs['analysis_plan_id']==batch['request']['expected_plan_id']
        and checked_plan(plan['plan'])['parameter_hash']==inputs['analysis_parameter_hash']
        and plan['expected_a00']==inputs['bound_a00']==batch['request']['expected_a00'],'A02系统方案绑定不一致')
    intake=read_json(verified_file(home,inputs['intake_result']))
    a01=read_json(verified_file(home,inputs['a01_result']))
    require(intake['run_id']==inputs['bound_a00'] and intake['study_id']==a01['study_id']==inputs['study_id']
        and a01['module_id']=='A01' and not a01['summary'].get('handoff_blocked'),'A02登记或三库依赖无效')
    purpose=intake['summary']['analysis_purpose'];identity=validate_mesh_identity(intake['summary'])
    require(purpose in ('formal_research','workflow_test') and a01['summary']['analysis_purpose']==purpose,'疾病与三库用途不同')
    base_run=read_json(verified_file(home,inputs['base_run']));base=read_json(verified_file(home,inputs['base_result']))
    require(base_run['run_id']==base['run_id']==base_id and base_run['study_id']==base['study_id']==inputs['study_id']
        and base_run['module_id']==base['module_id']=='A02' and base_run['config']==CONFIG
        and base_run['parent_runs']=={'A00':inputs['bound_a00']},'系统标准化只消费本批真实五库原始候选，不复用旧标准化或其他登记')
    validate_disease(base_run,base['summary'],base['tables'],base['anomalies'],base['outcome'])
    manifests=[r for r in base['sources'] if r['role']=='source_manifest'];require(len(manifests)==1,'原五库来源清单不唯一')
    sources=read_json(verified_file(home,manifests[0]));profile=source_profile('A02.source_profile.3')
    require(sources['source_profile']==profile and base['summary']['source_profile']==profile['version']
        and base['summary']['databases']==profile['databases'],'系统标准化要求现代五库方案')
    datasets=[]
    for item in sources['datasets']:
        raw=verified_file(home,item['source_record']).read_bytes()
        validate_source_identity(intake['summary'],item,raw)
        require(item['version'].strip().casefold() not in ('','unknown','未知','未注明'),'五库来源版本待核，不能系统交接')
        if purpose=='formal_research':
            require(item['format'] not in ('otp_legacy','disgenet_legacy'),'正式研究不能使用旧恢复来源')
        datasets.append(dict(item,data=raw))
    require(len(datasets)==5 and {x['database'] for x in datasets}==set(profile['databases']),'系统标准化五库原件不齐或重复')
    original,rows,_=organize(datasets,sources.get('scope_decisions',[]),profile['databases'],profile['version'])
    require(fingerprint(rows)==fingerprint(base['tables']) and all(base['summary'].get(k)==v for k,v in original.items()),
        '疾病候选与五库原件独立重建不一致')
    require(all(row['availability'] in ('已有候选资料，待核验','已查询但0条精确记录') for row in rows['source_summary']),
        '五库有缺失或查询失败，不能作为零记录放行')
    binding=inputs['mapping'];require(binding==batch['mapping'] and binding['mapping_rule']=='HGNC.resolve.3'
        and len(binding['identity_evidence_files'])==3,'A02映射必须使用本批完整HGNC及身份依据')
    evidence=IdentityEvidence(*(verified_file(home,r).read_bytes() for r in binding['identity_evidence_files']))
    mapper=HgncMap(verified_file(home,binding['mapping_file']).read_bytes(),rule=binding['mapping_rule'],supplement=evidence)
    require(mapper.digest==binding['mapping_snapshot']==a01['summary']['mapping_snapshot']
        and mapper.rule==a01['summary']['mapping_rule']
        and evidence.digest==binding['identity_evidence_snapshot']==a01['summary']['identity_evidence_snapshot'],
        '疾病与本批A01的HGNC或补充证据不同')
    terms={str(t).strip().casefold() for t in [identity['preferred_term'],*identity.get('entry_terms',[])]}
    scopes={};decisions=[]
    for row in rows['scope_groups']:
        saved=row['scope'];matched=row['disease_id'].strip().casefold()==identity['mesh_id'].casefold() or row['disease_term'].strip().casefold() in terms
        effective=saved if saved!='pending' else 'direct' if matched else 'pending'
        scopes[row['scope_id']]=effective
        decisions.append(dict(row,raw_scope=saved,effective_scope=effective,
            action='deferred' if effective=='pending' else 'include' if effective=='direct' else 'saved_exclusion',
            authority_kind='system_validation',reason_zh='身份与本病尚未精确对应，暂缓且保留原件，不判为其他疾病' if effective=='pending' else
                '沿用本批已保存范围决定' if saved!='pending' else 'MeSH编号、首选词或官方同义词精确一致'))
    summary,tables,anomalies=compute(base,mapper,'A02',scopes,False,None,purpose,identity)
    # 新显式协议允许范围未决暂缓；身份未决仍阻断，不改变旧compute/validator。
    require(not tables['identity_issues'],'疾病基因存在关键身份未决，不能系统交接')
    tables['scope_system_decisions']=decisions
    tables['scope_decisions_final']=[dict(row,authority_kind='system_validation') for row in tables['scope_decisions_final']]
    summary.update(protocol_version=VERSION,analysis_plan_id=plan['plan_id'],analysis_parameter_hash=plan['plan']['parameter_hash'],
        handoff_blocked=False,scope_authority='system_validation',**{'暂缓范围组数':sum(row['action']=='deferred' for row in decisions),
        '资料阶段':'本批系统标准化，尚未人工总体复核','身份问题处理':'关键身份全部明确；未决身份不自动略过'})
    anomalies=list(anomalies)+['范围未决项留因暂缓、不纳入本批集合；不标作已排除或人工确认。系统校验不代表人工批准。']
    return summary,tables,anomalies


def validator(root,fallback):
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return fallback(run,summary,tables,anomalies,outcome)
        require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['module_id']=='A02'
            and run['parent_review_ids']=={} and run['batch_file']==run['inputs']['system_batch_file']
            and run['config']==configuration(),'疾病系统执行协议或配置无效')
        home=Path(root)/'studies'/run['study_id'];inputs=run['inputs']
        for module,key in [('A00','intake_result'),('A01','a01_result')]:
            require(read_json(verified_file(home,inputs[key]))['run_id']==run['parent_runs'][module],'疾病实际父运行不一致')
        expected=facts(home,inputs)
        require(fingerprint((summary,tables,anomalies))==fingerprint(expected),'疾病系统结果与原件独立复算不同')
        require(outcome==('success' if summary['标准化基因数'] else 'empty'),'疾病系统空集状态错误')
    return check
