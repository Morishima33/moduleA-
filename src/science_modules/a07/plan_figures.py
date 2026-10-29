"""新报告同批图件：空交集不重叠，富集按实际展示，完整评分矩阵不删除全NA行列。"""
from copy import deepcopy
from pathlib import Path
import hashlib
from contracts import fingerprint,require
from storage import file_record,read_json,verified_file,write_json

VERSION='A07.plan_figures.1'


def venn(summary,folder):
    """按真实集合计数绘制示意图，空交集分离，面积不伪装为数量比例。"""
    from science_modules.a05.figures import Canvas
    left,middle,right=(summary[key] for key in ('仅方剂靶点数','交集靶点数','仅疾病靶点数'))
    require(all(type(value) is int and value>=0 for value in (left,middle,right)),'韦恩图缺少真实集合数量')
    canvas=Canvas(1600,800);canvas.text(800,28,'方剂与疾病的人类标准化靶点',38,bold=True,anchor='ma')
    centers=(440,1160) if middle==0 else (620,980)
    canvas.circle(centers[0],420,275,'#D2E5F0');canvas.circle(centers[1],420,275,'#E2D8EF')
    canvas.text(centers[0],110,'方剂侧 T',32,bold=True,anchor='ma');canvas.text(centers[1],110,'疾病侧 D',32,bold=True,anchor='ma')
    for x,value in ((380,left),(800,middle),(1220,right)):canvas.text(x,405,value,48,bold=True,anchor='ma')
    if middle==0:canvas.text(800,470,'交集为空',24,anchor='ma')
    canvas.text(800,730,'数量来自同一HGNC口径；图形面积不按集合大小缩放。',24,anchor='ma')
    return canvas.save(Path(folder)/'intersection')


def ppi(result,folder):
    """展示原网络有效边和已识别孤立点，不扩大候选范围或重新筛选。"""
    import networkx as nx
    from science_modules.a05.figures import Canvas
    tables=result['tables'];nodes={row['target_id']:row for row in tables['mapping']}
    graph=nx.Graph();graph.add_nodes_from(nodes)
    for row in tables['edges']:
        require(row['source'] in nodes and row['target'] in nodes,'PPI图出现额外节点')
        graph.add_edge(row['source'],row['target'])
    canvas=Canvas(1800,1250);canvas.text(900,25,'本批PPI有效边与已识别靶点',38,bold=True,anchor='ma')
    positions=nx.spring_layout(graph,seed=24,iterations=350) if graph else {}
    coords={key:(900+float(point[0])*720,610+float(point[1])*440) for key,point in positions.items()}
    for a,b in graph.edges():canvas.line(*coords[a],*coords[b],fill='#B9CDD5')
    for key,(x,y) in coords.items():
        canvas.circle(x,y,18 if graph.degree(key) else 12,'#A8CBDD' if graph.degree(key) else '#E4E9ED')
        canvas.text(x,y+23,nodes[key].get('symbol') or key,20,anchor='ma')
    if not graph:canvas.text(900,560,'本批没有可展示的已识别网络节点',30,anchor='ma')
    canvas.text(900,1180,f'已识别{len(nodes)}个节点，有效边{len(tables["edges"])}条；不代表因果关系或证据等级。',25,anchor='ma')
    return canvas.save(Path(folder)/'ppi')


def heatmaps(facts,folder):
    """分块呈现所有固定对象；缺失白底虚线NA，色标仅由同批有限原评分决定。"""
    from science_modules.a05.figures import Canvas,wrap
    from science_modules.a06.matrix_palette import color,text_color,RED_BLUE
    from science_modules.a06.trial_presentation import score_label,LEGEND
    scores=[row['score'] for row in facts['pairs'] if row['score'] is not None]
    low,high=(min(scores),max(scores)) if scores else (None,None);outputs=[]
    for row_start in range(0,len(facts['compounds']),20):
        for col_start in range(0,len(facts['receptors']),8):
            compounds=facts['compounds'][row_start:row_start+20];receptors=facts['receptors'][col_start:col_start+8]
            width=420+150*len(receptors)
            explanation=('本批无可用评分，全部缺失保持NA。' if not scores else f'完整同批原评分范围：{low:g} 至 {high:g} kcal/mol；越负越红，越不负越蓝。')
            footer=wrap(explanation,width-40,19)+wrap(LEGEND,width-40,19)
            height=225+66*len(compounds)+26*len(footer);canvas=Canvas(width,height)
            canvas.text(width/2,18,'同批完整固定范围评分矩阵',32,bold=True,anchor='ma')
            for j,row in enumerate(receptors):
                label=row.get('symbol') or row['target_id']
                for index,line in enumerate(wrap(label,140,24)):canvas.text(420+j*150+75,80+index*28,line,24,anchor='ma')
            cells={(row['compound_id'],row['target_id']):row for row in facts['pairs']}
            for i,compound in enumerate(compounds):
                y=175+i*66;canvas.text(400,y+17,f'成分{row_start+i+1}',26,anchor='ra')
                for j,receptor in enumerate(receptors):
                    x=420+j*150;score=cells[(compound['compound_id'],receptor['target_id'])]['score']
                    fill=color(score,low,high,RED_BLUE) if score is not None else '#FFFFFF';canvas.rect(x,y,150,66,fill)
                    if score is None:
                        # PNG/SVG使用相同虚线边，不以颜色或0伪造缺失评分。
                        for a,b,c,d in ((x,y,x+150,y),(x,y+66,x+150,y+66),(x,y,x,y+66),(x+150,y,x+150,y+66)):
                            length=max(abs(c-a),abs(d-b))
                            for offset in range(0,int(length),10):
                                start=(a+(c-a)*offset/length,b+(d-b)*offset/length)
                                end=(a+(c-a)*min(offset+5,length)/length,b+(d-b)*min(offset+5,length)/length)
                                canvas.line(*start,*end,fill='#80939C')
                    canvas.text(x+75,y+18,score_label(score,mark=True),26,color=text_color(fill),anchor='ma')
            foot=185+66*len(compounds)
            for index,line in enumerate(footer):canvas.text(20,foot+index*26,line,19)
            paths=canvas.save(Path(folder)/f'scores_{row_start+1}_{col_start+1}')
            outputs.append((paths,f'完整评分矩阵：成分{row_start+1}—{row_start+len(compounds)}，受体{col_start+1}—{col_start+len(receptors)}；成分序号对应同批矩阵行序，完整名称与原始值见表。'))
    return outputs


def attach(workflow,payload,folder):
    """后台公开Workflow调用的图件归档适配；生成PNG/SVG及真实来源和代码索引。"""
    require(payload.get('figure_source') is None and payload.get('figures')==[],'不能给已有图件的事实包重复追加')
    home=workflow.location(payload['study_id']);folder=Path(folder).resolve();folder.relative_to(home.resolve())
    require(not folder.exists(),'报告图件目录已存在，不覆盖历史');folder.mkdir(parents=True)
    m=workflow.load(payload['study_id']);figures=[];files=[]
    def add(paths,module,caption,scope_hash,group=None):
        """Word仅用同批PNG，SVG同时归档，图注明确实际范围。"""
        records={key:file_record(home,path,'plan_report_figure') for key,path in paths.items()}
        files.extend(records.values());entry={'module':module,'record':records['png'],'caption':caption,'scope_hash':scope_hash}
        if group:entry['group']=group
        figures.append(entry)
    result=workflow.result(m,payload['run_ids']['A03'])
    add(venn(result['summary'],folder),'A03','本批方剂与疾病标准化集合交集；来源、筛选范围及基因身份口径见数据来源。',fingerprint(result))
    if 'A04' in payload['run_ids']:
        result=workflow.result(m,payload['run_ids']['A04'])
        add(ppi(result,folder),'A04','本批STRING有效边与已识别孤立点；筛选依据与参数见同批记录。',fingerprint(result))
    if payload.get('enrichment'):
        from science_modules.a05.plan_display_figures import draw
        facts=payload['enrichment'];paths=draw(facts,payload['plan'],folder/'enrichment')
        for group in ('BP','CC','MF','KEGG'):
            if group+'_png' in paths:
                add({'png':paths[group+'_png'],'svg':paths[group+'_svg']},'A05',group+' 本批实际范围；缺译保留原名，未纳入和暂缓不改变原始统计。',fingerprint(facts),group)
    if payload.get('docking'):
        for paths,caption in heatmaps(payload['docking'],folder/'docking'):add(paths,'A06',caption,fingerprint(payload['docking']))
    implementation=[];src=Path(__file__).resolve().parents[2]
    for name in ('science_modules/a07/plan_figures.py','science_modules/a05/figures.py','science_modules/a05/plan_figures.py',
                 'science_modules/a05/plan_display_figures.py','science_modules/a06/trial_presentation.py',
                 'science_modules/a06/matrix_palette.py','report_figures.py','docking_formal.py',
                 'science_modules/a07/plan_payload.py','science_modules/a07/plan_facts.py','science_modules/a07/plan_documents.py',
                 'science_modules/a07/plan_document_style.py','science_modules/a07/plan_report_flow.py',
                 'science_modules/a07/appendix_documents.py','science_modules/a07/commented_documents.py',
                 'modulea/core/plan_reports.py','modulea/core/plan_report_contract.py','modulea/core/analysis_plans.py',
                 'modulea/core/system_validation.py','science_modules/analysis_protocol.py','report_flow.py',
                 'contracts.py','workflow.py','storage.py'):
        target=folder/'code'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((src/name).read_bytes())
        implementation.append(file_record(home,target,'plan_report_implementation'))
    from report_figures import _font
    fonts=[]
    for bold in (False,True):
        font_path=Path(_font(20,bold).path);content=font_path.read_bytes()
        fonts.append({'name':font_path.name,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)})
    source={'schema_version':VERSION,'study_id':payload['study_id'],'payload_hash':fingerprint(payload),'run_ids':deepcopy(payload['run_ids']),
            'figures':figures,'files':files,'implementation_files':implementation,'render_fonts':fonts,'human_review_written':False}
    path=folder/'figures.json';write_json(path,source)
    output=deepcopy(payload);output['figures']=figures;output['figure_source']=file_record(home,path,'plan_report_figure_index')
    return output


def validate(home,payload,base):
    """核验图件索引与同批完整事实指纹，拒绝任意图片或其他批次图件。"""
    reference=payload.get('figure_source');require(isinstance(reference,dict),'正式报告缺少同批图件索引')
    value=read_json(verified_file(home,reference))
    require(value.get('schema_version')==VERSION and value.get('study_id')==base['study_id'] and value.get('payload_hash')==fingerprint(base)
            and value.get('run_ids')==base['run_ids'] and value.get('human_review_written') is False,'报告图件不属于本批实际来源')
    require(value.get('figures')==payload['figures'] and value['figures'] and value['implementation_files'],'报告图件或实现来源不一致')
    for ref in [*value['files'],*value['implementation_files']]:verified_file(home,ref)
    for item in value['figures']:
        require(item['record'] in value['files'],'报告内嵌图未登记到本批索引');verified_file(home,item['record'])
    required={'A03':1,'A04':int('A04' in base['run_ids']),
              'A05':sum(row['included'] for row in (base.get('enrichment') or {}).get('groups',[])),
              'A06':0}
    if base.get('docking'):
        facts=base['docking'];required['A06']=((len(facts['compounds'])+19)//20)*((len(facts['receptors'])+7)//8)
    require(all(sum(item['module']==module for item in value['figures'])==count for module,count in required.items()),
            '报告缺少适用分支的完整图件或出现额外图片')
    require(all(item['module'] in required for item in value['figures']),'报告包含未知图件分支')
    return value
