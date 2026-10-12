"""A06一次核对摘要：复用完整方案校验，只读列出缺口及需单项确认的NA。"""
from copy import deepcopy
from science_modules.a06.two_pass_plan import validate


def confirmation_summary(plan, context, checks, materials=(), metadata=None):
    """汇总成分、受体、配置；确认资格仍以原完整校验及版本保护为准。"""
    pending = []
    normal = [r["target_id"] for r in checks if r["valid"] and r["bulk_allowed"]]
    unavailable = []
    names = {
        r["compound_id"]: r.get("name_zh") or r.get("name")
        for r in (metadata or {}).get("compounds", [])
    }
    for row, facts in zip(plan.get("receptors", []), checks):
        if not facts["valid"]:
            pending.append({
                "kind": "receptor", "id": row["target_id"],
                "label_zh": row["symbol"], "reason_zh": facts["reason_zh"],
            })
        elif not facts["bulk_allowed"]:
            unavailable.append({
                "kind": "receptor", "id": row["target_id"],
                "label_zh": row["symbol"], "reason_zh": row["reason"],
            })
    # 复用同版配体校验，单项坏数据不能被其余正常项掩盖。
    compounds = plan.get("compounds", [])
    compounds = compounds if isinstance(compounds, list) else []
    for source in context["compounds"]:
        matches = [
            r for r in compounds
            if isinstance(r, dict) and r.get("compound_id") == source["compound_id"]
        ]
        row = matches[0] if len(matches) == 1 else {}
        label = names.get(source["compound_id"]) or source.get("name") or source["compound_id"]
        try:
            mini = {**deepcopy(plan), "receptors": [], "compounds": [row], "package_id": "D000"}
            validate(mini, {**context, "receptors": [], "compounds": [source]}, [], materials)
        except (ValueError, KeyError, TypeError) as error:
            pending.append({
                "kind": "compound", "id": source["compound_id"],
                "label_zh": label, "reason_zh": str(error),
            })
        else:
            if row["status"] == "unavailable":
                unavailable.append({
                    "kind": "compound", "id": source["compound_id"],
                    "label_zh": label, "reason_zh": row["reason"],
                })
    # 配置缺口与逐项缺口同时列出，用户不用补完一类才发现下一类。
    try:
        validate(
            {**deepcopy(plan), "receptors": [], "compounds": []},
            {**context, "receptors": [], "compounds": []}, [], materials,
        )
    except (ValueError, KeyError, TypeError) as error:
        pending.append({
            "kind": "configuration", "id": "plan",
            "label_zh": "方案配置", "reason_zh": str(error),
        })
    # 完整校验检查顺序、范围与配置，保留所有原门控。
    try:
        validate(plan, context, [r["target_id"] for r in context["receptors"]], materials)
        ready = not pending
    except (ValueError, KeyError, TypeError) as error:
        ready = False
        if not pending:
            pending.append({
                "kind": "configuration", "id": "plan",
                "label_zh": "方案配置", "reason_zh": str(error),
            })
    return {
        "ready": ready,
        "receptor_count": len(context["receptors"]),
        "compound_count": len(context["compounds"]),
        "planned_pair_count": len(context["receptors"]) * len(context["compounds"]),
        "normal_target_ids": normal,
        "pending": pending,
        "unavailable": unavailable,
        "execution_allowed": False,
        "note_zh": "一次核对并提交完整方案；NA仍须明确核对。保存不启动计算、不批准质控或结果。",
    }
