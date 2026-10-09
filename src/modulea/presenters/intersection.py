"""A03 交集与成分排序、A03_SELECT 主候选确认的展示适配。"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, step, table, tables_of


def present_a03(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    T, D, I = pick(s, "方剂靶点数"), pick(s, "疾病靶点数"), pick(s, "交集靶点数")
    parts.kpis = clean([kpi("方剂靶点 T", T), kpi("疾病靶点 D", D), kpi("交集 I", I, "PPI 与富集共同输入")])
    parts.flow = clean([
        step("方剂靶点 T", T, f"其中仅方剂 {pick(s, '仅方剂靶点数', default='—')}", kind="main"),
        step("疾病靶点 D", D, f"其中仅疾病 {pick(s, '仅疾病靶点数', default='—')}", "与", kind="main"),
        step("交集 I", I, "PPI 与富集共同输入", "取共同部分", kind="end"),
    ])
    parts.flow_note_zh = "交集是两侧集合的共同部分；“仅方剂”“仅疾病”的基因保留在明细中。"
    ranking = sorted(t.get("ranking") or [], key=lambda r: (r.get("main_rank") or 10**9, str(r.get("compound_id"))))
    parts.table = table([("main_rank", "主排序"), ("name", "成分"), ("herbs", "药味"), ("intersection_count", "交集靶点数"), ("mixed_degree", "混合 Degree"), ("degree_rank", "Degree 排名")], ranking, "ranking", limit=20)
    # 韦恩图数字（三块面积）：仅方剂 / 交集 / 仅疾病
    parts.special["venn"] = {"formula_only": pick(s, "仅方剂靶点数"), "both": I, "disease_only": pick(s, "仅疾病靶点数"), "formula_total": T, "disease_total": D}
    parts.params = clean([param("计算", "I = T ∩ D", "outline"), param("标识空间", pick(s, "namespace"))])
    if s.get("截断处需要并列选择"):
        parts.focus.append(focus("前五截断处有并列", "请在 A03_SELECT 中确认并列成分的名额。", blocks=["A03_SELECT"]))
    if I == 0:
        parts.focus.append(focus("交集为空", "这是有效空结果，可以复核；PPI 与富集将说明无输入。", tier="should_know"))
    return parts


def present_a03_select(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    coverage = t.get("coverage") or []
    covered = sum(1 for row in coverage if row.get("covered"))
    parts.kpis = clean([
        kpi("正式候选", pick(s, "主候选数")),
        kpi("人工补充", pick(s, "人工补充纳入数")),
        kpi("药味代表", pick(s, "药味代表性纳入数")),
        kpi("药味覆盖", f"{covered} / {len(coverage)}" if coverage else None, "、".join(str(r.get("herb")) for r in coverage if r.get("covered"))),
    ])
    parts.table = table([("name", "成分"), ("herbs", "药味"), ("intersection_count", "交集靶点"), ("main_rank", "主排序"), ("selection_role", "角色")], t.get("selected") or [], "selected")
    parts.params = clean([param("选择策略", pick(s, "选择策略")), param("补充用途", pick(s, "补充用途")), param("复核人", pick(s, "复核人"))])
    if pick(s, "选择及替换理由"):
        parts.focus.append(focus("选择及替换理由", s["选择及替换理由"], tier="should_know"))
    return parts
