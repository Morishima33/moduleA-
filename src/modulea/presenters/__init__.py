"""展示适配登记表：模块编号 → 展示函数。

每个展示函数的签名都是 present(result, ctx) -> Parts：
- result：该模块当前运行已归档的 result.json（已由内核核验指纹）；
- ctx：研究级上下文，包括 workflow_profile、state_code，以及其他模块的当前结果 results（只读）。
没有登记的模块使用 present_generic，把摘要里的简单字段列为参数，保证新模块接入前也能显示。
"""

from __future__ import annotations

from .base import Parts, clean, fmt, param
from .docking import present_a06, present_a06_prep
from .intersection import present_a03, present_a03_select
from .network import present_a04, present_a05
from .registration import present_a00
from .report import present_a07
from .sources import present_a01, present_a02

PRESENTERS = {
    "A00": present_a00,
    "A01": present_a01,
    "A02": present_a02,
    "A03": present_a03,
    "A03_SELECT": present_a03_select,
    "A04": present_a04,
    "A05": present_a05,
    "A06_PREP": present_a06_prep,
    "A06": present_a06,
    "A07": present_a07,
}


def present_generic(result: dict, ctx: dict) -> Parts:
    """通用兜底：列出摘要中的简单字段。"""
    parts = Parts()
    summary = result.get("summary") or {}
    parts.params = clean([param(str(k), v) for k, v in summary.items() if isinstance(v, (str, int, float, bool))])
    return parts


def present(module_id: str, result: dict, ctx: dict) -> dict:
    """调用登记的展示函数；任何读取错误都降级为通用展示，并在 focus 中说明，不让整页失败。"""
    function = PRESENTERS.get(module_id, present_generic)
    try:
        return function(result, ctx).as_dict()
    except Exception as error:  # 展示层错误不应影响复核和其他模块
        parts = present_generic(result, ctx)
        parts.focus.append({"tier": "should_know", "title_zh": "展示适配未能完整读取本结果",
                            "body_zh": f"{type(error).__name__}: {fmt(str(error))}；请查看结果明细页签。", "impact_zh": "", "blocks": []})
        return parts.as_dict()
