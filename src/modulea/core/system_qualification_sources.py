"""逐对象准备的第二版系统资格调度；旧版来源、回执与人工意见保持。"""
from copy import deepcopy
from contracts import ContractError,fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution as execution

VERSION='A06.system_qualification.3'
RECORDS='analysis_plan_system_qualification_records'


def _execute(workflow,sid,body):
    """一次批次派生资格核查，只重新复验证据，不写人工确认或启动评分。"""
    require(isinstance(body,dict) and set(body)=={'batch_id','expected_preparation_run_id'},'系统资格请求字段错误，不接受名单/批准/科学覆盖')
    safe_id(body['batch_id'],'systembatch');safe_id(body['expected_preparation_run_id'],'run')
    m=workflow.load(sid);home=workflow.location(sid);current=m['current'].get('A06_PREP')
    if current:
        previous=workflow.run(m,current)
        if previous['config'].get('version')==VERSION:
            request=read_json(verified_file(home,previous['inputs']['qualification_request']))
            require(request['request']==body and workflow.active(m,current),'本批准备资格已生成或失效，不能静默重算')
            return workflow.result(m,current)
    require(current==body['expected_preparation_run_id'],'系统资格来源准备已改变')
    source=workflow.run(m,current);require(source['config'].get('version')=='A06.system_preparation.3'
        and source.get('execution_protocol')==execution.VERSION,'仅支持本批实际系统准备证据')
    batch_ref=source['batch_file'];batch,plan=execution.require_batch(workflow,m,batch_ref)
    require(batch['batch_id']==body['batch_id'] and workflow.active(m,current),'系统准备与批次不同或已失效')
    review=workflow.latest_review(m,source['artifact_id']);require(not review or review['decision']=='approved','准备已被明确暂存或退回')
    parents=deepcopy(source['parent_runs']);execution.ensure_parents(workflow,sid,parents);m=workflow.load(sid)
    binding={'batch_file':deepcopy(batch_ref),'source_run':deepcopy(m['runs'][current]['run_file']),
        'source_result':deepcopy(m['runs'][current]['result_file']),
        'source_reviews':[deepcopy(r) for r in m.get('reviews',[]) if read_json(verified_file(home,r))['artifact_id']==source['artifact_id']],
        'parent_validation_records':execution.parent_records(workflow,m,parents)}
    from science_modules.a06 import system_qualification_sources as science
    computed=science.compute(workflow,m,batch,plan,binding,body)
    with write_lock(workflow.root):
        m=workflow.load(sid);execution.require_batch(workflow,m,batch_ref)
        require(m['current'].get('A06_PREP')==current and workflow.active(m,current),'资格核查期间来源准备已改变')
        current_reviews=[r for r in m.get('reviews',[]) if read_json(verified_file(home,r))['artifact_id']==source['artifact_id']]
        require(current_reviews==binding['source_reviews'] and execution.parent_records(workflow,m,parents)==binding['parent_validation_records'],
            '资格核查期间人工决定或上游回执已改变')
        inputs,config,summary,tables,sources=computed
        run=execution.begin(workflow,m,'A06_PREP',inputs,config,batch['request']['note'],batch_ref,parents)
        checker=execution.validation.canonical_validator(workflow.root,'A06_PREP');checker(run,summary,tables,[],'success')
        result=workflow._finish(m,run['run_id'],summary,tables,[],'success',sources=[batch_ref,*run['parent_validation_records'].values(),*sources])
        receipt={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
            'batch_file':batch_ref,'source_run':binding['source_run'],'run_id':run['run_id'],
            'result_file':deepcopy(m['runs'][run['run_id']]['result_file']),'human_review_written':False,'created_at':now()}
        path=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'qualifications'/(new_id('qualification')+'.json')
        write_json(path,receipt);m.setdefault(RECORDS,[]).append(file_record(home,path,'system_qualification_record'));workflow.save(m)
    return result


def execute(workflow,sid,body):
    """失败保存实际请求与已生成文件，不以资格失败覆盖原准备。"""
    try:return _execute(workflow,sid,body)
    except Exception as error:
        if isinstance(body,dict) and set(body)=={'batch_id','expected_preparation_run_id'}:
            with write_lock(workflow.root):
                m=workflow.load(sid);home=workflow.location(sid)
                ref=next((r for r in m.get(execution.BATCHES,[]) if execution.read_batch(workflow,m,r)[0]['batch_id']==body.get('batch_id')),None)
                if ref and not m.get('trashed'):
                    batch,_=execution.read_batch(workflow,m,ref);folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']
                    evidence=folder/'qualification_attempts';files=[file_record(home,p,'qualification_diagnostic') for p in evidence.rglob('*') if p.is_file()] if evidence.exists() else []
                    # 科学发布被拒时，已生成但未登记的运行也保留在失败证据中。
                    for path in (home/'runs/A06_PREP').glob('*/run.json'):
                        candidate=read_json(path)
                        if candidate.get('batch_file')==ref and candidate['config'].get('version')==VERSION and candidate['run_id'] not in m['runs']:
                            files.append(file_record(home,path,'unpublished_system_qualification_run'))
                    value={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'batch_file':ref,'state':'failed',
                        'error_type':type(error).__name__,'error_zh':str(error),'files':files,'human_review_written':False,'created_at':now()}
                    path=folder/'qualification_failures'/(new_id('attempt')+'.json');write_json(path,value)
                    m.setdefault('analysis_plan_system_qualification_failures',[]).append(file_record(home,path,'system_qualification_failure'));workflow.save(m)
        raise
