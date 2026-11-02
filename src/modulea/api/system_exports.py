"""系统同批导出的只读资格、明确排队和安全附件下载；接口不加载图表或Excel依赖。"""
import hashlib
from pathlib import Path

from contracts import ContractError, require
from storage import verified_file
from ..core import system_exports_v2 as registry
from .errors import ApiError, from_contract, not_found


def downloads(sid, value):
    """URL只含本研究导出编号与文件索引，不将相对路径当作下载权限。"""
    if not value: return value
    value = dict(value)
    value['files'] = [dict(ref, name=Path(ref['path']).name,
        download_url=f"/api/v1/studies/{sid}/analysis-plan/system-exports/{value['export_id']}/files/{index}")
        for index, ref in enumerate(value['files'])]
    return value


def info(app, req, sid):
    """不启动任何导出；忙碌只影响新生成，既有下载继续保持。"""
    try: value = registry.info(app.kernel.read_workflow(), sid)
    except ContractError as error: raise from_contract(str(error)) from error
    value['current'] = downloads(sid, value['current']); value['history'] = [downloads(sid, row) for row in value['history']]
    if app.tasks.active_for(sid): value['enabled'] = False; value['blockers'].append('请等待本研究当前任务结束')
    return value


def submit(app, req, sid):
    """一次明确点击仅派生本批已有数据，严格字段及当前输入在worker再次核对。"""
    if app.tasks.active_for(sid): raise ApiError(409, 'GATE_BLOCKED', '请等待本研究当前任务结束')
    body = req.json()
    try: registry.validate_request(app.kernel.read_workflow(), sid, body)
    except ContractError as error: raise from_contract(str(error)) from error
    task, created = app.tasks.submit(sid, 'plan_system_exports', body['author'], body)
    return {'task': task, 'created': created, 'message_zh': '已提交本批导出文件生成；不重算评分或签署复核。'}, 202


def download(app, req, sid, export_id, index):
    """历史只读也逐件核验；返回的同一缓冲区再次核SHA，避免读后换字节。"""
    w = app.kernel.read_workflow(); m = w.load(sid); home = w.location(sid)
    try:
        records = [registry.read_record(w, m, ref) for ref in m.get(registry.INDEX, [])]
        value = next((row for row in records if row['export_id'] == export_id), None)
        if value is None or not 0 <= int(index) < len(value['files']): raise not_found('本研究的导出文件')
        ref = value['files'][int(index)]; path = verified_file(home, ref); raw = path.read_bytes()
        require(len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256'], '导出读取期间文件已改变')
    except ContractError as error: raise from_contract(str(error)) from error
    mime = {'.png': 'image/png', '.svg': 'image/svg+xml', '.csv': 'text/csv; charset=utf-8',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}[path.suffix.lower()]
    return ('download', raw, path.name, mime)
