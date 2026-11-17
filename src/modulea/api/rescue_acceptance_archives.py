"""同修订完整包目录、明确原任务及固定SHA快照下载；GET不打包或登记研究。"""
from contextlib import contextmanager
from urllib.parse import urlencode

from contracts import ContractError, safe_id
from ..core import rescue_acceptance_archives as core
from . import rescue_presentations as presentation
from .download_snapshot import capture_verified
from .errors import ApiError, not_found

TOKENS={'expected_revision_sha256','expected_input_key'}


@contextmanager
def _errors():
    """原件损坏一律拒绝，不把无法核验解释为无包或已完成。"""
    try:yield
    except (ContractError,OSError,KeyError,TypeError,ValueError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','完整包原件无法完整核验：'+str(error)) from error


def _base(sid,rid,revision_id):
    """链接只含稳定编号，不接受客户端路径。"""
    return f'/api/v1/studies/{sid}/runs/{rid}/rescue-presentations/{revision_id}/acceptance-archives'


def _descriptor(sid,rid,revision_id,record,tokens,matches):
    """固定图表回执、完整包回执和实际ZIP SHA，后来的包不改变旧链接。"""
    ref=record['archive_file']
    query=dict(tokens,expected_archive_receipt_sha256=record['file']['sha256'],expected_archive_sha256=ref['sha256'])
    return {'archive_id':record['archive_id'],'receipt_sha256':record['file']['sha256'],
        'archive_sha256':ref['sha256'],'bytes':ref['bytes'],'created_at':record['created_at'],
        'matches_input':matches,'download_url':_base(sid,rid,revision_id)+'/'+record['archive_id']+'/download?'+urlencode(query)}


def directory(app,req,sid,rid,revision_id):
    """只读核对所选版本完整包，不自动打包；忙碌仍可读取历史原件。"""
    presentation._query(req,TOKENS)
    with _errors():
        selected=presentation.select(app,req,sid,rid,revision_id);w=selected['workflow']
        value=w.rescue_acceptance_archive_info(sid,rid,revision_id,min_free_bytes=app.settings.compute_min_free_bytes)
        tokens={key:req.query1(key) for key in TOKENS}
        history=[_descriptor(sid,rid,revision_id,item,tokens,selected['matches_input']) for item in value['history']]
        current=next((item for item in history if value['current'] and item['archive_id']==value['current']['archive_id']),None)
        blockers=list(value['blockers_zh'])
        if app.tasks.active_for(sid):blockers.append('本研究已有活动任务，请等待完成')
        if current:blockers.append('本修订已有完整包，可直接下载，无需重复打包')
        return dict(value,current=current,history=history,enabled=bool(value['enabled'] and not blockers),
                    blockers_zh=blockers,input_key=req.query1('expected_input_key'),
                    receipt_sha256=req.query1('expected_revision_sha256'),matches_input=selected['matches_input'],
                    generate_url=_base(sid,rid,revision_id))


def submit(app,req,sid,rid,revision_id):
    """严格九字段只排原重任务archive阶段，源/实现及状态在worker再次核对。"""
    presentation._query(req,set());body=req.json()
    try:core.confirmed(body)
    except (ContractError,KeyError,TypeError,ValueError) as error:raise ApiError(422,'VALIDATION_FAILED',str(error)) from error
    if body['expected_run_id']!=rid or body['expected_revision_id']!=revision_id:
        raise ApiError(409,'STALE_VERSION','完整包所选运行或图表版本不同')
    if app.tasks.active_for(sid):raise ApiError(409,'TASK_BUSY','本研究已有活动任务，请等待完成')
    try:core.validate_request(app.kernel.workflow(),sid,body,app.settings.compute_min_free_bytes)
    except (ContractError,OSError,KeyError,TypeError,ValueError) as error:raise ApiError(409,'GATE_BLOCKED',str(error)) from error
    task,created=app.tasks.submit(sid,'plan_rescue_presentation',body['author'],{'stage':'archive','request':body})
    if not created:raise ApiError(409,'TASK_BUSY','本研究已有活动任务，请等待完成')
    return {'task':task,'created':True,'message_zh':'本修订完整包已排队落盘；保留全部原件，不重算、不签科研复核。'},202


def download(app,req,sid,rid,revision_id,archive_id):
    """完整原件及ZIP成员全核后，快照中的实际字节才交给HTTP发送。"""
    presentation._query(req,TOKENS|{'expected_archive_receipt_sha256','expected_archive_sha256'})
    try:safe_id(archive_id,'rescuearchive')
    except ContractError as error:raise ApiError(422,'VALIDATION_FAILED',str(error)) from error
    with _errors():
        selected=presentation.select(app,req,sid,rid,revision_id);w=selected['workflow'];m=w.load(sid)
        found=[]
        for ref in m.get(core.INDEX,[]):
            header=core._read(w,sid,ref)
            if (header.get('run_id'),header.get('revision_id'),header.get('archive_id'))==(rid,revision_id,archive_id):found.append(ref)
        if not found:raise not_found('本修订已登记完整包')
        if len(found)!=1:raise ApiError(503,'ARCHIVE_UNAVAILABLE','完整包编号重复登记')
        if found[0]['sha256']!=req.query1('expected_archive_receipt_sha256'):
            raise ApiError(409,'STALE_VERSION','完整包回执已改变，请重新读取')
        record=w.read_rescue_acceptance_archive(sid,found[0]);request=core._read_request(w,m,record['request_file'])
        if request['binding']['presentation_file']!=selected['record']['file']:
            raise ApiError(409,'STALE_VERSION','完整包不属于所选图表修订')
        ref=record['archive_file']
        if ref['sha256']!=req.query1('expected_archive_sha256'):
            raise ApiError(409,'STALE_VERSION','完整包实际字节已改变，请重新读取')
        snapshot=capture_verified(w.location(sid),ref,app.settings.runtime_dir/'acceptance_downloads',
                                  min_free_bytes=app.settings.compute_min_free_bytes)
        return ('verified_snapshot',snapshot,rid+'_'+archive_id+'_完整验收资料.zip','application/zip',False)
