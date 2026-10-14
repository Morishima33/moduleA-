"""第四版显示：同源中英标签、紧凑热图及右侧纵向色标，评分和旧导出保持。"""

from copy import deepcopy
from html import escape
import os
from pathlib import Path
from textwrap import wrap

from contracts import require
from .matrix_exports import validate_matrix, cell_label, na_lines
from .matrix_palette import color
from .trial_exports import matrix as original_matrix

VERSION = "A06.trial.display.4"


def matrix(packet, names=None):
    """复用原225格、展示范围与颜色，仅添加同源英文显示字段。"""
    view = deepcopy(original_matrix(packet))
    view["display_version"] = VERSION
    for part in (view["heatmap"], view["table"]):
        for row in part["rows"]:
            item = (names or {}).get(row["compound_id"], {})
            row["name_en"] = item.get("name_en", row.get("name_en", row.get("name", "")))
            row["name_zh"] = item.get("name_zh") or row["name_zh"]
    return validate_matrix(view)


def layout(view):
    """近方形绘图区给成分中英标签留空间，色标与矩阵等高。"""
    h = view["heatmap"]
    left, top, cw, rh = 308, 76, 66, 66
    return dict(
        left=left,
        top=top,
        cw=cw,
        rh=rh,
        width=left + len(h["columns"]) * cw + 106,
        height=top + len(h["rows"]) * rh + 80 + len(na_lines(view)) * 18,
    )


def _drawing(view):
    """PNG与SVG共用所有坐标、字号、颜色和文字，避免两种导出漂移。"""
    validate_matrix(view)
    g, h = layout(view), view["heatmap"]
    low, high = view["score_range"]
    elements = []

    def text(x, y, value, size=12, anchor="start", fill="#10253C"):
        elements.append(("text", x, y, str(value), size, anchor, fill))

    def rect(x, y, w, height, fill):
        elements.append(("rect", x, y, w, height, fill))

    x, y = g["left"], g["top"]
    plotheight = len(h["rows"]) * g["rh"]
    text(g["width"] / 2, 28, "重点结合能热图", 18, "middle")
    for j, target in enumerate(h["columns"]):
        text(x + (j + 0.5) * g["cw"], 51, target.get("symbol", target["target_id"]), 12, "middle")
        text(x + (j + 0.5) * g["cw"], 67, target.get("candidate_grade", ""), 10, "middle")
    for i, source in enumerate(h["rows"]):
        en = wrap(
            source.get("name_en", ""), width=47, break_long_words=True, break_on_hyphens=False
        )
        # 长化学名保持完整，必要时两行英文，不用省略号替代来源名称。
        linecount = max(1, len(en))
        first = y + i * g["rh"] + (g["rh"] - (linecount * 13 + 18)) / 2 + 15
        text(x - 12, first, source.get("name_zh", source["compound_id"]), 13, "end")
        for k, line in enumerate(en):
            text(x - 12, first + 15 + k * 13, line, 10, "end")
        for j, cell in enumerate(h["cells"][i]):
            cx, cy = x + j * g["cw"], y + i * g["rh"]
            rect(cx, cy, g["cw"] - 1, g["rh"] - 1, cell["color"])
            text(
                cx + (g["cw"] - 1) / 2,
                cy + g["rh"] / 2 + 5,
                cell_label(cell, view),
                13,
                "middle",
                cell["text_color"],
            )
    bx = x + len(h["columns"]) * g["cw"] + 24
    if low is not None:
        for pixel in range(plotheight):
            value = high - (high - low) * pixel / max(1, plotheight - 1)
            rect(bx, y + pixel, 17, 1, color(value, low, high, view["palette"]))
        for i in range(5):
            value = high - (high - low) * i / 4
            text(bx + 25, y + 4 + (plotheight - 7) * i / 4, f"{value:.3g}", 11)
        text(bx + 8, y - 15, "kcal/mol", 11, "middle")
    bottom = y + plotheight
    text(18, bottom + 27, "颜色范围取完整同批225格；越负越红，越不负越蓝。", 12)
    text(18, bottom + 48, "A/B表示候选梯队；Vina评分不能直接证明药效。", 12)
    for i, reason in enumerate(na_lines(view)):
        text(18, bottom + 68 + i * 18, reason, 11)
    return g, elements


def heatmap_svg(view):
    """接口只需标准库即可生成与后台PNG同几何的SVG。"""
    g, elements = _drawing(view)
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{g["width"]}" height="{g["height"]}" viewBox="0 0 {g["width"]} {g["height"]}" role="img" aria-label="中英成分重点结合能热图">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for item in elements:
        if item[0] == "rect":
            _, x, y, w, h, fill = item
            pieces.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
        else:
            _, x, y, value, size, anchor, fill = item
            pieces.append(
                f'<text x="{x}" y="{y}" font-family="Microsoft YaHei,Arial,sans-serif" font-size="{size}" text-anchor="{anchor}" fill="{fill}">{escape(value)}</text>'
            )
    return "".join(pieces) + "</svg>"


def export_heatmap(view, directory, font_path=None):
    """科学后台生成288dpi PNG，SVG文字可完整选取核查。"""
    from PIL import Image, ImageDraw, ImageFont

    font = Path(font_path or Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc")
    require(font.is_file(), "需要可用的中文绘图字体")
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    g, elements = _drawing(view)
    scale = 3
    image = Image.new("RGB", (g["width"] * scale, g["height"] * scale), "white")
    draw, fonts = ImageDraw.Draw(image), {}
    for item in elements:
        if item[0] == "rect":
            _, x, y, w, h, fill = item
            draw.rectangle(
                (
                    int(x * scale),
                    int(y * scale),
                    int((x + w) * scale) - 1,
                    int((y + h) * scale) - 1,
                ),
                fill=fill,
            )
        else:
            _, x, y, value, size, anchor, fill = item
            if size not in fonts:
                fonts[size] = ImageFont.truetype(str(font), size * scale)
            draw.text(
                (x * scale, y * scale),
                value,
                font=fonts[size],
                fill=fill,
                anchor={"start": "ls", "middle": "ms", "end": "rs"}[anchor],
            )
    files = {
        "svg": folder / "A06_01_中英重点结合能热图.svg",
        "png": folder / "A06_01_中英重点结合能热图.png",
    }
    files["svg"].write_text(heatmap_svg(view), encoding="utf-8")
    image.save(files["png"], dpi=(288, 288))
    return files
