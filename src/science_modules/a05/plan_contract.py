"""新方案A05标准库契约；科学入口和外壳共用，同源校验不向上依赖。"""
from contracts import require, safe_id
from science_modules.analysis_protocol import VERSION

FIELDS = {"expected_a00", "expected_a03", "expected_a05", "expected_plan_id", "reason"}


def is_current(workflow, manifest):
    """即使是早期显式方案研究，新富集也不能被旧报告/continue接管。"""
    rid=manifest.get('current',{}).get('A05')
    return bool(rid and workflow.run(manifest,rid)['config'].get('version')=='A05.plan_enrichment.1')


def info(workflow, sid):
    """逐次读取当前A03批准和方案，不从PPI或旧研究猜测输入集合。"""
    m = workflow.load(sid)
    a00, a03, a05 = (m["current"].get(key, "") for key in ("A00", "A03", "A05"))
    intake = workflow.result(m, a00)["summary"] if a00 else {}
    supported = intake.get("analysis_plan_profile") == VERSION
    records = workflow._analysis_plan_records(m) if supported else []
    draft = records[-1] if records and records[-1]["expected_a00"] == a00 else None
    blockers = []
    if not supported:
        blockers.append("历史固定研究不启用新方案A05")
    if m.get("trashed"):
        blockers.append("回收站研究只读")
    if not a03 or not workflow.approved(m, a03):
        blockers.append("请先复核通过当前A03交集，不使用PPI候选代替")
    if not draft:
        blockers.append("当前登记尚无有效方案草稿")
    if a03:
        parents = workflow.run(m, a03)["parent_runs"]
        if parents.get("A01"):
            a01 = workflow.run(m, parents["A01"])
            plan_id = a01.get("inputs", {}).get("analysis_plan_id")
            upstream = next((row for row in records if row["plan_id"] == plan_id), None)
            if upstream and draft and any(upstream["plan"]["parameters"][key] != draft["plan"]["parameters"][key]
                                         for key in ("a01.ob_min", "a01.dl_min")):
                blockers.append("当前方案改变了A01门槛，请先生成并复核对应A01及A03，不混用旧交集")
    inputs = workflow.run(m, a05).get("inputs", {}) if a05 else {}
    completed = bool(a05 and draft and inputs.get("analysis_plan_id") == draft["plan_id"] and
                     workflow.run(m, a05)["parent_runs"].get("A03") == a03 and workflow.active(m, a05))
    if completed:
        blockers.append("本方案及本交集已有有效A05，请核查当前结果；变更草稿后可生成新版")
    p = draft["plan"]["parameters"] if draft else {}
    applicable = bool(p.get('a05.include_go') or p.get('a05.include_kegg'))
    if draft and not applicable:
        blockers.append('本方案GO与KEGG均未纳入，富集不适用，不启动R；后续报告须明确说明')
    return {"supported": supported, "protocol_version": "A05.plan_enrichment.1", "enabled": not blockers,
            "blockers": blockers, "expected_a00": a00, "expected_a03": a03, "expected_a05": a05,
            "expected_plan_id": draft["plan_id"] if draft else "", "parameter_hash": draft["plan"]["parameter_hash"] if draft else "",
            "parameters": {key.removeprefix("a05."): value for key, value in p.items() if key.startswith("a05.")},
            "completed": completed, "applicable": applicable,
            "message_zh": "使用本研究已批准A03及固定注释，按方案执行ORA；结果待独立复核，完整自动接续尚未开放。"}


def validate(workflow, sid, body):
    """拒绝参数/路径覆盖；启动前以本研究全部预期版本重新核验。"""
    require(isinstance(body, dict) and set(body) == FIELDS, "新方案A05请求字段不完整或含未支持选项")
    for key, prefix in (("expected_a00", "run"), ("expected_a03", "run"), ("expected_plan_id", "plan")):
        safe_id(body[key], prefix)
    require(isinstance(body["expected_a05"], str), "A05版本格式无效")
    if body["expected_a05"]:
        safe_id(body["expected_a05"], "run")
    require(isinstance(body["reason"], str) and 0 < len(body["reason"].strip()) <= 2000, "请填写本次富集依据，最多2000字")
    value = info(workflow, sid)
    require(not workflow.load(sid).get("trashed"), "回收站研究只读")
    require(all(body[key] == value[key] for key in FIELDS - {"reason"}), "A05登记、交集或方案已改变，请刷新")
    require(value["enabled"], "上游条件未就绪：" + "；".join(value["blockers"]))
    return value
