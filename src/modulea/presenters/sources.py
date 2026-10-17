"""A01 成分与方剂靶点、A02 疾病靶点的展示适配。"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, step, table, tables_of


def present_a01(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    if "候选成分分组数" in s:
        return present_a01_multisource(result, ctx)
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


# 读取三库归档事实，区分来源编号、保守成分分组和进入交集的标准化靶点。
def present_a01_multisource(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    parts.kpis = clean([
        kpi("候选成分分组", pick(s, "候选成分分组数"), "保守分组，含结构待核条目"),
        kpi("方剂标准化靶点", pick(s, "标准化基因数"), "HGNC 统一身份"),
        kpi("结构待核分组", pick(s, "结构待核分组数"), "进入对接前须核实"),
    ])
    parts.flow = clean([
        step("候选成分分组", pick(s, "候选成分分组数"), "三库并集保守去重", kind="main"),
        step("标准成分—基因关系", pick(s, "去重成分—人类基因关系数"), "跨库去重，来源证据保留"),
        step("方剂标准化靶点", pick(s, "标准化基因数"), "进入交集", kind="end"),
    ])
    parts.flow_note_zh = "结构键分组与结构待核分组共同构成候选分组；各库来源编号不可相加当作独立成分数。"
    grouped = {}
    for row in t.get("component_sources") or []:
        source = row.get("source")
        source_id = row.get("source_id")
        if source and source_id:
            grouped.setdefault(source, set()).add(source_id)
    rows = [{"source": source, "source_ids": len(ids)} for source, ids in grouped.items()]
    parts.table = table([("source", "来源库"), ("source_ids", "不同来源编号数")], rows)
    parts.params = clean([
        param("成分来源方案", pick(s, "component_source_profile")),
        param("基因身份规则", pick(s, "mapping_rule")),
        param("标识空间", pick(s, "namespace")),
        param("资料阶段", pick(s, "资料阶段")),
        param("身份例外处理", pick(s, "身份例外处理")),
        param("结构待核处理", pick(s, "结构待核处理")),
    ])
    pending = pick(s, "结构待核分组数")
    if pending:
        parts.focus.append(focus("结构尚待核实", f"{pick(s, '结构键分组数', default='—')} 个结构键分组，{pending} 个结构待核分组；两者共同组成候选分组，候选分组数不等于已完全核实的独立物质数。", tier="should_know"))
    excluded = pick(s, "身份例外处理")
    if excluded:
        parts.focus.append(focus("本研究身份例外决定", str(excluded) + "；该决定仅适用于当前研究及绑定版本。", tier="should_know"))
    parts.focus.append(focus("已有关系的证据范围", "数据库已有关系及人类HGNC身份不等于人体直接结合实验证据；本方案未增加新的靶点预测。", tier="should_know"))
    if s.get("handoff_blocked"):
        parts.focus.insert(0, focus("尚不能交给下游", "当前仍有未处理的资料或身份问题；历史病例决定不会自动应用。", blocks=["A03"]))
    return parts


def present_a02(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    sources = source_display_rows(t.get("source_summary") or [])
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
        if str(row.get("records")) == "0" and row.get("availability") == "已查询但0条精确记录":
            parts.focus.append(focus(f"{row.get('database')} 为 0 条", f"状态：{row.get('availability')}。已检索但无精确命中，不等于未提供资料。", tier="should_know"))
    if s.get("handoff_blocked") and not parts.focus:
        parts.focus.append(focus("尚不能交给下游", "当前为候选整理阶段或仍有待决事项。", blocks=["A03"]))
    return parts


def source_display_rows(rows):
    """展示时区分未取得和真实空结果；不改写原始归档计数。"""
    result = []
    for row in rows:
        item = dict(row)
        if str(item.get("availability", "")).startswith(("查询失败", "尚未提供")):
            for key in ("records", "distinct_raw_symbols", "missing_score"):
                if key in item:
                    item[key] = "未取得"
        result.append(item)
    return result
