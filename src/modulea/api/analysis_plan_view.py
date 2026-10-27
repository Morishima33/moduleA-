"""分析参数、A04选择复核与A06准备输入接口；科研运行仍在后台入口。"""

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


def a04_selection_review(app, req, study_id, selection_id):
    """人工选择复核经Workflow写锁保存，路径和正文必须绑定同一记录。"""
    body = req.json()
    try:
        require(isinstance(body, dict) and body.get("selection_id") == selection_id,
                "A04选择复核路径与正文编号不一致")
        result = app.kernel.workflow().review_analysis_plan_a04_selection(study_id, body)
    except AnalysisPlanConflict as error:
        raise ApiError(409, "STALE_VERSION", str(error)) from error
    except ContractError as error:
        raise from_contract(str(error)) from error
    return result, 201 if result["created"] else 200


def a06_preparation_input(app, req, study_id):
    """只提交准备输入归档任务，真正结构准备和Vina仍须后续入口。"""
    body = req.json()
    fields = {"request_id", "expected_a00", "expected_a03", "expected_a03_select",
              "expected_a04", "expected_selection_id", "expected_selection_review_id",
              "expected_plan_id", "author", "note"}
    try:
        require(isinstance(body, dict) and set(body) == fields,
                "A06准备输入字段不完整或含不支持选项")
        safe_id(body["request_id"], "planreq")
        for key in ("expected_a00", "expected_a03", "expected_a03_select", "expected_a04"):
            safe_id(body[key], "run")
        safe_id(body["expected_selection_id"], "selection")
        safe_id(body["expected_selection_review_id"], "selectionreview")
        safe_id(body["expected_plan_id"], "plan")
        require(all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 2000
                    for key in ("author", "note")), "请填写A06准备输入登记人与依据")
        manifest = app.kernel.workflow().load(study_id)
    except ContractError as error:
        raise from_contract(str(error)) from error
    if manifest.get("trashed"):
        raise ApiError(423, "TRASHED_READONLY", "回收站研究只读")
    if any(manifest["current"].get(module) != body[key] for module, key in
           (("A00", "expected_a00"), ("A03", "expected_a03"),
            ("A03_SELECT", "expected_a03_select"), ("A04", "expected_a04"))):
        raise ApiError(409, "STALE_VERSION", "A06准备上游版本已更新，请刷新")
    task, created = app.tasks.submit(study_id, "a06_plan_input", body["author"].strip(), body)
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
    return {"task": task, "created": True,
            "message_zh": "新版A06准备输入已提交；归档不代表结构质控通过或允许Vina执行。"}, 202
