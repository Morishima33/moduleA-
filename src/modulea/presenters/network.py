"""A04 PPI 网络、A05 GO/KEGG 富集的展示适配。"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, step, table, tables_of


def present_a04(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    if s.get("selection_version") in ("A04.dual.1", "A04.dual.2", "A04.dual.3"):
        return present_a04_dual(s, t)
    parts = Parts()
    parts.kpis = clean(
        [
            kpi(
                "参与节点",
                pick(s, "参与节点数"),
                f"{pick(s, '有边分量数', default='—')} 个有边分量",
            ),
            kpi("合格边", pick(s, "合格边数")),
            kpi("第一轮主候选", pick(s, "第一轮主候选数")),
            kpi("第二轮参考", pick(s, "第二轮参考数")),
        ]
    )
    inp, known, used = pick(s, "交集输入数"), pick(s, "已识别数"), pick(s, "参与节点数")
    excluded, isolates = pick(s, "本次PPI暂不采用数", default=0), pick(s, "孤立节点数")
    parts.flow = clean(
        [
            step("交集输入", inp, kind="main"),
            step("STRING 已识别", known, "", f"−{excluded} 本次暂不采用" if excluded else ""),
            step("参与计算", used, "有边节点", f"−{isolates} 孤立节点" if isolates else ""),
            step("第一轮主候选", pick(s, "第一轮主候选数"), "", "三指标筛选", kind="end"),
            step("第二轮参考", pick(s, "第二轮参考数"), "更严格子集", "再取中位数"),
        ]
    )
    parts.flow_note_zh = "本次暂不采用的靶点仍保留在交集和富集中；孤立节点单列，不记作 Degree = 0。"
    round1 = sorted(
        t.get("round1") or [], key=lambda r: (-(r.get("degree") or 0), str(r.get("symbol")))
    )
    max_degree = max((r.get("degree") or 0) for r in round1) if round1 else 0
    parts.special["ppi_top"] = [
        {
            "symbol": r.get("symbol"),
            "degree": r.get("degree"),
            "bc": r.get("bc"),
            "cc": r.get("cc"),
            "round2": bool(r.get("round2")),
            "bar": (r.get("degree") or 0) / max_degree if max_degree else 0,
        }
        for r in round1[:10]
    ]
    parts.table = table(
        [
            ("round", "轮次"),
            ("population", "参与节点"),
            ("degree", "Degree 阈值"),
            ("bc", "BC 阈值"),
            ("cc", "CC 阈值"),
        ],
        t.get("thresholds") or [],
        "thresholds",
    )
    parts.params = clean(
        [
            param("STRING 版本", pick(s, "STRING版本")),
            param("置信度", "≥ 0.9", "outline"),
            param("计算库版本", pick(s, "计算库版本")),
            param("覆盖说明", pick(s, "覆盖说明")),
        ]
    )
    add_identity_review(parts, s, t)
    if excluded:
        names = "、".join(
            str(r.get("symbol") or r.get("target")) for r in (t.get("ppi_exclusions") or [])[:10]
        )
        parts.focus.append(
            focus(
                "本次 PPI 暂不采用",
                f"{excluded} 个（{names}）；仍保留在交集和富集中。",
                tier="should_know",
            )
        )
    return parts


# 双分支只显示归档的第二轮排名与阈值，不在网页层重新筛选或合成名次。
def present_a04_dual(s, t):
    parts = Parts()
    counts = {
        key: s[key]
        for key in (
            "degree_round1_count",
            "degree_round2_count",
            "bc_cc_round1_count",
            "bc_cc_round2_count",
        )
    }
    parts.kpis = clean(
        [
            kpi("参与节点", s.get("参与节点数")),
            kpi("合格边", s.get("合格边数")),
            kpi("Degree第二轮", counts["degree_round2_count"]),
            kpi("BC＋CC第二轮", counts["bc_cc_round2_count"]),
        ]
    )
    parts.flow = clean(
        [
            step("交集输入", s.get("交集输入数")),
            step("STRING已识别", s.get("已识别数")),
            step("完整网络参与节点", s.get("参与节点数")),
        ]
    )
    parts.flow_note_zh = "两分支独立从完整网络开始；第二轮只缩小取中位数的范围，指标不重算。"
    parts.special["ppi_dual"] = {
        "version": s["selection_version"],
        "counts": counts,
        "thresholds": t["dual_thresholds"],
        "degree_rows": t["degree_top10"],
        "bc_cc_rows": t["bc_cc_top15"],
        "note_zh": "Degree显示第二轮前十；BC＋CC显示第二轮前十五，按两项平均名次等权排序。边界并列全部保留，不足名额按实际数量展示，空结果不补足；完整名单见结果明细。",
        "network_note_zh": "网络图方案待用户确认，当前不替换正式图。",
    }
    if s["selection_version"] in ("A04.dual.2", "A04.dual.3"):
        parts.special["ppi_dual"].update(
            degree_round=1,
            degree_rows=t["degree_round1_top10"],
            network=None,
            note_zh="Degree图表取第一轮前十；BC＋CC表取第二轮前十五，按两项平均名次等权排序。边界并列全部保留；不足按实际数量、空结果不补足。完整四轮名单见结果明细。",
            network_note_zh="节点指标来自完整网络；红色与标签为第一轮Degree前十及边界并列，其余为蓝色。第一轮候选全部保留；后续对接候选另行确认。",
        )
    else:
        parts.special["ppi_dual"]["degree_round"] = 2
    if s["selection_version"] == "A04.dual.3":
        parts.special["ppi_dual"].update(
            network_round=2,
            note_zh="先展示Degree第一轮前十表，再展示第二轮全部候选网络图；BC＋CC表取第二轮前十五。边界并列全部保留，不足按实际数量、空结果不补足；完整名单见结果明细。",
            network_note_zh="圆形位置仅用于展示；节点大小表示完整网络Degree。红色为第二轮前十及边界并列，其余蓝色；候选及真实连边完整保留，对接候选另行确认。",
        )
    parts.table = table(
        [
            ("branch_zh", "分支"),
            ("round", "轮次"),
            ("population", "筛选前"),
            ("selected", "筛选后"),
            ("degree_threshold", "Degree阈值"),
            ("bc_threshold", "BC阈值"),
            ("cc_threshold", "CC阈值"),
            ("comparison_zh", "比较条件"),
        ],
        t["dual_thresholds"],
        "dual_thresholds",
    )
    parts.params = clean(
        [
            param("筛选版本", s["selection_version"]),
            param("STRING版本", s.get("STRING版本")),
            param("置信度", "≥0.9", "outline"),
            param("计算库版本", s.get("计算库版本")),
        ]
    )
    add_identity_review(parts, s, t)
    parts.focus.append(
        focus(
            "对接候选来源待确认",
            "本轮排名仅用于核查；尚未决定后续对接使用哪一分支和哪一轮。",
            blocks=["A06_PREP"],
        )
    )
    return parts


# 待核验清单只读归档原值；未提供明细时仍保留阻断提示，不伪造已完成。
def add_identity_review(parts, summary, tables):
    rows = tables.get("identity_issues") or []
    count = summary.get("身份待核验数")
    if not count:
        return  # 已解决或已批准的历史问题不重新制造待办。
    item = focus(
        "请先核验STRING基因身份",
        f"{count if count is not None else len(rows)}个靶点身份待核验。下方直接展示清单，点击基因名或“查看证据”查看原始证据。"
        if rows
        else "身份问题尚未处理；本次归档未提供可展示的明细，请补齐证据。",
        blocks=["A06_PREP"],
    )
    item["source_table"] = "identity_issues"
    parts.focus.append(item)
    if rows:
        parts.special["ppi_identity"] = {
            "total": len(rows),
            "source_table": "identity_issues",
            "note_zh": "核对输入基因、HGNC编号和STRING返回名称；需补齐身份核查证据，再确认本研究的处理方案。此清单不表示身份已经核实。",
            "rows": [
                {
                    "target_id": r.get("target_id", ""),
                    "symbol": r.get("symbol", ""),
                    "returned": r.get("returned", ""),
                    "reason_zh": r.get("reason", ""),
                }
                for r in rows
            ],
        }


GROUP_NAMES = {"BP": "GO BP", "CC": "GO CC", "MF": "GO MF", "KEGG": "KEGG"}


def present_a05(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    parts.kpis = clean(
        [
            kpi("GO BP", pick(s, "BP显著条目数"), "显著条目"),
            kpi("GO CC", pick(s, "CC显著条目数"), "显著条目"),
            kpi("GO MF", pick(s, "MF显著条目数"), "显著条目"),
            kpi("KEGG", pick(s, "KEGG显著条目数"), "显著条目"),
        ]
    )
    groups = t.get("group_summary") or []
    parts.flow = clean(
        [
            step("交集输入", pick(s, "交集输入数"), kind="main"),
            step("Entrez 映射", pick(s, "Entrez映射数")),
            step(
                "实际检验条目",
                sum(g.get("tested_count") or 0 for g in groups) or None,
                " · ".join(f"{g.get('group')} {g.get('tested_count')}" for g in groups),
            ),
            step(
                "显著条目",
                sum(g.get("significant_count") or 0 for g in groups) or None,
                " · ".join(f"{g.get('group')} {g.get('significant_count')}" for g in groups),
                pick(s, "主显著性", default=""),
                kind="end",
            ),
        ]
    )
    parts.flow_note_zh = "四类分别校正；各类分母取实际有效输入。" + (
        pick(s, "说明", default="") or ""
    )
    parts.table = table(
        [
            ("group", "类别"),
            ("effective_count", "有效输入"),
            ("background_count", "背景基因"),
            ("tested_count", "实际检验"),
            ("significant_count", "显著"),
        ],
        groups,
        "group_summary",
    )
    # 每类展示用的前列条目（与已归档 *_display 表同源）
    top = {}
    for key in ("bp", "cc", "mf", "kegg"):
        rows = t.get(key + "_display") or []
        top[key] = [
            {
                "id": r.get("ID"),
                "description": r.get("Description"),
                "count": r.get("Count"),
                "gene_ratio": r.get("GeneRatio"),
                "p_adjust": r.get("p.adjust"),
                "rich_factor": r.get("RichFactor"),
            }
            for r in rows
        ]
    parts.special["enrichment_top"] = top
    if s.get("display_version") == "A05.display.2":
        # 新展示直接读取完整显著表派生的已归档排名，不再沿用旧前十/二十截断。
        parts.special.pop("enrichment_top")
        parts.special["enrichment_display_tables"] = {name:t.get(name,[]) for name in ("bp_top15","cc_top15","mf_top15","kegg_p_top10","kegg_count_top10","kegg_excluded")}
        if not s.get("display_exclusions_confirmed"):
            parts.focus.append(focus("确认KEGG展示范围","在标题下方核对拟排除清单，勾选后点击“确认排除清单并生成图表”；不排除任何条目也须明确确认。未确认将阻断A05通过。",blocks=["A07"]))
        elif not s.get("display_layout_confirmed"):
            parts.focus.append(focus("确认GO与KEGG图表版式","检查中英文、配色、图例和排序，随后点击标题下方“确认当前图表版式”。确认后仍须独立复核A05结果。",blocks=["A07"]))
        if s.get("display_missing_translation_count"):
            parts.focus.append(focus("图表中文待核译",f"{s['display_missing_translation_count']}个实际入图入表条目待核译；不能用缺译图表确认版式。",blocks=["A07"]))
    parts.params = clean(
        [param("显著性", pick(s, "主显著性"))]
    )  # 其余实际参数由通用视图从 run.json 的 config 中列出
    for g in groups:
        if g.get("significant_count") == 0:
            parts.focus.append(
                focus(
                    f"{GROUP_NAMES.get(g.get('group'), g.get('group'))} 无显著条目",
                    "这是有效空结果；完整统计表照常保存，不放宽阈值。",
                    tier="should_know",
                )
            )
    if pick(s, "身份待核验数"):
        parts.focus.append(
            focus("身份待核验", f"{s['身份待核验数']} 个基因无法映射。", blocks=["A07"])
        )
    return parts
