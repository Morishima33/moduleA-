"""新方案A05展示只读接口和明确任务提交，HTTP不绘图或执行R。"""
import mimetypes
from contracts import ContractError
from storage import verified_file
from ..core import plan_a05_display as core
from .errors import ApiError,from_contract


def info(app,req,sid):
    """资格和同批已归档图件链接来自服务端，不根据前端数值猜测。"""
    value=core.info(app.kernel.workflow(),sid)
    if value['supported'] and app.tasks.active_for(sid):
        value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    if value.get('current'):
        current=value['current'];current['downloads']=[{'index':index,'name':ref['path'].rsplit('/',1)[-1],
            'url':f"/api/v1/studies/{sid}/analysis-plan/a05-display/{current['display_id']}/files/{index}"} for index,ref in enumerate(current['figures'])]
    return value


def execute(app,req,sid,action):
    """只接受明确同批决定，不接受科学参数、来源或路径替换。"""
    body=req.json()
    try:core.validate(app.kernel.workflow(),sid,body,action)
    except ContractError as error:raise from_contract(str(error)) from error
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待当前研究后台任务结束')
    task,created=app.tasks.submit(sid,'a05_plan_display',body['author'].strip(),{'action':action,'request':body})
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'已提交本批展示资料与明确决定，不重算R或批准A05。'},202


def file(app,req,sid,display_id,index):
    """只下载本研究已登记的图件；当前与历史都核验来源和实际文件。"""
    workflow=app.kernel.workflow();m=workflow.load(sid)
    for ref in m.get(core.INDEX,[]):
        value=core.read_record(workflow,m,ref)
        if value['display_id']==display_id:
            number=int(index)
            if number<0 or number>=len(value['figures']):raise ApiError(404,'NOT_FOUND','找不到本批展示图件')
            path=verified_file(workflow.location(sid),value['figures'][number]);mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            return ('file',path,path.name,mime,req.query1('inline')=='1' and mime.startswith('image/'))
    raise ApiError(404,'NOT_FOUND','找不到本研究登记的展示版本')
