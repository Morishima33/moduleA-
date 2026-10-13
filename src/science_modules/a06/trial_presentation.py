"""试算展示第三版：参考图红蓝渐变，原评分阈值仅用于表格标记。"""

import math
from copy import deepcopy

from .matrix_palette import RED_BLUE

VERSION = "A06.trial.display.3"
PALETTE = deepcopy(RED_BLUE)
THRESHOLD = -8.0
SYMBOL = "**"
LEGEND = "**：原始Vina评分≤−8 kcal/mol，仅为本表数值标记，不表示统计显著性。"


def highlighted(score):
    """使用原始有限评分，避免四舍五入后错误跨过边界。"""
    return (
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
        and score <= THRESHOLD
    )


def score_label(score, mark=False):
    """不改评分；8×8保持普通数字，15×15标记命中格。"""
    if score is None:
        return "NA"
    return f"{score:.2f}" + (SYMBOL if mark and highlighted(score) else "")
