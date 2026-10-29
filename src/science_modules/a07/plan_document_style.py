"""新报告的纯Word样式适配；沿用冻结模板的已确认字体/边距/表格，不加载科研计算依赖。"""
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm,Pt,RGBColor


def configure(document,title):
    """保留现行版式尺寸与留白，标题黑色无装饰线，元数据不带个人账户。"""
    section=document.sections[0]
    section.top_margin=section.bottom_margin=Cm(1.7);section.left_margin=section.right_margin=Cm(1.8)
    for name,size in (('Normal',10.5),('Title',22),('Heading 1',15),('Heading 2',12.5)):
        style=document.styles[name];style.font.name='Arial';style.font.size=Pt(size);style.font.color.rgb=RGBColor(0,0,0)
        style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    normal=document.styles['Normal'].paragraph_format;normal.space_after=Pt(5);normal.line_spacing=1.25
    pr=document.styles['Title']._element.get_or_add_pPr()
    for border in list(pr.findall(qn('w:pBdr'))):pr.remove(border)
    document.core_properties.title=title;document.core_properties.subject='Module A 网络药理学与分子对接报告'
    document.core_properties.author='Module A工作台'


def table(document,rows,columns,widths=None,font_size=9):
    """重复表头、完整行、可换行列宽；最终底色与边框复用既有tidy规范。"""
    result=document.add_table(rows=1,cols=len(columns));result.alignment=WD_TABLE_ALIGNMENT.CENTER;result.style='Table Grid'
    repeat=OxmlElement('w:tblHeader');repeat.set(qn('w:val'),'true');result.rows[0]._tr.get_or_add_trPr().append(repeat)
    for index,values in enumerate([dict(zip(columns,columns)),*rows]):
        row=result.rows[0] if index==0 else result.add_row();keep=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(keep)
        for offset,key in enumerate(columns):
            cell=row.cells[offset];value=values.get(key);cell.text='—' if value is None or value=='' else str(value)
            cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if widths:cell.width=Cm(widths[offset])
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after=Pt(0)
                for run in paragraph.runs:
                    run.font.name='Arial';run.font.size=Pt(font_size);run.bold=index==0
                    run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    document.add_paragraph().paragraph_format.space_after=Pt(0)
    return result
