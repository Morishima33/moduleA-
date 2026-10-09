"""来源方案的中文展示；读取研究绑定方案，不改科学内核的来源配置。"""
from __future__ import annotations

from disease import SOURCE_PROFILES

SOURCE_LABELS = {"BATMAN": "BATMAN-TCM", "OTP": "Open Targets Platform（OTP）"}

# 优先使用已归档的来源清单；尚无结果时仅显示当前登记所用方案。
def source_databases(module_id: str, manifest: dict, result: dict | None) -> list[str]:
    summary = (result or {}).get("summary") or {}
    if module_id == "A01":
        multisource = bool(summary.get("component_source_profile") or "候选成分分组数" in summary or (not result and manifest.get("component_source_profile")))
        return ["TCMSP", "HERB", "BATMAN"] if multisource else ["TCMSP"]
    if module_id == "A02":
        databases = summary.get("databases")
        if databases:
            return list(databases)
        rows = ((result or {}).get("tables") or {}).get("source_summary") or []
        if rows:
            return list(dict.fromkeys(row["database"] for row in rows))
        profile = summary.get("source_profile") or ("A02.source_profile.3" if manifest.get("workflow_profile") in ("A00.preupload.1", "A00.preupload.2") else "A02.source_profile.default.1")
        return list(SOURCE_PROFILES.get(profile, ()))
    return []

# 名称放在模块页首段，后文可使用库数简称；历史方案保留原库名。
def source_intro(module_id: str, manifest: dict, result: dict | None) -> str:
    databases = source_databases(module_id, manifest, result)
    if not databases:
        return ""
    count = {1: "单库", 3: "三库", 5: "五库"}.get(len(databases), str(len(databases)) + "库")
    subject = "成分与方剂靶点" if module_id == "A01" else "疾病靶点"
    return f"{subject}{count}：" + "、".join(SOURCE_LABELS.get(db, db) for db in databases) + "。"
