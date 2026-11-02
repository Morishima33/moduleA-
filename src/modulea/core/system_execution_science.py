"""系统授权的实际科学输入适配；函数内部才加载科学实现，不改变原算法或参数。"""
from copy import deepcopy
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json


def compounds(workflow,m,batch,plan,batch_ref):
    """一次批次授权派生成分选择请求，原排序、并列及身份待核规则完整保留。"""
    from science_modules.plan_compounds import facts,configuration
    sid=m['study_id'];home=workflow.location(sid);a03=m['current']['A03'];review=workflow.current_docking_review(m)
    binding={'study_id':sid,'a00':batch['request']['expected_a00'],'plan_id':plan['plan_id'],
        'parameter_hash':plan['plan']['parameter_hash'],'current':deepcopy(m['current']),'docking_review':review,
        'authorization_kind':'delegated_system_batch','authorization_file':deepcopy(batch_ref)}
    body={'expected_a00':batch['request']['expected_a00'],'expected_a03':a03,'expected_selection':m['current'].get('A03_SELECT',''),
        'expected_plan_id':plan['plan_id'],'expected_input_hash':fingerprint(binding),'operator':batch['request']['author'],
        'reason':batch['request']['note'],'confirmed':True}
    request={'schema_version':'A03.plan_selection.request.1','study_id':sid,'request':body,'binding':binding,
        'confirmation_basis':'原一次明确系统批次授权派生，不表示另一人工点击'}
    path=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'derived_requests'/(new_id('compound_request')+'.json')
    write_json(path,request);ref=file_record(home,path,'compound_selection_request')
    inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],'bound_a03':a03,'analysis_plan_id':plan['plan_id'],
        'analysis_plan_file':deepcopy(batch['plan_file']),'analysis_parameter_hash':plan['plan']['parameter_hash'],
        'a03_result':deepcopy(m['runs'][a03]['result_file']),'execution_request_file':ref}
    summary,tables=facts(home,inputs)
    return inputs,configuration(plan['plan']),summary,tables,[
        '名单来自本批原排序，保留边界并列；系统证据不代表人工批准或真实结构已可用。'],[batch['plan_file'],inputs['a03_result'],ref]


def compound_validator(root,fallback):
    """仅新系统执行分支改用真实系统授权，旧成分科学校验器和人工父签名断言保持。"""
    def check(run,summary,tables,anomalies,outcome):
        if run.get('execution_protocol')!='ModuleA.system_execution.1':return fallback(run,summary,tables,anomalies,outcome)
        from science_modules.plan_compounds import facts,configuration
        from .analysis_plans import AnalysisPlanWorkflow
        from .system_execution import is_active
        from pathlib import Path
        w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);candidate=deepcopy(m)
        # 规范发布时当前运行尚未提交manifest；只在内存提供候选运行，不写或制造批准。
        candidate['current']['A03_SELECT']=run['run_id']
        home=Path(root)/'studies'/run['study_id'];request=read_json(verified_file(home,run['inputs']['execution_request_file']))
        require(run['config'].get('version')=='A03.plan_selection.1' and run['parent_review_ids']=={}
            and request['binding']['authorization_kind']=='delegated_system_batch'
            and request['binding']['authorization_file']==run['batch_file'],'系统成分授权或人工字段错误')
        # is_active读取候选run需已注册文件指纹，run文件本身已真实落盘。
        candidate['runs'][run['run_id']]={'run_file':file_record(home,home/'runs/A03_SELECT'/run['run_id']/'run.json','run'),'result_file':None}
        require(is_active(w,candidate,run),'系统成分真实依赖已改变')
        expected,rows=facts(home,run['inputs']);plan=read_json(verified_file(home,run['inputs']['analysis_plan_file']))['plan']
        require(run['config']==configuration(plan) and run['parent_runs']['A03']==run['inputs']['bound_a03']
            and fingerprint((summary,tables))==fingerprint((expected,rows)), '系统成分原科学规则或结果不一致')
        require(outcome==('success' if rows['selected'] else 'empty'),'系统成分实际状态不一致')
    return check


def a04(workflow,m,batch,plan,batch_ref):
    """锁外真正请求固定STRING接口，原始响应分步保存，失败不发布占位网络。"""
    from science_modules.a04 import plan_flow as science
    sid=m['study_id'];home=workflow.location(sid);a03=m['current']['A03']
    folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'acquisition/A04'/new_id('attempt')
    write_json(folder/'request.json',{'system_batch_file':batch_ref,'bound_a03':a03,'analysis_plan_file':batch['plan_file'],
        'analysis_parameter_hash':plan['plan']['parameter_hash']})
    def evidence(name,value):
        """成功响应立即归档，后续请求失败仍保留。"""
        write_json(folder/(name+'.json'),value)
    targets=workflow.result(m,a03)['tables']['intersection_targets'];source=science.fetch(targets,plan['plan'],evidence=evidence)
    path=folder/'source.json';write_json(path,source);ref=file_record(home,path,'ppi_source')
    summary,tables=science.evaluate(targets,source,plan['plan']);summary['analysis_plan_id']=plan['plan_id']
    inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],'parent_result':deepcopy(m['runs'][a03]['result_file']),
        'source_file':ref,'analysis_plan_id':plan['plan_id'],'analysis_plan_file':deepcopy(batch['plan_file']),
        'analysis_parameter_hash':plan['plan']['parameter_hash']}
    config={'version':'A04.plan_network.1','string_version':'12.0','required_score':int(round(plan['plan']['parameters']['a04.required_score']*1000)),
        'network_type':'functional','add_nodes':0,'analysis_plan_id':plan['plan_id'],'analysis_parameter_hash':plan['plan']['parameter_hash']}
    return inputs,config,summary,tables,['PPI按原固定规则和本批实际系统依赖计算，不表示人工批准。'],[
        batch['plan_file'],ref,inputs['parent_result'],file_record(home,folder/'request.json','system_stage_acquisition')],{
        'outcome':'success' if summary['参与节点数'] else 'empty'}


def a05(workflow,m,batch,plan,batch_ref):
    """锁外原R来源、ORA及独立BH；输入固定到批次原方案，不调用旧人工资格门控。"""
    import hashlib
    from science_modules.a05 import plan_flow as science
    if batch.get('enrichment_protocol')=='A05.plan_enrichment.2':
        from science_modules.a05 import plan_flow_utf8 as science
    from science_modules.a05.flow import mapping_record
    sid=m['study_id'];home=workflow.location(sid);a03=m['current']['A03'];mapping=mapping_record(workflow,m,a03)
    source_ref=science.source_snapshot(workflow.root,plan['plan']);source=verified_file(workflow.root,source_ref)
    folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'acquisition/A05'/new_id('attempt')
    folder.mkdir(parents=True);archived=folder/source.name;archived.write_bytes(source.read_bytes())
    require(hashlib.sha256(archived.read_bytes()).hexdigest()==source_ref['sha256'],'本批富集原件归档指纹不一致')
    script=folder/science.SCRIPT.name;script.write_bytes(science.SCRIPT.read_bytes())
    inputs={'study_id':sid,'expected_a00':batch['request']['expected_a00'],'analysis_plan_id':plan['plan_id'],
        'analysis_plan_file':deepcopy(batch['plan_file']),'analysis_parameter_hash':plan['plan']['parameter_hash'],
        'parent_result':deepcopy(m['runs'][a03]['result_file']),'mapping_file':mapping,
        'source_file':file_record(home,archived,'annotation_source'),'execution_script':file_record(home,script,'execution_script')}
    write_json(folder/'request.json',{'system_batch_file':batch_ref,'inputs':inputs,'bound_a03':a03})
    _,summary,tables,log=science.facts(home,inputs);(folder/'R_log.txt').write_text(log,encoding='utf8')
    sources=[batch['plan_file'],inputs['parent_result'],mapping,inputs['source_file'],inputs['execution_script'],
        file_record(home,folder/'request.json','system_stage_acquisition'),file_record(home,folder/'R_log.txt','log')]
    return inputs,science.configuration(plan['plan']),summary,tables,[
        'GO各族及KEGG独立BH，实际R统计和完整背景保持；系统校验不表示人工批准。'],sources,{
        'log':log,'outcome':'success' if any(tables[group.lower()+'_significant'] for group in science.groups(plan['plan'])) else 'empty'}


def a02(workflow,m,batch,plan,batch_ref):
    """消费授权时绑定的原始五库候选，同本批三库映射重新标准化。"""
    if batch.get('identity_exception_file'):
        require(batch.get('disease_source_protocol')=='A02.system_source_reuse.3','身份例外只支持明确历史五库来源')
        from science_modules.a02.system_normalization_identity import compute
        return compute(workflow,m,batch,plan,batch_ref)
    if batch.get('disease_source_protocol')=='A02.system_source_reuse.3':
        from science_modules.a02.system_normalization_historical import compute
        return compute(workflow,m,batch,plan,batch_ref)
    if batch.get('disease_source_protocol')=='A02.system_source_reuse.2':
        from science_modules.a02.system_normalization_collection import compute
        return compute(workflow,m,batch,plan,batch_ref)
    if batch.get('disease_source_protocol')=='A02.system_source_reuse.1':
        from science_modules.a02.system_normalization_reuse import compute
        return compute(workflow,m,batch,plan,batch_ref)
    from science_modules.a02.system_normalization import configuration,facts
    sid=m['study_id'];home=workflow.location(sid);rid=batch['initial_binding']['current'].get('A02')
    require(rid and m['current'].get('A02')==rid,'原始五库候选尚未提供或已替换，请重新明确批次')
    run=workflow.run(m,rid);review=workflow.latest_review(m,run['artifact_id'])
    require(not review or review['decision']=='approved','疾病原候选已有明确暂存或退回')
    a01=m['current']['A01'];original=batch['initial_binding']['run_files'][rid]
    inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],'analysis_plan_id':plan['plan_id'],
        'analysis_plan_file':deepcopy(batch['plan_file']),'analysis_parameter_hash':plan['plan']['parameter_hash'],
        'system_batch_file':deepcopy(batch_ref),'base_run':deepcopy(original['run_file']),
        'base_reviews':[deepcopy(r) for r in m.get('reviews',[]) if read_json(verified_file(home,r))['artifact_id']==run['artifact_id']],
        'base_result':deepcopy(original['result_file']),'mapping':deepcopy(batch['mapping']),
        'a01_result':deepcopy(m['runs'][a01]['result_file']),
        'intake_result':deepcopy(m['runs'][batch['request']['expected_a00']]['result_file'])}
    summary,tables,anomalies=facts(home,inputs)
    return inputs,configuration(),summary,tables,anomalies,[batch['plan_file'],inputs['base_run'],inputs['base_result'],
        inputs['a01_result'],inputs['intake_result'],inputs['mapping']['mapping_file'],*inputs['mapping']['identity_evidence_files'],
        *workflow.result(m,rid)['sources']]


def a02_validator(root,fallback):
    """系统A02额外核对真实授权及系统父回执；旧疾病规则完全委托。"""
    from science_modules.a02.system_normalization import validator,VERSION
    from science_modules.a02.system_normalization_reuse import validator as reuse_validator,VERSION as REUSE_VERSION
    from science_modules.a02.system_normalization_collection import validator as collection_validator,VERSION as COLLECTION_VERSION
    from science_modules.a02.system_normalization_historical import validator as historical_validator,VERSION as HISTORICAL_VERSION
    from science_modules.a02.system_normalization_identity import validator as identity_validator,VERSION as IDENTITY_VERSION
    science=identity_validator(root,historical_validator(root,collection_validator(root,reuse_validator(root,validator(root,fallback)))))
    def check(run,*args):
        if run['config'].get('version') in (VERSION,REUSE_VERSION,COLLECTION_VERSION,HISTORICAL_VERSION,IDENTITY_VERSION):
            from pathlib import Path
            from .analysis_plans import AnalysisPlanWorkflow
            from .system_execution import is_active
            w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);home=Path(root)/'studies'/run['study_id']
            candidate=deepcopy(m);candidate['current']['A02']=run['run_id']
            candidate['runs'][run['run_id']]={'run_file':file_record(home,home/'runs/A02'/run['run_id']/'run.json','run'),'result_file':None}
            require(is_active(w,candidate,run),'疾病系统授权或真实依赖已改变')
        return science(run,*args)
    return check


def a01(workflow,m,batch,plan):
    """使用原三库方案事实和规范配置，只将执行授权改为独立系统协议。"""
    from components import parse_herbs
    from mesh_identity import validate_mesh_identity
    from science_modules.a01.plan_flow import facts,configuration
    sid=m['study_id'];home=workflow.location(sid);intake=workflow.result(m,batch['request']['expected_a00'])['summary']
    require(intake.get('analysis_purpose') in ('workflow_test','formal_research'),'登记缺少明确用途')
    inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],'staging_file':deepcopy(batch['staging_file']),
        'herbs':parse_herbs(intake['herbs']),'analysis_purpose':intake['analysis_purpose'],
        'disease_identity':validate_mesh_identity(intake) if intake['analysis_purpose']=='formal_research' else None,
        'analysis_plan_id':plan['plan_id'],'analysis_plan_file':deepcopy(batch['plan_file']),
        'analysis_parameter_hash':plan['plan']['parameter_hash'],'mapping':deepcopy(batch['mapping'])}
    source=read_json(verified_file(home,inputs['staging_file']))
    if batch.get('component_source_protocol')=='A01.system_source_binding.1':
        from science_modules.a01 import system_source_binding as system_sources
        inputs['system_source_binding']=deepcopy(batch['staging_file'])
        if batch.get('identity_exception_file'):
            from science_modules.a01 import identity_exception
            inputs['identity_exception_file']=deepcopy(batch['identity_exception_file'])
            summary,tables,anomalies=identity_exception.facts(home,inputs);config=identity_exception.configuration(plan['plan'])
        else:summary,tables,anomalies=system_sources.facts(home,inputs);config=system_sources.configuration(plan['plan'])
    else:summary,tables,anomalies=facts(home,inputs);config=configuration(plan['plan'])
    sources=[batch['plan_file'],batch['staging_file'],inputs['mapping']['mapping_file'],*inputs['mapping']['identity_evidence_files']]
    if batch.get('identity_exception_file'):sources.append(batch['identity_exception_file'])
    for slot in source['datasets']:sources.extend([slot['source_record'],*slot['files']])
    return inputs,config,summary,tables,anomalies,sources


def a03(workflow,m,batch,plan,batch_ref,body):
    """显式批次授权派生阶段请求，沿用原交集事实及图，不伪造逐阶段人工点击。"""
    from science_modules.plan_stages import a03_facts,A03_VERSION
    from science_modules.plan_stages_contract import VERSION as STAGES_VERSION
    from intersection_flow import CONFIG,payload_from,venn_svg
    sid=m['study_id'];home=workflow.location(sid);a00=batch['request']['expected_a00']
    a01,a02=(m['current'][key] for key in ('A01','A02'));binding={'study_id':sid,'a00':a00,'plan_id':plan['plan_id'],
        'parameter_hash':plan['plan']['parameter_hash'],'current':deepcopy(m['current']),
        'authorization_kind':'delegated_system_batch','authorization_file':deepcopy(batch_ref)}
    request={'schema_version':STAGES_VERSION,'study_id':sid,'binding':binding,'request':{
        'stage':'A03','expected_a00':a00,'expected_plan_id':plan['plan_id'],'expected_input_hash':fingerprint(binding),
        'operator':batch['request']['author'],'reason':batch['request']['note'],'confirmed':True},
        'confirmation_basis':'原一次明确批次授权派生，不表示另一次人工点击','system_batch_file':deepcopy(batch_ref)}
    path=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'derived_requests'/(new_id('stage_request')+'.json')
    write_json(path,request);request_ref=file_record(home,path,'plan_stage_request');m.setdefault('analysis_plan_stage_requests',[]).append(request_ref)
    inputs={'study_id':sid,'bound_a00':a00,'analysis_plan_id':plan['plan_id'],'analysis_plan_file':deepcopy(batch['plan_file']),
        'analysis_parameter_hash':plan['plan']['parameter_hash'],'intake_result':deepcopy(m['runs'][a00]['result_file']),
        'a01_result':deepcopy(m['runs'][a01]['result_file']),'a02_result':deepcopy(m['runs'][a02]['result_file']),
        'execution_request_file':request_ref,'payload':payload_from(workflow.result(m,a01),workflow.result(m,a02))}
    _,summary,tables=a03_facts(home,inputs);intake=workflow.result(m,a00)['summary']
    return inputs,dict(CONFIG,version=A03_VERSION),summary,tables,[
        '交集及排序取同批标准化原结果；系统依赖校验不表示人工批准。'],[
        batch['plan_file'],request_ref,inputs['intake_result'],inputs['a01_result'],inputs['a02_result']],venn_svg(summary,intake['formula'],intake['disease'])
