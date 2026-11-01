"""系统A01原件核对的只读接口；不接受决定、路径或外部URL。"""
import json
from urllib.parse import urlencode
from contracts import ContractError,fingerprint
from ..core import component_identity_evidence as core
from .errors import ApiError,from_contract


def _value(app,sid):
    """只读当前版，保留具体指纹/来源错误，不把损坏当空清单。"""
    try:return core.info(app.kernel.read_workflow(),sid)
    except ContractError as error:raise from_contract(str(error)) from error


def info(app,req,sid):
    """只组装当前版本的安全附件编号和导出链接。"""
    if req.query:raise ApiError(422,'VALIDATION_FAILED','本核对入口不接受额外参数')
    value=_value(app,sid)
    if value['supported']:
        base=f'/api/v1/studies/{sid}/analysis-plan/component-identity-evidence'
        binding=urlencode({'expected_a01':value['expected_a01'],'expected_input_hash':value['expected_input_hash']})
        value['export_json_url']=base+'/export?'+binding+'&format=json'
        value['export_csv_url']=base+'/export?'+binding+'&format=csv'
        for row in value['files']:row['url']=base+'/files/'+str(row['index'])+'?'+binding
    return value


def _bound(app,req,sid,extra=()):
    """旧链接遇到运行或来源变化就拒绝，不静默下载新版本。"""
    allowed={'expected_a01','expected_input_hash',*extra}
    if set(req.query)!=allowed or any(len(values)!=1 for values in req.query.values()):
        raise ApiError(422,'VALIDATION_FAILED','核对下载字段错误，不接受路径或通过标记')
    value=_value(app,sid)
    if not value['supported'] or req.query1('expected_a01')!=value['expected_a01'] or req.query1('expected_input_hash')!=value['expected_input_hash']:
        raise ApiError(409,'STALE_VERSION','核对版本已改变，请刷新后重新下载')
    return value


def export(app,req,sid):
    """JSON保留完整原响应摘要，CSV保留逐个原问题，不修改科学结果。"""
    if req.query1('format') not in ('json','csv'):raise ApiError(422,'VALIDATION_FAILED','请选择JSON或CSV')
    value=_bound(app,req,sid,('format',));fmt=req.query1('format')
    raw=core.export_csv(value) if fmt=='csv' else json.dumps(value,ensure_ascii=False,indent=2).encode('utf8')
    _unchanged(app,sid,value)
    return ('download',raw,f'{sid}_{value["expected_a01"]}_identity_evidence.{fmt}',
            'text/csv; charset=utf-8' if fmt=='csv' else 'application/json; charset=utf-8')


def file(app,req,sid,index):
    """只取当前核对清单中的编号，原字节重核后以附件发送。"""
    if len(index)>9:raise ApiError(404,'NOT_FOUND','本版不存在该核对原件')
    value=_bound(app,req,sid);number=int(index)
    if number>=len(value['files']):raise ApiError(404,'NOT_FOUND','本版不存在该核对原件')
    ref=value['files'][number]['file']
    try:raw=core.read_bytes(app.kernel.read_workflow().location(sid),ref)
    except ContractError as error:raise from_contract(str(error)) from error
    _unchanged(app,sid,value)
    suffix=ref['path'].rsplit('.',1)[-1]
    if suffix not in ('json','tsv','bin','gz'):suffix='bin'
    return ('download',raw,f'{sid}_{value["expected_a01"]}_evidence_{number}.{suffix}','application/octet-stream')


def _unchanged(app,sid,value):
    """组装或读取下载字节后再次核对当前绑定，避免并发替换造成混用。"""
    if fingerprint(core.snapshot(app.kernel.read_workflow().load(sid)))!=value['expected_input_hash']:
        raise ApiError(409,'STALE_VERSION','核对版本已改变，请刷新后重新下载')
