"""第23版局部模板：十组结构摘要、富集正文去重和对接分页整理。"""

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from contracts import require

from .commented_documents import replace_text, tidy


def top_pairs(rows):
    """按未四舍五入的评分升序取十组，同分用稳定身份排序，只截展示名单。"""
    return sorted(
        rows,
        key=lambda row: (
            row["结合能（kcal/mol）"],
            row["target_id"],
            row["compound_id"],
        ),
    )[:10]


def revise_layout(doc, payload):
    """只编辑新生成文档，保留完整矩阵、首页富集摘要与纵横向节设置。"""
    from report_flow_pathway import _table
    from docx.shape import InlineShape

    structure = next((p for p in doc.paragraphs if p.text.startswith("结构方向：")), None)
    if structure is not None:
        node = structure._p.getnext()
        obsolete = []
        while node is not None:
            following = node.getnext()
            text = "".join(node.itertext())
            obsolete.append(node)
            if text.startswith("该界值仅用于标记"):
                break
            require(
                node.find(".//" + qn("w:sectPr")) is None, "结构方向替换范围遇到节断，请核查模板"
            )
            node = following
        require(node is not None, "结构方向替换终点缺失，请核查模板")
        for node in obsolete:
            node.getparent().remove(node)
        selected = top_pairs(payload["strong_pairs"])
        replace_text(
            structure,
            f"结构方向：本批原始Vina评分≤−8 kcal/mol的组合共{len(payload['strong_pairs'])}组，"
            f"以下按评分从低到高仅列前{len(selected)}组；完整评分见分子对接矩阵。",
        )
        if selected:
            rows = [
                {
                    "序号": i,
                    "成分": row["成分"],
                    "受体": row["受体"],
                    "Vina评分（kcal/mol）": f"{row['结合能（kcal/mol）']:.2f}",
                }
                for i, row in enumerate(selected, 1)
            ]
            _table(
                doc,
                rows,
                ["序号", "成分", "受体", "Vina评分（kcal/mol）"],
                [1, 10, 2, 4],
                font_size=9,
            )
            structure._p.addnext(doc.tables[-1]._tbl)
    body = False
    removing = False
    for p in list(doc.paragraphs):
        if p.text == "5 GO与KEGG富集结果":
            body = True
        elif p.text == "6 分子对接结果":
            body = False
        if body and p.text.startswith(
            (
                "GO BP 生物过程前三：",
                "GO CC 细胞组分前三：",
                "GO MF 分子功能前三：",
                "KEGG统计显著性前五：",
                "KEGG命中基因数前五：",
            )
        ):
            p._p.getparent().remove(p._p)
            continue
        if body and p.text.startswith("GO将基因功能分为"):
            replace_text(
                p,
                "GO分为生物过程（BP）、细胞组分（CC）和分子功能（MF）；"
                "各类独立按BH校正后P值升序排列，前十五项见下表。",
            )
        if p.text == "8 主要限制":
            removing = True
        elif removing and p.style.name == "Heading 1":
            removing = False
        if removing:
            p._p.getparent().remove(p._p)
            continue
        if p.text == "9 结果复核说明":
            replace_text(p, "8 结果复核说明")
        elif p.text == "10 主要方法参考文献":
            replace_text(p, "9 主要方法参考文献")
        # 节断保留纸张方向，压缩不可见标记，防止尾部标记单独挤出一页。
        if not p.text and p._p.find(".//" + qn("w:sectPr")) is not None:
            fmt = p.paragraph_format
            fmt.space_before = fmt.space_after = Pt(0)
            fmt.line_spacing = Pt(1)
            fmt.keep_with_next = False
            for run in p.runs:
                run.font.size = Pt(1)
        following = p._p.getnext()
        if following is not None:
            from docx.text.paragraph import Paragraph

            caption = Paragraph(following, p._parent).text if following.tag == qn("w:p") else ""
            if caption.startswith("图 A06 01"):
                for inline in p._p.findall(
                    ".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline"
                ):
                    shape = InlineShape(inline)
                    ratio = shape.height / shape.width
                    shape.width = Cm(15.8)
                    shape.height = int(Cm(15.8) * ratio)
    tidy(doc)


def revise_file(destination, payload):
    """专业版局部修订并保存；旧模板和已经发布的文件不回写。"""
    doc = Document(destination)
    revise_layout(doc, payload)
    doc.save(destination)


def revise_concise(destination):
    """简报沿用摘要与前三组，专业版引用改为前十展示，避免声称列出全部64组。"""
    doc = Document(destination)
    for p in doc.paragraphs:
        if "受体及中英文成分完整清单见专业版" in p.text:
            replace_text(
                p,
                p.text.replace(
                    "受体及中英文成分完整清单见专业版",
                    "前十组见专业版摘要，完整评分见专业版矩阵",
                ),
            )
    doc.save(destination)
