"""A00 研究登记的展示适配。"""

from __future__ import annotations

from .base import Parts, clean, kpi, param, pick, table


def present_a00(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    mesh = s.get("mesh_verification") or {}
    parts = Parts()
    parts.kpis = clean([
        kpi("方剂", pick(s, "formula"), pick(s, "herbs", default="")),
        kpi("疾病", pick(s, "disease"), pick(s, "mesh_term", default="")),
        kpi("MeSH 编号", pick(s, "mesh_id"), "NLM 官方核对" if mesh else "未记录官方核对"),
        kpi("范围", pick(s, "disease_scope")),
    ])
    rows = [
        {"field": "方剂", "value": pick(s, "formula")},
        {"field": "药味", "value": pick(s, "herbs")},
        {"field": "疾病", "value": pick(s, "disease")},
        {"field": "MeSH 首选词", "value": pick(s, "mesh_term")},
        {"field": "MeSH 编号", "value": pick(s, "mesh_id")},
        {"field": "研究用途", "value": pick(s, "analysis_purpose")},
        {"field": "登记人", "value": pick(s, "operator")},
    ]
    parts.table = table([("field", "字段"), ("value", "内容")], [r for r in rows if r["value"] is not None])
    parts.params = clean([
        param("登记方案", ctx.get("workflow_profile")),
        param("疾病范围", pick(s, "disease_scope")),
        param("物种", pick(s, "species")),
        param("MeSH 生产年份", pick(mesh, "year", "production_year")),
    ])
    return parts
