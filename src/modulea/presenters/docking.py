"""A06_PREP 对接准备、A06 对接结果的展示适配。

热图数据规则沿用用户 2026-10-08 确认的矩阵样式：
- 行是成分、列是受体（前端可以转置显示）；
- 整列（受体）或整行（成分）都没有有效评分时，不进入图面，改在 omitted 中说明原因；
- 单个缺失格保留为 NA（value 为 null），不补 0、不改选其他姿势。
"""

from __future__ import annotations

from .base import Parts, clean, focus, kpi, param, pick, step, table, tables_of


def _receptor_roles(ctx: dict) -> dict[str, dict]:
    """从当前 A06_PREP 的受体诊断表读取每个受体的 PPI 顺序、PDB、RMSD 和质控角色。"""
    prep = (ctx.get("results") or {}).get("A06_PREP") or {}
    roles = {}
    for row in tables_of(prep).get("receptor_diagnostics") or []:
        name = row.get("受体")
        if not name:
            continue
        status = str(row.get("质控状态") or row.get("处理") or "")
        if "主要结果" not in row:
            # 较早格式只记录“诊断通过/处理”，没有主要与扩展的区分；如实显示，不推断分级
            role = "质控通过" if row.get("诊断通过") else "失败"
        elif row.get("主要结果"):
            role = "主要"
        elif "失败" in status:
            role = "失败"
        elif "探索" in status or "预测" in status:
            role = "探索"
        else:
            role = "扩展"
        roles[name] = {"order": row.get("PPI顺序"), "pdb": row.get("PDB"), "rmsd": row.get("RMSD_A"), "status_zh": status, "role_zh": role}
    return roles


def present_a06_prep(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    planned_note = f"{pick(s, '受体核查数', default='—')} 受体 × {pick(s, '成分数', default='—')} 成分" if pick(s, "受体核查数") else ""
    parts.kpis = clean([
        kpi("计划组合", pick(s, "计划组合数", "授权正式组合数"), planned_note),
        kpi("严格质控通过", pick(s, "严格质控通过受体数", "重对接通过受体数"), "参考配体重对接 RMSD ≤ 2 Å"),
        kpi("主要受体", pick(s, "主要受体数")),
        kpi("暂停组合", pick(s, "暂停组合数")),
    ])
    rows = sorted((dict(r) for r in t.get("receptor_diagnostics") or []), key=lambda r: r.get("PPI顺序") or 10**9)  # 复制后再补列，不改动读入的结果
    for row in rows:  # 较早格式没有“质控状态”列，用“处理”补上，便于同一张表显示
        row.setdefault("质控状态", row.get("处理"))
    parts.flow = clean([
        step("核查受体", pick(s, "受体核查数"), "含边界并列", kind="main"),
        step("严格质控通过", pick(s, "严格质控通过受体数"), "RMSD ≤ 2 Å"),
        step("主要受体", pick(s, "主要受体数"), "按 PPI 顺序", kind="end"),
    ])
    parts.flow_note_zh = "无参考配体的受体不伪造 RMSD；失败受体保留记录，不自动换结构或调参。"
    parts.table = table([("PPI顺序", "PPI 顺序"), ("受体", "受体"), ("PDB", "PDB"), ("RMSD_A", "重对接 RMSD（Å）"), ("质控状态", "质控状态")], rows, "receptor_diagnostics")
    if t.get("quality_packet"):
        # 两遍实际诊断直接显示归档理由，RMSD失败不能被通用环境说明掩盖。
        parts.kpis.append(kpi("待集中核查", pick(s, "等待集中核查受体数")))
        columns = [("PPI顺序", "PPI顺序"), ("受体", "受体"), ("候选级别", "A/B候选"),
                   ("PDB", "PDB"), ("RMSD_A", "Top-1 RMSD（Å）"),
                   ("质控状态", "实际质控状态"), ("第一遍", "第一遍诊断"), ("第二遍", "第二遍诊断")]
        parts.table = table(columns, rows, "receptor_diagnostics")
        parts.flow_note_zh = "A/B为候选依据；实际结构质控独立记录。预测口袋待确认或必要环境未解决时保持待核查，未计算成分×受体结合能。"
    for row in rows:
        if "失败" in str(row.get("质控状态") or ""):
            reason = str(row.get("结构限制") or row.get("质控状态"))
            if t.get("quality_packet"):
                reason = "第一遍：" + str(row.get("第一遍") or "") + "；第二遍：" + str(row.get("第二遍") or "")
            parts.focus.append(focus(f"{row.get('受体')} 结构准备失败", reason, tier="should_know"))
    return parts


def present_a06(result: dict, ctx: dict) -> Parts:
    s = result.get("summary") or {}
    t = tables_of(result)
    parts = Parts()
    matrix_rows = t.get("score_matrix") or []
    roles = _receptor_roles(ctx)
    id_keys = {"compound_id", "compound_name"}
    receptors = []
    for row in matrix_rows:
        for key in row:
            if key not in id_keys and key not in receptors:
                receptors.append(key)
    receptors.sort(key=lambda r: (roles.get(r, {}).get("order") or 10**9, r))

    # 找最负评分组合
    best = None
    for row in matrix_rows:
        for rec in receptors:
            value = row.get(rec)
            if isinstance(value, (int, float)) and (best is None or value < best[0]):
                best = (value, row.get("compound_name") or row.get("compound_id"), rec)

    parts.kpis = clean([
        kpi("计划组合", pick(s, "计划组合数")),
        kpi("有效评分", pick(s, "成功组合数")),
        kpi("未得到评分", pick(s, "失败组合数"), "原因见下方说明"),
        kpi("最负组合", best[0] if best else None, f"{best[1]}—{best[2]}" if best else ""),
    ])
    parts.flow = clean([
        step("计划组合", pick(s, "计划组合数"), kind="main"),
        step("有效评分", pick(s, "成功组合数"), "", f"−{pick(s, '失败组合数')} 未得到有效评分" if pick(s, "失败组合数") else "", kind="end"),
    ])
    parts.flow_note_zh = "每组按固定 Top-1 姿势计分；失败组保留 NA 和原因，不补 0、不改选第二姿势。"

    # 热图：去掉整列/整行无有效评分的受体与成分
    def valid(v):
        return isinstance(v, (int, float))
    shown_receptors = [r for r in receptors if any(valid(row.get(r)) for row in matrix_rows)]
    shown_rows = [row for row in matrix_rows if any(valid(row.get(r)) for r in receptors)]
    omitted = [{"kind": "receptor", "name": r, "reason_zh": roles.get(r, {}).get("status_zh") or "无有效评分"} for r in receptors if r not in shown_receptors]
    omitted += [{"kind": "compound", "name": row.get("compound_name") or row.get("compound_id"), "reason_zh": "全部组合均无有效评分"} for row in matrix_rows if row not in shown_rows]
    values = [row.get(r) for row in shown_rows for r in shown_receptors if valid(row.get(r))]
    parts.special["heatmap"] = {
        "unit": "kcal/mol",
        "orientation": "rows=compounds, columns=receptors",
        "color_rule_zh": "数值越负红色越深，越不负蓝色越深；不设通用结合能阈值",
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "receptors": [{"name": r, **roles.get(r, {})} for r in shown_receptors],
        "rows": [{"compound_id": row.get("compound_id"), "compound_name": row.get("compound_name"),
                  "cells": [{"receptor": r, "value": row.get(r) if valid(row.get(r)) else None} for r in shown_receptors]}
                 for row in shown_rows],
        "omitted": omitted,
    }
    setup = t.get("receptor_setup") or []
    parts.table = table([("靶点基因", "受体"), ("PDB ID", "PDB"), ("蛋白链", "链"), ("共晶参考配体", "参考配体"), ("重对接RMSD（Å）", "重对接 RMSD（Å）"), ("质控状态", "质控状态")], setup, "receptor_setup")
    parts.params = clean([param("NA 规则", pick(s, "NA规则")), param("自动调参", pick(s, "自动调参")), param("主要受体数", pick(s, "主要受体数"))])
    if pick(s, "失败组合数"):
        parts.focus.append(focus("有组合未得到有效评分", f"{s['失败组合数']} 组保留 NA；原因见受体限制表和热图下方说明。", tier="should_know"))
    return parts
