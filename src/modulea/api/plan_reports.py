"""新方案报告只读资格、明确后台生成及已登记历史文档下载。"""
from contracts import ContractError
from storage import verified_file
from ..core import report_registry as core
from ..core import report_archive_repair as repairs
from .errors import ApiError,from_contract


def info(app,req,sid):
    """下载链接只取真实归档文件，不能由浏览器提供路径。"""
    workflow=app.kernel.workflow();value=core.info(workflow,sid);m=workflow.load(sid)
    if app.tasks.active_for(sid):value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    for item in value['history']:
        result=workflow.result(m,item['run_id']);item['downloads']=[{'label_zh':'主报告' if index==0 else '简略版',
            'name':ref['path'].rsplit('/',1)[-1],'url':f"/api/v1/studies/{sid}/analysis-plan/reports/{item['run_id']}/files/{index}"}
            for index,ref in enumerate(result['tables']['report_files'])]
        for reference in m.get(repairs.RECEIPTS,[]):
            receipt=repairs.read_receipt(workflow,m,reference)
            if receipt['run_id']==item['run_id']:
                item['downloads'].append({'label_zh':'用户批注版（保留'+str(receipt['annotation_evidence']['comment_count'])+'条批注）',
                    'name':'简略版_用户批注.docx' if receipt['original_file']['role']=='brief_report' else '主报告_用户批注.docx',
                    'url':f"/api/v1/studies/{sid}/analysis-plan/reports/{item['run_id']}/annotations/{receipt['repair_id']}"})
    return value


def execute(app,req,sid):
    """只受理当前明确生成请求，实际事实和图表均由科学worker产生。"""
    body=req.json()
    try:payload=core.queued_payload(app.kernel.workflow(),sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待当前研究后台任务结束')
    task,created=app.tasks.submit(sid,'plan_report',body['author'].strip(),payload)
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'已提交同批主报告与简略版生成；科学状态及人工复核如实保留。'},202


def file(app,req,sid,rid,index):
    """只取本研究已登记的Word；历史报告仍可核对原件，不把历史当当前可用。"""
    workflow=app.kernel.workflow();m=workflow.load(sid)
    for model in core.PROTOCOLS:
        for reference in m.get(model.RECEIPTS,[]):
            value=model.read_receipt(workflow,m,reference)
            if value['run_id']==rid:
                refs=workflow.result(m,rid)['tables']['report_files'];number=int(index)
                if number<0 or number>=len(refs):raise ApiError(404,'NOT_FOUND','找不到该报告文档')
                path=verified_file(workflow.location(sid),refs[number])
                return 'file',path,path.name,'application/vnd.openxmlformats-officedocument.wordprocessingml.document',False
    raise ApiError(404,'NOT_FOUND','找不到本研究登记的报告版本')


def annotation_file(app,req,sid,rid,repair_id):
    """仅下载本研究恢复回执登记的批注原字节，不开放路径或未登记文件。"""
    workflow=app.kernel.workflow();m=workflow.load(sid)
    for reference in m.get(repairs.RECEIPTS,[]):
        receipt=repairs.read_receipt(workflow,m,reference)
        if receipt['run_id']==rid and receipt['repair_id']==repair_id:
            path=verified_file(workflow.location(sid),receipt['annotation_file'])
            name=('简略版' if receipt['original_file']['role']=='brief_report' else '主报告')+'_用户批注.docx'
            return 'file',path,name,'application/vnd.openxmlformats-officedocument.wordprocessingml.document',False
    raise ApiError(404,'NOT_FOUND','找不到本研究登记的批注版')
