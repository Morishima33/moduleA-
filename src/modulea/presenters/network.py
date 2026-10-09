"""A04 PPI 网络、A05 GO/KEGG 富集的展示适配。"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, step, table, tables_of


def present_a04(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    parts.kpis = clean([
        kpi("参与节点", pick(s, "参与节点数"), f"{pick(s, '有边分量数', default='—')} 个有边分量"),
        kpi("合格边", pick(s, "合格边数")),
        kpi("第一轮主候选", pick(s, "第一轮主候选数")),
        kpi("第二轮参考", pick(s, "第二轮参考数")),
    ])
    inp, known, used = pick(s, "交集输入数"), pick(s, "已识别数"), pick(s, "参与节点数")
    excluded, isolates = pick(s, "本次PPI暂不采用数", default=0), pick(s, "孤立节点数")
    parts.flow = clean([
        step("交集输入", inp, kind="main"),
        step("STRING 已识别", known, "", f"−{excluded} 本次暂不采用" if excluded else ""),
        step("参与计算", used, "有边节点", f"−{isolates} 孤立节点" if isolates else ""),
        step("第一轮主候选", pick(s, "第一轮主候选数"), "", "三指标筛选", kind="end"),
        step("第二轮参考", pick(s, "第二轮参考数"), "更严格子集", "再取中位数"),
    ])
    parts.flow_note_zh = "本次暂不采用的靶点仍保留在交集和富集中；孤立节点单列，不记作 Degree = 0。"
    round1 = sorted(t.get("round1") or [], key=lambda r: (-(r.get("degree") or 0), str(r.get("symbol"))))
    max_degree = max((r.get("degree") or 0) for r in round1) if round1 else 0
    parts.special["ppi_top"] = [
        {"symbol": r.get("symbol"), "degree": r.get("degree"), "bc": r.get("bc"), "cc": r.get("cc"),
         "round2": bool(r.get("round2")), "bar": (r.get("degree") or 0) / max_degree if max_degree else 0}
        for r in round1[:10]
    ]
    parts.table = table([("round", "轮次"), ("population", "参与节点"), ("degree", "Degree 阈值"), ("bc", "BC 阈值"), ("cc", "CC 阈值")], t.get("thresholds") or [], "thresholds")
    parts.params = clean([param("STRING 版本", pick(s, "STRING版本")), param("置信度", "≥ 0.9", "outline"), param("计算库版本", pick(s, "计算库版本")), param("覆盖说明", pick(s, "覆盖说明"))])
    if pick(s, "身份待核验数"):
        parts.focus.append(focus("STRING 身份待核验", f"{s['身份待核验数']} 个靶点身份未确认；未获授权前不能通过。", blocks=["A06_PREP"]))
    if excluded:
        names = "、".join(str(r.get("symbol") or r.get("target")) for r in (t.get("ppi_exclusions") or [])[:10])
        parts.focus.append(focus("本次 PPI 暂不采用", f"{excluded} 个（{names}）；仍保留在交集和富集中。", tier="should_know"))
    return parts


GROUP_NAMES = {"BP": "GO BP", "CC": "GO CC", "MF": "GO MF", "KEGG": "KEGG"}


def present_a05(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    parts.kpis = clean([
        kpi("GO BP", pick(s, "BP显著条目数"), "显著条目"),
        kpi("GO CC", pick(s, "CC显著条目数"), "显著条目"),
        kpi("GO MF", pick(s, "MF显著条目数"), "显著条目"),
        kpi("KEGG", pick(s, "KEGG显著条目数"), "显著条目"),
    ])
    groups = t.get("group_summary") or []
    parts.flow = clean([
        step("交集输入", pick(s, "交集输入数"), kind="main"),
        step("Entrez 映射", pick(s, "Entrez映射数")),
        step("实际检验条目", sum(g.get("tested_count") or 0 for g in groups) or None, " · ".join(f"{g.get('group')} {g.get('tested_count')}" for g in groups)),
        step("显著条目", sum(g.get("significant_count") or 0 for g in groups) or None, " · ".join(f"{g.get('group')} {g.get('significant_count')}" for g in groups), pick(s, "主显著性", default=""), kind="end"),
    ])
    parts.flow_note_zh = "四类分别校正；各类分母取实际有效输入。" + (pick(s, "说明", default="") or "")
    parts.table = table([("group", "类别"), ("effective_count", "有效输入"), ("background_count", "背景基因"), ("tested_count", "实际检验"), ("significant_count", "显著")], groups, "group_summary")
    # 每类展示用的前列条目（与已归档 *_display 表同源）
    top = {}
    for key in ("bp", "cc", "mf", "kegg"):
        rows = t.get(key + "_display") or []
        top[key] = [{"id": r.get("ID"), "description": r.get("Description"), "count": r.get("Count"), "gene_ratio": r.get("GeneRatio"),
                     "p_adjust": r.get("p.adjust"), "rich_factor": r.get("RichFactor")} for r in rows]
    parts.special["enrichment_top"] = top
    parts.params = clean([param("显著性", pick(s, "主显著性"))])  # 其余实际参数由通用视图从 run.json 的 config 中列出
    for g in groups:
        if g.get("significant_count") == 0:
            parts.focus.append(focus(f"{GROUP_NAMES.get(g.get('group'), g.get('group'))} 无显著条目", "这是有效空结果；完整统计表照常保存，不放宽阈值。", tier="should_know"))
    if pick(s, "身份待核验数"):
        parts.focus.append(focus("身份待核验", f"{s['身份待核验数']} 个基因无法映射。", blocks=["A07"]))
    return parts
