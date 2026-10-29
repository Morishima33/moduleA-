"""独立科学校验只读目录与明确提交；HTTP不运行科学验证器或制造批准。"""
from contracts import ContractError
from ..core import system_validation as core
from .errors import ApiError,from_contract


def info(app,req,sid):
    """当前任务占用时保留只读历史，禁止同时提交同研究校验。"""
    value=core.info(app.kernel.workflow(),sid)
    if app.tasks.active_for(sid):
        for item in value['items']:
            item['enabled']=False;item['blockers'].append('请等待当前研究后台任务结束')
    return value


def execute(app,req,sid):
    """只接受当前运行和输入指纹，不接受校验通过标记、路径或人工签名。"""
    body=req.json();workflow=app.kernel.workflow()
    try:core.validate_request(workflow,sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待当前研究后台任务结束')
    task,created=app.tasks.submit(sid,'plan_system_validation','系统科学校验',body)
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'已提交真实科学校验；回执与人工复核分开归档。'},202
