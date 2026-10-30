"""新版A07使用真实系统依赖形成同批双报告；不伪造人工parent_review_ids或改变旧报告规则。"""
from copy import deepcopy
from contracts import SCHEMA_VERSION,ContractError,fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from .plan_report_contract import validate_receipts
from . import system_validation as system

VERSION='A07.plan_report.1'
CONFIG={'version':VERSION,'dependency_kind':'system_validation','automatic_approval':False,
        'payload_version':'A07.plan_payload.1','documents_version':'A07.plan_documents.1','figures_version':'A07.plan_figures.1'}
REQUESTS='analysis_plan_report_requests'
RECEIPTS='analysis_plan_report_receipts'
FAILURES='analysis_plan_report_failures'
FIELDS={'request_id','expected_report_run_id','expected_input_hash','author','note','confirmed'}
SCIENTIFIC_BINDING_KEYS={'study_id','current','run_files','reviews','system_validations','trashed'}


def binding(workflow,m):
    """固定科学上游及其真实复核/校验；报告自身最终复核不让自己或上游失效。"""
    home=workflow.location(m['study_id']);reviews=[];receipts=[]
    for ref in m.get('reviews',[]):
        value=read_json(verified_file(home,ref));rid=value.get('run_id')
        if rid and workflow.run(m,rid)['module_id']!='A07':reviews.append(deepcopy(ref))
    for ref in m.get(system.INDEX,[]):
        # 此处只固定不可变回执文件；资格及发布另逐件完整核验源码、结果和依赖。
        value=read_json(verified_file(home,ref))
        require(value.get('study_id')==m['study_id'] and value.get('schema_version')==system.VERSION,'系统校验快照归属错误')
        if value['module_id']!='A07':receipts.append(deepcopy(ref))
    return {'binding_scope':'bound_scientific_runs.1','study_id':m['study_id'],'current':{key:value for key,value in m['current'].items() if key!='A07'},
            'run_files':{rid:deepcopy(m['runs'][rid]) for key,rid in m['current'].items() if key!='A07'},
            'reviews':reviews,'system_validations':receipts,'trashed':bool(m.get('trashed'))}


def scientific_binding(value):
    """只比较实际科学输入；旧测试回执中另存的未采用草稿和全局词典不替换归档来源。"""
    if value.get('binding_scope')=='bound_scientific_runs.1':
        require(set(value)==SCIENTIFIC_BINDING_KEYS|{'binding_scope'},'报告科学输入快照字段错误')
    else:
        require(set(value)==SCIENTIFIC_BINDING_KEYS|{'plan_records','classification_sha256','lexicon_sha256'},'报告历史输入快照版本不支持')
    return {key:deepcopy(value[key]) for key in SCIENTIFIC_BINDING_KEYS}


def read_receipt(workflow,m,reference):
    """历史报告只校验历史原件与登记关系，不把历史版本当当前可用。"""
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,reference))
    require(value.get('schema_version')==VERSION and value.get('study_id')==m['study_id'],'报告回执研究或版本错误')
    require(value.get('human_review_written') is False,'报告生成回执不得冒充人工签名')
    rid=value['run_id'];run=workflow.run(m,rid)
    require(run['module_id']=='A07' and run['config']==CONFIG and value['result_file']==m['runs'][rid]['result_file']
            and value['request_file'] in m.get(REQUESTS,[]) and run['inputs']['request_file']==value['request_file']
            and run['inputs']['payload_file']==value['payload_file'],'报告回执未绑定真实归档运行')
    request=read_json(verified_file(home,value['request_file']))
    require(request['request_id']==value['request_id'] and request['request_hash']==fingerprint(request['request'])
            and request['request']['confirmed'] is True,'报告明确请求或指纹错误')
    workflow.result(m,rid);verified_file(home,value['payload_file'])
    for ref in value['files']:verified_file(home,ref)
    return value


def info(workflow,sid):
    """单次资格读取内复用已验证内容，独立请求与发布前重新核验。"""
    if getattr(workflow,'_view_cache',None) is None and hasattr(workflow,'handoff_read_cache'):
        with workflow.handoff_read_cache():return _info(workflow,sid)
    return _info(workflow,sid)


def _info(workflow,sid):
    """标准库资格只读，完整事实/图件由后台生成；新旧报告及人工批准独立。"""
    m=workflow.load(sid);a03=m['current'].get('A03');supported=bool(a03 and workflow.run(m,a03)['config'].get('version')=='A03.plan_intersection.1')
    blockers=[]
    if not supported:blockers.append('请先生成本方案完整交集；历史固定报告保持原入口')
    if m.get('trashed'):blockers.append('回收站研究只读')
    required={'A00','A01','A02','A03'}
    if supported:
        result=workflow.result(m,a03)
        if result is None:blockers.append('本方案交集尚未完整归档')
        elif result['summary']['交集靶点数']:
            for module in ('A04','A05','A06_PREP'):
                if module=='A05':
                    plan=read_json(verified_file(workflow.location(sid),workflow.run(m,a03)['inputs']['analysis_plan_file']))['plan']
                    if not (plan['parameters']['a05.include_go'] or plan['parameters']['a05.include_kegg']):continue
                rid=m['current'].get(module)
                if not rid or not m['runs'][rid].get('result_file'):blockers.append('仍等待适用分支：'+module)
                elif module=='A06_PREP':
                    preparation=workflow.result(m,rid);score=m['current'].get('A06')
                    scoring=workflow.run(m,score) if score else None
                    if scoring and scoring['parent_runs'].get('A06_PREP')==rid:
                        required.add('A06')
                        if not m['runs'][score].get('result_file'):blockers.append('适用评分分支尚未完整归档')
                    elif any(row['state']=='ready' for row in preparation['tables'].get('planned_pairs',[])):
                        blockers.append('准备中仍有适用组合，等待实际评分结束')
                if rid:required.add(module)
        if result is not None:
            pending=list(required)
            while pending:
                module=pending.pop();rid=m['current'].get(module)
                if not rid:continue
                run=workflow.run(m,rid)
                for parent,parent_id in run['parent_runs'].items():
                    if m['current'].get(parent)!=parent_id:blockers.append(module+'的上游已改变，请刷新')
                    if parent not in required:required.add(parent);pending.append(parent)
            validated_receipts=[system.read_receipt(workflow,m,ref) for ref in m.get(system.INDEX,[])]
            for module in sorted(required):
                rid=m['current'].get(module)
                if not rid or not m['runs'][rid].get('result_file'):
                    blockers.append('缺少完整实际结果：'+module);continue
                if not workflow.active(m,rid):blockers.append('来源依赖或独立选择决定已失效：'+module)
                review=workflow.latest_review(m,workflow.run(m,rid)['artifact_id'])
                if review and review['decision']!='approved':blockers.append('来源已有明确暂存或退回决定：'+module)
                try:
                    expected=system.request(workflow,sid,rid);matches=[]
                    for value in validated_receipts:
                        if value['run_id']==rid and value['input_hash']==expected['expected_input_hash']:matches.append(value)
                    if not matches or not matches[-1]['passed']:blockers.append('等待实际系统校验：'+module)
                except ContractError as error:blockers.append(str(error))
    history=[]
    for ref in m.get(RECEIPTS,[]):
        value=read_receipt(workflow,m,ref);active=bool(m['current'].get('A07')==value['run_id'] and workflow.active(m,value['run_id']))
        approved=bool(active and workflow.approved(m,value['run_id']))
        history.append(dict(value,file=deepcopy(ref),active=active,approved=approved,
            status_zh='已明确复核通过' if approved else '本批报告已生成，待独立复核' if active else '历史版本保留'))
    return {'schema_version':VERSION,'supported':supported,'enabled':not blockers,'blockers':blockers,
            'expected_report_run_id':m['current'].get('A07'),'expected_input_hash':fingerprint(binding(workflow,m)),
            'history':history,'message_zh':'根据同批实际来源、系统校验和完整图件生成双报告；等待分支不冒充完成，报告不代签人工复核。'}


def validate_request(workflow,sid,body):
    """只接受明确请求和当前指纹，拒绝客户端事实、路径、参数或通过标记。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'新报告请求字段不完整或含未支持选项')
    safe_id(body['request_id'],'planreportreq')
    if body['expected_report_run_id'] is not None:safe_id(body['expected_report_run_id'],'run')
    require(body['confirmed'] is True and all(isinstance(body[key],str) and 0<len(body[key].strip())<=2000 for key in ('author','note')),
            '请填写报告登记人与依据并明确确认')
    m=workflow.load(sid);require(not m.get('trashed'),'回收站研究只读')
    require(m['current'].get('A07')==body['expected_report_run_id'] and fingerprint(binding(workflow,m))==body['expected_input_hash'],
            '报告上游、校验或当前报告已改变，请刷新')
    value=info(workflow,sid);require(value['enabled'],'报告条件未齐：'+'；'.join(value['blockers']))
    return m


def checked_inputs(workflow,m,inputs):
    """新运行只能消费本研究已登记的明确请求和同批完整事实，不能调用旧人工门控。"""
    require(set(inputs)=={'request_file','payload_file'} and inputs['request_file'] in m.get(REQUESTS,[]),'报告请求未登记或输入字段错误')
    home=workflow.location(m['study_id']);request=read_json(verified_file(home,inputs['request_file']))
    require(request.get('schema_version')==VERSION and request.get('study_id')==m['study_id']
            and request['request_hash']==fingerprint(request['request']) and request['request']['confirmed'] is True
            and request['input_hash']==fingerprint(request['binding'])
            and fingerprint(scientific_binding(request['binding']))==fingerprint(scientific_binding(binding(workflow,m))),
            '报告明确请求、校验或上游已改变，请刷新')
    payload=read_json(verified_file(home,inputs['payload_file']))
    from science_modules.a07.plan_payload import validate
    validate(payload,home,require_figures=True);validate_receipts(workflow,m,payload)
    require(payload['completion']['all_applicable_finished'],'报告必须等待所有适用分支结束')
    return request,payload


def begin(workflow,m,inputs,config,reason):
    """版本隔离的新A07运行：真实system_validation依赖独立留痕，人工复核字段为空。"""
    require(not m.get('trashed') and config==CONFIG and isinstance(reason,str) and reason.strip(),'新报告配置或状态无效')
    _,payload=checked_inputs(workflow,m,inputs);parents=deepcopy(payload['run_ids'])
    artifacts=[workflow.run(m,parents[key])['artifact_id'] for key in sorted(parents)]
    rid=new_id('run');run={'schema_version':SCHEMA_VERSION,'study_id':m['study_id'],'run_id':rid,'module_id':'A07',
        'artifact_id':new_id('artifact'),'parent_runs':parents,'parent_review_ids':{},'parent_artifact_ids':artifacts,
        'parent_validation_records':{row['module']:row['source'] for row in payload['validation_records']},
        'execution_authority':'system_validation','inputs':deepcopy(inputs),'config':deepcopy(config),
        'input_hash':fingerprint({'inputs':inputs,'parents':artifacts}),'config_hash':fingerprint(config),
        'code_version':workflow.code_version,'environment_version':fingerprint(workflow.environment),
        'environment':deepcopy(workflow.environment),'created_at':now(),'reason':reason}
    path=workflow.location(m['study_id'])/'runs/A07'/rid/'run.json';write_json(path,run)
    m['runs'][rid]={'run_file':file_record(workflow.location(m['study_id']),path,'run'),'result_file':None};m['current']['A07']=rid
    return run


def is_active(workflow,m,run):
    """仅新报告按系统证据判定依赖有效，旧approved/latest_review规则完全保持。"""
    if m['current'].get('A07')!=run['run_id']:return False
    try:
        _,payload=checked_inputs(workflow,m,run['inputs'])
        return (run['config']==CONFIG and run['execution_authority']=='system_validation' and run['parent_review_ids']=={}
                and run['parent_runs']==payload['run_ids'] and run['parent_validation_records']=={row['module']:row['source'] for row in payload['validation_records']})
    except ContractError:return False


def output(payload,documents):
    """结果摘要、平面导出表和原文结论均只从实际事实构造，partial不冒充全部成功。"""
    state=payload['completion'];scored=(payload.get('docking') or {}).get('counts',{}).get('scored')
    summary={'报告修订':VERSION,'共同结论草稿':payload['conclusion'],'研究线索数':len(payload['research_leads']),
             '结论复核状态':'待独立人工复核，系统未代签','实际分析状态':state['state'],
             'all_applicable_finished':state['all_applicable_finished'],'complete_analysis':state['complete_analysis'],
             'handoff_blocked':state['state']=='technical_blocked','automatic_approval':False}
    counts=[{'指标':'交集靶点数','数值':payload['counts']['intersection']},
            {'指标':'正式对接成功组合数','数值':scored}]
    tables={'report_files':deepcopy(documents),'key_counts':counts,
            'branch_status':[{'分支':row['branch'],'实际状态':row['state'],'依据':row['reason_zh']} for row in state['branches']],
            'research_leads':[{'线索':text,'支持事实':'本批原始结果','下一步核验':'独立科学验证'} for text in payload['research_leads']],
            'limitations':[{'限制':'系统证据校验不表示人工批准、临床疗效、通路激活或体内结合。'}]}
    return summary,tables,'failed' if state['state']=='technical_blocked' else 'empty' if state['state']=='valid_empty' else 'success'


def archive_enrichment(workflow,m,folder):
    """后台固定本批分类和词典原字节，不执行R或借用其他批次展示决定。"""
    a03=m['current']['A03'];result=workflow.result(m,a03)
    if not result['summary']['交集靶点数']:return None
    plan=read_json(verified_file(workflow.location(m['study_id']),workflow.run(m,a03)['inputs']['analysis_plan_file']))['plan']
    rid=m['current'].get('A05')
    if not rid or not (plan['parameters']['a05.include_go'] or plan['parameters']['a05.include_kegg']):return None
    from science_modules.a05 import plan_display as model
    home=workflow.location(m['study_id']);base=workflow.result(m,rid);intake=workflow.result(m,m['current']['A00'])['summary']
    source=model.make_source(base,plan,intake);folder=folder/'a05_source';folder.mkdir(parents=True,exist_ok=False)
    values={}
    for key,path in (('catalog',model.screening.CATALOG),('lexicon',model.LEXICON)):
        target=folder/(key+'.json');target.write_bytes(path.read_bytes());values[key]=file_record(home,target,'report_enrichment_source')
    path=folder/'snapshot.json';write_json(path,source);values['snapshot']=file_record(home,path,'report_enrichment_snapshot')
    return values


def _publish(workflow,sid,body):
    """公开Workflow委托：先保存明确请求，锁外绘图/Word，锁内再核对真实上游并发布。"""
    with write_lock(workflow.root):
        m=workflow.load(sid)
        for ref in m.get(RECEIPTS,[]):
            old=read_receipt(workflow,m,ref)
            if old['request_id']==body.get('request_id'):
                request=read_json(verified_file(workflow.location(sid),old['request_file']))
                require(request['request']==body,'报告请求编号已用于其他内容');return workflow.result(m,old['run_id'])
        m=validate_request(workflow,sid,body);home=workflow.location(sid)
        for ref in m.get(REQUESTS,[]):
            old=read_json(verified_file(home,ref));require(old['request_id']!=body['request_id'],'该报告请求已受理但尚未完整发布，请明确提交新请求')
        folder=home/'decisions/analysis_plans/reports'/body['request_id']
        record={'schema_version':VERSION,'study_id':sid,'request_id':body['request_id'],'request':deepcopy(body),
                'request_hash':fingerprint(body),'binding':binding(workflow,m),'input_hash':body['expected_input_hash'],'created_at':now()}
        path=folder/'request.json';write_json(path,record);request_ref=file_record(home,path,'plan_report_request')
        m.setdefault(REQUESTS,[]).append(request_ref);workflow.save(m)
    source=archive_enrichment(workflow,m,folder)
    from science_modules.a07.plan_payload import build as facts
    from science_modules.a07.plan_figures import attach
    from science_modules.a07.plan_documents import build as document,validate_document
    payload=facts(workflow,sid,source_evidence=source)
    require(payload['completion']['all_applicable_finished'],'报告必须等待所有适用分支结束，明确请求已保留')
    validate_receipts(workflow,workflow.load(sid),payload)
    payload=attach(workflow,payload,folder/'figures');path=folder/'payload.json';write_json(path,payload)
    inputs={'request_file':request_ref,'payload_file':file_record(home,path,'plan_report_payload')}
    with write_lock(workflow.root):
        m=validate_request(workflow,sid,body);run=workflow._begin(m,'A07',inputs,CONFIG,body['note']);workflow.save(m)
    documents=[];output_folder=home/'runs/A07'/run['run_id']/'plan_report'
    for concise,name,role in ((False,'主报告.docx','detailed_report'),(True,'简略版.docx','brief_report')):
        path=document(payload,output_folder/name,home,concise=concise);validate_document(path,payload,concise=concise)
        documents.append(file_record(home,path,role))
    summary,tables,outcome=output(payload,documents)
    with write_lock(workflow.root):
        m=workflow.load(sid);require(is_active(workflow,m,run),'报告生成期间上游或校验已改变，不发布旧报告')
        from science_modules.a07.plan_report_flow import validate_result
        validate_result(workflow.root,run,summary,tables,[],outcome)
        from .trace_export import _records
        sources=[];_records(inputs,sources);_records(payload,sources)
        index=read_json(verified_file(home,payload['figure_source']));_records(index,sources)
        for rid in payload['run_ids'].values():_records(workflow.result(m,rid),sources)
        result=workflow._finish(m,run['run_id'],summary,tables,[],outcome,sources=sources,attachments=documents)
        receipt={'schema_version':VERSION,'study_id':sid,'request_id':body['request_id'],'request_file':request_ref,
                 'run_id':run['run_id'],'result_file':m['runs'][run['run_id']]['result_file'],'payload_file':inputs['payload_file'],
                 'files':deepcopy(result['files']),
                 'human_review_written':False,'created_at':now()}
        path=folder/'receipt.json';write_json(path,receipt);m.setdefault(RECEIPTS,[]).append(file_record(home,path,'plan_report_receipt'));workflow.save(m)
    return result


def publish(workflow,sid,body):
    """失败保留已受理请求、真实异常和未发布文件；不伪造完整结果或自动重试。"""
    try:return _publish(workflow,sid,body)
    except Exception as error:
        if isinstance(body,dict):
            with write_lock(workflow.root):
                m=workflow.load(sid);home=workflow.location(sid);reference=None
                for ref in m.get(REQUESTS,[]):
                    request=read_json(verified_file(home,ref))
                    if request['request']==body:reference=ref
                if reference and not m.get('trashed'):
                    rid=m['current'].get('A07');run=workflow.run(m,rid) if rid else None
                    if not run or run.get('inputs',{}).get('request_file')!=reference:rid=None
                    folder=verified_file(home,reference).parent;files=[]
                    candidates=list(folder.rglob('*'))
                    if rid:candidates+=list((home/'runs/A07'/rid/'plan_report').rglob('*'))
                    for path in candidates:
                        if not path.is_file():continue
                        if path.is_relative_to(folder) and 'failures' in path.relative_to(folder).parts:continue
                        files.append(file_record(home,path,'plan_report_diagnostic_file'))
                    value={'schema_version':VERSION,'study_id':sid,'request_file':reference,'run_id':rid,
                           'authority_kind':'execution_failure','error_type':type(error).__name__,'error_zh':str(error),
                           'files':files,'human_review_written':False,'created_at':now()}
                    path=folder/'failures'/(new_id('reportfailure')+'.json');write_json(path,value)
                    m.setdefault(FAILURES,[]).append(file_record(home,path,'plan_report_failure'));workflow.save(m)
        raise
