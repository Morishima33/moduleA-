"""版本例外的严格任务入口；标准库预检，不在HTTP解析或发布科学候选。"""
from contracts import ContractError
from ..core import historical_disease_sources as core
from .errors import ApiError,from_contract


def info(app,req,sid):
    """只读原件和用户限定例外，不发出网络查询。"""
    if req.query:raise ApiError(422,'VALIDATION_FAILED','历史版本例外不接受额外参数')
    try:value=core.info(app.kernel.read_workflow(),sid)
    except ContractError as error:raise from_contract(str(error)) from error
    value['busy']=bool(app.tasks.active_for(sid))
    if value['busy']:value['enabled']=False;value['blockers'].append('请等待当前研究任务结束')
    return value


def publish(app,req,sid):
    """只接受明确原件和真实用户决定，排队后由科学worker再核验。"""
    if req.query:raise ApiError(422,'VALIDATION_FAILED','例外提交不接受额外参数')
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待当前研究任务结束')
    try:body=core.validate_request(app.kernel.read_workflow(),sid,req.json())
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_historical_disease_sources',body['author'],body)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究已有任务，请稍后明确重试')
    return {'task':task,'created':True,'request_id':body['request_id'],'message_zh':'已提交本研究历史版本例外候选整理；版本仍未知，不批准身份或启动下游。'},202
