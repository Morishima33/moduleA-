"""参数预览的中文分组和接通说明；默认值及合法范围仍只读取科学参数目录。"""

from copy import deepcopy

PREVIEW_VERSION = "ModuleA.analysis_plan_preview.1"

GROUPS = [
    {"key": "a01", "title_zh": "成分与来源", "stage_zh": "A01",
     "status": "backend_ready", "status_zh": "新方案获取与整理入口已接通，自动接续待开放",
     "description_zh": "三库共同整理成分与已有靶点关系，只有TCMSP采用OB/DL筛选。",
     "fields": ["a01.ob_min", "a01.dl_min"], "advanced_fields": []},
    {"key": "a04", "title_zh": "网络与受体筛选", "stage_zh": "A04",
     "status": "backend_ready", "status_zh": "后台已适配，自动接续待开放",
     "description_zh": "三种筛选模式选一种；A/B模式复用双分支结果，A优先、B补足。",
     "fields": ["a04.required_score", "a04.mode"],
     "advanced_fields": ["a04.degree_main_window", "a04.bc_cc_window", "a04.degree_pool_window"]},
    {"key": "a05", "title_zh": "GO与KEGG富集", "stage_zh": "A05",
     "status": "pending", "status_zh": "参数可预览，执行适配待接通",
     "description_zh": "选择分析内容、显著性和图表范围；原始统计与展示范围分别留存。",
     "fields": ["a05.include_go", "a05.include_kegg", "a05.adjusted_p_max", "a05.go_plot_top",
                "a05.go_table_top", "a05.kegg_plot_top", "a05.kegg_table_top"],
     "advanced_fields": ["a05.min_term_size", "a05.max_term_size"]},
    {"key": "a06", "title_zh": "对接与目标热图", "stage_zh": "A03_SELECT / A06",
     "status": "backend_ready", "status_zh": "准备与评分已接通，整链自动接续待开放",
     "description_zh": "先定目标范围，按同批准备和明确复核评分；对接包仍需后续按需交付适配。",
     "fields": ["a06.component_count", "a06.receptor_count", "a06.component_sort"],
     "advanced_fields": ["a06.exhaustiveness", "a06.num_modes", "a06.energy_range", "a06.seed",
                         "a06.box_padding", "a06.redocking_rmsd_max"]},
]

DETAILS = {
    "a01.ob_min": {"help_zh": "口服生物利用度预测下限；与DL同时达标才纳入TCMSP成分。"},
    "a01.dl_min": {"help_zh": "类药性预测下限；仅用于TCMSP，不套用到HERB或BATMAN。"},
    "a04.required_score": {"help_zh": "STRING关系置信度，以0～1的小数显示；新方案请求、筛边与复算读取同一参数。"},
    "a04.mode": {"help_zh": "Degree按连接数排序；BC＋CC参考桥梁作用和接近程度；A/B先取A，再由B补足。",
                 "choices_zh": {"degree": "按Degree排名", "bc_cc": "按BC＋CC排名", "dual_ab": "沿用A/B候选（当前方法）"}},
    "a04.degree_main_window": {"help_zh": "仅A/B模式使用：第二轮Degree主窗口，参与A组与B组划分。"},
    "a04.bc_cc_window": {"help_zh": "仅A/B模式使用：BC＋CC综合排名窗口，参与A组划分。"},
    "a04.degree_pool_window": {"help_zh": "仅A/B模式使用：Degree候选池窗口；最终目标受体数在对接范围中另设。"},
    "a05.include_go": {"help_zh": "是否纳入GO功能富集。"},
    "a05.include_kegg": {"help_zh": "默认纳入KEGG；其他疾病通路仍按已确认的官方分类范围规则处理。"},
    "a05.adjusted_p_max": {"help_zh": "保留BH校正后P值小于此值的条目；不改变已保存的原统计。"},
    "a05.go_plot_top": {"help_zh": "GO三类各展示的前列条目数。"},
    "a05.go_table_top": {"help_zh": "GO三类明细表各展示的前列条目数。"},
    "a05.kegg_plot_top": {"help_zh": "完成展示范围筛选后，KEGG图展示的前列条目数。"},
    "a05.kegg_table_top": {"help_zh": "KEGG统计显著性和命中基因数两张表各展示的前列条目数。"},
    "a05.min_term_size": {"help_zh": "一个功能条目在背景中包含的基因数下限，不是研究输入基因数。"},
    "a05.max_term_size": {"help_zh": "一个功能条目在背景中包含的基因数上限，不限制输入集合只能有500个基因。"},
    "a06.component_count": {"help_zh": "可填写1—25的整数；按选定排序取目标成分数，保留边界并列，不足按实际数量。"},
    "a06.receptor_count": {"help_zh": "可填写1—25的整数；保留边界并列。结构失败留NA，不用低排名受体凑数。"},
    "a06.component_sort": {"help_zh": "主排序按不同交集靶点数；混合Degree还计入药味—成分连接。",
                           "choices_zh": {"intersection_count": "按交集靶点数", "mixed_degree": "按混合Degree"}},
    "a06.exhaustiveness": {"help_zh": "搜索投入；增大通常增加计算时间，不保证一定得到更好姿势。"},
    "a06.num_modes": {"help_zh": "最多输出姿势数；不承诺每组一定输出这么多，评分仍沿用已确认的Top-1规则。"},
    "a06.energy_range": {"help_zh": "保留输出姿势相对最佳评分的能量差范围，不是疗效或统计显著性门槛。"},
    "a06.seed": {"help_zh": "固定随机种子，方便同输入、同工具版本下复现。"},
    "a06.box_padding": {"help_zh": "位点搜索盒每侧外扩距离；改变搜索范围，也可能增加计算量。"},
    "a06.redocking_rmsd_max": {"help_zh": "参考配体重对接的姿势一致性门槛；放宽后仍保留默认≤2 Å的严格判定。"},
}


def presentation():
    """仅返回界面说明和已实现状态，不改参数默认值，不提供研究创建或执行能力。"""
    return {"version": PREVIEW_VERSION, "preview_only": True, "groups": deepcopy(GROUPS),
            "details": deepcopy(DETAILS),
            "source_rules": [
                {"name": "TCMSP", "rule_zh": "OB与DL同时筛选；保留原始靶点和HGNC依据。"},
                {"name": "HERB", "rule_zh": "完整成分及已有成分—靶点关系；不额外套用OB/DL。"},
                {"name": "BATMAN", "rule_zh": "完整成分清单与known关系；不额外套用OB/DL，不采用预测关系。"}],
            "fixed_rules_zh": ["研究物种固定为人类", "Vina版本固定，不提供版本切换", "多重检验使用BH校正",
                               "默认保留边界并列，不足按实际", "对接包在结果后按需生成"],
            "message_zh": "本页用于预览和参数校验，不创建研究、不保存到已有项目、不启动计算。"}
