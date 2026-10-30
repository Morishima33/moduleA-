"""系统三库获取只读进度和严格任务入口；HTTP不执行科学解析或联网。"""
from contracts import ContractError
from ..core import system_acquisition as core
from .errors import ApiError,from_contract


def info(app,req,sid):
    """逐请求展示真实逐库事实及恢复条件；GET不排队、重试或改变研究。"""
    w=app.kernel.workflow();m=w.load(sid);home=w.location(sid);value=core.info(w,sid)
    value['busy']=bool(app.tasks.active_for(sid));value['requests']=[]
    groups={}
    for kind,index in (('record',core.RECORDS),('failure',core.FAILURES),('source',core.SOURCES)):
        groups[kind]=[(ref,core.read_record(w,m,ref,kind=kind)) for ref in m.get(index,[])]
    for ref in m.get(core.REQUESTS,[]):
        request=core.read_record(w,m,ref,kind='request');records=[r for _,r in groups['record'] if r['request_file']==ref]
        failures=[r for _,r in groups['failure'] if r['request_file']==ref]
        ready=[r['source'] for _,r in groups['source'] if r['request_file']==ref]
        latest=records[-1] if records else None;blockers=[]
        try:core.require_current(w,m,request)
        except ContractError as error:blockers.append(str(error))
        if value['busy']:blockers.append('请等待当前研究后台任务结束')
        value['requests'].append({'request_id':request['request']['request_id'],'request':request['request'],
            'plan_id':request['request']['expected_plan_id'],'created_at':request['created_at'],
            'state':latest['state'] if latest else 'incomplete','sources':latest['sources'] if latest else ready,
            'source_checkpoints':ready,
            'record_count':len(records),'failure_count':len(failures),'source_receipt_count':len(ready),
            'retry_enabled':not blockers,'retry_blockers':blockers,'message_zh':latest['message_zh'] if latest else '获取未形成整批记录；已归档成功库可核验恢复'})
    if value['busy']:value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    value['message_zh']='获取仅归档本研究三库原件；失败不是零结果，尚不发布A01或自动接入科学批次。'
    return value


def execute(app,req,sid):
    """只验证明确确认和当前输入后排队，后台再次核对；拒绝浏览器路径及通过标记。"""
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待本研究当前任务结束')
    try:body=core.validate_request(app.kernel.workflow(),sid,req.json())
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_system_acquisition',body['author'],body)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究当前已有任务，请在任务结束后明确重试原请求')
    return {'task':task,'created':True,'request_id':body['request_id'],
        'message_zh':'已提交三库原件获取；成功库立即留存，缺库使任务失败，尚不发布科学A01。'},202
