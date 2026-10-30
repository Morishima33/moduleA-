"""一次明确系统批次的顺序编排与逐阶段续做；不计算科学结果、不制造人工批准。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution as execution,system_decisions,plan_reports

VERSION='ModuleA.system_pipeline.1'
INDEX='analysis_plan_system_pipeline_records'
STAGES=('A01','A02','A03','A03_SELECT','A04','A05','A04_SELECTION','A06_INPUT','A06_PREP','A06_QUALIFY','A06','A07')


def batch_for(workflow,m,batch_id):
    """只接受本研究已明确授权的实际批次，绑定原方案而非最新草稿。"""
    safe_id(batch_id,'systembatch')
    ref=next((r for r in m.get(execution.BATCHES,[]) if execution.read_batch(workflow,m,r)[0]['batch_id']==batch_id),None)
    require(ref,'本研究不存在已明确授权的系统批次')
    batch,plan=execution.require_batch(workflow,m,ref)
    return ref,batch,plan


def required_inputs(workflow,m,batch=None):
    """必需原件只读预检；不联网获取，不把缺失、失败或未检索记为零条。"""
    home=workflow.location(m['study_id']);initial=batch['initial_binding'] if batch else m
    from . import system_disease_sources
    binding=system_disease_sources.read(workflow,m,batch) if batch and batch.get('disease_source_file') else system_disease_sources.resolve(workflow,m,initial)
    rid=binding['base_run_id']
    run=workflow.run(m,rid);result=workflow.result(m,rid)
    for source_id in (rid,initial['current']['A00']):
        review=workflow.latest_review(m,workflow.run(m,source_id)['artifact_id'])
        require(not review or review['decision']=='approved','必需来源已有明确人工暂存或退回')
    require(run['config'].get('version')=='A02.collect.2' and result is not None
        and result['summary'].get('source_profile')=='A02.source_profile.3','统一编排要求本研究现代五库原始候选，不接受旧标准化结果替代')
    require(run['parent_runs']=={'A00':initial['current']['A00']},'五库候选与本批登记不同')
    manifests=[r for r in result['sources'] if r['role']=='source_manifest'];require(len(manifests)==1,'五库原件清单不唯一')
    sources=read_json(verified_file(home,manifests[0]));rows=sources['datasets']
    require(len(rows)==5 and {r['database'] for r in rows}=={'GeneCards','OMIM','TTD','PharmGKB','OTP'},'五库原件缺失，不启动统一科学处理')
    for row in rows:
        require(isinstance(row.get('version'),str) and row['version'].strip().casefold() not in ('','unknown','未知','未注明'),
            '五库来源版本待核，不启动统一处理')
        verified_file(home,row['source_record'])
    return True


def read_record(workflow,m,reference):
    """读取真实流水记录及文件，历史终态不直接当当前成功。"""
    require(reference in m.get(INDEX,[]),'系统编排记录未登记')
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,reference))
    require(value['schema_version']==VERSION and value['study_id']==m['study_id'] and value['human_review_written'] is False
        and value['batch_file'] in m.get(execution.BATCHES,[]) and value['event'] in ('started','stage','finished','failed'),
        '系统编排记录归属或协议无效')
    batch=execution.read_batch(workflow,m,value['batch_file'])[0]
    require(batch['batch_id']==value['batch_id'],'系统编排记录混用了其他批次')
    verified_file(home,value['implementation_file'])
    if value['event']=='stage':
        require(value['stage'] in STAGES and value['state'] in ('completed','not_applicable'),'系统阶段状态无效')
        if value['state']=='not_applicable':require(value['reason_zh'] and value['run_id'] is None,'不适用不能伪造运行')
        elif value['run_id']:
            require(m['runs'][value['run_id']]==value['run_files'],'系统编排阶段原件已改变')
            for ref in value['run_files'].values():verified_file(home,ref)
        else:
            selected=system_decisions.read_record(workflow,m,value['decision_file'])
            require(selected['stage']==value['stage'] and selected['batch_id']==value['batch_id'],'系统编排名单来源不同')
    if value['event']=='finished':
        require(value['state']=='awaiting_report_review' and value['report_run_id'] in m['runs']
            and workflow.run(m,value['report_run_id'])['config'].get('version')=='A07.plan_report.1',
            '系统编排完成不能冒充科研结论批准')
    if value['event']=='failed':require(value['error_type'] and value['error_zh'],'系统编排失败缺少实际原因')
    return value


def info(workflow,sid):
    """标准库只读状态；GET不执行阶段、复验科学或自动恢复任务。"""
    m=workflow.load(sid);items=[]
    for ref in m.get(execution.BATCHES,[]):
        batch,plan=execution.read_batch(workflow,m,ref)
        history=[dict(read_record(workflow,m,r),file=deepcopy(r)) for r in m.get(INDEX,[])
            if read_json(verified_file(workflow.location(sid),r))['batch_file']==ref]
        items.append({'batch_id':batch['batch_id'],'plan_id':plan['plan_id'],'batch_file':deepcopy(ref),'history':history,
            'expected_input_hash':state_hash(workflow,m,ref),
            'latest_event':history[-1] if history else None})
    return {'schema_version':VERSION,'batches':items,'automatic_execution_available':False,
        'message_zh':'内部统一编排已接通；尚未开放网页按钮，失败或中断只在明确续做时恢复，科研结论仍须复核。'}


def state_hash(workflow,m,ref):
    """排队请求固定实际已保存的科学状态，后来草稿与运行时任务状态不替换原批参数。"""
    value={'study_id':m['study_id'],'batch_file':ref,'current':m['current'],
        'runs':{rid:m['runs'][rid] for rid in m['current'].values()},'reviews':m.get('reviews',[]),
        'staging_file':m.get('current_component_uploads'),'system_validations':m.get(execution.validation.INDEX,[]),
        'system_decisions':m.get(system_decisions.INDEX,[]),'trashed':bool(m.get('trashed'))}
    if m.get('current_system_component_sources'):value['system_component_source_file']=m['current_system_component_sources']
    return fingerprint(value)


def validate_request(workflow,sid,body):
    """HTTP和后台排队前后共用校验，不接受客户端参数、路径和通过结论。"""
    require(isinstance(body,dict) and set(body)=={'batch_id','expected_input_hash'},'统一后台请求只接受批次与当前输入指纹')
    m=workflow.load(sid);ref,batch,plan=batch_for(workflow,m,body['batch_id'])
    required_inputs(workflow,m,batch)
    require(body['expected_input_hash']==state_hash(workflow,m,ref),'统一编排输入已改变，请刷新后明确续做')
    return batch


def append(workflow,sid,context,event,**fields):
    """每步追加不可变真实记录；短锁仅写元数据，计算始终在锁外。"""
    with write_lock(workflow.root):
        m=workflow.load(sid);home=workflow.location(sid)
        value={'schema_version':VERSION,'study_id':sid,**deepcopy(context),'event':event,'created_at':now(),
            'human_review_written':False,**deepcopy(fields)}
        folder=home/'decisions/analysis_plans/system_batches'/context['batch_id']/'pipeline'/context['attempt_id']
        path=folder/(new_id('pipelineevent')+'.json');write_json(path,value)
        ref=file_record(home,path,'system_pipeline_record');m.setdefault(INDEX,[]).append(ref);workflow.save(m)
    return value


def usable(workflow,m,rid):
    """实际当前依赖与人工否决均检查；未批准不等于伪造批准。"""
    require(rid and workflow.active(m,rid),'本批已完成运行失效，须核对原因，不能静默重跑')
    run=workflow.run(m,rid);review=workflow.latest_review(m,run['artifact_id'])
    require(not review or review['decision']=='approved','本批结果已有明确人工暂存或退回')
    require(m['runs'][rid]['result_file'],'本批阶段尚无完整归档结果')
    return workflow.result(m,rid)


def execute(workflow,sid,body,*,tools=None,progress=None):
    """内部逐阶段真实接续；来源须已齐，空交集/未纳入富集不调用相应科学函数。"""
    require(isinstance(body,dict) and set(body)=={'batch_id'},'系统编排只接受已授权批次，不接受参数或批准覆盖')
    m=workflow.load(sid);ref,batch,plan=batch_for(workflow,m,body['batch_id']);home=workflow.location(sid)
    required_inputs(workflow,m,batch)
    attempt=new_id('pipelineattempt');folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'pipeline'/attempt
    source=folder/'implementation.py';source.parent.mkdir(parents=True,exist_ok=False);source.write_bytes(Path(__file__).read_bytes())
    context={'attempt_id':attempt,'batch_id':batch['batch_id'],'batch_file':ref,'implementation_file':file_record(home,source,'system_pipeline_implementation')}
    append(workflow,sid,context,'started');notify=progress or (lambda message:None);current_stage=None
    def record(stage,result=None,*,reason=None,decision=None):
        nonlocal current_stage
        current_stage=stage;latest=workflow.load(sid)
        return append(workflow,sid,context,'stage',stage=stage,state='not_applicable' if reason else 'completed',reason_zh=reason or '本批真实归档完成',
            run_id=result['run_id'] if result else None,run_files=deepcopy(latest['runs'][result['run_id']]) if result else None,
            decision_file=decision)
    def stage(module):
        nonlocal current_stage
        current_stage=module;notify('核对并接续本批 '+module);latest=workflow.load(sid);execution.require_batch(workflow,latest,ref)
        events=[read_json(verified_file(home,r)) for r in latest.get(execution.EVENTS,[])]
        completed=[v for v in events if v['batch_id']==batch['batch_id'] and v['stage']==module and v['state']=='completed']
        if completed:
            event=completed[-1];rid=event['run_id']
            if module=='A06_PREP' and latest['current'].get(module)!=rid:
                candidate=workflow.run(latest,latest['current'][module])
                require(candidate['config'].get('version')=='A06.system_qualification.1'
                    and candidate['inputs']['source_preparation_run']==latest['runs'][rid]['run_file'],
                    '本批准备已由其他来源替换')
                usable(workflow,latest,candidate['run_id']);result=workflow.result(latest,rid)
            else:result=usable(workflow,latest,rid)
        else:
            require(latest['current'].get(module)==batch['initial_binding']['current'].get(module),
                '该阶段已由本批外的新运行替换，不自动覆盖：'+module)
            result=workflow.execute_analysis_plan_system_stage(sid,{'batch_id':batch['batch_id'],'stage':module,
                'expected_current_run_id':latest['current'].get(module)},tools=tools,progress=notify)
            usable(workflow,workflow.load(sid),result['run_id'])
        record(module,result);return result
    try:
        for module in ('A01','A02','A03'):last=stage(module)
        if not last['summary']['交集靶点数']:
            for module in STAGES[3:-1]:record(module,reason='本批真实交集为空，该分支不适用，未执行计算')
        else:
            for module in ('A03_SELECT','A04'):stage(module)
            if plan['plan']['parameters']['a05.include_go'] or plan['plan']['parameters']['a05.include_kegg']:stage('A05')
            else:record('A05',reason='本批原方案未纳入GO或KEGG，不运行R')
            for module in ('A04_SELECTION','A06_INPUT'):
                current_stage=module;notify('核对本批 '+module);latest=workflow.load(sid)
                decision_ref,value=system_decisions.current(workflow,latest,batch['batch_id'],module)
                if value:require(system_decisions.active(workflow,latest,value),'本批系统名单已失效，不能静默替换')
                else:
                    value=workflow.execute_analysis_plan_system_decision(sid,{'batch_id':batch['batch_id'],'stage':module,'expected_decision_id':None})
                    decision_ref=value['file']
                record(module,decision=decision_ref)
            original=stage('A06_PREP');current_stage='A06_QUALIFY';notify('复核本批准备资格')
            qualified=workflow.qualify_analysis_plan_system_preparation(sid,{'batch_id':batch['batch_id'],'expected_preparation_run_id':original['run_id']})
            usable(workflow,workflow.load(sid),qualified['run_id']);record('A06_QUALIFY',qualified)
            if qualified['summary']['ready_pairs']:
                current_stage='A06';notify('执行或恢复本批实际评分');latest=workflow.load(sid);score=latest['current'].get('A06')
                if score and workflow.run(latest,score)['config'].get('version')=='A06.system_scoring.1':
                    run=workflow.run(latest,score);request=read_json(verified_file(home,run['inputs']['scoring_request']))['request']
                    require(run['batch_file']==ref,'当前评分属于其他系统批次')
                else:request={'batch_id':batch['batch_id'],'expected_preparation_run_id':qualified['run_id'],'expected_scoring_run_id':score}
                scored=workflow.score_analysis_plan_system_preparation(sid,request,tools=tools,progress=notify)
                usable(workflow,workflow.load(sid),scored['run_id']);record('A06',scored)
            else:record('A06',reason='本批实际资格后全部组合NA，评分不适用，未启动Vina')
        current_stage='A07';notify('核验本批全部适用分支及报告');latest=workflow.load(sid)
        # 按依赖顺序确保真实规范证据；已有精确有效回执直接复用，避免重复验证引起无谓失效。
        modules=['A00','A01','A02','A03']
        if last['summary']['交集靶点数']:
            modules+=['A03_SELECT','A04','A06_PREP']
            if plan['plan']['parameters']['a05.include_go'] or plan['plan']['parameters']['a05.include_kegg']:modules+=['A05']
            if qualified['summary']['ready_pairs']:modules+=['A06']
        for module in modules:execution.ensure_parents(workflow,sid,{module:workflow.load(sid)['current'][module]})
        value=plan_reports.info(workflow,sid);require(value['enabled'],'本批报告仍有阻塞：'+'；'.join(value['blockers']))
        existing=next((x for x in reversed(value['history']) if x['active']),None)
        if existing:report=workflow.result(workflow.load(sid),existing['run_id'])
        else:
            report=workflow.publish_analysis_plan_report(sid,{key:value[key] for key in ('expected_report_run_id','expected_input_hash')}|
                {'request_id':'planreportreq_'+new_id('attempt').split('_',1)[1], 'author':batch['request']['author'],
                 'note':batch['request']['note']+'；报告请求来自原一次明确批次授权，不表示新的人工签署','confirmed':True})
        record('A07',report)
        return append(workflow,sid,context,'finished',state='awaiting_report_review',report_run_id=report['run_id'],
            message_zh='本批适用分支和双报告已实际归档；不适用与NA保留，结论等待独立复核')
    except Exception as error:
        append(workflow,sid,context,'failed',stage=current_stage,state='failed',error_type=type(error).__name__,error_zh=str(error))
        raise
