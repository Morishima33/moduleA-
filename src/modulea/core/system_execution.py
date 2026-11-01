"""新系统执行协议：一次明确批次授权与真实规范依赖，独立于旧人工批准语义。"""
from copy import deepcopy
from contracts import SCHEMA_VERSION,ContractError,fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_validation as validation

VERSION='ModuleA.system_execution.1'
BATCHES='analysis_plan_system_batch_records'
EVENTS='analysis_plan_system_batch_events'
IMPLEMENTED=('A01','A02','A03','A03_SELECT','A04','A05','A06_PREP','A06')
DEPENDENCIES={'A01':{'A00'},'A02':{'A00','A01'},'A03':{'A01','A02'},'A03_SELECT':{'A03'},'A04':{'A03'},'A05':{'A03'},
    'A06_PREP':{'A03','A03_SELECT','A04'},'A06':{'A06_PREP'}}
SCIENTIFIC_VERSIONS={'A01':'A01.plan_publication.1','A02':'A02.system_normalization.1','A03':'A03.plan_intersection.1',
    'A03_SELECT':'A03.plan_selection.1','A04':'A04.plan_network.1','A05':'A05.plan_enrichment.1','A06_PREP':'A06.system_preparation.1',
    'A06':'A06.system_scoring.1'}
FIELDS={'request_id','expected_a00','expected_plan_id','expected_input_hash','author','note','confirmed'}


def scientific_version(module,config):
    """新资格修订仍属PREP，显式列出科学版本，不修改旧人工协议。"""
    if module=='A06_PREP' and config.get('version') in ('A06.system_preparation.2','A06.system_qualification.2'):
        return config.get('object_checkpoint_protocol')=='A06.system_preparation_checkpoints.1'
    if module=='A06' and config.get('version')=='A06.system_scoring.2':return True
    return config.get('version')==SCIENTIFIC_VERSIONS[module] or (module=='A01' and config.get('version')=='A01.system_publication.1'
        and config.get('source_binding_protocol')=='A01.system_source_binding.1') or (module=='A06_PREP' and config.get('version')=='A06.system_qualification.1') or (
        module=='A02' and (config.get('version'),config.get('source_binding_protocol')) in (
            ('A02.system_normalization.2','A02.system_source_reuse.1'),('A02.system_normalization.3','A02.system_source_reuse.2'),('A02.system_normalization.4','A02.system_source_reuse.3')))


def snapshot(workflow,m):
    """只读确认时的完整实际输入；报告自身最终决定不改变科学批次输入。"""
    value={'study_id':m['study_id'],'current':{key:rid for key,rid in m['current'].items() if key!='A07'},
        'run_files':{rid:deepcopy(m['runs'][rid]) for key,rid in m['current'].items() if key!='A07'},
        'plan_records':deepcopy(m.get('analysis_plan_records',[])),
        'staging_file':deepcopy(m.get('current_component_uploads')),'reviews':deepcopy(m.get('reviews',[])),'trashed':bool(m.get('trashed'))}
    if m.get('current_system_component_sources'):value['system_component_source_file']=deepcopy(m['current_system_component_sources'])
    return value


def source_for(workflow,m,plan_id):
    """新明确系统来源优先，旧上传协议保持；不自动跨方案借用来源。"""
    from . import system_component_sources as sources
    system=sources.current(workflow,m,plan_id=plan_id)
    return (system,sources.VERSION) if system else (deepcopy(m.get('current_component_uploads')),None)


def info(workflow,sid):
    """内部批次资格，不开放尚未接齐的网页一键全流程。"""
    m=workflow.load(sid);a00=m['current'].get('A00');home=workflow.location(sid);blockers=[]
    intake=workflow.result(m,a00)['summary'] if a00 else {}
    supported=bool(m.get('workflow_profile')=='A00.preupload.2' and intake.get('analysis_plan_profile')=='ModuleA.analysis_plan.1')
    plans=workflow._analysis_plan_records(m) if supported else [];draft=plans[-1] if plans and plans[-1]['expected_a00']==a00 else None
    if not supported:blockers.append('系统执行要求新版已核验疾病身份的登记')
    if m.get('trashed'):blockers.append('回收站研究只读')
    if not draft:blockers.append('当前登记没有可绑定方案')
    staging,protocol=source_for(workflow,m,draft['plan_id'] if draft else None)
    if not staging:blockers.append('请先补齐并明确绑定三库实际原件')
    else:
        value=read_json(verified_file(home,staging))
        if {row['database'] for row in value['datasets']}!={'TCMSP','HERB','BATMAN'} or len(value['datasets'])!=3:
            blockers.append('三库原件尚未完整暂存，不回退单库')
    return {'schema_version':VERSION,'supported':supported,'enabled':not blockers,'blockers':blockers,
        'expected_a00':a00,'expected_plan_id':draft['plan_id'] if draft else None,'expected_input_hash':fingerprint(snapshot(workflow,m)),
        'implemented_stages':list(IMPLEMENTED),'automatic_execution_available':False,
        'message_zh':'内部系统执行已接通三库、疾病标准化、交集、成分、PPI、富集、结构准备及专用资格/评分入口；完整一键入口仍未开放，不代签人工复核。'}


def read_batch(workflow,m,reference):
    """只接受本研究公开入口登记的不可变授权和真实绑定方案。"""
    require(reference in m.get(BATCHES,[]),'系统执行授权未登记到本研究')
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,reference))
    require(value.get('schema_version')==VERSION and value.get('study_id')==m['study_id']
        and value.get('human_review_written') is False and value['request']['confirmed'] is True
        and value['request_hash']==fingerprint(value['request']),'系统执行授权归属或明确确认无效')
    require(value.get('preparation_protocol') in (None,'A06.system_preparation.2'),'系统批次结构准备协议未知')
    safe_id(value['batch_id'],'systembatch');safe_id(value['request']['request_id'],'systembatchreq')
    require(value['plan_file'] in m.get('analysis_plan_records',[]),'批次方案未登记')
    plan=read_json(verified_file(home,value['plan_file']))
    require(plan['study_id']==m['study_id'] and plan['plan_id']==value['request']['expected_plan_id']
        and plan['expected_a00']==value['request']['expected_a00'],'批次方案、登记或研究不一致')
    from science_modules.analysis_protocol import checked_plan
    checked_plan(plan['plan'])
    require(value['initial_binding']['study_id']==m['study_id']
        and fingerprint(value['initial_binding'])==value['request']['expected_input_hash'],'系统执行原始输入指纹无效')
    if value.get('component_source_protocol'):
        from . import system_component_sources as sources
        require(value['component_source_protocol']==sources.VERSION
            and value['staging_file']==value['initial_binding'].get('system_component_source_file'),'系统批次新三库绑定不同')
        source=sources.read_record(workflow,m,value['staging_file'])
        require(source['plan_file']==value['plan_file'] and source['a00_run_id']==value['request']['expected_a00'],'系统批次来源不是原方案和登记')
    else:require(value['staging_file']==value['initial_binding']['staging_file'],'系统执行原始三库输入不同')
    for ref in (value['staging_file'],value['mapping']['mapping_file'],*value['mapping']['identity_evidence_files']):verified_file(home,ref)
    if value.get('disease_source_file') or value.get('disease_source_protocol'):
        from . import system_disease_sources
        system_disease_sources.read(workflow,m,value,check_reviews=False)
    return value,plan


def start(workflow,sid,body,*,preparation_protocol=None):
    """公开Workflow一次登记明确批次；不写人工reviews，不启动隐含科学计算。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'系统批次请求字段错误，不接受通过标记、参数或路径覆盖')
    require(preparation_protocol in (None,'A06.system_preparation.2'),'尚未接通该准备恢复协议')
    safe_id(body['request_id'],'systembatchreq');safe_id(body['expected_a00'],'run');safe_id(body['expected_plan_id'],'plan')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
        '请填写执行人、依据并明确确认本批次')
    with write_lock(workflow.root):
        m=workflow.load(sid);home=workflow.location(sid)
        for ref in m.get(BATCHES,[]):
            previous,_=read_batch(workflow,m,ref)
            if previous['request']['request_id']==body['request_id']:
                require(previous['request']==body,'批次请求号已用于其他内容');return dict(previous,file=deepcopy(ref),created=False)
        value=info(workflow,sid);require(value['enabled'],'系统批次条件未齐：'+'；'.join(value['blockers']))
        require(all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'批次输入或方案已改变，请刷新')
        plan_ref=next(ref for ref in m['analysis_plan_records'] if read_json(verified_file(home,ref))['plan_id']==body['expected_plan_id'])
        from science_modules.a01.uploads import mapping_binding
        record={'schema_version':VERSION,'study_id':sid,'batch_id':new_id('systembatch'),'request':deepcopy(body),
            'request_hash':fingerprint(body),'initial_binding':snapshot(workflow,m),'plan_file':deepcopy(plan_ref),
            'staging_file':source_for(workflow,m,body['expected_plan_id'])[0],'mapping':mapping_binding(workflow,m),
            'human_review_written':False,'created_at':now()}
        protocol=source_for(workflow,m,body['expected_plan_id'])[1]
        if preparation_protocol:record['preparation_protocol']=preparation_protocol
        if protocol:record['component_source_protocol']=protocol
        a02=m['current'].get('A02')
        from . import system_disease_sources
        if a02 and workflow.run(m,a02)['config'].get('version') in (system_disease_sources.NORMALIZED|{system_disease_sources.COLLECTION_VERSION,system_disease_sources.HISTORICAL_COLLECTION}):
            record['disease_source_protocol']=system_disease_sources.resolve(workflow,m,record['initial_binding'])['schema_version']
            record['disease_source_file']=system_disease_sources.create(workflow,m,record['batch_id'],record['initial_binding'])
            if record['disease_source_protocol']==system_disease_sources.HISTORICAL_REUSE:
                base=workflow.run(m,system_disease_sources.resolve(workflow,m,record['initial_binding'])['base_run_id'])
                require(base['inputs']['analysis_plan_file']==record['plan_file'],'历史版本例外不适用于新方案，请重新明确决定')
        target=home/'decisions/analysis_plans/system_batches'/record['batch_id']/'batch.json';write_json(target,record)
        ref=file_record(home,target,'system_batch_authorization');m.setdefault(BATCHES,[]).append(ref);workflow.save(m)
        return dict(record,file=ref,created=True)


def require_batch(workflow,m,ref):
    """绑定原方案、当前登记和同一原件；后来新草稿不替换正在执行的旧批。"""
    batch,plan=read_batch(workflow,m,ref)
    require(not m.get('trashed') and m['current'].get('A00')==batch['request']['expected_a00'],'批次登记已改变或研究只读')
    if batch.get('component_source_protocol'):
        require(m.get('current_system_component_sources')==batch['staging_file'],'批次系统三库原件已替换，请明确启动新批次')
    else:require(m.get('current_component_uploads')==batch['staging_file'],'批次三库原件已替换，请明确启动新批次')
    return batch,plan


def parent_records(workflow,m,parents):
    """同一次只读依赖核验复用已核验内容；操作结束清除，发布前另建新作用域。"""
    if getattr(workflow,'_view_cache',None) is None and hasattr(workflow,'handoff_read_cache'):
        with workflow.handoff_read_cache():return _parent_records(workflow,m,parents)
    return _parent_records(workflow,m,parents)


def _parent_records(workflow,m,parents):
    """真实规范回执及原科学状态逐件核验，明确人工暂存或退回仍否决交接。"""
    home=workflow.location(m['study_id']);records={}
    for module,rid in parents.items():
        require(m['current'].get(module)==rid and workflow.active(m,rid),'系统交接上游已改变：'+module)
        run=workflow.run(m,rid);review=workflow.latest_review(m,run['artifact_id'])
        require(not review or review['decision']=='approved','系统交接来源已被明确暂存或退回：'+module)
        expected=validation.request(workflow,m['study_id'],rid)
        matching=[]
        # 当前交接只展开所需父运行的最新精确回执；历史仍逐件验SHA，完整追溯另核全部内容。
        for ref in reversed(m.get(validation.INDEX,[])):
            value=read_json(verified_file(home,ref))
            if value.get('run_id')==rid and value.get('input_hash')==expected['expected_input_hash']:
                matching=[(ref,validation.read_receipt(workflow,m,ref))];break
        require(matching and matching[-1][1]['passed'] and matching[-1][1]['scientific_status']['ready_for_successor'],
            '系统交接仍缺少真实可交接规范回执：'+module)
        records[module]=deepcopy(matching[-1][0]);verified_file(home,records[module])
    return records


def is_active(workflow,m,run):
    """仅本显式协议按真实系统证据判定有效，不改变旧批准函数的含义。"""
    try:
        require(run.get('execution_protocol')==VERSION and run['module_id'] in IMPLEMENTED
            and m['current'].get(run['module_id'])==run['run_id'],'系统执行运行或协议无效')
        require(set(run['parent_runs'])==DEPENDENCIES[run['module_id']]
            and scientific_version(run['module_id'],run['config']), '系统执行科学版本或完整依赖错误')
        bound_batch,_=require_batch(workflow,m,run['batch_file'])
        if run['config'].get('version') in ('A06.system_preparation.2','A06.system_qualification.2','A06.system_scoring.2'):
            require(bound_batch.get('preparation_protocol')=='A06.system_preparation.2','新恢复版本缺少原批明确协议')
        if run['module_id']=='A02':
            base=read_json(verified_file(workflow.location(m['study_id']),run['inputs']['base_run']))
            review=workflow.latest_review(m,base['artifact_id'])
            require(not review or review['decision']=='approved','疾病原候选已被明确暂存或退回')
            if run['config'].get('version') in ('A02.system_normalization.2','A02.system_normalization.3','A02.system_normalization.4'):
                from . import system_disease_sources
                batch,_=read_batch(workflow,m,run['batch_file']);source=system_disease_sources.read(workflow,m,batch)
                require(run['inputs']['disease_source_binding']==batch['disease_source_file']
                    and run['inputs']['base_run']==source['base_run'],'疾病新批原件复用绑定不同')
        if run['module_id']=='A06_PREP':
            from . import system_decisions
            fixed=system_decisions.read_record(workflow,m,run['inputs']['system_input_ref'])
            require(fixed['stage']=='A06_INPUT' and fixed['binding']['batch_file']==run['batch_file']
                and system_decisions.active(workflow,m,fixed),'结构准备的系统固定范围已失效')
            if run['config'].get('version') in ('A06.system_qualification.1','A06.system_qualification.2'):
                request=read_json(verified_file(workflow.location(m['study_id']),run['inputs']['qualification_request']))
                source=read_json(verified_file(workflow.location(m['study_id']),run['inputs']['source_preparation_run']))
                review=workflow.latest_review(m,source['artifact_id'])
                require(not review or review['decision']=='approved','资格来源准备已有明确暂存或退回')
                require(request['binding']['source_run']==run['inputs']['source_preparation_run'],'系统资格来源运行不同')
        require(run['execution_authority']=='system_validation' and run['parent_review_ids']=={}
            and bound_parent_records(workflow,m,run),'系统执行依赖与真实回执不一致')
        require(run['config_hash']==fingerprint(run['config'])
            and run['input_hash']==fingerprint({'inputs':run['inputs'],'parents':run['parent_artifact_ids']}),'系统执行运行指纹无效')
        require(run['parent_artifact_ids']==[workflow.run(m,run['parent_runs'][key])['artifact_id'] for key in sorted(run['parent_runs'])],
            '系统执行父产物身份不一致')
        return True
    except ContractError:return False


def bound_parent_records(workflow,m,run):
    """新评分保留实际采用回执；同输入再次通过不废弃原评分，最新失败仍否决。"""
    latest=parent_records(workflow,m,run['parent_runs']);bound=run['parent_validation_records']
    if run['config'].get('version') not in ('A06.system_scoring.1','A06.system_scoring.2'):return bound==latest
    require(set(bound)==set(latest),'系统评分原依赖回执不完整')
    for module,reference in bound.items():
        require(reference in m.get(validation.INDEX,[]),'系统评分原采用回执未登记')
        old=validation.read_receipt(workflow,m,reference);current=validation.read_receipt(workflow,m,latest[module])
        require(old['passed'] and old['scientific_status']['ready_for_successor']
            and old['run_id']==run['parent_runs'][module]==current['run_id'] and old['input_hash']==current['input_hash'],
            '系统评分原回执与当前实际输入、结果或人工决定不同')
    return True


def ensure_parents(workflow,sid,parents):
    """后台实际执行规范核查，绝不把缺少人工记录伪装成批准。"""
    for module,rid in parents.items():
        m=workflow.load(sid);review=workflow.latest_review(m,workflow.run(m,rid)['artifact_id'])
        require(not review or review['decision']=='approved','来源已有明确暂存或退回：'+module)
        try:parent_records(workflow,m,{module:rid})
        except ContractError:
            expected=validation.request(workflow,sid,rid)
            value=workflow.validate_analysis_plan_scientific_run(sid,{key:expected[key] for key in ('expected_run_id','expected_input_hash')}|
                {'request_id':'syscheckreq_'+new_id('attempt').split('_',1)[1]})
            require(value['passed'] and value['scientific_status']['ready_for_successor'],'实际规范核查未能放行：'+module)


def begin(workflow,m,module,inputs,config,reason,batch_ref,parents):
    """只供内部真实科学适配调用，运行明确记录系统授权而不是人工父签名。"""
    require(module in IMPLEMENTED and module in workflow.validators,'系统执行尚未接入该模块')
    require(set(parents)==DEPENDENCIES[module] and scientific_version(module,config),'系统执行依赖或科学版本错误')
    batch,plan=require_batch(workflow,m,batch_ref)
    require(inputs['analysis_plan_file']==batch['plan_file'] and inputs['analysis_plan_id']==plan['plan_id']
        and inputs['analysis_parameter_hash']==plan['plan']['parameter_hash'],'系统执行输入与批次绑定方案不一致')
    records=parent_records(workflow,m,parents);artifacts=[workflow.run(m,parents[key])['artifact_id'] for key in sorted(parents)]
    rid=new_id('run');run={'schema_version':SCHEMA_VERSION,'study_id':m['study_id'],'run_id':rid,'module_id':module,
        'artifact_id':new_id('artifact'),'parent_runs':deepcopy(parents),'parent_artifact_ids':artifacts,'parent_review_ids':{},
        'parent_validation_records':records,'execution_authority':'system_validation','execution_protocol':VERSION,
        'batch_file':deepcopy(batch_ref),'inputs':deepcopy(inputs),'config':deepcopy(config),'reason':reason,
        'input_hash':fingerprint({'inputs':inputs,'parents':artifacts}),'config_hash':fingerprint(config),
        'code_version':workflow.code_version,'environment_version':fingerprint(workflow.environment),
        'environment':deepcopy(workflow.environment),'created_at':now()}
    path=workflow.location(m['study_id'])/'runs'/module/rid/'run.json';write_json(path,run)
    m['runs'][rid]={'run_file':file_record(workflow.location(m['study_id']),path,'run'),'result_file':None};m['current'][module]=rid
    return run


def _execute(workflow,sid,body,*,tools=None,progress=None):
    """内部逐阶段真实执行；全自动调度未开放，拒绝未接入阶段和客户端科学覆盖。"""
    require(isinstance(body,dict) and set(body)=={'batch_id','stage','expected_current_run_id'},'系统阶段请求字段错误')
    safe_id(body['batch_id'],'systembatch');require(body['stage'] in IMPLEMENTED,'系统执行尚未接通该阶段')
    require(body['stage']!='A06','系统评分须使用绑定实际资格准备的专用评分入口')
    if body['expected_current_run_id'] is not None:safe_id(body['expected_current_run_id'],'run')
    m=workflow.load(sid);home=workflow.location(sid)
    ref=next((ref for ref in m.get(BATCHES,[]) if read_batch(workflow,m,ref)[0]['batch_id']==body['batch_id']),None)
    require(ref,'找不到本研究登记的系统批次');batch,plan=require_batch(workflow,m,ref);module=body['stage']
    for event_ref in m.get(EVENTS,[]):
        event=read_json(verified_file(home,event_ref))
        require(event.get('schema_version')==VERSION and event.get('study_id')==sid and event.get('human_review_written') is False,
            '系统批次阶段回执归属无效')
        if event['batch_id']==body['batch_id'] and event['stage']==module and event['state']=='completed':
            run=workflow.run(m,event['run_id']);require(workflow.active(m,run['run_id']),'本批历史阶段已失效，不能静默重跑')
            require(event['result_file']==m['runs'][event['run_id']]['result_file'] and run['batch_file']==ref,
                '系统阶段回执与实际结果不一致')
            require(event['request']==body,'本批阶段已经执行，请查看当前结果');return workflow.result(m,run['run_id'])
    require(m['current'].get(module)==body['expected_current_run_id'],'当前阶段已改变，请刷新')
    parents={key:m['current'].get(key) for key in DEPENDENCIES[module]}
    require(all(parents.values()),'系统阶段上游尚未生成');ensure_parents(workflow,sid,parents)
    parent_snapshot=parent_records(workflow,workflow.load(sid),parents)
    if module in ('A03_SELECT','A04','A05'):
        require(workflow.result(m,parents['A03'])['summary']['交集靶点数']>0,'本批交集为空，该分支不适用，不启动科学任务')
    if module=='A05':require(plan['plan']['parameters']['a05.include_go'] or plan['plan']['parameters']['a05.include_kegg'],
        '本批未纳入GO或KEGG，富集不适用，不启动R')
    computed=None
    if module=='A01':
        # 原件均由不可变记录绑定；科学复算期间释放锁，允许追加新草稿。
        from .system_execution_science import a01
        computed=a01(workflow,m,batch,plan)
    elif module=='A02':
        from .system_execution_science import a02
        computed=a02(workflow,m,batch,plan,ref)
    elif module in ('A04','A05'):
        from . import system_execution_science as science
        computed=getattr(science,module.lower())(workflow,m,batch,plan,ref)
    elif module=='A06_PREP':
        require(tools is not None,'系统准备尚未配置固定结构工具，不启动来源或计算')
        if batch.get('preparation_protocol')=='A06.system_preparation.2':
            from science_modules.a06.system_preparation_incremental import compute
        else:
            from science_modules.a06.system_preparation import compute
        computed=compute(workflow,m,batch,plan,ref,tools,progress or (lambda _:None))
    with write_lock(workflow.root):
        m=workflow.load(sid);batch,plan=require_batch(workflow,m,ref)
        require(m['current'].get(module)==body['expected_current_run_id'],'计算前当前阶段已改变')
        require(all(m['current'].get(key)==rid for key,rid in parents.items()),'系统阶段上游已改变')
        require(parent_records(workflow,m,parents)==parent_snapshot,'科学计算期间上游系统回执或人工决定已改变')
        if module=='A06_PREP':
            from . import system_decisions
            fixed=system_decisions.read_record(workflow,m,computed[0]['system_input_ref'])
            require(system_decisions.active(workflow,m,fixed),'科学计算期间系统固定准备范围已改变')
        if module=='A02':
            base=read_json(verified_file(home,computed[0]['base_run']))
            reviews=[r for r in m.get('reviews',[]) if read_json(verified_file(home,r))['artifact_id']==base['artifact_id']]
            require(reviews==computed[0]['base_reviews'],'疾病标准化期间原候选人工决定已改变')
            if computed[1]['version'] in ('A02.system_normalization.2','A02.system_normalization.3','A02.system_normalization.4'):
                source=read_json(verified_file(home,computed[0]['source_current_run']))
                reviews=[r for r in m.get('reviews',[]) if read_json(verified_file(home,r))['artifact_id']==source['artifact_id']]
                require(reviews==computed[0]['source_current_reviews'],'疾病原件复用期间原标准化人工决定已改变')
        attachments=[]
        if module in ('A01','A02'):
            inputs,config,summary,tables,anomalies,sources=computed
            outcome='empty' if module=='A02' and not summary['标准化基因数'] else 'success';figure=None
        elif module=='A03':
            from .system_execution_science import a03
            inputs,config,summary,tables,anomalies,sources,figure=a03(workflow,m,batch,plan,ref,body)
            outcome='success' if summary['交集靶点数'] else 'empty'
        elif module=='A03_SELECT':
            from .system_execution_science import compounds
            inputs,config,summary,tables,anomalies,sources=compounds(workflow,m,batch,plan,ref)
            outcome='success' if tables['selected'] else 'empty';figure=None
        else:
            inputs,config,summary,tables,anomalies,sources,extra=computed;figure=None
            outcome=extra['outcome']
        run=begin(workflow,m,module,inputs,config,batch['request']['note'],ref,parents)
        figures=[]
        if figure is not None:
            path=home/'runs'/module/run['run_id']/'venn.svg';path.write_text(figure,encoding='utf8');figures=[file_record(home,path,'figure')]
        if module=='A05':
            from science_modules.a05.plan_figures import draw
            folder=home/'runs'/module/run['run_id'];figures=[file_record(home,path,'figure') for path in draw(tables,plan['plan'],folder).values()]
            path=folder/'R_log.txt';path.write_text(extra['log'],encoding='utf8');attachments.append(file_record(home,path,'log'))
        # 科学一致性必须取真实生产验证器，不信任调用者传入的lambda或客户端标记。
        canonical=validation.canonical_validator(workflow.root,module);require(callable(canonical),'实际规范验证器未接通')
        canonical(run,summary,tables,anomalies,outcome)
        result=workflow._finish(m,run['run_id'],summary,tables,anomalies,outcome,
            sources=[ref,*run['parent_validation_records'].values(),*sources],figures=figures,attachments=attachments)
        event={'schema_version':VERSION,'study_id':sid,'batch_id':batch['batch_id'],'stage':module,'state':'completed',
            'batch_file':deepcopy(ref),
            'request':deepcopy(body),'run_id':run['run_id'],'result_file':deepcopy(m['runs'][run['run_id']]['result_file']),
            'human_review_written':False,'created_at':now()}
        path=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'events'/(new_id('batchevent')+'.json');write_json(path,event)
        m.setdefault(EVENTS,[]).append(file_record(home,path,'system_batch_event'));workflow.save(m)
    return result


def execute(workflow,sid,body,*,tools=None,progress=None):
    """失败保留真实批次请求、异常和未发布文件，不挂伪结果或写人工批准。"""
    try:return _execute(workflow,sid,body,tools=tools,progress=progress)
    except Exception as error:
        if isinstance(body,dict) and set(body)=={'batch_id','stage','expected_current_run_id'} and body.get('stage') in IMPLEMENTED:
            with write_lock(workflow.root):
                m=workflow.load(sid);home=workflow.location(sid)
                ref=next((ref for ref in m.get(BATCHES,[]) if read_batch(workflow,m,ref)[0]['batch_id']==body.get('batch_id')),None)
                if ref and not m.get('trashed'):
                    batch,_=read_batch(workflow,m,ref);folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id'];files=[]
                    for path in folder.rglob('*'):
                        if path.is_file() and 'failures' not in path.relative_to(folder).parts:
                            files.append(file_record(home,path,'system_execution_diagnostic'))
                    # 领域规范失败前可能已创建不可变run文件；保留诊断但不伪装成已发布运行。
                    run_folder=home/'runs'/body['stage']
                    if run_folder.exists():
                        for path in run_folder.glob('*/run.json'):
                            value=read_json(path)
                            if value.get('batch_file')==ref and value['run_id'] not in m['runs']:
                                files.append(file_record(home,path,'unpublished_system_run'))
                    failure={'schema_version':VERSION,'study_id':sid,'batch_id':batch['batch_id'],'batch_file':deepcopy(ref),
                        'stage':body['stage'],'state':'failed','request':deepcopy(body),'run_id':None,
                        'error_type':type(error).__name__,'error_zh':str(error),'files':files,'human_review_written':False,'created_at':now()}
                    path=folder/'failures'/(new_id('batchevent')+'.json');write_json(path,failure)
                    m.setdefault(EVENTS,[]).append(file_record(home,path,'system_batch_event'));workflow.save(m)
        raise
