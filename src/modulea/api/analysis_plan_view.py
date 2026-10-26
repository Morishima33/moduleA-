"""分析参数与方案草稿接口；仅标准库校验和Workflow写入，无科研执行。"""

from contracts import ContractError, require
from science_modules.analysis_protocol import affected_stages, compile_plan, parameter_catalog
from ..core.analysis_plans import AnalysisPlanConflict
from .errors import ApiError, from_contract


def schema(app, req):
    """参数目录来自统一定义，不在网页维护第二份默认值。"""
    return parameter_catalog()


def validate(app, req):
    """校验草稿及重算范围，不保存输入或触发任务。"""
    body = req.json()
    try:
        require(isinstance(body, dict) and "specification" in body and set(body) <= {"specification", "previous"}, "参数校验请求字段无效")
        plan = compile_plan(body["specification"])
        impact = affected_stages(body["previous"], plan) if "previous" in body else None
    except ContractError as error:
        raise from_contract(str(error)) from error
    return {"plan": plan, "impact": impact, "execution_available": False}


def info(app, req, study_id):
    """旧研究只读显示不支持，不追加新方案。"""
    return app.kernel.workflow().analysis_plan_info(study_id)


def draft(app, req, study_id):
    """追加草稿时允许旧批继续，绝不以保存草稿代替执行确认。"""
    try:
        result = app.kernel.workflow().save_analysis_plan_draft(study_id, req.json())
    except AnalysisPlanConflict as error:
        raise ApiError(409, "STALE_VERSION", str(error)) from error
    except ContractError as error:
        raise from_contract(str(error)) from error
    return result, 201 if result["created"] else 200
