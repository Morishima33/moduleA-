"""新版受体选择至固定输入的只读网页信息，不在HTTP重新计算科学名单。"""
from modulea.core.plan_selection_ui import info as read_info


def info(app,req,sid):
    """统一任务快照关闭正在运行研究的重复操作。"""
    value=read_info(app.kernel.workflow(),sid)
    if value['supported'] and app.tasks.active_for(sid):
        for operation in value['operations'].values():
            operation['enabled']=False;operation['blockers'].append('请等待当前研究后台任务结束')
    return value
