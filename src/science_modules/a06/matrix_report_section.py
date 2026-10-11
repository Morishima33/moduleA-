"""专业报告A06新章节：同源热图及扩展表，不把候选梯队当作结构质控。"""
from docx.shared import Cm
from docx.enum.section import WD_SECTION,WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from contracts import require
from .matrix_exports import validate_matrix,label

# 逐格使用原值，展示两位小数；NA不填零，完整原因另列并绑定同一版本。
def table_rows(matrix):
    part=matrix["table"]
    return [[r.get("name_zh",r.get("name",r["compound_id"]))]+["NA" if c["score"] is None else f'{c["score"]:.2f}' for c in line] for r,line in zip(part["rows"],part["cells"])]

# 只替换专业版第六章，用横向页面容纳十五受体列；后续章节恢复原纸张设置。
def replace_section(document,matrix,png,receptor_setup=None,receptor_limitations=None,docking_note=None):
    validate_matrix(matrix)
    starts=[p for p in document.paragraphs if p.text=="6 分子对接结果"];stops=[p for p in document.paragraphs if p.text=="7 待进一步核验的研究线索"]
    require(len(starts)==len(stops)==1,"专业报告A06位置不唯一")
    node=starts[0]._p
    while node is not stops[0]._p:
        following=node.getnext();node.getparent().remove(node);node=following
    before=list(document._element.body);last=document.sections[-1]
    settings={k:getattr(last,k) for k in ("orientation","page_width","page_height","left_margin","right_margin","top_margin","bottom_margin")}
    landscape=document.add_section(WD_SECTION.NEW_PAGE);landscape.orientation=WD_ORIENT.LANDSCAPE
    landscape.page_width=max(settings["page_width"],settings["page_height"]);landscape.page_height=min(settings["page_width"],settings["page_height"]);landscape.left_margin=landscape.right_margin=Cm(1.5)
    document.add_heading("6 分子对接结果",level=1)
    if receptor_setup:
        from report_flow_pathway import _receptor_setup_table
        _receptor_setup_table(document,receptor_setup)
    document.add_heading("A06 01 重点结合能热图",level=2)
    document.add_picture(str(png),width=Cm(24))
    document.add_paragraph("图 A06 01 重点成分与受体热图。"+matrix["palette"]["label_zh"]+"。"+label(matrix)+"。")
    document.add_paragraph("图表来自同一Vina Top-1批次；色标范围取完整批次有效评分。A/B仅为候选梯队，严格／探索为独立结构质控；评分不能直接证明药效。")
    if receptor_limitations:
        from report_flow_pathway import _receptor_limitation_report_table
        _receptor_limitation_report_table(document,receptor_limitations)
    document.add_heading("A06 02 扩展结合能表（kcal/mol）",level=2)
    columns=["成分"]+[r.get("symbol",r["target_id"])+"（"+r.get("candidate_grade","")+"）" for r in matrix["table"]["columns"]]
    table=document.add_table(rows=1,cols=len(columns));table.style="Table Grid";table.autofit=False
    usable=(landscape.page_width-landscape.left_margin-landscape.right_margin)/914400*2.54
    widths=[4]+[(usable-4)/(len(columns)-1)]*(len(columns)-1)
    for i,(cell,value) in enumerate(zip(table.rows[0].cells,columns)):cell.text=value;cell.width=Cm(widths[i])
    repeat=OxmlElement("w:tblHeader");table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values in table_rows(matrix):
        row=table.add_row();keep=OxmlElement("w:cantSplit");row._tr.get_or_add_trPr().append(keep)
        for i,(cell,value) in enumerate(zip(row.cells,values)):cell.text=value;cell.width=Cm(widths[i])
    from docx.shared import Pt
    for i,row in enumerate(table.rows):
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:run.font.name="Microsoft YaHei";run.font.size=Pt(8);run.bold=i==0
    document.add_paragraph("本表取扩展展示窗口，完整"+str(matrix["full_pair_count"])+"个组合留存。NA为无法计算，原因如下；不以零填补，也不为展示重新计算。")
    document.add_paragraph("受体结构质控："+"；".join(r.get("symbol",r["target_id"])+"（"+r.get("candidate_grade","")+"；"+r.get("quality_zh","NA")+"）" for r in matrix["table"]["columns"]))
    failures=[r.get("name_zh",r["compound_id"])+" × "+c.get("symbol",c["target_id"])+"："+cell["reason_zh"] for r,line in zip(matrix["table"]["rows"],matrix["table"]["cells"]) for c,cell in zip(matrix["table"]["columns"],line) if cell["score"] is None]
    if failures:
        for reason in failures:document.add_paragraph(reason)
    document.add_paragraph("结果版本："+matrix["result_version"])
    if docking_note:document.add_paragraph(docking_note)
    restored=document.add_section(WD_SECTION.NEW_PAGE)
    for key,value in settings.items():setattr(restored,key,value)
    for element in list(document._element.body):
        if element not in before and element.tag!=qn("w:sectPr"):stops[0]._p.addprevious(element)
    validate_section(document,matrix)

# 报告的扩展表必须与归档矩阵逐格一致，避免只核对图件颜色。
def validate_section(document,matrix):
    columns=["成分"]+[r.get("symbol",r["target_id"])+"（"+r.get("candidate_grade","")+"）" for r in matrix["table"]["columns"]]
    matches=[t for t in document.tables if [c.text for c in t.rows[0].cells]==columns]
    require(len(matches)==1 and [[c.text for c in row.cells] for row in matches[0].rows[1:]]==table_rows(matrix),"专业报告结合能表与同批归档不一致")
    require(any(p.text=="结果版本："+matrix["result_version"] for p in document.paragraphs),"专业报告缺少同批结果版本")
