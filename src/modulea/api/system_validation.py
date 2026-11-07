"""独立科学校验只读目录与明确提交；HTTP不运行科学验证器或制造批准。"""
from contracts import ContractError
from ..core import system_validation as core
from .errors import ApiError,from_contract


def info(app,req,sid,*,workflow=None):
    """当前任务占用时保留只读历史，禁止同时提交同研究校验。"""
    workflow=workflow or app.kernel.read_workflow()
    if getattr(workflow,'_view_cache',None) is None:
        with workflow.handoff_read_cache():value=core.info(workflow,sid)
    else:value=core.info(workflow,sid)
    if app.tasks.active_for(sid):
        for item in value['items']:
            item['enabled']=False;item['blockers'].append('请等待当前研究后台任务结束')
    # 原资格、状态和校验结果不变；完整证据在归档/追溯中，不在每个首屏重复数MB。
    def summary(item):
        return {key:item[key] for key in ('validation_id','module_id','run_id','passed','label_zh','created_at','error_zh','scientific_status')}
    value['history']=[summary(item) for item in value['history']]
    for item in value['items']:
        if item['current']:item['current']=summary(item['current'])
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
