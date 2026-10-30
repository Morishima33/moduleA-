"""新方案主报告与扩展简略版：复用冻结第24版样式，实际数量/缺译/NA和校验身份如实呈现。"""
from pathlib import Path
from docx import Document
from docx.shared import Cm,Pt
from contracts import require,fingerprint
from storage import verified_file,read_json
from science_modules.analysis_protocol import checked_plan,FIELDS
from science_modules.a06.trial_presentation import score_label,LEGEND
from .plan_facts import VERSION,BOUNDARY
from .appendix_documents import APPENDIX,APPENDIX_TITLE
from .commented_documents import tidy
from .plan_document_style import configure as _configure,table as _table

VERSION_DOCUMENTS='A07.plan_documents.1'
STATUS_ZH={'completed':'适用分支已完成','partial':'部分结果','valid_empty':'有效空结果','not_applicable':'不适用',
           'waiting':'仍有适用分支未完成','technical_blocked':'存在关键技术阻塞'}


def review_description(payload):
    """正文简短汇总实际技术核查；完整逐模块回执保存在同批追溯，不能代替人工签名。"""
    labels={'A00':'研究登记','A01':'三库标准化','A02':'疾病标准化','A03':'交集',
            'A03_SELECT':'成分选择','A04':'PPI网络','A05':'富集统计','A06_PREP':'结构准备','A06':'对接评分'}
    records=payload.get('validation_records',[])
    if not records:return '当前为事实投影与模板核查，尚无可用于生产交付的系统校验回执；未生成任何人工审核签名。'
    passed=[labels.get(key,key) for key in labels if any(row['module']==key and row['passed'] is True for row in records)]
    failed=[labels.get(row['module'],row['module']) for row in records if row['passed'] is not True]
    pieces=[]
    if passed:pieces.append('、'.join(passed)+'已通过系统技术校验。')
    if failed:pieces.append('、'.join(failed)+'系统技术校验未通过。')
    return ''.join(pieces)+'完整回执见同批追溯包；系统校验不表示人工签署。'


def check(payload,*,draft=False):
    """报告只消费同研究事实；模板核查与可正式交付资料明确区分，不代替科学验证。"""
    require(isinstance(payload,dict) and payload.get('schema_version')=='A07.plan_payload.1','报告事实包版本无效')
    sid=payload.get('study_id');require(isinstance(sid,str) and sid,'报告缺少研究身份')
    require(isinstance(payload.get('intake'),dict) and all(payload['intake'].get(key) for key in ('formula','disease')),'报告缺少实际方剂或疾病')
    plan=checked_plan(payload['plan']);state=payload['completion']
    require(state.get('schema_version')==VERSION and state.get('state') in STATUS_ZH,'报告缺少实际分支完成状态')
    for key in ('enrichment','docking'):
        value=payload.get(key)
        if value:
            require(value.get('study_id')==sid,'报告不能混入其他研究的统计或评分')
            if key=='enrichment':require(value['parameter_hash']==plan['parameter_hash'],'报告富集参数不属于本方案')
    if not draft:
        require(state['all_applicable_finished'],'报告必须等待所有适用分支结束')
        records=payload.get('validation_records',[])
        require(records and all(row.get('study_id')==sid and row.get('authority_kind')=='system_validation'
                               and row.get('passed') is True and row.get('source') for row in records),
                '缺少本研究真实系统校验回执，不能生成正式报告；人工签名不由报告生成器制造')
    return plan


def validate_receipts(payload,home):
    """正式生成必须核对本研究登记的真实系统校验文件，不能信任客户端passed标记。"""
    path=Path(home)/'manifest.json';require(path.is_file(),'正式报告缺少本研究实际归档索引')
    manifest=read_json(path);sid=payload['study_id'];require(manifest.get('study_id')==sid,'报告系统校验研究归属不一致')
    from workflow import Workflow
    from modulea.core.plan_report_contract import validate_receipts as validate
    workflow=Workflow(Path(home).resolve().parents[1])
    require(workflow.location(sid).resolve()==Path(home).resolve(),'报告研究归档位置不一致')
    validate(workflow,manifest,payload)


def table(document,title,rows,columns,widths=None):
    """统一沿用既有报告表格组件，保留空集合的明确原因，不用虚构数据填满表。"""
    caption=document.add_paragraph(title);caption.paragraph_format.keep_with_next=True
    if rows:_table(document,rows,columns,widths,font_size=9)
    else:document.add_paragraph('本范围没有可列示的记录，具体原因见对应分支说明。')


def figure(document,home,entry):
    """只插入已登记且指纹核验的同研究图件，不从其他批次借图。"""
    path=verified_file(home,entry['record']);paragraph=document.add_paragraph()
    from docx.image.image import Image
    size=Image.from_file(str(path));width=min(14.0 if entry.get('module')=='A03' else 15.8,20.0*size.px_width/size.px_height)
    if entry.get('module')=='A06':width=min(width,size.px_width*2.54/180)
    if width<15.8:paragraph.alignment=1
    paragraph.add_run().add_picture(str(path),width=Cm(width))
    document.add_paragraph(entry['caption'])


def add_enrichment(document,payload,home,concise):
    """图先表后；缺译留英文，未纳入/无显著/范围暂缓分别解释。"""
    facts=payload.get('enrichment')
    if not facts:
        document.add_paragraph(payload['branch_reasons'].get('enrichment','富集分支尚未提供可绑定事实，不能补写统计。'));return
    p=payload['plan']['parameters']
    for row in facts['groups']:
        group=row['group']
        if not row['included']:
            document.add_paragraph(f'{group} 本方案未纳入，本类别不适用，不表示零显著。');continue
        document.add_heading(group+' 富集结果',2)
        document.add_paragraph(f"本批完整显著{row['significant_count']}项，展示范围{row['retained_count']}项，图{row['plot_count']}项、表{row['table_count']}项；BH p.adjust < {p['a05.adjusted_p_max']:g}。")
        if not row['retained_count'] and row['significant_count']:
            document.add_paragraph('原始显著条目仍存在；因分类范围处理暂不列入主图，原件、原统计及待判断附录保留。')
        for entry in payload.get('figures',[]):
            if entry.get('module')=='A05' and entry.get('group')==group:
                require(entry.get('scope_hash')==fingerprint(facts),'富集图不属于本批实际展示范围');figure(document,home,entry)
                if concise:
                    # 图后说明与紧随的名称摘要一起显示，避免摘要单独落到下一页。
                    document.paragraphs[-2].paragraph_format.keep_with_next=True
                    document.paragraphs[-1].paragraph_format.space_after=Pt(0)
                    document.paragraphs[-1].paragraph_format.keep_with_next=True
        key=group.lower();values=facts['tables'][key+'_plan_top']
        def rows(items):
            """原统计值完整写入表格，不因显示格式改变阈值判断或排序。"""
            return [{'英文条目与编号':item['english']+' '+item['ID'],'中文名称':item['chinese'] or '中文待核译',
                     'Count':item['Count'],'BH校正后P值':format(float(item['p.adjust']),'.3e')} for item in items]
        if concise:
            document.add_paragraph('；'.join(item['label'] for item in values[:3]) or '本类别没有进入主展示范围的条目。')
        else:
            table(document,group+' 按统计显著性排名',rows(values),['英文条目与编号','中文名称','Count','BH校正后P值'],[7,5,1.4,3.4])
            if group=='KEGG':table(document,'KEGG 按命中基因数排名',rows(facts['tables']['kegg_plan_count_top']),['英文条目与编号','中文名称','Count','BH校正后P值'],[7,5,1.4,3.4])


def add_docking(document,payload,home,concise):
    """完整矩阵分列容纳实际规模；评分保持原精度供判断，NA与失败原因另列。"""
    facts=payload.get('docking')
    if not facts:
        document.add_paragraph(payload['branch_reasons'].get('docking','对接分支尚未结束，不能补写评分。'));return
    counts=facts['counts'];document.add_paragraph(f"固定{counts['compounds']}成分 × {counts['receptors']}受体，共{counts['pairs']}组；实际评分{counts['scored']}组，失败{counts['failed']}组，准备NA {counts['NA']}组。严格评分{counts['strict_scored']}组，探索评分{counts['exploratory_scored']}组。")
    document.add_paragraph(facts['reason_zh']);document.add_paragraph(LEGEND)
    for entry in payload.get('figures',[]):
        if entry.get('module')=='A06':
            require(entry.get('scope_hash')==fingerprint(facts),'热图不属于本批原评分范围');figure(document,home,entry)
    receptors=facts['receptors'];compound_names={row['compound_id']:row.get('name_zh') or row.get('name') or row['compound_id'] for row in facts['compounds']}
    if concise:
        scored=sorted((row for row in facts['pairs'] if row['state']=='completed'),key=lambda row:(row['score'],row['compound_id'],row['target_id']))[:10]
        table(document,'原始评分排序前列',[
            {'成分':compound_names[row['compound_id']],'受体':row['target_id'],'原始Vina评分':row['score'],'范围':row['quality']} for row in scored],
            ['成分','受体','原始Vina评分','范围'],[6,4,3.8,3])
        return
    for offset in range(0,len(receptors),6):
        part=receptors[offset:offset+6];ids=[row['target_id'] for row in part]
        labels={row['target_id']:(row.get('symbol') or row['target_id'])+' '+row['target_id'] for row in part}
        rows=[]
        for item in facts['matrix']:
            cells={row['target_id']:row for row in item['cells']};rows.append({'成分':compound_names[item['compound_id']],**{labels[tid]:score_label(cells[tid]['score'],mark=True) for tid in ids}})
        table(document,f'完整同批评分矩阵 第{offset+1}至{offset+len(part)}列',rows,['成分']+[labels[tid] for tid in ids],[5]+[11.8/len(part)]*len(part))


def add_appendix(document,payload,plan):
    """沿用已确认术语附录的通用解释；固定旧数量和旧参数改读本批真实方案。"""
    heading=document.add_heading(APPENDIX_TITLE,1);heading.paragraph_format.page_break_before=True
    document.add_paragraph('以下术语为方法解释；本批是否实际执行，以前述分支完成情况为准。保存的方案参数不表示不适用分支已经运行。')
    for title,text in APPENDIX:
        if title in ('A与B对接候选分组','分子对接运行参数','热图与评分标记'):continue
        document.add_heading(title,2);document.add_paragraph(text)
    document.add_heading('本批方案与实际参数',2)
    table(document,'创建时保存的参数与规则',[
        {'参数':FIELDS[key]['label'] if key in FIELDS else key,'实际值':str(value)} for key,value in plan['parameters'].items()],['参数','实际值'],[8.5,8.3])
    document.add_paragraph('受体名单取本批实际选择记录；A/B不表示证据等级，失败对象保留NA且不以低排名受体补位。')
    document.add_paragraph('热图取完整同批有效评分范围的色标，缺失保留NA；'+LEGEND)
    enrich=payload.get('enrichment')
    if enrich:
        for key,title in (('kegg_excluded','依据官方分类未进入主图的其他疾病条目'),('kegg_deferred','分类或本病身份待判断条目')):
            table(document,title,[{'编号':row['ID'],'原英文':row['english'],'处理依据':row.get('defer_reason_zh') or row['reason_zh']} for row in enrich['tables'][key]],['编号','原英文','处理依据'],[2.5,6,8.3])
        document.add_paragraph('展示条目缺译编号：'+('、'.join(enrich['pending_translations']) or '无')+'；原英文保留，待核译不伪造中文。')
    scores=payload.get('docking')
    if scores:
        table(document,'本批未评分或执行失败组合',[
            {'成分':row['compound_id'],'受体':row['target_id'],'实际状态':row['state'],'原因':row.get('reason_zh') or '尚未开始评分'} for row in scores['pairs'] if row['state']!='completed'],
            ['成分','受体','实际状态','原因'],[3,3,2.8,8])
    document.add_paragraph(BOUNDARY)


def build(payload,destination,home,*,concise=False,draft=False):
    """生成一份Word；此函数不发布A07、不写研究或人工复核，不运行R/Vina。"""
    plan=check(payload,draft=draft)
    if not draft:
        from .plan_payload import validate
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
    network_heading.paragraph_format.page_break_before=not payload.get('counts',{}).get('intersection')
    for row in payload['network_summary']:
        if row!=BOUNDARY:document.add_paragraph(row)  # 总体限制已在开头与附录完整说明。
    for entry in payload.get('figures',[]):
        if entry.get('module') in ('A03','A04'):figure(document,home,entry)
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
    add_appendix(document,payload,plan);tidy(document)
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


def validate_document(path,payload,*,concise=False,draft=False):
    """独立回读Word的章节、参数与每个矩阵单元格；缺列/补零/错参数均拒绝。"""
    plan=check(payload,draft=draft);document=Document(path)
    headings=[paragraph.text for paragraph in document.paragraphs if paragraph.style.name=='Heading 1']
    required=['1 主要结论','2 关键数量与完成情况','3 数据来源与方法','4 交集 成分与PPI网络',
              '5 GO与KEGG富集结果','6 分子对接结果','7 待进一步核验的研究线索','8 结果复核说明','9 主要方法参考文献',APPENDIX_TITLE]
    require(headings==required,'报告章节缺失、重复或顺序改变')
    text='\n'.join(paragraph.text for paragraph in document.paragraphs)
    paragraphs=[paragraph.text for paragraph in document.paragraphs]
    require(payload['conclusion'] in paragraphs,'报告共同结论与同批实际事实不一致')
    require(all(row['label']+'：'+row['description'] in paragraphs for row in payload['sources']),'报告实际来源或筛选范围缺失')
    require(all(row in paragraphs for row in payload['network_summary']+payload['research_leads']+payload['references']),
            '报告网络说明、研究线索或实际方法参考缺失')
    old_review=[f"{row['module']} 系统技术校验：{'通过' if row['passed'] else '未通过'}，完整回执见同批追溯索引。不表示人工签署。" for row in payload.get('validation_records',[])]
    require(review_description(payload) in paragraphs or (old_review and all(row in paragraphs for row in old_review)),
            '报告技术核查说明与实际回执不一致')
    require(('隔离模板核查稿' in text)==draft,'模板核查身份与实际交付状态不一致')
    if payload['intake'].get('analysis_purpose')=='workflow_test':
        require('用途：流程测试；仅用于技术验证，不作为正式研究结论。' in text,'报告漏标真实流程测试用途')
    require('本报告状态 '+STATUS_ZH[payload['completion']['state']] in text,'报告误写实际完成状态')
    def rows_after(caption):
        """按唯一标题定位原Word表格，不依赖截图或未知列号猜测。"""
        matches=[paragraph for paragraph in document.paragraphs if paragraph.text==caption]
        require(len(matches)==1,'报告表题缺失或重复：'+caption)
        node=matches[0]._p.getnext();require(node is not None and node.tag.endswith('}tbl'),'报告表格位置改变：'+caption)
        table=next(table for table in document.tables if table._tbl is node)
        return [[cell.text for cell in row.cells] for row in table.rows]
    expected=[['参数','实际值']]+[[FIELDS[key]['label'] if key in FIELDS else key,str(value)] for key,value in plan['parameters'].items()]
    require(rows_after('创建时保存的参数与规则')==expected,'报告参数与实际绑定方案不一致')
    branches=[['分支','实际状态','依据']]+[[row['branch'],STATUS_ZH[row['state']],row['reason_zh']] for row in payload['completion']['branches']]
    require(rows_after('实际分支完成情况')==branches,'报告实际分支完成情况被改变')
    scores=payload.get('docking');checked=0
    if scores and not concise:
        labels={row['compound_id']:row.get('name_zh') or row.get('name') or row['compound_id'] for row in scores['compounds']}
        for offset in range(0,len(scores['receptors']),6):
            receptors=scores['receptors'][offset:offset+6]
            expected=[['成分']+[(row.get('symbol') or row['target_id'])+' '+row['target_id'] for row in receptors]]
            for compound in scores['matrix']:
                cells={row['target_id']:row for row in compound['cells']}
                expected.append([labels[compound['compound_id']]]+[score_label(cells[row['target_id']]['score'],mark=True) for row in receptors])
                checked+=len(receptors)
            require(rows_after(f'完整同批评分矩阵 第{offset+1}至{offset+len(receptors)}列')==expected,'报告完整矩阵列、原评分或NA不一致')
        require(checked==scores['counts']['pairs'],'报告完整矩阵漏项')
    return {'passed':True,'sections':len(headings),'matrix_cells_verified':checked,'draft_only':draft}
