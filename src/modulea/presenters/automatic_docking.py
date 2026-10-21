"""新自动对接协议只读展示；不套用旧准备或旧评分矩阵。"""
from .base import Parts, kpi, table, focus


def present(result):
    """数量、受体及解释范围全部来自当前归档。"""
    summary = result["summary"]
    parts = Parts()
    parts.kpis = [kpi(label, summary[key]) for label, key in (("计划组合", "计划组合数"), ("有效评分", "成功组合数"), ("计算／姿势未通过", "失败组合数"), ("准备未通过", "NA组合数"), ("严格受体", "严格受体数"), ("探索受体", "探索受体数"))]
    parts.table = table([("受体", "基因"), ("HGNC", "HGNC"), ("结构编号" if summary.get("science_version") in ("A06.automatic.2", "A06.automatic.3") else "PDB", "PDB"), ("质控范围", "质控"), ("状态", "状态"), ("原因", "原因")], result["tables"]["receptor_setup"], "receptor_setup")
    parts.focus = [focus("预测位点单列为探索", "自动执行不代表实验验证；严格与探索结果分别使用，具体构型、位点和原件可在上方逐分数追溯。", tier="should_know")]
    return parts.as_dict()
