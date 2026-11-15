"""报告三版文档：复用已确认第24版排版，只输出完整核译与可追溯实际名称。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
from docx import Document
from docx.shared import Pt
from contracts import require
from storage import verified_file
from . import plan_documents as original
from .plan_translations_v2 import check_readability, PLACEHOLDER
from .plan_facts_v2 import VERSION, BOUNDARY

VERSION_DOCUMENTS = 'A07.plan_documents.3'
STATUS_ZH = original.STATUS_ZH
APPENDIX_TITLE = original.APPENDIX_TITLE
_configure = original._configure
table = original.table
figure = original.figure
add_enrichment = original.add_enrichment
review_description = original.review_description
validate_receipts = original.validate_receipts
tidy = original.tidy


def check(payload, *, draft=False):
    """先核对二版身份与全部可读文字，再复用原完整度、同源及回执检查。"""
    require(payload.get('schema_version') == 'A07.plan_payload.3', '报告事实包版本不是三版')
    check_readability(payload)
    legacy = deepcopy(payload)
    legacy['schema_version'] = 'A07.plan_payload.1'
    legacy['completion']['schema_version'] = 'A07.plan_facts.1'
    return original.check(legacy, draft=draft)


def failure_rows(payload):
    """未成功区域沿同批实际名称显示，保留稳定编号，避免把内部字段当表头。"""
    facts = payload.get('docking') or {}
    compounds = {r['compound_id']: (r.get('name_zh') or r.get('name') or r['compound_id'])+'（'+r['compound_id']+'）'
                 for r in facts.get('compounds', [])}
    receptors = {r['target_id']: (r.get('symbol') or r['target_id'])+'（'+r['target_id']+'）'
                 for r in facts.get('receptors', [])}
    return [{'成分': compounds[r['compound_id']], '受体': receptors[r['target_id']], '区域': r['region_id'],
             '实际状态': {'failed': '评分失败', 'NA': '无有效评分'}.get(r['state'], r['state']), '原因': r['reason_zh']}
            for r in facts.get('rescue', {}).get('failed_regions', [])]


def add_docking(document, payload, home, concise):
    """评分矩阵沿用原布局和原精度，摘要受体名称补全到标准符号与稳定编号。"""
    original.add_docking(document, payload, home, concise)
    rescue = (payload.get('docking') or {}).get('rescue')
    if rescue:
        document.add_paragraph(rescue['notice_zh'])
        table(document, '补救未成功区域（按实际记录）', failure_rows(payload),
              ['成分', '受体', '区域', '实际状态', '原因'])
    if concise and payload.get('docking'):
        names = {r['target_id']: (r.get('symbol') or r['target_id'])+' '+r['target_id'] for r in payload['docking']['receptors']}
        for value in document.tables:
            if [cell.text for cell in value.rows[0].cells] == ['成分','受体','原始Vina评分','范围']:
                for row in value.rows[1:]:
                    row.cells[1].text = names.get(row.cells[1].text, row.cells[1].text)


def add_appendix(document, payload, plan, home):
    """保留术语和真实参数；异常表使用实际名称，整网概览单列附录。"""
    original.add_appendix(document, payload, plan)
    for paragraph in document.paragraphs:
        if paragraph.text.startswith('展示条目缺译编号：'):
            paragraph.text = '本报告正文、图表及附录所展示条目的中文核译已经逐编号检查。'
    facts = payload.get('docking')
    if facts:
        compounds = {r['compound_id']: (r.get('name_zh') or r.get('name') or r['compound_id'])+'（'+r['compound_id']+'）' for r in facts['compounds']}
        receptors = {r['target_id']: (r.get('symbol') or r['target_id'])+'（'+r['target_id']+'）' for r in facts['receptors']}
        for value in document.tables:
            if [cell.text for cell in value.rows[0].cells] == ['成分','受体','实际状态','原因']:
                for row in value.rows[1:]:
                    row.cells[0].text = compounds.get(row.cells[0].text, row.cells[0].text)
                    row.cells[1].text = receptors.get(row.cells[1].text, row.cells[1].text)
    for entry in payload.get('figures', []):
        if entry.get('role') == 'full_network_overview':
            document.add_heading('本批PPI全网络概览（附图）', 2)
            figure(document, home, entry)


def build(payload,destination,home,*,concise=False,draft=False):
    """生成一份Word；此函数不发布A07、不写研究或人工复核，不运行R/Vina。"""
    plan=check(payload,draft=draft)
    if not draft:
        from .plan_payload_v3 import validate
        validate(payload,home,require_figures=True);validate_receipts(payload,home)
    document=Document();title='ModuleA 方剂与疾病分析报告'+(' 简略版' if concise else '')
    _configure(document,title);document.add_paragraph(title,style='Title')
    document.add_paragraph(payload['intake']['formula']+' 与 '+payload['intake']['disease'])
    if payload['intake'].get('analysis_purpose')=='workflow_test':
        document.add_paragraph('用途：流程测试；仅用于技术验证，不作为正式研究结论。')
    if draft:document.add_paragraph('隔离模板核查稿 未完成生产归档及系统校验 不作为正式研究报告')
    state=payload['completion'];document.add_paragraph('本报告状态 '+STATUS_ZH[state['state']]+'。'+BOUNDARY)
    document.add_heading('1 主要结论',1)
    document.add_paragraph(payload['conclusion'])
    document.add_heading('2 关键数量与完成情况',1)
    table(document,'实际分支完成情况',[{'分支':row['branch'],'实际状态':STATUS_ZH[row['state']],'依据':row['reason_zh']} for row in state['branches']],['分支','实际状态','依据'],[3,4,9.8])
    document.add_heading('3 数据来源与方法',1)
    for row in payload['sources']:document.add_paragraph(row['label']+'：'+row['description'])
    methods=['本报告只汇总本批所绑定的原结果。']
    if payload.get('enrichment'):methods.append('本批富集各检验族独立BH校正。')
    if payload.get('docking'):methods.append('对接范围、原始评分及NA/失败原因按实际保留。')
    methods.append('不适用分支未执行；创建方案参数和术语详见附录。');document.add_paragraph(''.join(methods))
    network_heading=document.add_heading('4 交集 成分与PPI网络',1)
    # 非空报告来源较长时允许在方法段后接续，避免单独留一页方法说明。
    historical_sources=any(row['label']=='历史数据库版本限制' for row in payload['sources'])
    network_heading.paragraph_format.page_break_before=not payload.get('counts',{}).get('intersection') and not historical_sources
    for row in payload['network_summary']:
        if row!=BOUNDARY:document.add_paragraph(row)  # 总体限制已在开头与附录完整说明。
    for entry in payload.get('figures',[]):
        if entry.get('module') in ('A03','A04') and entry.get('role') != 'full_network_overview':figure(document,home,entry)
    document.add_heading('5 GO与KEGG富集结果',1);add_enrichment(document,payload,home,concise)
    document.add_heading('6 分子对接结果',1);add_docking(document,payload,home,concise)
    document.add_heading('7 待进一步核验的研究线索',1)
    for text in payload['research_leads']:document.add_paragraph(text)
    if not payload['research_leads']:document.add_paragraph('本批没有可据以提出具体研究线索的完成结果，不补写机制或疗效推断。')
    document.add_heading('8 结果复核说明',1)
    records=payload.get('validation_records',[])
    document.add_paragraph(review_description(payload))
    document.add_heading('9 主要方法参考文献',1)
    for index,text in enumerate(payload['references']):
        paragraph=document.add_paragraph(text)
        paragraph.paragraph_format.keep_with_next=index<len(payload['references'])-1
    add_appendix(document,payload,plan,home);tidy(document)
    for paragraph in document.paragraphs:
        # 短说明保持完整，避免仅两三个字跨页；标题仍与后文相连。
        paragraph.paragraph_format.keep_together=True
        if paragraph.style.name=='Title':
            paragraph.paragraph_format.space_after=Pt(10)
        elif paragraph.style.name in ('Heading 1','Heading 2'):
            paragraph.paragraph_format.space_before=Pt(10)
            paragraph.paragraph_format.space_after=Pt(5)
    # 仅新报告的紧凑表格留白，避免末尾一句被参数表挤成孤页。
    for value in document.tables:
        for row in value.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_before=Pt(1)
                    paragraph.paragraph_format.space_after=Pt(1)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True);document.save(destination)
    return destination


# 原验证器完整核对章节、原始矩阵和参数；只将版本检查交给本二版check。
_validate = FunctionType(original.validate_document.__code__, dict(vars(original), check=check),
                         original.validate_document.__name__, original.validate_document.__defaults__)
_validate.__kwdefaults__ = dict(original.validate_document.__kwdefaults__ or {})


def validate_document(path, payload, *, concise=False, draft=False):
    """独立回读实际Word，拒绝缺译占位、漏评分及不完整矩阵。"""
    result = _validate(path, payload, concise=concise, draft=draft)
    document = Document(path)
    visible = [p.text for p in document.paragraphs]
    visible += [cell.text for value in document.tables for row in value.rows for cell in row.cells]
    require(not any(PLACEHOLDER.search(text) for text in visible), '实际Word仍有缺译占位文字')
    rescue = (payload.get('docking') or {}).get('rescue')
    if rescue:
        require(rescue['notice_zh'] in visible, '实际Word缺少本批补救代次和区域限制')
        expected = failure_rows(payload)
        headers = ['成分', '受体', '区域', '实际状态', '原因']
        actual = [value for value in document.tables if [cell.text for cell in value.rows[0].cells] == headers]
        require(len(actual) == bool(expected), '实际Word缺少或重复补救区域表')
        if expected:
            require([[cell.text for cell in row.cells] for row in actual[0].rows[1:]]
                    == [[str(row[key]) for key in headers] for row in expected], '实际Word补救区域与对象或原原因不一致')
    return dict(result, documents_version=VERSION_DOCUMENTS, readability_checked=True)
