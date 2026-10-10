"""A04双分支第1版：固定完整网络指标，独立筛选并保留真实并列。"""
from copy import deepcopy
import math
from statistics import median
from contracts import require

VERSION = "A04.dual.1"

# 分别排名时同值取占用位置的平均名次，避免稳定编号决定科学名次。
def average_ranks(rows, key):
    ordered = sorted(rows, key=lambda r: (-r[key], r["target_id"]))
    ranks = {}
    start = 0
    while start < len(ordered):
        stop = start + 1
        while stop < len(ordered) and ordered[stop][key] == ordered[start][key]:
            stop += 1
        rank = (start + 1 + stop) / 2
        ranks.update({r["target_id"]: rank for r in ordered[start:stop]})
        start = stop
    return ranks

# 主排名同值使用竞争名次；稳定编号只整理同名次的显示次序。
def ranked(rows, key, reverse=False):
    rows = sorted(deepcopy(rows), key=lambda r: ((-r[key] if reverse else r[key]), r["target_id"]))
    previous = object()
    rank = 0
    for position, row in enumerate(rows, 1):
        if row[key] != previous:
            rank = position
        row["rank"] = rank
        previous = row[key]
    return rows

# 名额是展示上限；第N个处相同排序值的所有节点一起展示。
def boundary_top(rows, size, key):
    if len(rows) <= size:
        return deepcopy(rows)
    boundary = rows[size - 1][key]
    return deepcopy([r for r in rows if r[key] >= boundary] if key == "degree" else [r for r in rows if r[key] <= boundary])

# 校验指标并进行四次筛选；不改图、不重算Degree/BC/CC、不自动改变阈值。
def select(metrics):
    rows = deepcopy(metrics)
    require(len({r["target_id"] for r in rows}) == len(rows), "PPI指标表身份重复")
    for row in rows:
        require(isinstance(row.get("degree"), int) and not isinstance(row["degree"], bool) and row["degree"] > 0, "参与节点Degree须为正整数")
        require(all(isinstance(row.get(k), (int, float)) and not isinstance(row[k], bool) and math.isfinite(row[k]) and row[k] >= 0 for k in ("bc", "cc")), "PPI中心性指标缺失或非有限值")
        row.pop("round1", None)
        row.pop("round2", None)
    thresholds = []
    groups = {}
    for branch in ("degree", "bc_cc"):
        population = rows
        for number in (1, 2):
            med = {k: median(r[k] for r in population) if population else None for k in ("degree", "bc", "cc")}
            limit = med["degree"] * (2 if number == 1 else 1) if population else None
            selected = [r for r in population if (r["degree"] >= limit if branch == "degree" else r["bc"] > med["bc"] and r["cc"] > med["cc"])]
            thresholds.append({"branch": branch, "branch_zh": "Degree" if branch == "degree" else "BC＋CC", "round": number, "population": len(population), "selected": len(selected), "degree_threshold": limit if branch == "degree" else None, "bc_threshold": med["bc"] if branch == "bc_cc" else None, "cc_threshold": med["cc"] if branch == "bc_cc" else None, "comparison_zh": "Degree ≥ 阈值" if branch == "degree" else "BC > 阈值且CC > 阈值"})
            groups[f"{branch}_round{number}"] = deepcopy(selected)
            population = selected
    groups["degree_round2"] = ranked(groups["degree_round2"], "degree", True)
    bc_ranks = average_ranks(groups["bc_cc_round2"], "bc")
    cc_ranks = average_ranks(groups["bc_cc_round2"], "cc")
    for row in groups["bc_cc_round2"]:
        row.update(bc_rank=bc_ranks[row["target_id"]], cc_rank=cc_ranks[row["target_id"]], mean_rank=(bc_ranks[row["target_id"]] + cc_ranks[row["target_id"]]) / 2)
    groups["bc_cc_round2"] = ranked(groups["bc_cc_round2"], "mean_rank")
    for row in rows:
        for name, members in groups.items():
            row[name] = row["target_id"] in {r["target_id"] for r in members}
    return dict(groups, metrics=rows, dual_thresholds=thresholds,
                degree_top10=boundary_top(groups["degree_round2"], 10, "degree"),
                bc_cc_top15=boundary_top(groups["bc_cc_round2"], 15, "mean_rank"))

# 从冻结网络计算结果提取原指标；清除旧混合筛选字段，防止下游误当新分支。
def from_legacy(summary, tables):
    result = deepcopy(tables)
    result.pop("round1", None)
    result.pop("round2", None)
    result.pop("thresholds", None)
    result.update(select(tables["metrics"]))
    summary = deepcopy(summary)
    summary.pop("第一轮主候选数", None)
    summary.pop("第二轮参考数", None)
    summary.update(selection_version=VERSION, degree_round1_count=len(result["degree_round1"]), degree_round2_count=len(result["degree_round2"]), bc_cc_round1_count=len(result["bc_cc_round1"]), bc_cc_round2_count=len(result["bc_cc_round2"]), docking_candidate_source_pending=True, network_design_status="awaiting_user_confirmation")
    return summary, result
