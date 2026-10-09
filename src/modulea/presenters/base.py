"""展示适配的公共工具。

展示适配（presenter）只读已归档的 result.json，把它整理成前端需要的结构：
关键数字(kpis)、数量变化链(flow)、重点核对项(focus)、参数(params)、摘要表(table)和模块专属数据(special)。
约束：不联网、不计算科学结果、不改写任何文件；读不到的字段直接省略，不编造数字。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Parts:
    """一个模块视图中由展示适配负责的部分。"""

    kpis: list[dict] = field(default_factory=list)
    flow: list[dict] = field(default_factory=list)
    flow_note_zh: str = ""
    focus: list[dict] = field(default_factory=list)
    params: list[dict] = field(default_factory=list)
    table: dict | None = None
    special: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "kpis": self.kpis,
            "flow": self.flow,
            "flow_note_zh": self.flow_note_zh,
            "focus": self.focus,
            "params": self.params,
            "table": self.table,
            "special": self.special,
        }


def pick(mapping: dict | None, *keys: str, default: Any = None) -> Any:
    """依次尝试多个字段名，返回第一个存在且非空的值（不同版本结果的字段名可能不同）。"""
    if not mapping:
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def fmt(value: Any) -> str:
    """把数字和布尔值转成适合显示的文字；浮点数保留 3 位小数。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if abs(value) >= 1e-3 or value == 0 else f"{value:.2e}"
    return str(value)


def kpi(label: str, value: Any, note: str = "", source: str | None = None) -> dict | None:
    """关键数字卡片；值为空时返回 None，由调用方过滤。"""
    if value is None:
        return None
    return {"label_zh": label, "value": value, "text": fmt(value), "note_zh": note, "source": source}


def step(label: str, value: Any, note: str = "", delta: str = "", kind: str = "plain") -> dict | None:
    """数量变化链中的一步。kind: main(起点) / plain(中间) / end(进入下游的结果)。"""
    if value is None:
        return None
    return {"label_zh": label, "value": value, "text": fmt(value), "note_zh": note, "delta_zh": delta, "kind": kind}


def param(key: str, value: Any, origin: str = "recorded") -> dict | None:
    """参数与版本页签中的一行。origin 说明来源：recorded(运行记录) / outline(已批准大纲) / decision(用户决定)。"""
    if value in (None, ""):
        return None
    return {"label_zh": key, "value": fmt(value) if not isinstance(value, str) else value, "origin": origin}


def focus(title: str, body: str, tier: str = "must_handle", blocks: list[str] | None = None, impact: str = "") -> dict:
    """重点核对项。tier: must_handle(必须处理，置顶) / should_know(需要知悉)。"""
    blocks = blocks or []
    return {
        "tier": tier,
        "title_zh": title,
        "body_zh": body,
        "impact_zh": impact or ("不处理将阻断：" + "、".join(blocks) if blocks else ""),
        "blocks": blocks,
    }


def table(columns: list[tuple[str, str]], rows: list[dict], source: str | None = None, limit: int = 50) -> dict | None:
    """摘要表：columns 为 (字段名, 中文列名)；完整明细通过表格分页接口读取。"""
    if not rows:
        return None
    return {
        "columns": [{"key": key, "label_zh": label} for key, label in columns],
        "rows": [{key: row.get(key) for key, _ in columns} for row in rows[:limit]],
        "row_count": len(rows),
        "source_table": source,
    }


def clean(items: list) -> list:
    """去掉值为空而返回 None 的条目。"""
    return [item for item in items if item]


def tables_of(result: dict) -> dict:
    return result.get("tables") or {}
