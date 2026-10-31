"""新方案疾病五库原件明确获取与逐库恢复；不发布A02或制造人工批准。"""
from copy import deepcopy
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution

VERSION='A02.system_acquisition.1'
REQUESTS='analysis_plan_disease_acquisition_requests'
RECORDS='analysis_plan_disease_acquisition_records'
SOURCES='analysis_plan_disease_acquisition_sources'
FAILURES='analysis_plan_disease_acquisition_failures'
DATABASES=('GeneCards','OMIM','TTD','PharmGKB','OTP')
FIELDS={'request_id','expected_a00','expected_plan_id','expected_input_hash','author','note','confirmed'}


def snapshot(w,m):
    """固定当前疾病侧与登记及手动原件，后来追加方案不替换本次检索。"""
    current={key:m['current'].get(key) for key in ('A00','A02')};artifacts={w.run(m,rid)['artifact_id'] for rid in current.values() if rid}
    return {'study_id':m['study_id'],'current':current,'run_files':{rid:deepcopy(m['runs'][rid]) for rid in current.values() if rid},
        'staging_file':deepcopy(m.get('current_source_staging')),'trashed':bool(m.get('trashed')),
        'reviews':[deepcopy(ref) for ref in m.get('reviews',[]) if read_json(verified_file(w.location(m['study_id']),ref))['artifact_id'] in artifacts]}


def info(w,sid):
    """标准库只读获取资格，GeneCards/OMIM缺原件不伪装成零查询结果。"""
    m=w.load(sid);rid=m['current'].get('A00');summary=w.result(m,rid)['summary'] if rid else {};blockers=[]
    supported=m.get('workflow_profile')=='A00.preupload.2' and summary.get('analysis_plan_profile')=='ModuleA.analysis_plan.1'
    plans=w._analysis_plan_records(m) if supported else [];draft=plans[-1] if plans and plans[-1]['expected_a00']==rid else None
    if not supported:blockers.append('疾病系统获取只支持新版已核验MeSH的研究登记')
    if m.get('trashed'):blockers.append('回收站研究只读')
    if not draft:blockers.append('请先保存本研究当前分析方案')
    for module in ('A00','A02'):
        rid=m['current'].get(module)
        review=w.latest_review(m,w.run(m,rid)['artifact_id']) if rid else None
        if review and review['decision']!='approved':blockers.append(module+'已有明确人工暂存或退回')
    return {'schema_version':VERSION,'supported':supported,'enabled':not blockers,'blockers':blockers,
        'expected_a00':m['current'].get('A00'),'expected_plan_id':draft['plan_id'] if draft else None,
        'expected_input_hash':fingerprint(snapshot(w,m)),'automatic_databases':['TTD','PharmGKB','OTP'],
        'manual_databases':['GeneCards','OMIM'],'scientific_publication_available':False}


def require_current(w,m,request):
    """登记、疾病来源或人工意见变化立即停止；原方案仍保留完整历史。"""
    require(not m.get('trashed'),'回收站研究只读')
    require(fingerprint(snapshot(w,m))==fingerprint(request['binding']),'疾病原件获取输入或人工意见已改变，请刷新')
    plan=read_json(verified_file(w.location(m['study_id']),request['plan_file']))
    require(request['plan_file'] in m.get('analysis_plan_records',[]) and plan['study_id']==m['study_id']
        and plan['plan_id']==request['request']['expected_plan_id'] and plan['expected_a00']==request['request']['expected_a00'],
        '疾病获取方案不属于本研究登记')
    return plan


def read_record(w,m,ref,*,kind):
    """只读归属、明确确认和递归SHA；不联网或导入科学解析器。"""
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref));index={'request':REQUESTS,'record':RECORDS,'source':SOURCES,'failure':FAILURES}[kind]
    require(ref in m.get(index,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']
        and value['human_review_written'] is False and value['a02_published'] is False,'疾病获取归属、版本或人工字段错误')
    if kind=='request':
        from .system_validation import read_receipt,INDEX
        require(value['request_hash']==fingerprint(value['request']) and value['request']['confirmed'] is True
            and value['request']['expected_input_hash']==fingerprint(value['binding'])
            and value['plan_file'] in m.get('analysis_plan_records',[]) and value['a00_validation'] in m.get(INDEX,[]),
            '疾病原件获取请求不同于原明确确认或真实系统证据')
        proof=read_receipt(w,m,value['a00_validation']);plan=read_json(verified_file(home,value['plan_file']))
        require(proof['passed'] and proof['module_id']=='A00' and proof['run_id']==value['request']['expected_a00']
            ==value['binding']['current']['A00']==plan['expected_a00'] and plan['study_id']==m['study_id']
            and plan['plan_id']==value['request']['expected_plan_id'],'疾病原件缺少同登记真实校验或原方案')
    else:
        request=read_record(w,m,value['request_file'],kind='request')
        if kind=='source':
            require(value['source']['state']=='ready' and value['source']['database'] in DATABASES,'恢复检查点不是真实成功库')
            verified_file(home,value['source']['archive'])
        elif kind=='failure':require(value['state']=='failed' and value['error_type'] and value['error_zh'],'疾病获取失败诊断不完整')
        else:
            require(value['plan_file']==request['plan_file'] and [r['database'] for r in value['sources']]==list(DATABASES),
                '疾病获取缺库或混用了方案')
            for row in value['sources']:
                require(row['state'] in ('ready','failed','missing') and row['reason_zh'],'疾病获取状态或依据缺失')
                if row['state']=='ready':verified_file(home,row['archive'])
            require(value['state']==('complete' if all(r['state']=='ready' for r in value['sources']) else 'incomplete'),
                '疾病获取不能将缺失或失败改为完整')
        for item in value['files']:verified_file(home,item)
    return value


def validate_request(w,sid,body):
    """HTTP与后台共用标准库预检，不接收来源地址、路径、疾病词或通过标记。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'疾病获取请求字段错误，不接受路径、疾病词或通过覆盖')
    for key,prefix in (('request_id','diseaseacqreq'),('expected_a00','run'),('expected_plan_id','plan')):safe_id(body[key],prefix)
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
        '请填写疾病获取登记人和说明并明确确认')
    m=w.load(sid)
    for ref in m.get(REQUESTS,[]):
        value=read_record(w,m,ref,kind='request')
        if value['request']['request_id']==body['request_id']:
            require(value['request']==body,'疾病获取请求号已用于其他内容');require_current(w,m,value);return deepcopy(body)
    value=info(w,sid);require(value['enabled'],'疾病原件获取条件未齐：'+'；'.join(value['blockers']))
    require(all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'疾病来源或方案已改变，请刷新')
    return deepcopy(body)


def execute(w,sid,body,*,progress=None):
    """同研究独立采集锁；网络不占全局写锁，每个成功库立即保存恢复检查点。"""
    validate_request(w,sid,body)
    with write_lock(w.root/'environments/system_disease_acquisition'/sid):
        return _execute(w,sid,body,progress or (lambda message:None))


def _execute(w,sid,body,progress):
    """实际系统A00授权后取原件，原current/runs/reviews与手动暂存保持。"""
    validate_request(w,sid,body);m=w.load(sid);home=w.location(sid);request=None;request_ref=None
    for ref in m.get(REQUESTS,[]):
        value=read_record(w,m,ref,kind='request')
        if value['request']['request_id']==body['request_id']:request=value;request_ref=ref;break
    if request is None:
        system_execution.ensure_parents(w,sid,{'A00':body['expected_a00']})
        with write_lock(w.root):
            validate_request(w,sid,body);m=w.load(sid)
            plan=next(ref for ref in m['analysis_plan_records'] if read_json(verified_file(home,ref))['plan_id']==body['expected_plan_id'])
            request={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
                'binding':snapshot(w,m),'plan_file':deepcopy(plan),'a00_validation':system_execution.parent_records(w,m,{'A00':body['expected_a00']})['A00'],
                'human_review_written':False,'a02_published':False,'created_at':now()}
            path=home/'decisions/analysis_plans/disease_acquisition'/body['request_id']/'request.json';write_json(path,request)
            request_ref=file_record(home,path,'disease_acquisition_request');m.setdefault(REQUESTS,[]).append(request_ref);w.save(m)
    from science_modules.a02 import system_acquisition as science
    history=[read_record(w,m,ref,kind='record') for ref in m.get(RECORDS,[]) if read_json(verified_file(home,ref))['request_file']==request_ref]
    if history and history[-1]['state']=='complete':science.validate_record(home,request,history[-1]);return history[-1]
    recovered={};source_refs=[]
    for ref in m.get(SOURCES,[]):
        value=read_record(w,m,ref,kind='source')
        if value['request_file']==request_ref:
            row=value['source'];require(row['database'] not in recovered,'同请求出现竞争来源检查点')
            recovered[row['database']]=row;source_refs.append(ref)
    def source_ready(row):
        """逐库原文真正解析通过后，短写锁登记不变的原件与恢复事实。"""
        with write_lock(w.root):
            current=w.load(sid);require_current(w,current,request);science.validate_source(home,row,request)
            value={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'source':deepcopy(row),
                'human_review_written':False,'a02_published':False,'created_at':now(),'files':[row['archive']]}
            path=home/'decisions/analysis_plans/disease_acquisition'/body['request_id']/'sources'/(new_id('diseasesource')+'.json');write_json(path,value)
            ref=file_record(home,path,'disease_acquisition_source');current.setdefault(SOURCES,[]).append(ref);w.save(current);source_refs.append(ref)
    try:
        result=science.collect(w,m,request,request_ref,recovered,source_ready,progress)
        result['source_receipts']=deepcopy(source_refs)
        with write_lock(w.root):
            current=w.load(sid);require_current(w,current,request);science.validate_record(home,request,result)
            path=home/'decisions/analysis_plans/disease_acquisition'/body['request_id']/'records'/(new_id('diseaseacq')+'.json');write_json(path,result)
            current.setdefault(RECORDS,[]).append(file_record(home,path,'disease_acquisition_record'));w.save(current)
        return result
    except Exception as error:
        with write_lock(w.root):
            current=w.load(sid);folder=home/'raw/A02_system_acquisition'/body['request_id']
            value={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'state':'failed','error_type':type(error).__name__,
                'error_zh':str(error),'human_review_written':False,'a02_published':False,'created_at':now(),
                'files':[file_record(home,p,'disease_acquisition_diagnostic') for p in folder.rglob('*') if p.is_file()] if folder.exists() else []}
            path=home/'decisions/analysis_plans/disease_acquisition'/body['request_id']/'failures'/(new_id('attempt')+'.json');write_json(path,value)
            current.setdefault(FAILURES,[]).append(file_record(home,path,'disease_acquisition_failure'));w.save(current)
        raise
