"""A05中文原因修订公开桥接：绑定原统计与同批方案，新版本复算，不改原运行。"""
from copy import deepcopy
from pathlib import Path

from contracts import ContractError,fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution as execution

VERSION='A05.plan_text_revision.1'
REQUESTS='analysis_plan_a05_text_requests'
RECEIPTS='analysis_plan_a05_text_receipts'
FAILURES='analysis_plan_a05_text_failures'
FIELDS={'request_id','expected_a05','expected_input_hash','author','note','confirmed'}


def context(workflow,m):
    """当前只修复明确系统批次的第一版；其他来源和人工暂停不借用修订入口。"""
    rid=m['current'].get('A05');require(rid,'尚无可修订A05')
    run=workflow.run(m,rid);require(run['config'].get('version')=='A05.plan_enrichment.1'
        and run.get('execution_protocol')==execution.VERSION,'仅支持本批第一版系统富集的显式文字修订')
    batch,plan=execution.require_batch(workflow,m,run['batch_file'])
    require(not m.get('trashed') and workflow.active(m,rid),'A05已失效或研究在回收站')
    for current in (rid,run['parent_runs']['A03']):
        review=workflow.latest_review(m,workflow.run(m,current)['artifact_id'])
        require(not review or review['decision']=='approved','A05或实际交集已有人工暂停/退回')
    require(run['parent_runs']['A03']==m['current'].get('A03') and run['inputs']['analysis_plan_file']==batch['plan_file'],
        'A05实际交集或原方案已经改变')
    result=workflow.result(m,rid);require(result and not result['summary'].get('handoff_blocked'),'A05尚有实际科学阻断，文字修订不豁免')
    binding={'study_id':m['study_id'],'source_a05':rid,'source_files':deepcopy(m['runs'][rid]),
        'a03':run['parent_runs']['A03'],'a03_files':deepcopy(m['runs'][run['parent_runs']['A03']]),
        'batch_file':deepcopy(run['batch_file']),'plan_file':deepcopy(batch['plan_file']),
        'reviews':deepcopy(m.get('reviews',[])),'trashed':False}
    return run,result,batch,plan,binding


def info(workflow,sid):
    """只读资格，无R、联网、任务或研究写入。"""
    m=workflow.load(sid)
    try:
        run,result,batch,plan,binding=context(workflow,m)
    except ContractError as error:
        return {'schema_version':VERSION,'enabled':False,'blockers':[str(error)],'expected_a05':m['current'].get('A05'),
            'expected_input_hash':None}
    bad=0;p=plan['plan']['parameters']
    for group in ('bp','cc','mf','kegg'):
        for row in result['tables'].get(group+'_skipped',[]):
            reason='条目背景基因数不在本方案范围' if not p['a05.min_term_size']<=row['Size']<=p['a05.max_term_size'] else '有效输入无命中'
            bad+=row['reason']!=reason
    return {'schema_version':VERSION,'enabled':bool(bad),'blockers':[] if bad else ['本版中文原因完整，无需修订'],
        'expected_a05':run['run_id'],'expected_input_hash':fingerprint(binding),'malformed_reason_rows':bad}


def read_request(workflow,m,ref):
    """历史请求仅读原绑定及实现，不将其视为当前仍可执行。"""
    require(ref in m.get(REQUESTS,[]),'A05文字修订请求未登记到本研究')
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,ref))
    require(value['schema_version']==VERSION and value['study_id']==m['study_id'] and value['human_review_written'] is False,
        'A05修订请求研究、版本或人工字段错误')
    require(value['request_hash']==fingerprint(value['request']) and value['input_hash']==fingerprint(value['binding'])
        ==value['request']['expected_input_hash'],'A05修订确认或原输入指纹不同')
    binding=value['binding'];rid=binding['source_a05']
    require(value['request']['expected_a05']==rid and binding['source_files']==m['runs'][rid]
        and binding['a03_files']==m['runs'][binding['a03']],'A05修订原运行已改变')
    for refs in (binding['source_files'],binding['a03_files']):
        for source in refs.values():
            if source:verified_file(home,source)
    for source in value['implementation_files']:verified_file(home,source)
    require(value['implementation_files'],'A05修订缺少真实实现快照')
    return value


def validate_run(workflow,m,run):
    """生产规范检查修订来源与确认，不接受调用者填通过标记或任意A05引用。"""
    inputs=run['inputs'];ref=inputs.get('text_revision_request_file')
    if not ref:
        batch,_=execution.read_batch(workflow,m,run['batch_file'])
        require(batch.get('enrichment_protocol')=='A05.plan_enrichment.2','新A05缺少批次明确协议或文字修订确认')
        return
    value=read_request(workflow,m,ref);binding=value['binding']
    require(run['batch_file']==binding['batch_file'] and run['parent_runs']=={'A03':binding['a03']}
        and run['parent_review_ids']=={} and inputs['source_a05_result']==binding['source_files']['result_file'],
        'A05新修订与原确认、实际交集或系统权限不同')
    source=workflow.run(m,binding['source_a05'])
    require(source['config']['version']=='A05.plan_enrichment.1' and source.get('execution_protocol')==execution.VERSION
        and source['batch_file']==run['batch_file'],'A05文字修订不能借用其他协议或其他批次')


def read_receipt(workflow,m,ref):
    """修订回执必须引用本研究登记请求和真实发布的第二版运行。"""
    require(ref in m.get(RECEIPTS,[]),'A05文字修订回执未登记')
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,ref))
    require(value['schema_version']==VERSION and value['study_id']==m['study_id'] and value['human_review_written'] is False,
        'A05文字修订回执研究、版本或人工字段错误')
    request=read_request(workflow,m,value['request_file']);rid=value['run_id']
    require(value['run_files']==m['runs'][rid],'A05修订结果原件不同')
    run=workflow.run(m,rid)
    require(run['config']['version']=='A05.plan_enrichment.2' and run['inputs']['text_revision_request_file']==value['request_file']
        and run['batch_file']==request['binding']['batch_file'],'A05修订回执与真实新运行不一致')
    return value


def statistics(summary,tables):
    """比较科学数据时只去除协议号、表行索引和原损坏中文原因；保留全部统计字段。"""
    summary=deepcopy(summary);summary.pop('protocol_version',None);tables=deepcopy(tables)
    for name,rows in tables.items():
        if isinstance(rows,list):
            for row in rows:
                if isinstance(row,dict):
                    row.pop('_row',None)
                    if name.endswith('_skipped'):row.pop('reason',None)
    return summary,tables


def publish(workflow,sid,body):
    """独立新版本离线实际R复算；锁内确认原件/依赖不变后才发布并追加同批事件。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'A05文字修订字段错误，不接受参数、路径或批准覆盖')
    safe_id(body['request_id'],'a05textreq');safe_id(body['expected_a05'],'run')
    require(body['confirmed'] is True,'请明确确认本次A05文字修订')
    for key in ('author','note'):require(isinstance(body[key],str) and 0<len(body[key].strip())<=2000,'请填写有效修订登记人和说明')
    home=workflow.location(sid)
    with write_lock(workflow.root):
        m=workflow.load(sid)
        for receipt_ref in m.get(RECEIPTS,[]):
            receipt=read_receipt(workflow,m,receipt_ref);request=read_request(workflow,m,receipt['request_file'])
            if request['request']['request_id']==body['request_id']:
                require(request['request']==body,'A05文字修订编号已用于其他内容')
                require(receipt['run_files']==m['runs'][receipt['run_id']],'A05修订历史结果指纹不同')
                return {'created':False,'run_id':receipt['run_id'],'result':workflow.result(m,receipt['run_id'])}
        source_run,source_result,batch,plan,binding=context(workflow,m);value=info(workflow,sid)
        require(value['enabled'] and body['expected_a05']==value['expected_a05']
            and body['expected_input_hash']==value['expected_input_hash'],'A05版本、中文状态或原输入已经改变')
        folder=home/'decisions/analysis_plans/a05_text_revisions'/body['request_id'];folder.mkdir(parents=True,exist_ok=True)
        from science_modules.a05 import plan_flow_utf8 as science
        snapshots=[]
        for path in (Path(__file__),Path(science.__file__),Path(science.original.__file__),science.SCRIPT,science.original.SCRIPT):
            target=folder/'implementation'/path.name;target.parent.mkdir(exist_ok=True)
            if target.exists():require(target.read_bytes()==path.read_bytes(),'原未完成修订实现已改变，请用新请求')
            else:target.write_bytes(path.read_bytes())
            snapshots.append(file_record(home,target,'a05_text_implementation'))
        record={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
            'binding':binding,'input_hash':fingerprint(binding),'implementation_files':snapshots,'human_review_written':False,'created_at':now()}
        path=folder/'request.json'
        if path.exists():
            old=read_json(path);require(old['request']==body and old['binding']==binding,'原修订请求已用于其他输入')
            record=old
        else:write_json(path,record)
        request_ref=file_record(home,path,'a05_text_request')
        if request_ref not in m.get(REQUESTS,[]):m.setdefault(REQUESTS,[]).append(request_ref);workflow.save(m)
    try:
        attempt_folder=folder/'attempts'/new_id('attempt');attempt_folder.mkdir(parents=True,exist_ok=False)
        execution.ensure_parents(workflow,sid,{'A03':source_run['parent_runs']['A03']})
        script=attempt_folder/science.SCRIPT.name;script.write_bytes(science.SCRIPT.read_bytes())
        inputs=deepcopy(source_run['inputs']);inputs.update(execution_script=file_record(home,script,'execution_script'),
            source_a05_result=deepcopy(binding['source_files']['result_file']),text_revision_request_file=request_ref)
        _,summary,tables,log=science.facts(home,inputs);(attempt_folder/'R_log.txt').write_text(log,encoding='utf8')
        require(statistics(summary,tables)==statistics(source_result['summary'],source_result['tables']),
            'A05文字修订改变了原统计、背景或命中，禁止发布')
        with write_lock(workflow.root):
            m=workflow.load(sid);require(fingerprint(context(workflow,m)[-1])==body['expected_input_hash'],'修订期间A05、交集或人工意见已改变')
            request=read_request(workflow,m,request_ref)
            require(all(verified_file(home,ref).read_bytes()==Path(path).read_bytes() for ref,path in zip(request['implementation_files'],
                (Path(__file__),Path(science.__file__),Path(science.original.__file__),science.SCRIPT,science.original.SCRIPT))),
                '修订期间实现已改变')
            parents={'A03':source_run['parent_runs']['A03']}
            run=execution.begin(workflow,m,'A05',inputs,science.configuration(plan['plan']),body['note'],source_run['batch_file'],parents)
            from .system_validation import canonical_validator
            outcome=source_result['outcome'];canonical_validator(workflow.root,'A05')(run,summary,tables,source_result['anomalies'],outcome)
            from science_modules.a05.plan_figures import draw
            figures=[file_record(home,path,'figure') for path in draw(tables,plan['plan'],home/'runs/A05'/run['run_id']).values()]
            result=workflow._finish(m,run['run_id'],summary,tables,source_result['anomalies'],outcome,
                sources=[run['batch_file'],*run['parent_validation_records'].values(),request_ref,binding['source_files']['result_file'],
                    inputs['analysis_plan_file'],inputs['source_file'],inputs['mapping_file'],inputs['execution_script']],
                figures=figures,attachments=[file_record(home,attempt_folder/'R_log.txt','log')])
            event={'schema_version':execution.VERSION,'study_id':sid,'batch_id':batch['batch_id'],'stage':'A05','state':'completed',
                'batch_file':source_run['batch_file'],'request':{'batch_id':batch['batch_id'],'stage':'A05','expected_current_run_id':body['expected_a05']},
                'run_id':run['run_id'],'result_file':m['runs'][run['run_id']]['result_file'],'human_review_written':False,'created_at':now(),
                'text_revision_request_file':request_ref}
            path=attempt_folder/'event.json';write_json(path,event);m.setdefault(execution.EVENTS,[]).append(file_record(home,path,'system_batch_event'))
            receipt={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'run_id':run['run_id'],
                'run_files':deepcopy(m['runs'][run['run_id']]),'human_review_written':False,'created_at':now()}
            path=attempt_folder/'receipt.json';write_json(path,receipt);m.setdefault(RECEIPTS,[]).append(file_record(home,path,'a05_text_receipt'));workflow.save(m)
        return {'created':True,'run_id':run['run_id'],'result':result}
    except Exception as error:
        with write_lock(workflow.root):
            m=workflow.load(sid);path=folder/(new_id('failed')+'.json')
            write_json(path,{'schema_version':VERSION,'study_id':sid,'state':'failed','request_file':request_ref,
                'error_zh':str(error),'created_at':now(),'human_review_written':False})
            m.setdefault(FAILURES,[]).append(file_record(home,path,'a05_text_failure'));workflow.save(m)
        raise
