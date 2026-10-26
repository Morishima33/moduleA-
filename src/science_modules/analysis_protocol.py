"""新研究分析方案第一版：参数、阶段依赖及复用指纹，不改变旧固定协议。"""

from copy import deepcopy
import math
import re

from contracts import ContractError, fingerprint, require

VERSION = "ModuleA.analysis_plan.1"
WINDOWS = (10, 15, 20, 25)
FIXED = {
    "species": 9606, "vina_version": "1.2.7", "p_adjust_method": "BH",
    "keep_boundary_ties": True, "batman_relations": "known",
    "herb_adme_filter": False, "batman_adme_filter": False,
    "receptor_failure": "retain_na_no_rank_replacement",
    "uncertain_records": "hold_out_with_evidence",
    "docking_packages": "on_demand", "default_strict_rmsd_A": 2.0,
    "alphafold_region": {"mean_plddt": 80.0, "min_plddt": 70.0, "max_bidirectional_pae_A": 10.0},
}

# 参数所属阶段决定实际接入及失效范围；合法上限不伪装为科研推荐阈值。
FIELDS = {
    "a01.ob_min": {"label": "TCMSP最低OB", "default": 30.0, "type": "number", "min": 0, "max": 100, "unit": "%", "stages": ["A01"]},
    "a01.dl_min": {"label": "TCMSP最低DL", "default": .18, "type": "number", "min": 0, "unit": "", "stages": ["A01"]},
    "a04.required_score": {"label": "STRING置信度", "default": .90, "type": "number", "min": 0, "max": 1, "resolution": .001, "unit": "", "stages": ["A04_NETWORK"]},
    "a04.mode": {"label": "受体筛选模式", "default": "dual_ab", "type": "enum", "choices": ["degree", "bc_cc", "dual_ab"], "stages": ["A04_SELECTION"]},
    "a04.degree_main_window": {"label": "Degree主窗口", "default": 10, "type": "integer", "choices": WINDOWS, "active_when": {"a04.mode": "dual_ab"}, "stages": ["A04_SELECTION"]},
    "a04.bc_cc_window": {"label": "BC＋CC窗口", "default": 15, "type": "integer", "choices": WINDOWS, "active_when": {"a04.mode": "dual_ab"}, "stages": ["A04_SELECTION"]},
    "a04.degree_pool_window": {"label": "Degree候选池", "default": 15, "type": "integer", "choices": WINDOWS, "active_when": {"a04.mode": "dual_ab"}, "stages": ["A04_SELECTION"]},
    "a05.include_go": {"label": "纳入GO", "default": True, "type": "boolean", "stages": ["A05_STATISTICS"]},
    "a05.include_kegg": {"label": "纳入KEGG", "default": True, "type": "boolean", "stages": ["A05_STATISTICS"]},
    "a05.adjusted_p_max": {"label": "BH校正后P值上界", "default": .05, "type": "number", "min_exclusive": 0, "max": 1, "comparison": "<", "stages": ["A05_FILTER"]},
    "a05.min_term_size": {"label": "条目背景基因数下限", "default": 10, "type": "integer", "min": 1, "stages": ["A05_STATISTICS"]},
    "a05.max_term_size": {"label": "条目背景基因数上限", "default": 500, "type": "integer", "min": 1, "stages": ["A05_STATISTICS"]},
    "a05.go_plot_top": {"label": "GO各类图展示前列", "default": 15, "type": "integer", "choices": WINDOWS, "stages": ["A05_DISPLAY"]},
    "a05.go_table_top": {"label": "GO各类表展示前列", "default": 15, "type": "integer", "choices": WINDOWS, "stages": ["A05_DISPLAY"]},
    "a05.kegg_plot_top": {"label": "KEGG图展示前列", "default": 15, "type": "integer", "choices": WINDOWS, "stages": ["A05_DISPLAY"]},
    "a05.kegg_table_top": {"label": "KEGG两种排名表展示前列", "default": 10, "type": "integer", "choices": WINDOWS, "stages": ["A05_DISPLAY"]},
    "a06.component_count": {"label": "目标成分数", "default": 15, "type": "integer", "min": 1, "max": 25, "stages": ["A03_SELECT"]},
    "a06.receptor_count": {"label": "目标受体数", "default": 15, "type": "integer", "min": 1, "max": 25, "stages": ["A04_SELECTION"]},
    "a06.component_sort": {"label": "成分排序", "default": "intersection_count", "type": "enum", "choices": ["intersection_count", "mixed_degree"], "stages": ["A03_SELECT"]},
    "a06.exhaustiveness": {"label": "Vina搜索投入", "default": 8, "type": "integer", "min": 1, "max": 2147483647, "stages": ["A06_REDOCKING", "A06_SCORING"]},
    "a06.num_modes": {"label": "最多输出姿势数", "default": 9, "type": "integer", "min": 1, "max": 2147483647, "stages": ["A06_REDOCKING", "A06_SCORING"]},
    "a06.energy_range": {"label": "输出能量差范围", "default": 3.0, "type": "number", "min": 0, "unit": "kcal/mol", "stages": ["A06_REDOCKING", "A06_SCORING"]},
    "a06.seed": {"label": "固定随机种子", "default": 1, "type": "integer", "min": 1, "max": 2147483647, "stages": ["A06_REDOCKING", "A06_SCORING"]},
    "a06.box_padding": {"label": "搜索盒每侧外扩", "default": 5.0, "type": "number", "min": 0, "unit": "Å", "stages": ["A06_BOX"]},
    "a06.redocking_rmsd_max": {"label": "方案重对接RMSD上限", "default": 2.0, "type": "number", "min_exclusive": 0, "unit": "Å", "stages": ["A06_QUALITY"]},
}

STAGES = {
    "A00": (), "A01": ("A00",), "A02": ("A00",),
    "A03": ("A01", "A02"), "A03_SELECT": ("A03",),
    "A04_NETWORK": ("A03",), "A04_SELECTION": ("A04_NETWORK",),
    "A05_STATISTICS": ("A03",), "A05_FILTER": ("A05_STATISTICS",),
    "A05_DISPLAY": ("A05_FILTER",),
    "A06_PREPARATION": ("A03_SELECT", "A04_SELECTION"),
    "A06_BOX": ("A06_PREPARATION",), "A06_REDOCKING": ("A06_BOX",),
    "A06_QUALITY": ("A06_REDOCKING",), "A06_SCORING": ("A06_QUALITY",),
    "A06_DISPLAY": ("A06_SCORING",),
    "A07": ("A00", "A01", "A02", "A03", "A04_SELECTION", "A05_DISPLAY", "A06_DISPLAY"),
}


def parameter_catalog():
    """返回独立副本，供接口、未来表单及文档共同读取；不声明全流程已接通。"""
    return {"schema_version": VERSION, "parameters": deepcopy(FIELDS), "fixed": deepcopy(FIXED),
            "stage_dependencies": deepcopy(STAGES), "execution_ready": False,
            "message_zh": "参数与版本基础层；全流程模块尚未接通，不提供执行入口。"}


def _value(key, value):
    """严格拒绝布尔数值、非有限数、未知枚举及工具不能表达的置信度。"""
    field = FIELDS[key]
    kind = field["type"]
    if kind == "number":
        require(type(value) in (int, float), field["label"] + "类型无效")
        try:
            value = float(value)
        except (ValueError, OverflowError) as error:
            raise ContractError(field["label"] + "不是可表示的有限数值") from error
        require(math.isfinite(value), field["label"] + "不是有限数值")
    else:
        require((type(value) is bool) if kind == "boolean" else
                (type(value) is int) if kind == "integer" else (type(value) is str), field["label"] + "类型无效")
    if "min" in field:
        require(value >= field["min"], field["label"] + "低于允许下限")
    if "min_exclusive" in field:
        require(value > field["min_exclusive"], field["label"] + "须大于允许下限")
    if "max" in field:
        require(value <= field["max"], field["label"] + "超过允许上限")
    if "choices" in field:
        require(value in field["choices"], field["label"] + "不在允许选项中")
    if key == "a04.required_score":
        require(abs(value * 1000 - round(value * 1000)) < 1e-8, "STRING置信度最多三位小数")
    return float(value) if kind == "number" else value


def compile_plan(specification):
    """补齐统一默认值并固定内容指纹；标准方案不接受隐蔽的自定义参数。"""
    require(isinstance(specification, dict) and set(specification) <= {"schema_version", "mode", "parameters"}, "分析方案字段无效")
    require(specification.get("schema_version", VERSION) == VERSION, "分析方案版本不支持")
    mode = specification.get("mode")
    require(mode in ("standard", "personalized"), "请选择标准自动版或个性化版")
    supplied = specification.get("parameters", {})
    require(isinstance(supplied, dict) and set(supplied) <= set(FIELDS), "分析方案包含未知参数或不可调保护项")
    parameters = {key: _value(key, supplied.get(key, field["default"])) for key, field in FIELDS.items()}
    if mode == "standard":
        require(all(parameters[k] == f["default"] for k, f in FIELDS.items()), "标准自动版不能修改参数，请选择个性化版")
    require(parameters["a05.min_term_size"] <= parameters["a05.max_term_size"], "条目大小下限不能大于上限")
    if parameters["a04.mode"] == "dual_ab":
        require(parameters["a04.degree_pool_window"] >= parameters["a04.degree_main_window"], "Degree候选池不能小于Degree主窗口")
    warnings = []
    if parameters["a04.mode"] == "dual_ab" and parameters["a06.receptor_count"] > parameters["a04.degree_pool_window"]:
        warnings.append({"code": "POOL_SMALLER_THAN_TARGET", "message_zh": "目标受体数超过Degree候选池窗口；不足时按实际数量，不自动扩大或凑数。"})
    if not parameters["a05.include_go"] and not parameters["a05.include_kegg"]:
        warnings.append({"code": "ENRICHMENT_DISABLED", "message_zh": "GO与KEGG均未纳入，报告须说明富集不适用。"})
    if parameters["a06.redocking_rmsd_max"] > FIXED["default_strict_rmsd_A"]:
        warnings.append({"code": "CUSTOM_RMSD", "message_zh": "所选RMSD门槛高于默认2 Å；仍保留默认严格判定，不能改标为默认严格通过。"})
    content = {"schema_version": VERSION, "mode": mode, "parameters": parameters, "fixed": deepcopy(FIXED)}
    return dict(content, parameter_hash=fingerprint(content), warnings=warnings)


def _same_value(value, expected):
    """允许JSON跨语言的30与30.0等价，但布尔值绝不充当数值或保护开关。"""
    if isinstance(expected, dict):
        return isinstance(value, dict) and set(value) == set(expected) and all(_same_value(value[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(value, list) and len(value) == len(expected) and all(_same_value(a, b) for a, b in zip(value, expected))
    if type(expected) is float:
        return type(value) in (int, float) and value == expected
    return type(value) is type(expected) and value == expected


def checked_plan(plan):
    """读取已编译方案时重新校验完整内容，拒绝伪造指纹及保护规则。"""
    require(isinstance(plan, dict), "缺少已编译方案")
    expected = compile_plan({key: plan[key] for key in ("schema_version", "mode", "parameters") if key in plan})
    require(_same_value(plan, expected), "分析方案内容或指纹不一致")
    return expected


def affected_stages(previous, following):
    """按依赖闭包计算失效范围，不把展示调整升级为科研重算。"""
    old, new = checked_plan(previous)["parameters"], checked_plan(following)["parameters"]
    changed = [key for key in FIELDS if old[key] != new[key]]
    affected = {stage for key in changed for stage in FIELDS[key]["stages"]}
    if previous["mode"] != following["mode"]:
        affected.add("A07")
    while True:
        expanded = affected | {stage for stage, parents in STAGES.items() if any(p in affected for p in parents)}
        if expanded == affected:
            break
        affected = expanded
    return {"changed_parameters": changed, "stages": [s for s in STAGES if s in affected],
            "preserved_stages": [s for s in STAGES if s not in affected]}


def stage_fingerprint(plan, stage, inputs, tools):
    """复用键由算法、阶段参数、输入和工具指纹组成，不受展示名或无关参数影响。"""
    plan = checked_plan(plan)
    require(stage in STAGES, "未知分析阶段")
    require(isinstance(inputs, dict) and inputs and all(isinstance(k, str) and k and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in inputs.items()), "阶段输入须提供真实SHA256指纹")
    require(isinstance(tools, dict) and tools and all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in tools.items()), "阶段缺少工具及环境版本")
    parameters = {k: plan["parameters"][k] for k, field in FIELDS.items() if stage in field["stages"]}
    if stage == "A07":
        parameters = dict(plan["parameters"], mode=plan["mode"])
    return fingerprint({"algorithm_version": VERSION, "stage": stage, "parameters": parameters,
                        "fixed": plan["fixed"], "inputs": inputs, "tools": tools})
