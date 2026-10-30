"""新方案明确获取三库原件；实际A00系统证据授权，原科学发布和人工复核保持。"""
from copy import deepcopy
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution

VERSION='A01.system_acquisition.1'
REQUESTS='analysis_plan_system_acquisition_requests'
RECORDS='analysis_plan_system_acquisition_records'
FAILURES='analysis_plan_system_acquisition_failures'
SOURCES='analysis_plan_system_acquisition_source_records'
FIELDS={'request_id','expected_a00','expected_plan_id','expected_input_hash','author','note','confirmed'}


def snapshot(workflow,m):
    """只固定本次来源获取相关状态，后加草稿不替换已确认计划。"""
    rid=m['current'].get('A00');run=workflow.run(m,rid) if rid else None
    return {'study_id':m['study_id'],'a00':rid,'a01':m['current'].get('A01',''),
        'a00_files':deepcopy(m['runs'][rid]) if rid else None,'staging_file':deepcopy(m.get('current_component_uploads')),
        'a00_reviews':[deepcopy(r) for r in m.get('reviews',[]) if read_json(verified_file(workflow.location(m['study_id']),r))['artifact_id']==run['artifact_id']] if run else [],
        'trashed':bool(m.get('trashed'))}


def info(workflow,sid):
    """只读原件获取条件；不联网、不把未获取资料写成零结果。"""
    m=workflow.load(sid);rid=m['current'].get('A00');blockers=[];summary=workflow.result(m,rid)['summary'] if rid else {}
    supported=m.get('workflow_profile')=='A00.preupload.2' and summary.get('analysis_plan_profile')=='ModuleA.analysis_plan.1'
    plans=workflow._analysis_plan_records(m) if supported else [];draft=plans[-1] if plans and plans[-1]['expected_a00']==rid else None
    if not supported:blockers.append('只支持本研究已核验MeSH的新方案登记')
    if m.get('trashed'):blockers.append('回收站研究只读')
    if not draft:blockers.append('请先保存当前登记的分析方案')
    if rid:
        review=workflow.latest_review(m,workflow.run(m,rid)['artifact_id'])
        if review and review['decision']!='approved':blockers.append('登记已有明确人工暂存或退回')
    return {'schema_version':VERSION,'supported':supported,'enabled':not blockers,'blockers':blockers,
        'expected_a00':rid,'expected_plan_id':draft['plan_id'] if draft else None,
        'expected_input_hash':fingerprint(snapshot(workflow,m)),'scientific_publication_available':False,
        'message_zh':'获取只保留可追溯原件，不发布A01、切换研究运行或签署复核；统一采集接续界面后续接入。'}


def require_current(workflow,m,request):
    """原登记、来源或明确人工意见变化就停止；新的未采用草稿不影响本次获取。"""
    require(not m.get('trashed'),'回收站研究只读')
    require(fingerprint(snapshot(workflow,m))==fingerprint(request['binding']),'原件获取输入或登记意见已改变，请刷新')
    home=workflow.location(m['study_id']);plan=read_json(verified_file(home,request['plan_file']))
    require(request['plan_file'] in m.get('analysis_plan_records',[]) and plan['study_id']==m['study_id']
        and plan['plan_id']==request['request']['expected_plan_id'] and plan['expected_a00']==request['binding']['a00'],
        '原件获取计划不属于当前研究登记')
    return plan


def validate_request(workflow,sid,body):
    """HTTP和排队后共享只读预检；不获取、不运行科学校验或登记请求。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'系统获取请求字段错误，不接受路径、阈值或通过标志')
    for key,prefix in (('request_id','systemacqreq'),('expected_a00','run'),('expected_plan_id','plan')):safe_id(body[key],prefix)
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
        '请填写获取登记人、说明并明确确认')
    m=workflow.load(sid);home=workflow.location(sid)
    require(not m.get('trashed'),'回收站研究只读')
    for ref in m.get(REQUESTS,[]):
        value=read_record(workflow,m,ref,kind='request')
        if value['request']['request_id']==body['request_id']:
            require(value['request']==body,'原件获取请求号已用于其他内容');require_current(workflow,m,value)
            return deepcopy(body)
    value=info(workflow,sid);require(value['enabled'],'原件获取条件未齐：'+'；'.join(value['blockers']))
    require(all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'来源或方案已改变，请刷新后确认')
    return deepcopy(body)


def read_record(workflow,m,reference,*,kind):
    """标准库只读原件获取档案；真实科学解析仅在后台执行，不在导出重跑下载。"""
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,reference))
    index={'request':REQUESTS,'record':RECORDS,'failure':FAILURES,'source':SOURCES}[kind]
    require(reference in m.get(index,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']
        and value['human_review_written'] is False,'原件获取记录归属或协议错误')
    if kind=='request':
        from .system_validation import read_receipt
        require(value['request_hash']==fingerprint(value['request']) and value['request']['confirmed'] is True
            and value['binding']['study_id']==m['study_id'] and value['request']['expected_input_hash']==fingerprint(value['binding'])
            and value['a01_published'] is False and value['plan_file'] in m.get('analysis_plan_records',[]),'原件获取请求与原确认不同')
        proof=read_receipt(workflow,m,value['a00_validation'])
        require(proof['passed'] and proof['run_id']==value['binding']['a00'] and proof['module_id']=='A00','原件获取未采用真实登记核验')
        verified_file(home,value['plan_file'])
    else:
        request=read_record(workflow,m,value['request_file'],kind='request')
        if kind=='source':
            require(value['plan_file']==request['plan_file'] and value['source']['state']=='ready'
                and value['source']['mode']=='downloaded' and value['a01_published'] is False,'逐库恢复记录不能冒充科学发布')
            verified_file(home,value['source']['archive'])
        elif kind=='failure':require(value['state']=='failed' and value['error_type'] and value['error_zh'],'原件获取失败缺少真实诊断')
        else:
            require(value['a01_published'] is False and value['current_sources_changed'] is False
                and value['plan_file']==request['plan_file'] and [r['database'] for r in value['sources']]==['TCMSP','HERB','BATMAN'],
                '原件获取结果不能冒充已发布三库或隐藏缺库')
            for row in value['sources']:
                require(row['state'] in ('ready','failed') and row['reason_zh'],'原件获取来源状态或依据缺失')
                if row['state']=='ready':verified_file(home,row['archive'])
            require(value['state']==('complete' if all(r['state']=='ready' for r in value['sources']) else 'partial_failure'),
                '原件获取总体状态不同于逐库事实')
        for ref in value['files']:verified_file(home,ref)
    return value


def execute(workflow,sid,body,*,progress=None,opener=None,sleeper=None):
    """同研究来源获取使用独立进程锁；网络期间不占全局研究写锁。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'系统获取请求字段错误，不接受路径、阈值或通过标志')
    safe_id(sid,'study');safe_id(body['request_id'],'systemacqreq')
    workflow.load(sid)
    with write_lock(workflow.root/'environments/system_acquisition'/sid):
        return _execute(workflow,sid,body,progress=progress,opener=opener,sleeper=sleeper)


def _execute(workflow,sid,body,*,progress=None,opener=None,sleeper=None):
    """内部明确授权入口；成功原件与失败请求均留存，但不改旧approved或科学结果。"""
    validate_request(workflow,sid,body)
    m=workflow.load(sid);home=workflow.location(sid);request_ref=None;request=None;previous=None
    for ref in m.get(REQUESTS,[]):
        candidate=read_json(verified_file(home,ref))
        if candidate['request']['request_id']==body['request_id']:
            require(candidate['request']==body,'原件获取请求号已用于其他内容');request_ref=ref;request=candidate;break
    if request:
        plan=require_current(workflow,m,request)
        history=[read_json(verified_file(home,r)) for r in m.get(RECORDS,[]) if read_json(verified_file(home,r))['request_file']==request_ref]
        previous=history[-1] if history else None
        if previous and previous['state']=='complete':
            from science_modules.a01.system_acquisition import validate_record
            validate_record(home,request,previous);return previous
    else:
        value=info(workflow,sid);require(value['enabled'],'原件获取条件未齐：'+'；'.join(value['blockers']))
        require(all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'来源或方案已改变，请刷新后确认')
        # 调用真实A00生产核验；没有把未签人工意见变成批准。
        system_execution.ensure_parents(workflow,sid,{'A00':body['expected_a00']})
        with write_lock(workflow.root):
            m=workflow.load(sid);value=info(workflow,sid)
            require(value['enabled'] and all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'获取确认期间输入已改变')
            plan_ref=next(r for r in m['analysis_plan_records'] if read_json(verified_file(home,r))['plan_id']==body['expected_plan_id'])
            request={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
                'binding':snapshot(workflow,m),'plan_file':deepcopy(plan_ref),
                'a00_validation':system_execution.parent_records(workflow,m,{'A00':body['expected_a00']})['A00'],
                'human_review_written':False,'a01_published':False,'created_at':now()}
            path=home/'decisions/analysis_plans/system_acquisition'/body['request_id']/'request.json';write_json(path,request)
            request_ref=file_record(home,path,'system_acquisition_request');m.setdefault(REQUESTS,[]).append(request_ref);workflow.save(m)
            plan=require_current(workflow,m,request)
    from science_modules.a01 import system_acquisition as science
    # 每库合格原件立即登记，进程中断而尚无整批记录时仍能核验复用。
    recovered=[];source_refs=[]
    for ref in m.get(SOURCES,[]):
        value=read_record(workflow,m,ref,kind='source')
        if value['request_file']==request_ref:
            recovered.append(value['source']);source_refs.append(ref)
    if recovered:
        saved={row['database']:deepcopy(row) for row in previous['sources'] if row['state']=='ready'} if previous else {}
        for row in recovered:
            require(row['database'] not in saved or saved[row['database']]==row,'同请求逐库恢复记录冲突')
            saved[row['database']]=row
        previous={'sources':list(saved.values())}

    def source_ready(row):
        """实际ZIP复算通过后锁内保存单库检查点；不切换旧三库暂存指针。"""
        with write_lock(workflow.root):
            current=workflow.load(sid);require_current(workflow,current,request)
            science.validate_source(home,row,request,plan['plan'],science.source_herbs(workflow,current,request))
            value={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'plan_file':request['plan_file'],
                'source':deepcopy(row),'a01_published':False,'human_review_written':False,'created_at':now(),
                'files':[deepcopy(row['archive'])]}
            path=home/'decisions/analysis_plans/system_acquisition'/body['request_id']/'sources'/(new_id('acqsource')+'.json')
            write_json(path,value);ref=file_record(home,path,'system_acquisition_source');current.setdefault(SOURCES,[]).append(ref)
            workflow.save(current);source_refs.append(ref)
    try:
        result=science.collect(workflow,m,request,request_ref,plan,previous,progress or (lambda message:None),opener,sleeper,source_ready)
        result['source_receipts']=deepcopy(source_refs)
        with write_lock(workflow.root):
            m=workflow.load(sid);require_current(workflow,m,request);science.validate_record(home,request,result)
            path=home/'decisions/analysis_plans/system_acquisition'/body['request_id']/'records'/(new_id('acqrecord')+'.json')
            write_json(path,result);m.setdefault(RECORDS,[]).append(file_record(home,path,'system_acquisition_record'));workflow.save(m)
        return result
    except Exception as error:
        with write_lock(workflow.root):
            m=workflow.load(sid);folder=home/'raw/A01_system_acquisition'/body['request_id']
            value={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'state':'failed','human_review_written':False,
                'error_type':type(error).__name__,'error_zh':str(error),'created_at':now(),
                'files':[file_record(home,p,'system_acquisition_diagnostic') for p in folder.rglob('*') if p.is_file()] if folder.exists() else []}
            path=home/'decisions/analysis_plans/system_acquisition'/body['request_id']/'failures'/(new_id('attempt')+'.json');write_json(path,value)
            m.setdefault(FAILURES,[]).append(file_record(home,path,'system_acquisition_failure'));workflow.save(m)
        raise
