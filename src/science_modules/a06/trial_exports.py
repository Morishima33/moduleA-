"""同批试算的矩阵、CSV和专业报告适配；原始姿势与评分不回写。"""

import csv
from pathlib import Path

from storage import write_json

from .matrix_exports import export_heatmap
from .matrix_palette import PALETTE, color, text_color
from .trial_rules import validate_matrix

MODE_ZH = {
    "fixed_site": "预先固定共晶位点",
    "predicted_sites": "预测位点探索",
    "partitioned_blind": "分区盲搜",
}


def matrix(packet):
    """专业版及热图使用同一批225格范围，不调用原严格结果验证器放宽旧规则。"""
    validate_matrix(packet)
    values = [p["score"] for p in packet["pairs"] if p["state"] == "completed"]
    low, high = (min(values), max(values)) if values else (None, None)
    pairmap = {(p["compound_id"], p["target_id"]): p for p in packet["pairs"]}
    targets = [
        {
            **r,
            "quality_zh": "严格输入"
            if r.get("reused") and r.get("history_quality_zh") == "严格"
            else "试算",
        }
        for r in packet["receptors"]
    ]

    def part(compounds, receptors):
        cells = []
        for compound in compounds:
            line = []
            for receptor in receptors:
                pair = pairmap[(compound["compound_id"], receptor["target_id"])]
                fill = (
                    color(pair["score"], low, high)
                    if pair["score"] is not None
                    else PALETTE["na_color"]
                )
                line.append({**pair, "color": fill, "text_color": text_color(fill)})
            cells.append(line)
        return {"rows": compounds, "columns": receptors, "cells": cells}

    config = packet["display"]["config"]
    heat_compounds = [
        c
        for c in packet["compounds"]
        if c["compound_id"] in config["heatmap_compounds"]
    ]
    heat_targets = [r for r in targets if r["target_id"] in config["heatmap_targets"]]
    return {
        "ready": True,
        "result_version": packet["trial_id"],
        "score_range": [low, high],
        "palette": PALETTE,
        "full_pair_count": 225,
        "heatmap": part(heat_compounds, heat_targets),
        "table": part(packet["compounds"], targets),
        "display_version": "A06.trial.display.1",
    }


def create_export_data(packet, directory):
    """CSV与Excel输入保留实际Top-1精度，并附结构处理及区域追溯明细。"""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=False)
    view = matrix(packet)
    headers = ["成分"] + [r["symbol"] for r in packet["receptors"]]
    rows = [
        [c["name_zh"]] + [p["score"] if p["score"] is not None else "NA" for p in line]
        for c, line in zip(packet["compounds"], view["table"]["cells"])
    ]
    receptor_headers = [
        "受体",
        "A/B",
        "结构",
        "评分来源",
        "区域数",
        "原RMSD（Å）",
        "处理及用途",
        "HGNC",
    ]
    receptor_rows = [
        [
            r["symbol"],
            r["candidate_grade"],
            r.get("structure_id", "NA"),
            MODE_ZH[r["mode"]],
            len(r["regions"]),
            r.get("history_rmsd_A"),
            r.get("processing_zh", r.get("reason_zh", "")),
            r["target_id"],
        ]
        for r in packet["receptors"]
    ]
    region_headers = [
        "成分",
        "成分ID",
        "受体",
        "区域",
        "Top-1（kcal/mol）",
        "状态",
        "选中最低区域",
        "评分来源",
        "姿势文件",
        "失败原因",
    ]
    cmap = {c["compound_id"]: c["name_zh"] for c in packet["compounds"]}
    tmap = {r["target_id"]: r["symbol"] for r in packet["receptors"]}
    region_rows = [
        [
            cmap[p["compound_id"]],
            p["compound_id"],
            tmap[p["target_id"]],
            r["region_id"],
            r["score"],
            r["state"],
            r["region_id"] == p["selected_region_id"],
            MODE_ZH[p["mode"]],
            r.get("pose", {}).get("path", ""),
            r.get("reason_zh", ""),
        ]
        for p in packet["pairs"]
        for r in p["regions"]
    ]
    for name, head, lines in (
        ("15×15结合能试算表.csv", headers, rows),
        ("受体处理明细.csv", receptor_headers, receptor_rows),
        ("区域计算明细.csv", region_headers, region_rows),
    ):
        with (folder / name).open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(head)
            writer.writerows(lines)
    data = {
        "trial_id": packet["trial_id"],
        "matrix_headers": headers,
        "matrix_rows": rows,
        "receptor_headers": receptor_headers,
        "receptor_rows": receptor_rows,
        "region_headers": region_headers,
        "region_rows": region_rows,
        "cell_colors": [[c["color"] for c in line] for line in view["table"]["cells"]],
        "cell_text_colors": [
            [c["text_color"] for c in line] for line in view["table"]["cells"]
        ],
    }
    write_json(folder / "excel_input.json", data)
    write_json(folder / "matrix.json", view)
    export_heatmap(view, folder)
    return view


def append_professional_trial(document, packet, png):
    """新专业报告A06扩展节；十五列横向表，独立试算不替换正式得分表。"""
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    view = matrix(packet)
    empty = not document.paragraphs and not document.tables
    section = (
        document.sections[-1] if empty else document.add_section(WD_SECTION.NEW_PAGE)
    )
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21)
    section.left_margin = section.right_margin = Cm(1.5)
    section.top_margin = section.bottom_margin = Cm(1.4)
    if empty:
        document.add_paragraph("A06分子对接扩展试算", style="Title")
    document.add_heading("A06 扩展试算", level=2)
    document.add_paragraph(
        "十五个已确认成分与十五个受体，共225个组合。"
        "本节为Vina对接评分试算，单位kcal/mol，不是实测结合自由能。"
        "共晶位点预先固定；预测口袋与分区盲搜取各区域Top-1最低值，保留完整区域明细。"
    )
    document.add_picture(str(png), width=Cm(18))
    document.add_paragraph(
        "图 A06 01 重点8×8热图。冰蓝至莓果红，越负越偏红；"
        "色标取同批完整225格的有效评分范围，NA为灰色。A/B为候选梯队。"
    )
    document.add_page_break()
    document.add_heading("表 A06 01 15×15结合能试算表", level=3)
    document.add_paragraph(
        "Vina对接评分，kcal/mol。表格显示两位小数，Excel与CSV保留实际输出精度。"
    )
    columns = ["成分"] + [
        r["symbol"] + "\n" + r["candidate_grade"] for r in packet["receptors"]
    ]
    table = document.add_table(rows=1, cols=16)
    table.autofit = False
    widths = [3.7] + [23 / 15] * 15
    for col, width in zip(table.columns, widths):
        col.width = Cm(width)
    values = [
        [c["name_zh"]]
        + ["NA" if cell["score"] is None else f"{cell['score']:.2f}" for cell in line]
        for c, line in zip(packet["compounds"], view["table"]["cells"])
    ]
    for line in values:
        table.add_row()
    for i, (row, line) in enumerate(zip(table.rows, [columns] + values)):
        props = row._tr.get_or_add_trPr()
        props.append(OxmlElement("w:cantSplit"))
        if i == 0:
            props.append(OxmlElement("w:tblHeader"))
        for j, (cell, value) in enumerate(zip(row.cells, line)):
            cell.text = value
            cell.width = Cm(widths[j])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            shading = OxmlElement("w:shd")
            shading.set(
                qn("w:fill"), "0F5E6E" if i == 0 else "FFFFFF" if i % 2 else "F2F6F7"
            )
            cell._tc.get_or_add_tcPr().append(shading)
            borders = OxmlElement("w:tcBorders")
            for side in ("top", "bottom", "left", "right"):
                edge = OxmlElement("w:" + side)
                for key, val in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                    edge.set(qn("w:" + key), val)
                borders.append(edge)
            cell._tc.get_or_add_tcPr().append(borders)
            for paragraph in cell.paragraphs:
                paragraph.alignment = (
                    WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.CENTER
                )
                paragraph.paragraph_format.space_before = Pt(2)
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.font.name = "Microsoft YaHei"
                    run.font.size = Pt(6 if i == 0 else 8)
                    run.bold = i == 0
                    run.font.color.rgb = RGBColor.from_string(
                        "FFFFFF" if i == 0 else "10253C"
                    )
    document.add_paragraph(
        "预先固定位点与多区域最低值的搜索范围不同，跨受体分数不能直接解释为亲和力优劣。"
        "原重对接失败及其他质控记录保留，试算不表示严格验证通过。"
    )
    document.add_paragraph("同批试算版本：" + packet["trial_id"])
    document.add_page_break()
    document.add_heading("受体结构与处理范围", level=3)
    document.add_paragraph(
        "所选链及可解析功能域用于本轮试算。仅增加已解析残基的缺失侧链与既定补氢，"
        "原重原子坐标不变，不重建缺失主链。详细组分、未采用候选及区域输出附Excel和归档明细。"
    )
    for r in packet["receptors"]:
        preparation = (
            "复用已核查准备输入。"
            if r.get("reused")
            else "独立准备；新增侧链原子"
            + str(len(r.get("repair", {}).get("added_atoms", [])))
            + "个，仅试算。"
        )
        document.add_paragraph(
            r["symbol"]
            + "（"
            + r["candidate_grade"]
            + "；"
            + r.get("structure_id", "NA")
            + "）："
            + MODE_ZH[r["mode"]]
            + "，"
            + str(len(r["regions"]))
            + "个区域。"
            + preparation
        )
    document.add_paragraph(
        "范围提示：JUN使用1S9K单链bZIP片段，并非完整蛋白或原复合物；"
        "GNAI1使用6CRK独立单体位点，GDP用于定位后移除。"
        "所选范围与伴随组分的逐项证据见Excel“受体处理”及processing_review.json。"
    )
    if not empty:
        restored = document.add_section(WD_SECTION.NEW_PAGE)
        restored.orientation = WD_ORIENT.PORTRAIT
        restored.page_width, restored.page_height = Cm(21), Cm(29.7)
    return view


def insert_professional_trial(document, packet, png):
    """完整专业报告只在A06之后、A07之前插入扩展节；临床版不调用此入口。"""
    from docx.oxml.ns import qn

    starts = [p for p in document.paragraphs if p.text == "6 分子对接结果"]
    stops = [p for p in document.paragraphs if p.text == "7 待进一步核验的研究线索"]
    if len(starts) != 1 or len(stops) != 1:
        raise ValueError("专业报告A06/A07章节位置不唯一")
    before = list(document._element.body)
    view = append_professional_trial(document, packet, png)
    for element in list(document._element.body):
        if element not in before and element.tag != qn("w:sectPr"):
            stops[0]._p.addprevious(element)
    return view
