"""第22版文档修改层：保留既有报告骨架，按用户批注重排局部与统一样式。"""

from pathlib import Path
import re
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from contracts import require
from storage import verified_file

INTERNAL_ID = re.compile(r"(?:study|run|trial|report_rev|review|decision)_[0-9a-f]{32}")


def replace_text(paragraph, text, size=None):
    """局部改文字保留段落样式与原首个run的字形属性。"""
    old = paragraph.runs[0]._r.rPr if paragraph.runs else None
    from copy import deepcopy

    paragraph.text = text
    if old is not None:
        paragraph.runs[0]._r.insert(0, deepcopy(old))
    if size:
        paragraph.runs[0].font.size = Pt(size)


def clean_text(text):
    text = re.sub(r"完整排名见A03归档（[^）]*）。", "", text)
    text = INTERNAL_ID.sub("", text)
    return (
        text.replace("首轮", "第一轮").replace("次轮", "第二轮").replace("首次筛选", "第一轮筛选")
    )


def tidy(document):
    """清理内部编号，正文表格采用一致表头、边框、行距及可扩展行高。"""
    for style in document.styles:
        if style.type == 1 and (
            style.name.startswith("Heading") or style.name in ("Title", "Subtitle")
        ):
            style.font.color.rgb = RGBColor(0, 0, 0)
    for paragraph in document.paragraphs:
        text = clean_text(paragraph.text)
        if text != paragraph.text:
            replace_text(paragraph, text)
        if paragraph.style.name.startswith("Heading") or paragraph.style.name in (
            "Title",
            "Subtitle",
        ):
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor(0, 0, 0)
    for table in list(document.tables):
        if len(table.columns) == 1:
            # 旧提示框改成普通段落，不丢失用途或数据来源说明。
            p = document.add_paragraph(table.cell(0, 0).text)
            table._tbl.addprevious(p._p)
            table._tbl.getparent().remove(table._tbl)
            continue
        if (
            len(table.columns) == 2
            and table.rows[0].cells[0].text == "模块"
            and table.rows[0].cells[1].text == "运行编号"
        ):
            table._tbl.getparent().remove(table._tbl)
            continue
        for row in list(table.rows):
            if len(row.cells) == 2 and row.cells[0].text in ("研究编号", "报告修订"):
                table._tbl.remove(row._tr)
        table.autofit = False
        for column, cell in zip(table.columns, table.rows[0].cells):
            if cell.width is not None:
                column.width = cell.width
        for index, row in enumerate(table.rows):
            row.height = None
            pr = row._tr.get_or_add_trPr()
            for height in list(pr.findall(qn("w:trHeight"))):
                pr.remove(height)
            for cell in row.cells:
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                props = cell._tc.get_or_add_tcPr()
                for tag in ("tcBorders", "shd", "tcMar"):
                    for old in list(props.findall(qn("w:" + tag))):
                        props.remove(old)
                borders = OxmlElement("w:tcBorders")
                for edge in ("top", "bottom", "left", "right"):
                    node = OxmlElement("w:" + edge)
                    for key, value in {"val": "single", "sz": "4", "color": "D9D9D9"}.items():
                        node.set(qn("w:" + key), value)
                    borders.append(node)
                props.append(borders)
                fill = OxmlElement("w:shd")
                fill.set(
                    qn("w:fill"),
                    "0F5E6E" if index == 0 else ("F2F6F7" if index % 2 == 0 else "FFFFFF"),
                )
                props.append(fill)
                margins = OxmlElement("w:tcMar")
                for edge in ("top", "bottom", "left", "right"):
                    node = OxmlElement("w:" + edge)
                    node.set(qn("w:w"), "65")
                    node.set(qn("w:type"), "dxa")
                    margins.append(node)
                props.append(margins)
                for paragraph in cell.paragraphs:
                    text = clean_text(paragraph.text)
                    if text != paragraph.text:
                        replace_text(paragraph, text)
                    paragraph.paragraph_format.space_after = Pt(2)
                    paragraph.paragraph_format.space_before = Pt(2)
                    paragraph.paragraph_format.line_spacing = 1.08
                    for run in paragraph.runs:
                        run.font.color.rgb = (
                            RGBColor(255, 255, 255) if index == 0 else RGBColor(0, 0, 0)
                        )
                        if index == 0:
                            run.font.bold = True
    for section in document.sections:
        for container in (section.header, section.footer):
            for p in container.paragraphs:
                if INTERNAL_ID.search(p.text):
                    replace_text(p, clean_text(p.text))


def append_before(document, anchor, writer):
    """新增内容只移动到指定章节，末尾sectPr不移动。"""
    before = set(document._element.body)
    writer()
    for node in list(document._element.body):
        if node not in before and node.tag != qn("w:sectPr"):
            anchor.addprevious(node)


def clear_between(start, stop):
    boundary = None
    node = start._p.getnext()
    while node is not stop._p:
        nxt = node.getnext()
        if node.find(".//" + qn("w:sectPr")) is not None:
            boundary = node
        else:
            node.getparent().remove(node)
        node = nxt
    return boundary


def add_ranked_maps(document, payload, root):
    """两张客观命中位置图分别绑定当前排名，不使用机制通路批准替代来源检查。"""
    from PIL import Image

    for item in payload["ranked_pathway_maps"]["items"]:
        label = "统计显著性" if item["ranking"] == "statistical_significance" else "命中基因数"
        heading = document.add_heading("KEGG" + label + "排名第一通路命中图", level=2)
        heading.paragraph_format.page_break_before = True
        intro = document.add_paragraph(
            item["name_zh"]
            + "（"
            + item["name_en"]
            + "；"
            + item["id"]
            + "）。"
            + f"Count={item['count']}，BH校正后P值={item['adjusted_p']:.3e}。红色仅标记本次输入命中的基因，不表示表达上调或通路激活。"
        )
        intro.paragraph_format.keep_with_next = True
        path = verified_file(root, item["png"])
        with Image.open(path) as image:
            ratio = image.height / image.width
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        width = min(6.35, 8.2 / ratio)
        pic = p.add_run().add_picture(str(path), width=Inches(width))
        pic._inline.docPr.set("descr", item["name_zh"] + "本次命中基因在KEGG原生图的位置")
        document.add_paragraph(
            "图 KEGG "
            + label
            + "第一名。使用KEGG原生通路图和pathview标注；命中基因在多个节点出现时均保留。"
        )
        missing = item.get("not_in_current_kgml", [])
        if missing:
            document.add_paragraph(
                f"原富集命中中有{len(missing)}个基因未出现在本次KEGG图节点中，名单和下载版本保存在图源证据中；富集Count及P值保持原值。"
            )


def revise_detailed(destination, payload, root):
    """局部修改首页、方法、富集排列和A06展示，未涉及章节继续沿用原模板。"""
    from science_modules.a05.compact_report_section import (
        add_graph,
        add_table,
        GO_COLUMNS,
        KEGG_COLUMNS,
        GO_CAPTION,
        KEGG_CAPTION,
    )
    from science_modules.a05.compact_display import go_rows, kegg_rows

    doc = Document(destination)
    structure = next((p for p in doc.paragraphs if p.text.startswith("结构方向：")), None)
    if structure:
        replace_text(
            structure,
            f"结构方向：原始Vina评分≤−8 kcal/mol的组合共{len(payload['strong_pairs'])}组，按受体分列如下（单位kcal/mol）。",
        )
        anchor = structure._p
        for target in dict.fromkeys(row["受体"] for row in payload["strong_pairs"]):
            text = (
                target
                + "："
                + "、".join(
                    row["成分"] + f"（{row['结合能（kcal/mol）']:.2f}）"
                    for row in payload["strong_pairs"]
                    if row["受体"] == target
                )
                + "。"
            )
            paragraph = doc.add_paragraph(text)
            anchor.addnext(paragraph._p)
            anchor = paragraph._p
        paragraph = doc.add_paragraph("该界值仅用于标记本批展示组合，不表示统计显著性或实测药效。")
        anchor.addnext(paragraph._p)
    for p in doc.paragraphs:
        if p.text.startswith("成分与方剂靶点："):
            replace_text(p, payload["report_methods"][0])
        elif p.text.startswith("疾病靶点："):
            replace_text(p, payload["report_methods"][1])
        elif p.text.startswith("交集与候选："):
            replace_text(p, payload["report_methods"][2])
        elif p.text.startswith("PPI："):
            replace_text(p, payload["report_methods"][3])
        elif p.text.startswith("富集："):
            replace_text(p, payload["report_methods"][4])
        elif p.text.startswith("分子对接："):
            replace_text(p, payload["report_methods"][5])
        elif p.text == "9 复核与追溯":
            replace_text(p, "9 结果复核说明")
            note = doc.add_paragraph(
                "双报告使用同一份事实包，结论仍需人工复核；完整来源、参数、软件和文件指纹随研究归档保存。"
            )
            p._p.addnext(note._p)
    h5 = next(p for p in doc.paragraphs if p.text == "5 GO与KEGG富集结果")
    h6 = next(p for p in doc.paragraphs if p.text == "6 分子对接结果")
    boundary = clear_between(h5, h6)
    tables = payload["a05_display"]["tables"]

    def enrichment():
        doc.add_heading("GO富集结果", level=2)
        doc.add_paragraph(
            "GO将基因功能分为生物过程（BP）、细胞组分（CC）和分子功能（MF）。各类独立按BH校正后P值升序排序，前三项摘要见主要结论，完整前十五列于下表。"
        )
        for row in payload["conclusion_sections"]:
            if row["层次"].startswith("GO "):
                doc.add_paragraph(row["层次"] + "：" + row["结论"])
        for i, (group, name) in enumerate(
            (("BP", "生物过程"), ("CC", "细胞组分"), ("MF", "分子功能")), 1
        ):
            add_table(
                doc,
                f"表 A05 0{i} GO {group} {name}前十五",
                go_rows(tables, group),
                GO_COLUMNS,
                [8.1, 5.5, 3.4],
            )
        add_graph(doc, tables, root, "go", GO_CAPTION)
        doc.add_heading("KEGG富集结果", level=2)
        doc.add_paragraph(
            "KEGG两种排名来自同一已确认展示范围。统计显著性按BH校正后P值升序，Count排名按命中基因数降序；两者分别反映统计证据与命中规模，均不直接表示疾病关联强弱或疗效。"
        )
        for row in payload["conclusion_sections"]:
            if row["层次"].startswith("KEGG"):
                doc.add_paragraph(row["层次"] + "：" + row["结论"])
        add_table(
            doc,
            "表 A05 04 KEGG统计显著性前十",
            kegg_rows(tables, "kegg_p_top10"),
            KEGG_COLUMNS,
            [7, 4.7, 1.4, 3.9],
        )
        add_table(
            doc,
            "表 A05 05 KEGG命中基因数前十",
            kegg_rows(tables, "kegg_count_top10"),
            KEGG_COLUMNS,
            [7, 4.7, 1.4, 3.9],
        )
        add_graph(doc, tables, root, "kegg", KEGG_CAPTION)
        add_ranked_maps(doc, payload, root)
        # 机制通路另有人工认可，排名图不会新增或替代该批准。
        if payload.get("selected_pathway"):
            from report_pathway import add_selected_pathway
            from report_flow_pathway import _font

            add_selected_pathway(doc, payload, root, _font)

    append_before(doc, boundary if boundary is not None else h6._p, enrichment)
    # 同批矩阵保留所有评分，成分第一列统一中英文。
    matrix_tables = [
        t for t in doc.tables if len(t.columns) == len(payload["trial_packet"]["receptors"]) + 1
    ]
    require(len(matrix_tables) == 1, "专业报告同批对接矩阵缺失或重复")
    for row, compound in zip(matrix_tables[0].rows[1:], payload["trial_packet"]["compounds"]):
        row.cells[0].text = payload["compound_labels"][compound["compound_id"]]
        for run in row.cells[0].paragraphs[0].runs:
            run.font.size = Pt(7)
    # 删除长篇受体处理说明及其前面的强制分页，保留返回纵向的节断。
    long_heading = next((p for p in doc.paragraphs if p.text == "受体结构与处理范围"), None)
    if long_heading:
        previous = long_heading._p.getprevious()
        if previous is not None and previous.find(".//" + qn("w:br")) is not None:
            previous.getparent().remove(previous)
        node = long_heading._p
        while node is not None:
            if node.find(".//" + qn("w:sectPr")) is not None:
                break
            nxt = node.getnext()
            node.getparent().remove(node)
            node = nxt
    for table in doc.tables:
        if table.rows[0].cells[0].text == "名次" and len(table.columns) == 5:
            for row, source in zip(table.rows[1:], payload["a03_top10"]):
                row.cells[1].text = source["成分名称"]
    from docx.shape import InlineShape
    from docx.text.paragraph import Paragraph

    for p in list(doc.paragraphs):
        if p.text.startswith("同批试算版本："):
            p._p.getparent().remove(p._p)
            continue
        following = p._p.getnext()
        if (
            following is not None
            and following.tag == qn("w:p")
            and Paragraph(following, p._parent).text.startswith("图 A06 01")
        ):
            for inline in p._p.findall(
                ".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline"
            ):
                shape = InlineShape(inline)
                ratio = shape.height / shape.width
                shape.width = Cm(18)
                shape.height = int(Cm(18) * ratio)
                p.paragraph_format.keep_with_next = True
                shape._inline.docPr.set("descr", "同批8×8中英文成分行受体列热图")
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tidy(doc)
    doc.save(destination)


def build_concise(payload, destination, root, revision):
    """简报共用全部核心事实，完整64组清单及两张大通路图见专业版。"""
    from report_flow_pathway import _configure, _font, _add_heatmap, _table
    from science_modules.a06.trial_handoff import NOTE

    doc = Document()
    _configure(doc, "网络药理学与分子对接结果简报")
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Cm(1.3)
    section.left_margin = section.right_margin = Cm(1.4)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.05
    doc.styles["Normal"].paragraph_format.space_after = Pt(4)
    p = doc.add_paragraph("网络药理学与分子对接结果简报", style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(payload["research"]["formula"] + "  " + payload["research"]["disease"])
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if payload["analysis_purpose"] == "workflow_test":
        doc.add_paragraph("本次为流程测试，结果用于优先核验方向，不作为正式研究或临床疗效结论。")
    doc.add_heading("主要结论", level=1)
    for row in payload["conclusion_sections"]:
        if row["层次"] == "结构方向":
            text = f"本批{len(payload['trial_packet']['pairs'])}组中{len(payload['strong_pairs'])}组原始评分≤−8 kcal/mol，受体及中英文成分完整清单见专业版；该标记不表示统计显著性或疗效。"
        elif row["层次"] == "后续研究":
            continue
        else:
            text = row["结论"]
        p = doc.add_paragraph()
        _font(p.add_run(row["层次"] + "："), size=9, bold=True)
        _font(p.add_run(text), size=9)
    doc.add_heading("方法与关键数量", level=1)
    method = "；".join(payload["concise_methods"]) + "。"
    _font(doc.add_paragraph().add_run(method), size=9)
    rows = payload["key_counts"][:3] + [payload["key_counts"][-1]]
    _table(doc, rows, ["指标", "数值"], [13, 4], font_size=9)
    doc.add_page_break()
    doc.add_heading("重点对接结果", level=1)
    _add_heatmap(doc, payload, root, width=6.4)
    strongest = sorted(payload["strong_pairs"], key=lambda r: r["结合能（kcal/mol）"])[:3]
    text = (
        "评分最负的前三组："
        + "；".join(
            r["成分"] + "—" + r["受体"] + f"（{r['结合能（kcal/mol）']:.2f} kcal/mol）"
            for r in strongest
        )
        + "。"
    )
    _font(doc.add_paragraph().add_run(text), size=9)
    doc.add_paragraph(NOTE)
    doc.add_heading("解释与下一步", level=1)
    doc.add_paragraph(
        "网络中心性与富集反映当前数据库和统计背景；分子对接受构象、配体电离状态和搜索位点影响，评分不是实测结合自由能。优先核查同源姿势，再用生化或细胞实验验证候选方向。完整来源、统计表格、排名通路图及方法文献见专业详细版。"
    )
    tidy(doc)
    destination.parent.mkdir(parents=True, exist_ok=True)
    doc.save(destination)
