"""新方案的TCMSP筛选适配；复用原身份与关系核验，旧A01.1行为不改。"""

from types import FunctionType

import components as legacy
from science_modules.analysis_protocol import checked_plan

VERSION = "A01.plan_screening.1"


def screening_parameters(plan):
    """获取服务端已校验参数，HERB和BATMAN不套用这些阈值。"""
    values = checked_plan(plan)["parameters"]
    return {"ob_min": values["a01.ob_min"], "dl_min": values["a01.dl_min"]}


def analyze_rows(rows, herbs, plan):
    """只为本次函数绑定配置，不改全局CONFIG，保留冲突及不明映射。"""
    parameters = screening_parameters(plan)
    configuration = dict(legacy.CONFIG, **parameters, version=VERSION)
    namespace = dict(vars(legacy), CONFIG=configuration)
    analyze = FunctionType(legacy.analyze.__code__, namespace, legacy.analyze.__name__, legacy.analyze.__defaults__, legacy.analyze.__closure__)
    summary, tables, anomalies = analyze(rows, herbs)
    reason = f"未同时达到OB≥{parameters['ob_min']:g}%且DL≥{parameters['dl_min']:g}"
    for row in tables["exclusions"]:
        if row.get("reason") == "未同时达到OB≥30%且DL≥0.18":
            row["reason"] = reason
    return {"schema_version": VERSION, "config": configuration, "summary": summary,
            "tables": tables, "anomalies": anomalies,
            "mapping_verified": False, "note_zh": "保留原始人类映射检查；后续仍须按本研究HGNC依据标准化。"}
