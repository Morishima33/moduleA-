"""分析参数、方案草稿与A04选择接口；网络和科研运行仍在后台入口。"""

from contracts import ContractError, require, safe_id
from science_modules.analysis_protocol import affected_stages, compile_plan, parameter_catalog
from ..core.analysis_plans import AnalysisPlanConflict
from .errors import ApiError, from_contract


def schema(app, req):
    """参数目录来自统一定义，不在网页维护第二份默认值。"""
    from .analysis_plan_preview import presentation
    return dict(parameter_catalog(), preview=presentation())


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


def a04_selection(app, req, study_id):
    """只提交后台复算和归档；当前版本与批准在任务中再次核验。"""
    body = req.json()
    fields = {"request_id", "expected_a00", "expected_a04", "expected_plan_id", "author", "note"}
    try:
        require(isinstance(body, dict) and set(body) == fields,
                "A04选择字段不完整或含不支持选项")
        safe_id(body["request_id"], "planreq")
        safe_id(body["expected_a00"], "run")
        safe_id(body["expected_a04"], "run")
        safe_id(body["expected_plan_id"], "plan")
        require(isinstance(body["author"], str) and 0 < len(body["author"].strip()) <= 2000,
                "请填写A04选择登记人")
        require(isinstance(body["note"], str) and len(body["note"]) <= 2000,
                "A04选择说明过长或格式不合法")
        workflow = app.kernel.workflow()
        manifest = workflow.load(study_id)
    except ContractError as error:
        raise from_contract(str(error)) from error
    if manifest.get("trashed"):
        raise ApiError(423, "TRASHED_READONLY", "回收站研究只读")
    if (manifest["current"].get("A00") != body["expected_a00"]
            or manifest["current"].get("A04") != body["expected_a04"]):
        raise ApiError(409, "STALE_VERSION", "A00或A04版本已更新，请刷新")
    if not workflow.approved(manifest, body["expected_a04"]):
        raise ApiError(409, "GATE_BLOCKED", "请先通过当前A04")
    task, created = app.tasks.submit(study_id, "a04_plan_selection", body["author"].strip(), body)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
    return {"task": task, "created": True,
            "message_zh": "A04方案受体选择已提交；归档后仍须独立核查，不启动A06。"}, 202
