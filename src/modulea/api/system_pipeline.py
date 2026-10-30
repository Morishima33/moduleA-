"""统一后台执行的标准库接口：一次批次确认、明确续做及真实流水只读。"""
from contracts import ContractError,require
from ..core import system_execution,system_pipeline
from .errors import ApiError,from_contract


def info(app,req,sid):
    """只读已有批次与流水；不联网计算、不自动重试或替用户确认。"""
    w=app.kernel.workflow();value=system_pipeline.info(w,sid);value['start']=system_execution.info(w,sid)
    try:system_pipeline.required_inputs(w,w.load(sid))
    except ContractError as error:
        value['start']['enabled']=False;value['start']['blockers'].append(str(error))
    value['busy']=bool(app.tasks.active_for(sid));return value


def execute(app,req,sid,*,start=False):
    """HTTP只登记原一次授权并排队，科学处理在独立worker；缺资料仍如实失败。"""
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待本研究当前任务结束')
    w=app.kernel.workflow();body=req.json()
    try:
        require(not w.load(sid).get('trashed'),'回收站研究只读')
        if start:
            m=w.load(sid);original=None
            for ref in m.get(system_execution.BATCHES,[]):
                candidate,_=system_execution.read_batch(w,m,ref)
                if isinstance(body,dict) and candidate['request']['request_id']==body.get('request_id'):original=candidate;break
            # 新确认先查必需五库原件；原确认重试仍按原批绑定的原件核对。
            system_pipeline.required_inputs(w,m,original)
            batch=w.start_analysis_plan_system_batch(sid,body);m=w.load(sid)
            payload={'batch_id':batch['batch_id'],'expected_input_hash':system_pipeline.state_hash(w,m,batch['file'])}
        else:
            batch=system_pipeline.validate_request(w,sid,body);payload=body
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_system_pipeline',batch['request']['author'],payload)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究当前已有任务；已登记批次保留，可在任务结束后明确续做')
    return {'task':task,'created':True,'batch_id':batch['batch_id'],
        'message_zh':'已提交本批统一后台执行；失败和NA保留，结论仍需独立复核。'},202
