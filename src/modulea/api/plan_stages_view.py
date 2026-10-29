"""新版阶段只读资格及明确执行接口；科学过程由独立后台处理。"""
from contracts import ContractError
from science_modules.plan_stages_contract import info as stage_info, validate
from .errors import ApiError, from_contract


def info(app,req,sid):
    """同一任务快照决定所有阶段是否忙碌，不在HTTP采集或计算。"""
    value=stage_info(app.kernel.workflow(),sid)
    if app.tasks.active_for(sid):
        for stage in value['stages']:
            stage['enabled']=False;stage['blockers'].append('请等待当前研究后台任务结束')
    return value


def execute(app,req,sid):
    """只允许确认体绑定当前实际资格，不能传入源文件、阈值或批准。"""
    body=req.json()
    try:validate(app.kernel.workflow(),sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_stage',body['operator'].strip(),body)
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'已提交新版'+body['stage']+'；完成后仍须核对结果，未自动批准。'},202
