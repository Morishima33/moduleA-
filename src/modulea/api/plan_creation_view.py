"""新模式建档接口：显式预检与确认，所有研究写入经Workflow公开入口。"""
import json

from contracts import ContractError
from ..core.plan_creation import context
from ..core.study_creation import CreationConflict
from .errors import ApiError, from_contract


def invoke(function, body):
    """沿用原建档的NLM错误和冲突状态，不把网络失败当成身份不匹配。"""
    try:
        return function(body)
    except CreationConflict as error:
        raise ApiError(409, 'CREATE_CONFLICT', str(error)) from error
    except ContractError as error:
        if '暂时无法连接NLM' in str(error):
            raise ApiError(503, 'MESH_UNAVAILABLE', str(error), retryable=True) from error
        raise from_contract(str(error)) from error


def preflight(app, req):
    """预检只写运行凭证，不产生研究、复核或任务。"""
    return invoke(app.plan_creation.preflight, req.json())


def create(app, req):
    """一次明确确认将登记和初始方案共同发布。"""
    value = invoke(app.plan_creation.create, req.json())
    return value, 201 if value['created'] else 200


def info(app, req, sid):
    """只读显示初始和当前方案，不能把新草稿当成已运行方案。"""
    try:
        return context(app.kernel.workflow(), sid)
    except ContractError as error:
        raise from_contract(str(error)) from error


def export(app, req, sid):
    """下载绑定本研究初始A00的预检与方案，不下载运行凭证目录。"""
    value = info(app, req, sid)
    if value is None:
        raise ApiError(404, 'NOT_FOUND', '本研究不是新方案建档协议')
    return ('download', json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'),
            sid + '_creation_plan.json', 'application/json; charset=utf-8')
