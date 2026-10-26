"""新方案的三种受体筛选适配：复用原两轮指标规则，A04输出最终名单。"""

from copy import deepcopy

from contracts import fingerprint, require
from science_modules.analysis_protocol import checked_plan
from .selection import boundary_top, ranked, select

VERSION = "A04.plan_selection.1"


def select_receptors(metrics, plan):
    """不重新建网或计算指标；保留科学并列，编号仅决定并列显示次序。"""
    plan = checked_plan(plan)
    params = plan["parameters"]
    tables = select(metrics)
    degree, bc_cc = tables["degree_round2"], tables["bc_cc_round2"]
    count, mode = params["a06.receptor_count"], params["a04.mode"]
    group_a, group_b = [], []
    if mode == "degree":
        chosen = boundary_top(degree, count, "degree")
    elif mode == "bc_cc":
        chosen = boundary_top(bc_cc, count, "mean_rank")
    else:
        main = boundary_top(degree, params["a04.degree_main_window"], "degree")
        bc_window = boundary_top(bc_cc, params["a04.bc_cc_window"], "mean_rank")
        pool = boundary_top(degree, params["a04.degree_pool_window"], "degree")
        common = {r["target_id"] for r in main} & {r["target_id"] for r in bc_window}
        group_a = ranked([r for r in main if r["target_id"] in common], "degree", True)
        group_b = ranked([r for r in pool if r["target_id"] not in common], "degree", True)
        chosen_a = boundary_top(group_a, count, "degree")
        remaining = max(0, count - len(chosen_a))
        chosen = chosen_a + (boundary_top(group_b, remaining, "degree") if remaining else [])
    require(len(chosen) == len({r["target_id"] for r in chosen}), "最终受体名单身份重复")
    a_ids = {r["target_id"] for r in group_a}
    selected = [dict(deepcopy(row), selection_order=i, candidate_grade=("A" if row["target_id"] in a_ids else "B") if mode == "dual_ab" else None)
                for i, row in enumerate(chosen, 1)]
    settings = {key: params[key] for key in ("a04.mode", "a04.degree_main_window", "a04.bc_cc_window", "a04.degree_pool_window", "a06.receptor_count")}
    return {"schema_version": VERSION, "selection_hash": fingerprint({"version": VERSION, "metrics": sorted(tables["metrics"], key=lambda r: r["target_id"]), "settings": settings}),
            "mode": mode, "requested_count": count, "actual_count": len(selected),
            "boundary_ties_retained": True, "selected": selected, "group_a": group_a, "group_b": group_b,
            "thresholds": tables["dual_thresholds"], "tables": tables,
            "range_owner": "A04", "replacement_after_preparation_failure": False}
