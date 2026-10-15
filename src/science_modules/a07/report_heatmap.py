"""第23版报告专用热图：长英文名称换行，沿用原格值、色标及全部坐标。"""

from textwrap import wrap
from types import FunctionType

from science_modules.a06 import bilingual_heatmap as original


def label_lines(value, **_):
    """完整名称按最多30字符换行，优先在化学名连字符处分行，不省略字符。"""
    return wrap(value, width=30, break_long_words=True, break_on_hyphens=True)


def bind(function, **changes):
    """为本版绑定局部展示函数，不修改已冻结版本的全局变量。"""
    return FunctionType(
        function.__code__,
        dict(function.__globals__, **changes),
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )


_drawing = bind(original._drawing, wrap=label_lines)
heatmap_svg = bind(original.heatmap_svg, _drawing=_drawing)
export_heatmap = bind(original.export_heatmap, _drawing=_drawing, heatmap_svg=heatmap_svg)
