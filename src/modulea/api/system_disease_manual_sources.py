"""手动原件严格multipart预检与排队；HTTP不解析表格或签署登记。"""
from hashlib import sha256
from uuid import uuid4
from contracts import ContractError,require
from ..core import system_disease_manual_sources as core
from .errors import ApiError,from_contract

FORM_FIELDS={'request_id','expected_a00','expected_plan_id','expected_input_hash','author','note','confirmed',
    'database','format','query','retrieved_at','version','encoding','query_quoted','export_completeness'}


def info(app,req,sid):
    """只显示真实原件字节、元信息和当前资格，不把待解析原件显示成零条。"""
    value=core.info(app.kernel.workflow(),sid);value['busy']=bool(app.tasks.active_for(sid))
    if value['busy']:value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    return value


def upload(app,req,sid):
    """固定文件名与真实SHA进入队列，客户端不能提供服务端路径或批准字段。"""
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待本研究当前任务结束')
    fields,files=req.multipart()
    try:
        require(set(fields)==FORM_FIELDS and set(files)=={'upload'},'手动上传字段错误，只接受一个原件，不接收路径、地址或通过覆盖')
        require(fields['confirmed']=='yes','请明确确认本研究原件上传')
        raw=files['upload']['data'];require(0<len(raw)<=core.MAX_BYTES,'上传原件为空或超出16MiB边界')
        source={k:fields[k] for k in core.SOURCE_FIELDS-{'name'}};source['name']=files['upload']['name']
        body={k:fields[k] for k in ('request_id','expected_a00','expected_plan_id','expected_input_hash','author','note')}
        body.update(confirmed=True,source=source);core.validate_request(app.kernel.workflow(),sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    folder=app.settings.runtime_dir/'upload_queue';folder.mkdir(parents=True,exist_ok=True)
    name=uuid4().hex+'.bin';(folder/name).write_bytes(raw)
    payload={'request':body,'blob_name':name,'blob_sha256':sha256(raw).hexdigest(),'blob_bytes':len(raw)}
    task,created=app.tasks.submit(sid,'plan_system_disease_manual_source',body['author'],payload)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究当前已有任务，上传字节保留，请刷新后明确重试')
    return {'task':task,'created':True,'request_id':body['request_id'],
        'message_zh':'已提交原件校验与预上传；不会批准登记或生成疾病候选。'},202
