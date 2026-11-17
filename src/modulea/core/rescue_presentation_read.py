"""明确图表修订的共用只读选择；原件/归属与当前适用性分开核验。"""
from copy import deepcopy

from contracts import ContractError, fingerprint, require, safe_id
from . import rescue_presentations as core
from .rescue_result_read import load_rescue_result, same_file


def matches_current(w,m,record,bound=None):
    """沿原API规则核同协议科学来源，生成实现/本机字体改变不能隐藏归档原图。"""
    request=core._read_request(w,m,record['request_file'])
    if bound is None:
        try:
            current,basis,_,source=core._context(w,m['study_id'],record['run_id'])
            require(fingerprint(current)==fingerprint(m),'名称修订适用性读取期间登记改变')
            bound,_=core._binding(w,m,basis,source,font_path=w.location(m['study_id'])/request['font_file']['path'])
        except (ContractError,KeyError,OSError,ValueError,TypeError):return False
    readable=deepcopy(bound);readable['font']=deepcopy(request['binding']['font'])
    readable['implementation']=deepcopy(request['binding']['implementation'])
    return core.compatible_binding(w,m,request['binding'],readable)


def select_presentation(w,sid,rid,revision_id):
    """只读取明确登记的修订，不能用后来current或目录存在替代授权。"""
    safe_id(rid,'run');safe_id(revision_id,'rescueview');m=w.load(sid)
    require(rid in m['runs'],'本研究评分运行未登记')
    found=[]
    for ref in m.get(core.INDEX,[]):
        header=core._read(w,sid,ref)
        if header.get('run_id')==rid and header.get('revision_id')==revision_id:found.append(ref)
    require(len(found)==1,'本运行没有唯一已登记图表修订')
    record=w.read_rescue_presentation(sid,found[0]);request=core._read_request(w,m,record['request_file'])
    bound=request['binding'];bundle=load_rescue_result(w,m,sid,rid)
    require(record['study_id']==sid and record['run_id']==rid
            and same_file(bundle[4]['tables']['scoring_packet'][0],bound['source']['scoring_packet']),
            '图表修订与明确评分包不同')
    ref=next(ref for ref in record['files'] if ref['role']=='a06_rescue_display_view')
    value={'workflow':w,'manifest':m,'home':w.location(sid),'record':record,'request':request,
           'binding':bound,'bundle':bundle,'view':core._read(w,sid,ref)}
    require(fingerprint(w.load(sid))==fingerprint(m),'图表修订读取期间登记改变')
    return value
