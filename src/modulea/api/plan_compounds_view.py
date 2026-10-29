"""新方案成分选择的资格与后台提交接口；HTTP只读取原始排名。"""
from contracts import ContractError
from modulea.core.plan_compounds import info as read_info, validate
from .errors import ApiError, from_contract


def info(app,req,sid):
    """返回当前归档与真实阻塞，名单只由科学任务计算。"""
    value=read_info(app.kernel.workflow(),sid)
    if app.tasks.active_for(sid):
        value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    return value


def execute(app,req,sid):
    """严格确认体进入独立任务，不能从客户端接收拟造科学名单。"""
    body=req.json()
    try:validate(app.kernel.workflow(),sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'a03_plan_selection',body['operator'].strip(),body)
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'已提交本方案成分名单生成，完成后仍须独立复核。'},202
