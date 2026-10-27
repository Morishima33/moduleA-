"""A04新方案受体选择：只消费已复算的网络指标。"""
from copy import deepcopy

from contracts import fingerprint, require
from science_modules.analysis_protocol import checked_plan
from .personalized_selection import select_receptors

VERSION = "A04.plan_selection.1"


def select_from_network(network_run_id, network_summary, network_tables, plan):
    """将网络运行绑定到受体名单；选择参数变化会形成新的选择指纹。"""
    plan = checked_plan(plan)
    require(isinstance(network_run_id, str) and network_run_id, "缺少A04网络运行编号")
    require(isinstance(network_summary, dict) and isinstance(network_tables, dict), "A04网络结果格式不完整")
    metrics = network_tables.get("metrics")
    require(isinstance(metrics, list), "A04网络缺少完整指标表")
    selected = select_receptors(metrics, plan)
    selected.update({"schema_version": VERSION, "network_run_id": network_run_id,
                     "network_summary_fingerprint": fingerprint(network_summary),
                     "network_tables_fingerprint": fingerprint(network_tables),
                     "analysis_parameter_hash": plan["parameter_hash"],
                     "range_owner": "A04", "replacement_after_preparation_failure": False})
    return selected


def validate_selection(selection, network_run_id, network_summary, network_tables, plan):
    """复算并比较完整对象，防止单独修改名单、窗口或网络来源。"""
    expected = select_from_network(network_run_id, network_summary, network_tables, plan)
    require(selection == expected, "A04受体名单与网络结果或方案参数复算不一致")
    return expected
