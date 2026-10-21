"""第三版只增加明确共晶方案接入，旧计算参数与预测置信度保持。"""
from copy import deepcopy
from contracts import fingerprint
from .automatic_coverage_rules import POLICY as PREVIOUS_POLICY, binding as previous_binding

VERSION = "A06.automatic.3"
POLICY = dict(deepcopy(PREVIOUS_POLICY), version=VERSION,
    reference_selection="explicit_target_candidate_component_keys_verified_against_archived_cif",
    reference_fallback="unchanged_v2_exploration_when_unselected_or_strict_failed")
SUMMARY = "集中核定共晶参考配体后一次确认执行；未核定仍探索，严格重对接与80／70／10不放宽。"
DETAILS = ["参考配体候选来自同研究已归档实验坐标，不自动采用添加剂或共价配体。",
    "选择结构及配体稳定编号纳入本次执行授权；空选择继续原探索路线。",
    "共晶参考仍须原始原子完整、环境通过且Top-1重对接RMSD≤2Å；失败保留并转探索。",
    "旧一、二版连接和执行授权不自动升级，原评分不重写。"]


def binding(workflow, manifest):
    """版本指纹隔离，父研究及批准记录沿用既有保护。"""
    return dict(previous_binding(workflow, manifest), policy=fingerprint(POLICY))
