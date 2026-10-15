"""第24版局部修订：正文简洁、图先表后，术语解释统一置于末尾附录。"""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

from contracts import require
from .commented_documents import replace_text, tidy

APPENDIX_TITLE = "附录 术语与方法说明"
APPENDIX = (
    (
        "化学结构身份标识",
        "InChIKey是根据化学结构标准表示生成的27字符身份编码，用于跨数据库核对成分身份。本项目只有完整InChIKey一致且分子式无冲突时才合并记录；该编码不表示活性或含量。HGNC用于统一人类基因身份。",
    ),
    (
        "A与B对接候选分组",
        "A组为Degree第二轮前十与BC/CC第二轮前十五的交集；B组为Degree第二轮前十五中除去A组的其余靶点。各排名窗口均保留边界并列。A/B用于对接受体候选分组，不代表临床证据等级或结构质控通过。PPI主要结论中的完整名单交集另取两分支第二轮全部结果，不能与A组混为一谈。",
    ),
    (
        "人类物种编号与功能关联",
        "9606是人类的物种编号，本研究只使用人类蛋白质网络。STRING功能关联既包含直接相互作用，也包含间接功能联系；网络连边不等于每一对蛋白均已证实直接结合。",
    ),
    (
        "分子对接运行参数",
        "AutoDock Vina 1.2.7采用exhaustiveness=8、num_modes=9、energy_range=3、seed=1。exhaustiveness控制搜索强度，设为8；num_modes表示最多输出9种结合姿势，实际可能少于9种；energy_range表示输出姿势与最优姿势的评分差不超过3 kcal/mol；seed是随机种子，固定为1便于相同输入、软件与运行条件下复现。",
    ),
    (
        "多区域评分取值",
        "Top-1是某一搜索区域中排名第一、评分最低的姿势。同一成分与受体若搜索多个区域，先分别取各区域Top-1，再取这些评分中的最低值作为本报告展示值。例如各区域为−7、−8、−6 kcal/mol，展示−8 kcal/mol，不取平均值；其他区域和输出姿势仍完整归档。",
    ),
    (
        "混合网络连接数",
        "表中的混合网络连接数（参考），原字段为混合Degree，等于一个成分关联的不同交集靶点数加来源药味数。例如20个交集靶点、来自2味药，连接数为22。该项是药味—成分—靶点混合网络的参考指标，与PPI中蛋白节点的Degree不同；本报告成分主排名仍按不同交集靶点数排列。",
    ),
    (
        "热图与评分标记",
        "热图颜色范围取完整同批225格中的有效评分，越负越红、越不负越蓝；缺失值保留NA及原因。A/B表示上述候选分组。矩阵中的双星号仅标记原始Vina评分≤−8 kcal/mol，不表示统计显著性。Vina评分不能直接证明药效，也不是实测结合自由能。",
    ),
)


def move_graph_before(document, caption_prefix, table_prefix):
    """只移动图片与图注两段，不移动表格、节断或其他章节。"""
    caption = next((p for p in document.paragraphs if p.text.startswith(caption_prefix)), None)
    table = next((p for p in document.paragraphs if p.text.startswith(table_prefix)), None)
    require(caption is not None and table is not None, "待调整的富集图注或表题缺失")
    image = caption._p.getprevious()
    require(
        image is not None and image.find(".//" + qn("w:drawing")) is not None, "富集图与图注未相邻"
    )
    require(image.find(".//" + qn("w:sectPr")) is None, "富集图段包含节断，不能直接移动")
    table._p.addprevious(image)
    table._p.addprevious(caption._p)


def revise_body(document, detailed):
    """精简本轮批注涉及的说明；实际方法、数据状态与科研范围不变。"""
    for paragraph in document.paragraphs:
        text = paragraph.text
        if text.startswith("成分与靶点概览："):
            text = text.split("；PPI第二轮Degree前十靶点为", 1)[0].rstrip("；。") + "。"
        if text.startswith("成分与方剂靶点："):
            text = text.replace("完整InChIKey是化学结构的标准身份标识，", "")
            text = text.replace("完整InChIKey是化学结构的标准身份标识，不能当作活性评分。", "")
            text = text.replace("跨库合并要求完整标识一致", "跨库合并要求完整InChIKey一致")
            text = text.replace("不能当作活性评分。", "")
        if text.startswith("疾病靶点："):
            text = text.replace("，待核验", "").replace("待核验", "")
        if text.startswith("PPI："):
            text = text.replace("人类9606的功能关联网络", "人类蛋白质功能关联网络")
        if text.startswith("分子对接："):
            text = text.replace(
                "以exhaustiveness=8、最多9个姿势、energy_range=3、seed=1运行", "按既定参数运行"
            )
            text = text.replace("多区域取各区域Top-1中最低评分", "多区域评分按既定规则汇总")
        text = text.replace(
            "预测口袋与分区盲搜取各区域Top-1最低值", "预测口袋与分区盲搜按既定多区域规则汇总评分"
        )
        # 排名段只保留主排序，参考指标的公式移至附录。
        text = text.replace("混合Degree为交集靶点数加来源药味数，仅供参考。", "")
        if text.startswith("图 A06 01"):
            text = "图 A06 01 重点8×8原始Vina评分热图，单位kcal/mol。"
        elif text.startswith("图：") and "结合能热图" in text:
            text = "图 重点8×8原始Vina评分热图，单位kcal/mol。"
        if text.startswith(("GO分为", "KEGG两种排名来自")):
            paragraph.paragraph_format.keep_with_next = True
        if text != paragraph.text:
            replace_text(paragraph, text)
    for table in document.tables:
        for cell in table.rows[0].cells:
            if cell.text == "混合Degree":
                replace_text(cell.paragraphs[0], "混合网络连接数（参考）")
    if detailed:
        move_graph_before(document, "图 A05 01", "表 A05 01")
        move_graph_before(document, "图 A05 02", "表 A05 04")


def add_appendix(document, payload):
    """末尾新页统一解释六处术语和热图脚注，正文不插入长篇释义。"""
    heading = document.add_heading(APPENDIX_TITLE, 1)
    heading.paragraph_format.page_break_before = True
    for title, text in APPENDIX:
        document.add_heading(title, 2)
        p = document.add_paragraph(text)
        p.paragraph_format.space_after = Pt(5)
    from science_modules.a06.matrix_exports import na_lines
    from science_modules.a06.bilingual_heatmap import matrix

    reasons = na_lines(matrix(payload["trial_packet"], payload["compound_names"]))
    for reason in reasons:
        document.add_paragraph(reason)


def revise_file(destination, payload, detailed):
    """只改本次新文档；正文、图注和附录使用既有报告样式。"""
    document = Document(destination)
    revise_body(document, detailed)
    add_appendix(document, payload)
    for paragraph in document.paragraphs:
        if paragraph._p.find(".//" + qn("w:drawing")) is not None:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tidy(document)
    document.save(destination)


def validate_document(document, detailed):
    """防止术语回流正文、图表次序回退或待核验残留。"""
    text = [p.text for p in document.paragraphs]
    require(text.count(APPENDIX_TITLE) == 1, "报告末尾术语附录缺失或重复")
    appendix = text.index(APPENDIX_TITLE)
    body = "\n".join(text[:appendix])
    for title, explanation in APPENDIX:
        require(
            title in text[appendix:] and explanation in text[appendix:],
            "术语附录内容缺失：" + title,
        )
    require("待核验" not in body, "报告仍含待核验字样")
    require("PPI第二轮Degree前十靶点为" not in body, "首页重复PPI名单未删除")
    require("exhaustiveness=" not in body and "混合Degree为" not in body, "参数或指标释义仍在正文")
    if detailed:
        require(text.index("9 主要方法参考文献") < appendix, "附录未位于参考文献后")
        require(
            text.index(next(p for p in text if p.startswith("图 A05 01")))
            < text.index("表 A05 01 GO BP 生物过程前十五"),
            "GO图未在三个表之前",
        )
        require(
            text.index(next(p for p in text if p.startswith("图 A05 02")))
            < text.index("表 A05 04 KEGG统计显著性前十"),
            "KEGG图未在两个表之前",
        )
