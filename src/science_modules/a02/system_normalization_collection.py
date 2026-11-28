"""系统新原候选的显式第三版标准化；原解析/HGNC/范围规则及前两版保持。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require
from storage import read_json,verified_file

VERSION='A02.system_normalization.3'
PARALLEL_VERSION='A02.system_normalization.6'


def configuration(version=VERSION):
    return {'version':version,'source_binding_protocol':'A02.system_source_reuse.2','scope_policy':'direct_only_defer_unresolved',
        'score_filter':'none','mapping_rule':'HGNC.resolve.3','identity_policy':'block_unresolved',
        'source_profile':'A02.source_profile.3'}


def facts(home,inputs,version=VERSION,*,review_preview=False):
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
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    from modulea.core import system_disease_sources
    workflow=AnalysisPlanWorkflow(home.parents[1]);manifest=workflow.load(inputs['study_id'])
    require(inputs['system_batch_file'] in manifest.get('analysis_plan_system_batch_records',[]),
        '复用来源的新系统批次未登记到本研究')
    bound_source=system_disease_sources.read(workflow,manifest,batch)
    base_id=bound_source['base_run_id']
    require(inputs['base_result']==bound_source['base_result'] and inputs['base_run']==bound_source['base_run']
        and inputs['disease_source_binding']==batch['disease_source_file']
        and inputs['source_current_run']==bound_source['source_current_run']
        and inputs['source_current_result']==bound_source['source_current_result'],
        '疾病复用不是原明确当前来源链，不允许改写初始快照或换其他候选')
    plan=read_json(verified_file(home,inputs['analysis_plan_file']))
    require(inputs['analysis_plan_file']==batch['plan_file'] and plan['study_id']==inputs['study_id']
        and plan['plan_id']==inputs['analysis_plan_id']==batch['request']['expected_plan_id']
        and checked_plan(plan['plan'])['parameter_hash']==inputs['analysis_parameter_hash']
        and plan['expected_a00']==inputs['bound_a00']==batch['request']['expected_a00'],'A02系统方案绑定不一致')
    intake=read_json(verified_file(home,inputs['intake_result']))
    parallel=version==PARALLEL_VERSION
    require(parallel==(batch.get('foundation_stage')=='A02') and intake['run_id']==inputs['bound_a00']
        and intake['study_id']==inputs['study_id'] and intake['module_id']=='A00','A02登记或执行协议无效')
    purpose=intake['summary']['analysis_purpose'];identity=validate_mesh_identity(intake['summary'])
    require(purpose in ('formal_research','workflow_test'),'A02登记用途无效')
    a01=None
    if parallel:
        require('a01_result' not in inputs,'独立疾病标准化不绑定方剂结果')
    else:
        a01=read_json(verified_file(home,inputs['a01_result']))
        require(a01['study_id']==inputs['study_id'] and a01['module_id']=='A01'
            and not a01['summary'].get('handoff_blocked') and a01['summary']['analysis_purpose']==purpose,
            'A02登记或三库依赖无效')
    base_run=read_json(verified_file(home,inputs['base_run']));base=read_json(verified_file(home,inputs['base_result']))
    require(base_run['run_id']==base['run_id']==base_id and base_run['study_id']==base['study_id']==inputs['study_id']
        and base_run['module_id']==base['module_id']=='A02' and base_run['config'].get('version')=='A02.system_collection.1'
        and base_run['parent_runs']=={'A00':inputs['bound_a00']},'系统标准化只消费本批真实五库原始候选，不复用旧标准化或其他登记')
    from .system_collection import configuration as collection_configuration,facts as collection_facts
    require(base_run['config']==collection_configuration()
        and fingerprint((base['summary'],base['tables'],base['anomalies']))==fingerprint(collection_facts(home,base_run['inputs'])),
        '新原候选与本研究完整获取、范围决定和原科学整理不一致')
    validate_disease({'config':CONFIG},base['summary'],base['tables'],base['anomalies'],base['outcome'])
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
    require(mapper.digest==binding['mapping_snapshot'] and mapper.rule==binding['mapping_rule']
        and evidence.digest==binding['identity_evidence_snapshot'],'疾病与本批HGNC或补充证据不同')
    if a01:
        require(mapper.digest==a01['summary']['mapping_snapshot'] and mapper.rule==a01['summary']['mapping_rule']
            and evidence.digest==a01['summary']['identity_evidence_snapshot'],'疾病与本批A01的HGNC或补充证据不同')
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
    require(not tables['identity_issues'] or review_preview and parallel,'疾病基因存在关键身份未决，不能系统交接')
    tables['scope_system_decisions']=decisions
    tables['scope_decisions_final']=[dict(row,authority_kind='system_validation') for row in tables['scope_decisions_final']]
    summary.update(protocol_version=version,source_binding_protocol='A02.system_source_reuse.2',analysis_plan_id=plan['plan_id'],analysis_parameter_hash=plan['plan']['parameter_hash'],
        handoff_blocked=bool(tables['identity_issues']),scope_authority='system_validation',**{'暂缓范围组数':sum(row['action']=='deferred' for row in decisions),
        '资料阶段':'本批系统标准化，尚未人工总体复核','身份问题处理':'关键身份全部明确；未决身份不自动略过'})
    anomalies=list(anomalies)+['范围未决项留因暂缓、不纳入本批集合；不标作已排除或人工确认。系统校验不代表人工批准。']
    if summary['handoff_blocked']:
        summary['身份问题处理']='仅供核验，关键身份未决'
    return summary,tables,anomalies


def validator(root,fallback):
    def check(run,summary,tables,anomalies,outcome):
        version=run['config'].get('version')
        if version not in (VERSION,PARALLEL_VERSION):return fallback(run,summary,tables,anomalies,outcome)
        parents={'A00':'intake_result'} if version==PARALLEL_VERSION else {'A00':'intake_result','A01':'a01_result'}
        require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['module_id']=='A02'
            and run['parent_review_ids']=={} and run['batch_file']==run['inputs']['system_batch_file']
            and run['config']==configuration(version) and set(run['parent_runs'])==set(parents),'疾病系统执行协议或配置无效')
        home=Path(root)/'studies'/run['study_id'];inputs=run['inputs']
        for module,key in parents.items():
            require(read_json(verified_file(home,inputs[key]))['run_id']==run['parent_runs'][module],'疾病实际父运行不一致')
        expected=facts(home,inputs,version)
        require(fingerprint((summary,tables,anomalies))==fingerprint(expected),'疾病系统结果与原件独立复算不同')
        require(outcome==('success' if summary['标准化基因数'] else 'empty'),'疾病系统空集状态错误')
    return check


def compute(workflow,m,batch,plan,batch_ref,*,review_preview=False):
    """新批重新标准化但不重取原件，实际新A01及共同HGNC保持绑定。"""
    from copy import deepcopy
    from modulea.core import system_disease_sources
    sid=m['study_id'];home=workflow.location(sid);binding=system_disease_sources.read(workflow,m,batch)
    require(m['current'].get('A02')==batch['initial_binding']['current'].get('A02'),'疾病来源已由其他运行改变')
    source=read_json(verified_file(home,binding['source_current_run']));base=read_json(verified_file(home,binding['base_run']))
    def reviews(artifact):
        return [deepcopy(r) for r in m.get('reviews',[]) if read_json(verified_file(home,r))['artifact_id']==artifact]
    parallel=batch.get('foundation_stage')=='A02'
    version=PARALLEL_VERSION if parallel else VERSION
    inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],
        'analysis_plan_id':plan['plan_id'],'analysis_plan_file':deepcopy(batch['plan_file']),
        'analysis_parameter_hash':plan['plan']['parameter_hash'],'system_batch_file':deepcopy(batch_ref),
        'base_run':binding['base_run'],'base_result':binding['base_result'],'base_reviews':reviews(base['artifact_id']),
        'disease_source_binding':batch['disease_source_file'],'source_current_run':binding['source_current_run'],
        'source_current_result':binding['source_current_result'],'source_current_reviews':reviews(source['artifact_id']),
        'mapping':deepcopy(batch['mapping']),
        'intake_result':deepcopy(m['runs'][batch['request']['expected_a00']]['result_file'])}
    if not parallel:
        inputs['a01_result']=deepcopy(m['runs'][m['current']['A01']]['result_file'])
    summary,tables,anomalies=facts(home,inputs,version,review_preview=review_preview)
    sources=[batch['plan_file'],inputs['base_run'],inputs['base_result'],inputs['source_current_run'],inputs['source_current_result'],
        inputs['disease_source_binding'],*([inputs['a01_result']] if not parallel else []),
        inputs['intake_result'],inputs['mapping']['mapping_file'],
        *inputs['mapping']['identity_evidence_files'],*read_json(verified_file(home,inputs['base_result']))['sources']]
    return inputs,configuration(version),summary,tables,anomalies,sources
