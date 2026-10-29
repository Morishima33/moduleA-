"""新版准备的只读条件及明确执行接口，科学准备只在原隔离后台运行。"""
from contracts import ContractError
from modulea.core.plan_preparation_ui import info as read_info, validate
from .errors import ApiError, from_contract


def blockers(app,sid):
    """只检查本机配置和研究任务，不在HTTP启动科学工具。"""
    reasons=[]
    if app.tasks.active_for(sid):reasons.append('请等待当前研究后台任务结束')
    tools=app.kernel.settings.science_tools_root
    if tools is None:reasons.append('本机未配置固定科学工具目录')
    elif not (tools/'environments/vina_1.2.7/vina_1.2.7_win.exe').is_file():reasons.append('固定工具目录缺少Vina 1.2.7')
    return reasons


def info(app,req,sid):
    """界面只有实际就绪时才允许明确启动，GET不写入或计算。"""
    value=read_info(app.kernel.workflow(),sid)
    if value['supported']:
        value['blockers'].extend(blockers(app,sid));value['enabled']=not value['blockers']
    return value


def execute(app,req,sid):
    """拒绝浏览器传入参数、路径或伪造状态，后台再核对全部版本。"""
    body=req.json()
    try:validate(app.kernel.workflow(),sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    reasons=blockers(app,sid)
    if reasons:raise ApiError(409,'GATE_BLOCKED','；'.join(reasons))
    task,created=app.tasks.submit(sid,'a06_plan_preparation_ui',body['author'].strip(),body)
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'本批结构与配体准备已提交，失败留NA及原因；未评分或自动批准。'},202
