"""专业报告A05段落：先GO图及三段表，再KEGG图与两张表；预览不代替A07。"""

from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from contracts import require
from storage import verified_file
import report_flow_pathway as style
from .compact_display import metadata, go_rows, kegg_rows

GO_COLUMNS=["条目名称（英文）","中文名称","校正后P值（BH）"]
KEGG_COLUMNS=["通路名称（英文）","中文名称","Count","校正后P值（BH）"]
GO_CAPTION="图 A05 01 GO三分类富集前八。各类按校正后P值升序；柱长及同组颜色深浅表示Count。BP、CC、MF分别进行BH校正。"
KEGG_CAPTION="图 A05 02 KEGG统计显著性前十五。横轴为RichFactor，气泡面积表示Count，颜色表示−log10(BH校正后P值)；疾病名称型通路不直接代表疗效。"


# 报告使用已核查图件的原始PNG，保持与网页同一图源和指纹。
def add_graph(document,tables,root,group,caption):
    record=next(r for r in tables["display_figures"] if r["group"]==group)
    path=verified_file(root,{k:record["png_"+k] for k in ("path","bytes","sha256")})
    paragraph=document.add_paragraph()
    paragraph.alignment=WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next=True
    picture=paragraph.add_run().add_picture(str(path),width=Inches(6.35))
    picture._inline.docPr.set("descr",caption)
    p=document.add_paragraph(caption)
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    for run in p.runs:style._font(run,size=8.5,color=(73,102,117))


# 每张表使用相同报告配色、可换行名称和重复表头，禁止生成空白名额。
def add_table(document,title,rows,columns,widths):
    p=document.add_paragraph(title)
    p.paragraph_format.keep_with_next=True
    for run in p.runs:style._font(run,size=10,bold=True)
    if rows:
        style._table(document,rows,columns,widths,font_size=9.5)
        # 英文列末尾编号使用7号字，与网页小号ID保持同一层级。
        for row in document.tables[-1].rows[1:]:
            cell=row.cells[0]
            name, identifier=cell.text.rsplit(" ",1)
            cell.text=""
            p=cell.paragraphs[0]
            style._font(p.add_run(name),size=9.5)
            run=p.add_run(" "+identifier)
            style._font(run,size=7,color=(91,108,120))
    else:
        document.add_paragraph("当前范围无符合条件的显著条目，不放宽阈值补项。")


def add_section(document,tables,root,include_heading=True):
    if include_heading:document.add_heading("5 GO与KEGG富集结果",level=1)
    document.add_paragraph("富集基于当前已批准A03完整交集，采用ORA；GO三类分别BH校正，KEGG单独BH校正。只展示校正后P值小于0.05的条目；排名不能直接代表疾病关联、通路激活或疗效。")
    meta=metadata(tables)
    if not meta["exclusions_confirmed"]:
        document.add_paragraph("本段为真实数据预览，KEGG展示排除范围尚待人工确认。")
    add_graph(document,tables,root,"go",GO_CAPTION)
    for index,(group,name) in enumerate((("BP","生物过程"),("CC","细胞组分"),("MF","分子功能")),1):
        add_table(document,f"表 A05 0{index} GO {group} {name}前十五",go_rows(tables,group),GO_COLUMNS,[8.1,5.5,3.4])
    document.add_paragraph("GO各类独立按校正后P值升序排列；同值按稳定编号排列。数量不足时按实际数量展示，完整编号及原始指标保存在绑定A05归档。")
    add_graph(document,tables,root,"kegg",KEGG_CAPTION)
    add_table(document,"表 A05 04 KEGG统计显著性前十",kegg_rows(tables,"kegg_p_top10"),KEGG_COLUMNS,[7.0,4.7,1.4,3.9])
    document.add_paragraph("按校正后P值升序，体现统计证据；同值按稳定编号排列。")
    add_table(document,"表 A05 05 KEGG命中基因数前十",kegg_rows(tables,"kegg_count_top10"),KEGG_COLUMNS,[7.0,4.7,1.4,3.9])
    document.add_paragraph("按Count降序，体现命中规模；同值依次按校正后P值和稳定编号排列。两表来自同一确认后的展示范围；不足名额按实际数量展示。")
    if tables["kegg_excluded"]:
        document.add_paragraph("本次经人工确认仅从展示中排除："+ "；".join(r["ID"]+" "+r["description_zh"] for r in tables["kegg_excluded"])+"。完整统计、原始校正后P值和历史记录保留。")
    else:
        document.add_paragraph("当前展示未排除任何通路。人工排除只影响展示，不改变原统计及BH校正。")


# 独立段落预览只含A05，不伪装成上游尚未齐备的完整专业报告。
def preview(result,root,destination):
    document=Document()
    style._configure(document,"A05富集图表专业报告段落预览")
    document.add_paragraph("A05富集图表专业报告段落预览","Title")
    document.add_paragraph("用于核对GO与KEGG图表、中文名称及排列。本文件仅为A05段落预览，不代表A05或A07已验收。")
    add_section(document,result["tables"],root)
    document.save(destination)


# 对照每个单元格验证图表段落，防止Word与网页或归档表错配。
def validate_section(document,tables):
    expected=[go_rows(tables,g) for g in ("BP","CC","MF")]+[kegg_rows(tables,"kegg_p_top10"),kegg_rows(tables,"kegg_count_top10")]
    targets=[t for t in document.tables if [c.text for c in t.rows[0].cells] in (GO_COLUMNS,KEGG_COLUMNS)]
    nonempty=[rows for rows in expected if rows]
    require(len(targets)==len(nonempty),"专业报告A05表格数不一致")
    for table,rows in zip(targets,nonempty):
        columns=GO_COLUMNS if "条目名称（英文）" in rows[0] else KEGG_COLUMNS
        require([[c.text for c in row.cells] for row in table.rows[1:]]==[[str(row[k]) for k in columns] for row in rows],"专业报告A05表与归档排名不一致")
    text=[p.text for p in document.paragraphs]
    require(GO_CAPTION in text and KEGG_CAPTION in text,"专业报告缺少A05图注")
    require(text.index(GO_CAPTION)<text.index(KEGG_CAPTION),"专业报告GO与KEGG顺序不一致")
