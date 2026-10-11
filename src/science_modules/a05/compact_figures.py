"""A05第三版绘图：GO原字号和尺寸不变，KEGG及图例统一单蓝色深浅。"""
from pathlib import Path
from types import FunctionType
from . import figures as previous
from .compact_display import RULE

KEGG_PALETTE = RULE["palette"]
# 使用旧插值公式与新单色顺序色；颜色仍表示完整原始BH P的显著性。
color_scale = FunctionType(previous.color_scale.__code__, dict(vars(previous), KEGG_PALETTE=KEGG_PALETTE), "color_scale")

# 继承坐标、Count面积及图例尺寸，Count图例与气泡使用同一单蓝映射。
def draw_kegg(tables, stem):
    # Count图例的旧固定蓝色属于同一蓝色系；归档图的其余信息完全沿用。
    draw = FunctionType(previous.draw_kegg.__code__, dict(vars(previous), color_scale=color_scale), "draw_kegg")
    return draw(tables, stem)

# GO使用原函数保证PNG和SVG逐字节一致；只有KEGG颜色改变。
def draw_all(tables, directory):
    directory = Path(directory)
    return {"go": previous.draw_go(tables, directory/"A05_01_GO三分类前八"), "kegg": draw_kegg(tables, directory/"A05_02_KEGG统计显著性前十五")}
