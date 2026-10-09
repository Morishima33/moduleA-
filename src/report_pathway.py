from pathlib import Path # 明确研究与报告文件位置。
import shutil # 将批准图冻结到新的报告修订。
from docx.enum.section import WD_SECTION, WD_ORIENT # 独立横向展示复杂通路。
from docx.enum.text import WD_ALIGN_PARAGRAPH # 控制图和图注对齐。
from docx.shared import Cm, Pt # 明确页面及图片物理尺寸。
from contracts import require # 科学版本不匹配必须停止。
from storage import read_json, verified_file, file_record # 沿用统一文件指纹核验。

def report_pathway_record(workflow, manifest): # 只使用当前A05下已由用户确认的通路。
    home=workflow.location(manifest['study_id']) # 确定当前研究目录。
    pointer=home/'governance'/'A05_pathway_index.json' # 通路选择使用显式指针，不扫描文件猜测。
    if not pointer.is_file(): return None # 未选择通路的研究保持原报告行为。
    index=read_json(pointer) # 读取本研究的选择记录。
    if index.get('source_a05_run')!=manifest['current'].get('A05'): return None # 上游改变后旧选择不得沿用。
    require(index.get('review_status')=='approved','通路图及解释尚未由用户确认') # 助手核验不能代替科学确认。
    record=index['metadata'] # 取得不可变的选择事实包。
    data=read_json(verified_file(home,record)) # 事实包自身须匹配指纹。
    require(data.get('study_id')==manifest['study_id'] and data.get('source_a05_run')==index['source_a05_run'] and data.get('review_status')=='approved','通路选择身份或批准状态不正确') # 防止跨研究套用。
    result=workflow.result(manifest,index['source_a05_run']) # 核验真实富集及附件。
    run=workflow.run(manifest,index['source_a05_run']) # 使用不可变富集运行记录。
    require(data['source_a05_result_sha256']==manifest['runs'][run['run_id']]['result_file']['sha256'],'通路选择的富集指纹不一致') # 拒绝同名新数据。
    matches=[r for r in result['tables']['kegg_significant'] if r['ID']==data['pathway_id']] # 选择必须来自真实显著结果。
    require(len(matches)==1 and matches[0]['Count']==data['count'] and float(matches[0]['p.adjust'])==float(data['adjusted_p']),'通路统计与绑定A05不一致') # 不允许手抄改数。
    require(set(matches[0]['geneID'].split('/'))==set(data['entrez_ids']),'通路命中基因与A05不一致') # 同时核对身份而非仅计数。
    for item in data['files']: verified_file(home,item) # 图源、映射、解释及审核记录全部核验。
    return record # 返回唯一批准版本。

def attach_report_pathway(workflow, manifest, payload, report_dir, record): # 向专业报告绑定可选通路事实。
    if record is None: return [] # 普通研究不自动选择通路。
    home=workflow.location(manifest['study_id']) # 研究根用于统一相对指纹。
    data=read_json(verified_file(home,record)) # 再次读取已核验事实包。
    source=verified_file(home,data['native_figure']) # 使用无重复标题的完整官方布局图。
    destination=report_dir/'figures'/'07_选定通路基因定位图.png' # 可读名称随报告修订冻结。
    shutil.copy2(source,destination) # 不修改预览和官方图源。
    data['report_figure']=file_record(home,destination,'selected_pathway_png') # 为报告实际嵌图保存指纹。
    data['metadata']=record # 反向绑定用户批准事实包。
    payload['selected_pathway']=data # 临床简略版不读取此可选字段。
    payload['method_references']=payload['method_references']+data['references'] # 专业版添加疾病原始研究与绘图工具出处。
    return [record]+data['files'] # 来源链保留选择、原图、基因及解释。

def add_selected_pathway(document, payload, root, font): # 按用户认可的解释与图制作专业版补充。
    data=payload.get('selected_pathway') # 没有人工选择时不生成此部分。
    if not data: return # 不改变其他研究的正文结构。
    previous=document.sections[-1] # 保存已有纵向报告的页面规则。
    fields=('orientation','page_width','page_height','top_margin','bottom_margin','left_margin','right_margin','header_distance','footer_distance') # 页面恢复覆盖实际修改项。
    saved={key:getattr(previous,key) for key in fields} # 不依赖可被后续分节修改的对象。
    section=document.add_section(WD_SECTION.NEW_PAGE) # 图单独分页，不插入半页挤压。
    section.orientation=WD_ORIENT.LANDSCAPE # 完整通路使用横向页面。
    section.page_width=Cm(29.7); section.page_height=Cm(21) # 明确A4横向尺寸。
    section.top_margin=Cm(1.1); section.bottom_margin=Cm(1.1) # 保证图题和图注可容纳。
    section.left_margin=Cm(1.5); section.right_margin=Cm(1.5) # 保留打印安全边距。
    section.header_distance=Cm(0.45); section.footer_distance=Cm(0.45) # 避免页眉页脚侵入图面。
    heading=document.add_heading('5.1 '+data['display_name']+'中的候选靶点定位',level=2) # 标题使用人工选择的实际通路。
    heading.paragraph_format.space_before=Pt(0); heading.paragraph_format.space_after=Pt(3) # 控制独立图页的间距。
    paragraph=document.add_paragraph() # 图片使用独立段落。
    paragraph.alignment=WD_ALIGN_PARAGRAPH.CENTER # 不偏向页面一侧。
    paragraph.paragraph_format.space_after=Pt(0); paragraph.paragraph_format.keep_with_next=True # 图片和图注保持同页。
    picture=paragraph.add_run().add_picture(str(verified_file(root,data['report_figure'])),height=Cm(16.2)) # 保持原图比例，不拉伸。
    picture._inline.docPr.set('descr',data['caption']) # 为图片提供明确替代说明。
    caption=document.add_paragraph() # 中文图注紧随图面。
    caption.paragraph_format.space_before=Pt(2); caption.paragraph_format.space_after=Pt(0); caption.paragraph_format.keep_together=True # 避免图注跨页。
    font(caption.add_run(data['caption']),size=8.0) # 标红含义不能只依赖颜色。
    restored=document.add_section(WD_SECTION.NEW_PAGE) # 后续解释和报告恢复纵向。
    for key,value in saved.items(): setattr(restored,key,value) # 不影响原报告其余页面布局。
    document.add_heading('5.2 通路选择依据与解释边界',level=2) # 将图和解释紧邻而不塞进图内。
    for text in data['paragraphs']: document.add_paragraph(text) # 原样写入用户已认可的客观说明。
    document.add_paragraph(data.get('comparison_note') or '该通路是人工选定的展示与后续研究候选，不代表富集排名第一；完整富集结果及原排序不变。') # 防止选择性展示改变科学结果。
