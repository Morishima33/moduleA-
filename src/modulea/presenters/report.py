"""A07 双报告与共同结论的展示适配。

“本轮你只需核对这些”固定为三项：共同结论、研究线索、限制边界（沿用现行 A07 复核规则）。
底层表格、版本绑定和文件指纹由程序校验，不要求人工逐条核对。
"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, table, tables_of

REPORT_ROLES = {"detailed_report": "专业详细报告", "brief_report": "临床简略报告", "clinical_report": "临床简略报告", "concise_report": "临床简略报告"}


def present_a07(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    counts = t.get("key_counts") or []
    by_name = {row.get("指标"): row.get("数值") for row in counts}
    leads = t.get("research_leads") or []
    parts.kpis = clean([
        kpi("交集靶点", by_name.get("交集靶点数")),
        kpi("PPI 第一轮", by_name.get("PPI第一轮主候选数")),
        kpi("有效对接", by_name.get("正式对接成功组合数")),
        kpi("研究线索", pick(s, "研究线索数", default=len(leads) or None)),
    ])
    parts.table = table([("指标", "指标"), ("数值", "数值")], counts, "key_counts")
    parts.special["conclusion_zh"] = pick(s, "共同结论草稿")
    parts.special["leads"] = [{"title_zh": r.get("线索"), "fact_zh": r.get("支持事实"), "next_zh": r.get("下一步核验")} for r in leads]
    parts.special["limits"] = [r.get("限制") for r in (t.get("limitations") or []) if r.get("限制")]
    parts.special["pathway"] = [{"id": r.get("通路ID"), "name_zh": r.get("通路名称"), "status_zh": r.get("确认状态"), "hits": r.get("命中基因数")} for r in (t.get("selected_pathway") or [])]
    # 两份 Word 的下载入口：file_path 在视图层换成下载键
    parts.special["report_files"] = [{"role": r.get("role"), "label_zh": REPORT_ROLES.get(r.get("role"), r.get("role")), "path": r.get("path"),
                                      "sha256": r.get("sha256"), "row": row}
                                     for row, r in enumerate(t.get("report_files") or []) if str(r.get("path", "")).endswith(".docx")]
    if s.get('报告修订')=='A07.plan_report.1':
        for item in parts.special['report_files']:
            item['label_zh']={'detailed_report':'主报告','brief_report':'简略版'}.get(item['role'],item['label_zh'])
    parts.params = clean([param("报告修订", pick(s, "报告修订")), param("结论复核状态", pick(s, "结论复核状态")), param("差异说明", pick(s, "差异说明"))])
    status = ctx.get("state_code")
    if status in ("review", "hold", "returned"):
        parts.focus = [
            focus("共同结论是否准确、表述是否过度", "两份报告共用同一段结论。", blocks=["报告发布"]),
            focus(f"{len(leads)} 条研究线索是否合理", "重点看“下一步核验”是否可执行。", blocks=["报告发布"]),
            focus("限制边界是否写全", "尤其是研究用途（流程测试或正式研究）和资料来源限制。", blocks=["报告发布"]),
        ]
    return parts
