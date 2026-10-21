"""自动结果的同源动态展示与独立导出；不改变评分、质控或运行批准。"""

from copy import deepcopy
import csv
from html import escape
import json
import math
import os
from pathlib import Path
from textwrap import wrap

from contracts import require
from .matrix_palette import RED_BLUE, color, text_color

VERSION = "A06.automatic.display.1"


def _selection(rows, key, selected):
    """显示选择只裁切原顺序；未知身份、重复或空选择均拒绝。"""
    ids = [r[key] for r in rows]
    chosen = ids[:8] if selected is None else selected
    require(isinstance(chosen, list) and chosen and all(isinstance(i, str) for i in chosen)
            and len(set(chosen)) == len(chosen) and set(chosen) <= set(ids), "显示范围包含未知、重复或空对象")
    return [deepcopy(r) for r in rows if r[key] in chosen]


def build_view(packet, names=None, selected_compounds=None, selected_targets=None):
    """完整矩阵与重点图读取同批评分；无中文保留原名，NA不填零。"""
    require(packet.get("schema_version") in ("A06.automatic.1", "A06.automatic.2", "A06.automatic.3"), "不支持的自动结果协议")
    names = names or {}
    rows = []
    for compound in packet["compounds"]:
        item = names.get(compound["compound_id"], {})
        en = item.get("name_en") or compound.get("name_en") or compound.get("name") or compound["compound_id"]
        zh = item.get("name_zh") or compound.get("name_zh") or ""
        rows.append({"compound_id": compound["compound_id"], "name_en": en, "name_zh": zh,
                     "name": zh or en, "name_evidence": deepcopy(item.get("evidence", []))})
    columns = [{"target_id": r["target_id"], "symbol": r.get("symbol", r["target_id"]),
                "candidate_grade": r.get("candidate_grade", r.get("grade", "")),
                "quality_zh": r.get("quality", "未通过")} for r in packet["receptors"]]
    require(len({r["compound_id"] for r in rows}) == len(rows) and len({r["target_id"] for r in columns}) == len(columns), "自动对象身份重复")
    pairs = {(p["compound_id"], p["target_id"]): p for p in packet["pairs"]}
    expected = {(c["compound_id"], r["target_id"]) for c in rows for r in columns}
    require(len(pairs) == len(packet["pairs"]) and set(pairs) == expected, "自动结果不是完整唯一矩阵")
    values = [p["score"] for p in pairs.values() if p["state"] == "completed"]
    require(all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in values), "有效评分非法")
    low, high = (min(values), max(values)) if values else (None, None)
    palette = dict(deepcopy(RED_BLUE), na_color="#FFFFFF")
    def part(cs, rs):
        cells = []
        for c in cs:
            line = []
            for r in rs:
                pair = pairs[(c["compound_id"], r["target_id"])]
                require(pair["state"] in ("completed", "failed", "NA"), "未知组合状态")
                valid = pair["state"] == "completed"
                require(valid or pair.get("score") is None, "未通过组合不能采用评分")
                score = pair["score"] if valid else None
                shade = color(score, low, high, RED_BLUE) if valid else "#FFFFFF"
                line.append({"compound_id": c["compound_id"], "target_id": r["target_id"],
                             "state": pair["state"], "score": score, "quality": pair.get("quality", ""),
                             "reason_zh": pair.get("reason_zh", "") or ("" if valid else "本组合无可用评分"),
                             "color": shade, "text_color": text_color(shade),
                             "display_score": f"{score:.2f}" if valid else "NA",
                             "threshold_mark": "**" if valid and score <= -8 else ""})
            cells.append(line)
        return {"rows": deepcopy(cs), "columns": deepcopy(rs), "cells": cells}
    view = {"schema_version": VERSION, "display_version": VERSION, "ready": True,
            "study_id": packet["study_id"], "run_id": packet["run_id"], "packet_id": packet["id"],
            "science_version": packet["schema_version"], "palette": palette, "score_range": [low, high],
            "heatmap": part(_selection(rows, "compound_id", selected_compounds), _selection(columns, "target_id", selected_targets)),
            "table": part(rows, columns), "summary": deepcopy(packet.get("summary", {})),
            "threshold_note_zh": "原始Vina评分≤−8 kcal/mol附**，不代表统计显著性。",
            "scope_note_zh": "A/B为候选梯队，严格与探索范围按逐组合依据解释；评分不能直接证明药效。"}
    return validate_view(view)


def validate_view(view):
    """导出入口重新验证完整范围、原始值、色标和子集，拒绝客户端替换图值。"""
    require(view.get("schema_version") == VERSION and view.get("palette") == dict(RED_BLUE, na_color="#FFFFFF"), "显示协议或颜色错误")
    full = view["table"]
    cells = {}
    for part in (full, view["heatmap"]):
        require(part["rows"] and part["columns"] and len(part["rows"]) == len(part["cells"]), "矩阵行不完整")
        for c, line in zip(part["rows"], part["cells"]):
            require(len(line) == len(part["columns"]), "矩阵列不完整")
            for r, value in zip(part["columns"], line):
                key = (c["compound_id"], r["target_id"])
                require(key == (value["compound_id"], value["target_id"]), "矩阵对象错误")
                if part is full:
                    require(key not in cells, "矩阵重复对象")
                    cells[key] = value
                else:
                    require(key in cells and cells[key] == value, "重点图与完整矩阵不一致")
    values = [c["score"] for c in cells.values() if c["state"] == "completed"]
    require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values), "有效评分非法")
    limits = [min(values), max(values)] if values else [None, None]
    require(view["score_range"] == limits, "色标未采用完整同批范围")
    for c in cells.values():
        valid = c["state"] == "completed"
        require(c["state"] in ("completed", "failed", "NA") and (valid or (c["score"] is None and bool(c["reason_zh"]))), "NA和异常必须保留原因")
        shade = color(c["score"], *limits, RED_BLUE) if valid else "#FFFFFF"
        require(c["color"] == shade and c["text_color"] == text_color(shade), "色值与评分不一致")
        require(c["display_score"] == (f"{c['score']:.2f}" if valid else "NA") and c["threshold_mark"] == ("**" if valid and c["score"] <= -8 else ""), "评分显示或标记不一致")
    return view


def _drawing(view, full=False, include_notes=True):
    """SVG与PNG共享动态几何；完整长名称换行、NA白底虚线、右侧纵色标。"""
    validate_view(view)
    part = view["table" if full else "heatmap"]
    labels = []
    for row in part["rows"]:
        en = wrap(row["name_en"], 42, break_on_hyphens=False) or [row["compound_id"]]
        labels.append(([row["name_zh"]] if row["name_zh"] and row["name_zh"] != row["name_en"] else []) + en)
    rh = max(66, max(len(lines) for lines in labels) * 16 + 18)
    left, top, cw = 314, 84, 72
    width, height = left + cw * len(part["columns"]) + 110, top + rh * len(labels) + 80
    items = []
    def text(x, y, value, size=12, anchor="start", fill="#10253C"):
        items.append(("text", x, y, str(value), size, anchor, fill))
    def rect(x, y, w, h, fill, dashed=False):
        items.append(("rect", x, y, w, h, fill, dashed))
    text(width / 2, 28, ("完整" if full else "重点") + f"结合能热图 {len(labels)}×{len(part['columns'])}", 18, "middle")
    for j, r in enumerate(part["columns"]):
        text(left + (j + .5) * cw, 55, r["symbol"], 12, "middle")
        text(left + (j + .5) * cw, 73, r["candidate_grade"], 10, "middle")
    for i, (row, lines) in enumerate(zip(part["rows"], labels)):
        first = top + i * rh + (rh - 16 * len(lines)) / 2 + 13
        for k, line in enumerate(lines):
            text(left - 12, first + 16 * k, line, 12 if k == 0 and row["name_zh"] else 10, "end")
        for j, c in enumerate(part["cells"][i]):
            x, y = left + j * cw, top + i * rh
            rect(x, y, cw - 1, rh - 1, c["color"], c["score"] is None)
            text(x + (cw - 1) / 2, y + rh / 2 + 4, c["display_score"], 13, "middle", c["text_color"])
    low, high = view["score_range"]
    plotheight = rh * len(labels)
    if low is not None:
        bx = left + cw * len(part["columns"]) + 24
        for p in range(plotheight):
            rect(bx, top + p, 17, 1, color(high - (high - low) * p / max(1, plotheight - 1), low, high, RED_BLUE))
        text(bx + 8, top - 15, "kcal/mol", 11, "middle")
        for k in range(5):
            text(bx + 24, top + 4 + (plotheight - 7) * k / 4, f"{high-(high-low)*k/4:.2f}", 10)
    bottom = top + plotheight
    if not include_notes:
        return {"width": width, "height": bottom + 12}, items
    total = len(view["table"]["rows"]) * len(view["table"]["columns"])
    text(18, bottom + 25, f"色标取完整同批{total}组有效范围；越负越红，越不负越蓝；NA白底虚线。", 11)
    text(18, bottom + 46, "A/B为候选梯队；探索评分不等于严格验证，不能直接证明药效。", 11)
    text(18, bottom + 66, "各NA及未通过原因见同批完整明细；原始评分≤−8的**标记见矩阵表。", 11)
    return {"width": width, "height": height}, items


def heatmap_svg(view, full=False, include_notes=True):
    """标准库内生成可编辑文字SVG，页面和下载使用同一布局。"""
    geometry, items = _drawing(view, full, include_notes)
    w, h = geometry["width"], geometry["height"]
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/>']
    for item in items:
        if item[0] == "rect":
            _, x, y, width, height, fill, dashed = item
            outline = ' stroke="#AAB4BE" stroke-dasharray="4 4"' if dashed else ""
            pieces.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}"{outline}/>')
        else:
            _, x, y, value, size, anchor, fill = item
            pieces.append(f'<text x="{x}" y="{y}" font-family="Microsoft YaHei,Arial,sans-serif" font-size="{size}" text-anchor="{anchor}" fill="{fill}">{escape(value)}</text>')
    return "".join(pieces) + "</svg>"


def export(view, directory, font_path=None, include_notes=True):
    """科学子进程生成PNG/SVG/Excel/CSV；延迟依赖不进入网页进程。"""
    from PIL import Image, ImageDraw, ImageFont
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, PatternFill, Font
    from openpyxl.comments import Comment
    validate_view(view)
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    planned = [f"A06_{label}结合能热图.{suffix}" for label in ("重点", "完整") for suffix in ("png", "svg")]
    planned += ["A06_完整评分明细.csv", "A06_完整结合能矩阵.xlsx"]
    require(not any((folder / name).exists() for name in planned), "禁止覆盖已有自动图表，请创建独立导出版本")
    font = Path(font_path or Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc")
    require(font.is_file(), "请配置可用的中文绘图字体")
    files = {}
    for full, prefix, label in ((False, "heatmap", "重点"), (True, "full_heatmap", "完整")):
        geometry, items = _drawing(view, full, include_notes)
        scale = 3
        image = Image.new("RGB", (geometry["width"] * scale, geometry["height"] * scale), "white")
        draw, fonts = ImageDraw.Draw(image), {}
        for item in items:
            if item[0] == "rect":
                _, x, y, width, height, fill, dashed = item
                box = tuple(round(v * scale) for v in (x, y, x + width, y + height))
                draw.rectangle(box, fill=fill)
                if dashed:
                    for start in range(0, round(width * scale), 8 * scale):
                        for edge in (box[1], box[3]):
                            draw.line((box[0] + start, edge, min(box[0] + start + 4 * scale, box[2]), edge), fill="#AAB4BE", width=scale)
                    for start in range(0, round(height * scale), 8 * scale):
                        for edge in (box[0], box[2]):
                            draw.line((edge, box[1] + start, edge, min(box[1] + start + 4 * scale, box[3])), fill="#AAB4BE", width=scale)
            else:
                _, x, y, value, size, anchor, fill = item
                if size not in fonts:
                    fonts[size] = ImageFont.truetype(str(font), size * scale)
                draw.text((x * scale, y * scale), value, fill=fill, font=fonts[size], anchor={"start": "ls", "middle": "ms", "end": "rs"}[anchor])
        png, svg = folder / f"A06_{label}结合能热图.png", folder / f"A06_{label}结合能热图.svg"
        image.save(png, dpi=(288, 288))
        svg.write_text(heatmap_svg(view, full, include_notes), encoding="utf-8")
        files[prefix + "_png"], files[prefix + "_svg"] = png, svg
    table = view["table"]
    csvpath = folder / "A06_完整评分明细.csv"
    fields = ["compound_id", "name_zh", "name_en", "target_id", "symbol", "candidate_grade", "state", "score", "display_score", "threshold_mark", "quality", "reason_zh"]
    with csvpath.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row, line in zip(table["rows"], table["cells"]):
            for target, cell in zip(table["columns"], line):
                source = dict(row, **target)
                source.update(cell)
                writer.writerow({k: source[k] for k in fields})
    files["csv"] = csvpath
    book = Workbook()
    sheet = book.active
    sheet.title = "完整评分矩阵"
    sheet.append(["成分中文名", "成分英文名"] + [r["symbol"] + (f" ({r['candidate_grade']})" if r["candidate_grade"] else "") for r in table["columns"]])
    for row, line in zip(table["rows"], table["cells"]):
        sheet.append([row["name_zh"], row["name_en"]] + [c["score"] if c["score"] is not None else "NA" for c in line])
        for j, cell in enumerate(line, 3):
            output = sheet.cell(sheet.max_row, j)
            output.fill = PatternFill("solid", fgColor=cell["color"].lstrip("#"))
            output.font = Font(color=cell["text_color"].lstrip("#"))
            output.number_format = '0.00"**"' if cell["threshold_mark"] else '0.00'
            output.comment = Comment(f"{cell['quality']}\n{cell['reason_zh']}\n{view['threshold_note_zh']}", "ModuleA")
    sheet.freeze_panes = "C2"
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 52
    for row in sheet:
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.append([view["threshold_note_zh"]])
    sheet.append([view["scope_note_zh"]])
    detail = book.create_sheet("原始评分与异常")
    detail.append(fields)
    with csvpath.open(encoding="utf-8-sig", newline="") as stream:
        for item in csv.DictReader(stream):
            detail.append([float(item[k]) if k == "score" and item[k] else item[k] for k in fields])
    xlsx = folder / "A06_完整结合能矩阵.xlsx"
    book.save(xlsx)
    files["xlsx"] = xlsx
    return files


def main():
    """仅消费已由Workflow归档核验的视图，不从客户端读取新评分或执行计算。"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--view", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--font-path")
    args = parser.parse_args()
    files = export(json.loads(Path(args.view).read_text(encoding="utf-8")), args.directory, args.font_path)
    print(json.dumps({k: str(v) for k, v in files.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
