"""一次系统批次的真实评分与同批未完成组合续算，人工批准含义保持。"""
from copy import deepcopy
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution as execution

VERSION='A06.system_scoring.1'
RECORDS='analysis_plan_system_scoring_records'
FAILURES='analysis_plan_system_scoring_failures'


def execute(workflow,sid,body,tools,progress):
    """内部公开入口只绑定当前批次/准备；工具及参数不由客户端提供。"""
    require(isinstance(body,dict) and set(body)=={'batch_id','expected_preparation_run_id','expected_scoring_run_id'},'系统评分请求字段错误')
    safe_id(body['batch_id'],'systembatch');safe_id(body['expected_preparation_run_id'],'run')
    if body['expected_scoring_run_id'] is not None:safe_id(body['expected_scoring_run_id'],'run')
    from science_modules.a06 import system_scoring as science
    science.check_tools(tools)
    with write_lock(workflow.root):
        m=workflow.load(sid);home=workflow.location(sid);current=m['current'].get('A06');run=None
        if current:
            candidate=workflow.run(m,current)
            if candidate['config'].get('version')==VERSION:
                request=read_json(verified_file(home,candidate['inputs']['scoring_request']))
                require(request['request']==body and workflow.active(m,current),'系统评分已有不同请求或准备已失效')
                if m['runs'][current]['result_file']:return workflow.result(m,current)
                run=candidate
        if run is None:require(current==body['expected_scoring_run_id'],'当前评分版本已改变')
    if run is None:
        m=workflow.load(sid);prep=workflow.run(m,body['expected_preparation_run_id'])
        require(m['current'].get('A06_PREP')==prep['run_id'] and prep['config'].get('version')=='A06.system_qualification.1',
            '系统评分要求当前实际系统资格准备')
        batch_ref=prep['batch_file'];batch,plan=execution.require_batch(workflow,m,batch_ref)
        require(batch['batch_id']==body['batch_id'],'评分准备不属于本批')
        parents={'A06_PREP':prep['run_id']};execution.ensure_parents(workflow,sid,parents)
        with write_lock(workflow.root):
            m=workflow.load(sid);execution.require_batch(workflow,m,batch_ref)
            require(m['current'].get('A06')==body['expected_scoring_run_id'] and m['current'].get('A06_PREP')==prep['run_id'],
                '评分准备或当前版本已改变')
            require(workflow.result(m,prep['run_id'])['summary']['ready_pairs']>0,'本批无可用组合，评分不适用，不启动Vina')
            request={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
                'batch_file':batch_ref,'parent_validation_records':execution.parent_records(workflow,m,parents),
                'human_review_written':False,'created_at':now()}
            path=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'scoring_requests'/(new_id('scorerequest')+'.json')
            write_json(path,request);request_ref=file_record(home,path,'system_scoring_request')
            inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],'analysis_plan_id':plan['plan_id'],
                'analysis_plan_file':deepcopy(batch['plan_file']),'analysis_parameter_hash':plan['plan']['parameter_hash'],
                'preparation_run':deepcopy(m['runs'][prep['run_id']]['run_file']),
                'preparation_result':deepcopy(m['runs'][prep['run_id']]['result_file']),
                'system_input_ref':prep['inputs']['system_input_ref'],'scoring_request':request_ref}
            config=science.configuration(prep)
            run=execution.begin(workflow,m,'A06',inputs,config,batch['request']['note'],batch_ref,parents);workflow.save(m)
    try:
        summary,tables,sources=science.compute(workflow,sid,run,tools,progress)
        with write_lock(workflow.root):
            m=workflow.load(sid);require(workflow.active(m,run['run_id']),'评分发布前准备或人工决定已改变')
            checker=execution.validation.canonical_validator(workflow.root,'A06')
            outcome='success' if summary['scored_pairs'] else 'failed';checker(run,summary,tables,[],outcome)
            result=workflow._finish(m,run['run_id'],summary,tables,[],outcome,sources=sources)
            record={'schema_version':VERSION,'study_id':sid,'run_id':run['run_id'],'batch_file':run['batch_file'],
                'request_file':run['inputs']['scoring_request'],'result_file':deepcopy(m['runs'][run['run_id']]['result_file']),
                'human_review_written':False,'created_at':now()}
            path=home/'decisions/analysis_plans/system_batches'/body['batch_id']/'scoring_receipts'/(new_id('scorereceipt')+'.json')
            write_json(path,record);m.setdefault(RECORDS,[]).append(file_record(home,path,'system_scoring_record'));workflow.save(m)
        return result
    except Exception as error:
        with write_lock(workflow.root):
            m=workflow.load(sid);home=workflow.location(sid);folder=home/'runs/A06'/run['run_id']/'system_scoring'
            value={'schema_version':VERSION,'study_id':sid,'run_id':run['run_id'],'batch_file':run['batch_file'],
                'state':'failed','error_type':type(error).__name__,'error_zh':str(error),'human_review_written':False,
                'files':[file_record(home,p,'system_scoring_diagnostic') for p in folder.rglob('*') if p.is_file()],'created_at':now()}
            path=home/'decisions/analysis_plans/system_batches'/body['batch_id']/'scoring_failures'/(new_id('attempt')+'.json')
            write_json(path,value);m.setdefault(FAILURES,[]).append(file_record(home,path,'system_scoring_failure'));workflow.save(m)
        raise
