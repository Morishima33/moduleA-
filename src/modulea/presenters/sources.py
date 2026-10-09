"""A01 成分与方剂靶点、A02 疾病靶点的展示适配。"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, step, table, tables_of


def present_a01(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    parts.kpis = clean([
        kpi("筛选后成分", pick(s, "筛选后不同成分数"), "全部药味合计"),
        kpi("方剂标准化靶点", pick(s, "标准化基因数", "不同人类基因数"), "HGNC 统一身份" if pick(s, "标准化基因数") is not None else "源表基因符号"),
        kpi("身份问题组", pick(s, "身份问题组数")),
    ])
    raw, passed, human = pick(s, "原始关系记录数"), pick(s, "通过OB/DL的关系记录数"), pick(s, "人类关系证据行数")
    dedup, genes, normalized = pick(s, "去重成分—人类靶点关系数"), pick(s, "不同人类基因数"), pick(s, "标准化基因数")
    parts.flow = clean([
        step("原始关系记录", raw, "TCMSP 快照", kind="main"),
        step("通过 OB/DL", passed, "", f"−{raw - passed} 未达阈值或待核验" if raw is not None and passed is not None else ""),
        step("人类关系", human, "", f"−{passed - human} 非人类或缺物种" if passed is not None and human is not None else ""),
        step("去重关系", dedup, "成分—靶点"),
        step("不同人类基因", genes, "合并为基因"),
        step("标准化靶点", normalized, "进入交集", f"−{genes - normalized} 身份问题不采用" if genes is not None and normalized is not None and genes > normalized else "", kind="end"),
    ])
    parts.flow_note_zh = "所有排除记录都保留在明细表中，可逐条查看原因。"
    parts.table = table([("herb", "药味"), ("components", "筛选后成分"), ("human_genes", "人类基因"), ("raw_rows", "原始记录")], t.get("herb_summary") or [], "herb_summary")
    parts.params = clean([param("基因身份规则", pick(s, "mapping_rule")), param("标识空间", pick(s, "namespace")), param("资料阶段", pick(s, "资料阶段"))])
    if pick(s, "身份问题组数"):
        parts.focus.append(focus("身份问题组", f"共 {s['身份问题组数']} 组；处理方式：{pick(s, '身份问题处理', default='见明细')}", tier="should_know"))
    if s.get("handoff_blocked"):
        parts.focus.insert(0, focus("尚不能交给下游", "仍有资料或身份问题未处理。", blocks=["A03"]))
    return parts


def present_a02(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    sources = t.get("source_summary") or []
    parts = Parts()
    expected = len(s.get("databases") or []) or len(sources) or None
    parts.kpis = clean([
        kpi("疾病标准化靶点", pick(s, "标准化基因数"), "多库并集"),
        kpi("来源库", f"{pick(s, '已有来源库数', default='—')} / {expected}" if expected else pick(s, "已有来源库数"),
            "查询失败 " + str(pick(s, "失败来源库数", default=0)) + " 个"),
        kpi("身份问题组", pick(s, "身份问题组数")),
        kpi("待范围复核", pick(s, "待范围复核条目数", "待定范围组数")),
    ])
    parts.flow = clean([
        step("候选记录", pick(s, "候选记录数"), "", kind="main"),
        step("不同原始名称", pick(s, "不同原始名称数（非正式基因数）"), "", "合并同名记录"),
        step("标准化疾病靶点", pick(s, "标准化基因数"), "进入交集", "身份问题组不采用" if pick(s, "身份问题组数") else "", kind="end"),
    ])
    parts.flow_note_zh = "身份问题按组计数，与名称差值不是一一对应；每组明细可在结果表中查看。"
    parts.table = table([("database", "来源"), ("records", "记录数"), ("query", "检索词"), ("retrieved_at", "获取日期"), ("version", "版本"), ("availability", "状态")], sources, "source_summary")
    parts.params = clean([param("来源方案", pick(s, "source_profile")), param("基因身份规则", pick(s, "mapping_rule")), param("资料阶段", pick(s, "资料阶段"))])
    failed = pick(s, "失败来源库数", default=0)
    if failed:
        parts.focus.append(focus("有数据库查询失败", f"{failed} 个来源查询失败；这是执行失败，不是 0 条结果。", blocks=["A03"]))
    pending = pick(s, "待范围复核条目数", "待定范围组数", default=0)
    if pending:
        parts.focus.append(focus("疾病范围尚待复核", f"{pending} 个条目尚未判断是否属于本病；范围未定的记录不进入疾病主集合。", blocks=["A03"]))
    if pick(s, "身份问题组数"):
        parts.focus.append(focus("身份问题组", f"共 {s['身份问题组数']} 组；处理方式：{pick(s, '身份问题处理', default='见明细')}", tier="should_know"))
    for row in sources:
        if str(row.get("records")) == "0":
            parts.focus.append(focus(f"{row.get('database')} 为 0 条", f"状态：{row.get('availability')}。已检索但无精确命中，不等于未提供资料。", tier="should_know"))
    if s.get("handoff_blocked") and not parts.focus:
        parts.focus.append(focus("尚不能交给下游", "当前为候选整理阶段或仍有待决事项。", blocks=["A03"]))
    return parts
