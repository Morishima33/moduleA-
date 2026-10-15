"""第24版报告热图：量取标签宽度，移除图内脚注；不改变评分及颜色。"""

import math
import os
from pathlib import Path

from contracts import require
from .report_heatmap import bind, label_lines
from science_modules.a06 import bilingual_heatmap as original


def layout(view):
    """按完整换行标签的真实字体宽度留边，避免固定大块空白或截字。"""
    from PIL import ImageFont

    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    require(path.is_file(), "报告热图需要可用的中文字体")
    zh, en = (ImageFont.truetype(str(path), size) for size in (13, 10))
    widths = []
    for row in view["heatmap"]["rows"]:
        widths.append(zh.getlength(row.get("name_zh", row["compound_id"])))
        widths.extend(en.getlength(line) for line in label_lines(row.get("name_en", "")))
    geometry = original.layout(view)
    geometry["left"] = math.ceil(max(widths, default=0)) + 32
    geometry["width"] = geometry["left"] + len(view["heatmap"]["columns"]) * geometry["cw"] + 106
    geometry["height"] = geometry["top"] + len(view["heatmap"]["rows"]) * geometry["rh"] + 18
    return geometry


_draw = bind(original._drawing, layout=layout, wrap=label_lines)


def drawing(view):
    """图内只保留标题、完整标签、原格值及色标；脚注在Word附录解释。"""
    geometry, elements = _draw(view)
    bottom = geometry["top"] + len(view["heatmap"]["rows"]) * geometry["rh"]
    return geometry, [item for item in elements if item[0] != "text" or item[2] <= bottom]


heatmap_svg = bind(original.heatmap_svg, _drawing=drawing)
export_heatmap = bind(original.export_heatmap, _drawing=drawing, heatmap_svg=heatmap_svg)
