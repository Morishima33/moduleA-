"""模块登记表：模块编号、中文名、导航分组、依赖关系和下游影响说明。

依赖关系直接取自科学内核 contracts.MODULES，不在这里另写一份，避免两处不一致。
本文件只补充“展示用”的信息：分组、用途说明、是否为子关口。
新增模块时：先在 contracts.MODULES 登记依赖，再在 PRESENTATION 补一行展示信息。
"""

from __future__ import annotations

from dataclasses import dataclass

from .kernel import MODULES

# 展示信息：(导航分组, 一句话用途, 是否在导航中缩进显示为子关口)
PRESENTATION: dict[str, tuple[str, str, bool]] = {
    "A00": ("研究登记", "方剂、药味、疾病与研究范围；MeSH 身份向 NLM 官方核对。", False),
    "A01": ("方剂与疾病资料", "从 TCMSP 固定快照整理成分、药味归属和成分—靶点关系。", False),
    "A02": ("方剂与疾病资料", "多来源疾病基因汇集、本病范围确认与 HGNC 身份统一。", False),
    "A03": ("交集与候选", "方剂靶点 T 与疾病靶点 D 取交集，作为 PPI 和富集的共同输入。", False),
    "A03_SELECT": ("交集与候选", "确定进入对接的成分；补充候选只保存，不自动对接。", True),
    "A04": ("网络与功能 · 并行", "STRING 人类功能关联网络，全部有边分量统一计算三指标两轮名单。", False),
    "A05": ("网络与功能 · 并行", "交集基因做 GO 三类与 KEGG 过度代表分析，BH 校正 p.adjust。", False),
    "A06_PREP": ("分子对接", "受体结构、搜索盒、配体准备与参考配体重对接质控。", False),
    "A06": ("分子对接", "固定 Top-1 姿势的原始 Vina 评分；失败保留 NA，不补 0。", False),
    "A07": ("报告", "专业详细版与临床简略版共用同一份结论、数字和图件。", False),
}

# 导航分组顺序
GROUP_ORDER = ["研究登记", "方剂与疾病资料", "交集与候选", "网络与功能 · 并行", "分子对接", "报告"]


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    title_zh: str
    group_zh: str
    purpose_zh: str
    sub: bool
    depends_on: tuple[str, ...]


def _build() -> dict[str, ModuleSpec]:
    specs = {}
    for module_id, (title, depends) in MODULES.items():
        group, purpose, sub = PRESENTATION.get(module_id, ("其他", "", False))
        specs[module_id] = ModuleSpec(module_id, title, group, purpose, sub, tuple(depends))
    return specs


SPECS: dict[str, ModuleSpec] = _build()
ORDER: list[str] = list(MODULES.keys())


def dependents(module_id: str) -> list[str]:
    """返回所有直接或间接依赖本模块的下游模块（按模块顺序）。"""
    found: set[str] = set()
    frontier = [module_id]
    while frontier:
        current = frontier.pop()
        for spec in SPECS.values():
            if current in spec.depends_on and spec.module_id not in found:
                found.add(spec.module_id)
                frontier.append(spec.module_id)
    return [m for m in ORDER if m in found]


def downstream_note(module_id: str) -> str:
    """生成“本模块变化会影响哪些下游”的中文说明。"""
    affected = dependents(module_id)
    if not affected:
        return "最后一步，没有下游模块。"
    independent = [m for m in ORDER if m != module_id and m not in affected and module_id not in SPECS[m].depends_on]
    text = "产生新版本后，依赖它的 " + "、".join(affected) + " 将失效并需重新生成和复核"
    siblings = [m for m in independent if set(SPECS[m].depends_on) & set(SPECS[module_id].depends_on) and m not in ("A00",)]
    if siblings:
        text += "；" + "、".join(siblings) + " 不受影响"
    return text + "。"
