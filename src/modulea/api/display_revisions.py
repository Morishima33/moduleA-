"""只读同批展示、明确排队与登记附件下载；HTTP不导入绘图依赖。"""
from pathlib import Path
from hashlib import sha256

from contracts import ContractError, require
from storage import read_json, verified_file
from ..core import display_revisions as core
from .errors import ApiError, from_contract


LABELS={
    'venn':'方剂与疾病靶点交集（面积为示意）','ppi_degree_round2':'Degree第二轮网络',
    'ppi_overview':'已识别全网概览','enrichment_bp':'GO生物过程（BP）',
    'enrichment_cc':'GO细胞组分（CC）','enrichment_mf':'GO分子功能（MF）',
    'enrichment_kegg':'KEGG通路',
}
TABLE_LABELS={
    'a03_counts':'本批真实集合数量','ppi_degree_round2_nodes':'Degree第二轮节点',
    'ppi_degree_round2_edges':'Degree第二轮内部边','ppi_full_network_overview_nodes':'全网节点',
    'ppi_full_network_overview_edges':'全网连边','a06_compounds':'本批固定成分',
    'a06_receptors':'本批固定受体','a06_pairs':'本批全部组合及缺失原因',
}
COLUMN_LABELS={
    'ID':'稳定编号','english':'原英文','chinese':'核译中文','Count':'命中数','pvalue':'P值',
    'p.adjust':'校正P值','GeneRatio':'命中比例','BgRatio':'背景比例','reason_zh':'原因',
    'classification_zh':'范围分类','translation_source':'核译来源','target_id':'靶点稳定编号',
    'symbol':'基因名称','namespace':'编号体系','string_id':'STRING编号','source':'起点','target':'终点',
    'score':'原始分数','source_row':'原始记录','compound_id':'成分编号','name':'实际名称',
    'compound_name':'实际成分名称','receptor_symbol':'实际受体名称','state_zh':'实际状态',
    'execution_path':'评分类别','quality':'质控类别','only_formula':'仅方剂靶点',
    'intersection':'交集靶点','only_disease':'仅疾病靶点','formula_total':'方剂靶点合计',
    'disease_total':'疾病靶点合计','degree_rank':'原Degree排名','selection_role':'原候选类别',
    'rank':'原排名','degree':'Degree','bc':'BC','cc':'CC','selection_order':'固定顺序',
}


def _downloads(sid,value):
    """链接仅由本研究回执的索引构成，客户端不能选择磁盘路径。"""
    refs=value['files']+[value['bundle_file'],value['payload_file']]+value['implementation_files']
    return [dict(label_zh=Path(ref['path']).name,name=Path(ref['path']).name,bytes=ref['bytes'],
                 url=f"/api/v1/studies/{sid}/analysis-plan/display-revisions/{value['revision_id']}/files/{i}")
            for i,ref in enumerate(refs)]


def _counts(counts):
    """数量直接取已核验展示包，页面不推算科学集合。"""
    rows=[]
    if 'a03' in counts:
        row=counts['a03'];rows.append({'label_zh':'本批标准化靶点（方剂／疾病／交集）',
            'text':f"{row['formula_total']} / {row['disease_total']} / {row['intersection']}"})
    for key,label in (('degree_round2','Degree第二轮（节点／内部边）'),('full_network_overview','全网概览（节点／连边）')):
        if key in counts:
            row=counts[key];rows.append({'label_zh':label,'text':f"{row['nodes']} / {row['edges']}"})
    if 'docking' in counts:
        row=counts['docking'];rows.extend([
            {'label_zh':'固定成分记录／受体／组合','text':f"{row['compounds']} / {row['receptors']} / {row['pairs']}"},
            {'label_zh':'已有评分／NA','text':f"{row['scored']} / {row['NA']}"}])
    rows.append({'label_zh':'核译独立条目／展示记录',
                 'text':f"{counts.get('translation_terms',0)} / {counts.get('translation_rows',0)}"})
    return rows


def _table(key,rows,downloads):
    """首屏只回已声明的少量预览；完整CSV保留每一行与原精度。"""
    module='A03' if key.startswith('a03_') else 'A04' if key.startswith('ppi_') else 'A05' if key.startswith('a05_') else 'A06'
    maximum=len(rows) if module=='A05' else 50
    preferred=(['ID','english','chinese','Count','p.adjust','GeneRatio','reason_zh','classification_zh','translation_source']
               if module=='A05' else ['compound_name','receptor_symbol','state_zh','score','quality','reason_zh']
               if key=='a06_pairs' else [])
    keys=[name for name in preferred if any(name in row for row in rows)]
    if not keys:keys=list(dict.fromkeys(name for row in rows[:maximum] for name in row))
    label=TABLE_LABELS.get(key,key)
    if module=='A05':
        parts=key.split('_');group=parts[1].upper()
        suffix=key[len('a05_'+parts[1]+'_'):]
        label=group+' '+{'display':'图中条目','plan_top':'原正文范围','plan_count_top':'原命中数排名',
                         'excluded':'原排除范围（保留原因）','deferred':'原暂缓范围'}.get(suffix,suffix)
    return {'key':key,'module_id':module,'label_zh':label,'columns':[{'key':name,'label_zh':COLUMN_LABELS.get(name,name)} for name in keys],
            'rows':[{name:row.get(name) for name in keys} for row in rows[:maximum]],'total':len(rows),
            'preview_note_zh':f'本页预览前{maximum}条，完整记录见CSV。' if len(rows)>maximum else '本表显示全部记录。',
            'downloads':[item for item in downloads if item['name']==key+'.csv']}


def _current(workflow,sid,item):
    """完整科学和核译表保留于附件；首屏不重复发送大篇来源绑定。"""
    home=workflow.location(sid);bundle=read_json(verified_file(home,item['bundle_file']))
    downloads=_downloads(sid,item);by_name={row['name']:row for row in downloads};figures=[]
    matrices=[row['key'] for row in bundle['figures'] if row['role']=='score_matrix']
    for row in bundle['figures']:
        files=[by_name[Path(path).name] for path in row['files'].values()]
        label=(f"同批评分矩阵（第{matrices.index(row['key'])+1}部分，共{len(matrices)}部分）" if row['role']=='score_matrix'
               else LABELS.get(row['key'],'同批图表'))
        figures.append({'key':row['key'],'module_id':row['module'],'group':row.get('group'),'role':row['role'],
                        'label_zh':label,'caption_zh':row['caption'],
                        'image_url':by_name[Path(row['files']['png']).name]['url']+'?inline=1','downloads':files})
    tables=[];compounds={r['compound_id']:r['name'] for r in bundle['tables'].get('a06_compounds',[])}
    receptors={r['target_id']:r.get('symbol',r['target_id']) for r in bundle['tables'].get('a06_receptors',[])}
    for key,rows in bundle['tables'].items():
        if key=='a06_pairs':
            rows=[dict(row,compound_name=compounds[row['compound_id']],receptor_symbol=receptors[row['target_id']],
                       score='NA' if row['score'] is None else row['score']) for row in rows]
        tables.append(_table(key,rows,downloads))
    required=bundle['counts'].get('translation_terms',0);verified=len(bundle['translation_audit'])
    require(required==verified,'展示译名覆盖不完整，最终交付已阻断')
    return {'revision_id':item['revision_id'],'created_at':item['created_at'],'source_run_ids':item['source_run_ids'],
            'matches_input':item['matches_input'],'counts':_counts(bundle['counts']),
            'translation_coverage':{'required':required,'verified':verified,'missing':[]},
            'figures':figures,'tables':tables,'downloads':downloads,
            'human_review_written':False,'scientific_results_changed':False}


def _info(app,sid,workflow):
    """任何损坏都报告不可用，不将缺译或损坏伪装为空数据。"""
    value=core.info(workflow,sid)
    history=[{'revision_id':item['revision_id'],'created_at':item['created_at'],
              'source_run_ids':item['source_run_ids'],'matches_input':item['matches_input'],
              'downloads':_downloads(sid,item)} for item in value['history']]
    if app.tasks.active_for(sid):value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    return dict(value,current=_current(workflow,sid,value['current']) if value['current'] else None,history=history)


def info(app,req,sid):
    """GET只读归档，不生成图片、译名、任务或Word。"""
    workflow=app.kernel.read_workflow()
    try:
        with workflow.handoff_read_cache():return _info(app,sid,workflow)
    except (ContractError,OSError,KeyError,ValueError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','展示归档未通过核验：'+str(error),retryable=True) from error


def submit(app,req,sid):
    """只接受明确五字段，实际绘图由已有预算worker调用公开Workflow。"""
    body=req.json()
    try:_,_,existing=core.validate_request(app.kernel.workflow(),sid,body)
    except ContractError as error:raise from_contract(str(error)) from error
    if existing:return {'created':False,'revision_id':existing['revision_id'],'message_zh':'该请求的展示已归档，未重复生成。'},200
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待当前研究后台任务结束')
    task,created=app.tasks.submit(sid,'plan_display_revision',body['author'].strip(),body)
    if not created:raise ApiError(409,'GATE_BLOCKED','当前研究已有后台任务')
    return {'task':task,'created':True,'message_zh':'已提交同批图表和译名修订；原始结果、复核与Word保持。'},202


def download(app,req,sid,revision_id,index):
    """逐附件核验原登记，历史来源可追溯，不接收路径或跨研究借用。"""
    workflow=app.kernel.read_workflow();m=workflow.load(sid)
    if set(req.query)-{'inline'} or req.query1('inline') not in (None,'1'):
        raise ApiError(422,'VALIDATION_FAILED','附件只支持inline=1显示参数')
    try:
        for ref in m.get(core.INDEX,[]):
            item=core.read_record(workflow,m,ref)
            if item['revision_id']!=revision_id:continue
            refs=item['files']+[item['bundle_file'],item['payload_file']]+item['implementation_files'];number=int(index)
            if number<0 or number>=len(refs):break
            path=verified_file(workflow.location(sid),refs[number]);suffix=path.suffix.lower()
            inline=req.query1('inline')=='1'
            if inline and suffix not in ('.png','.svg'):raise ApiError(422,'VALIDATION_FAILED','此附件不支持内嵌显示')
            mime={'.png':'image/png','.svg':'image/svg+xml','.csv':'text/csv; charset=utf-8',
                  '.json':'application/json; charset=utf-8','.py':'text/plain; charset=utf-8'}.get(suffix,'application/octet-stream')
            # 发送同一份已核验不可变字节，不能检查Path后让HTTP再打开变化后的文件。
            raw=path.read_bytes();expected=refs[number]
            require(len(raw)==expected['bytes'] and sha256(raw).hexdigest()==expected['sha256'],
                    '展示附件在读取期间改变')
            return 'verified_download',raw,path.name,mime,inline
    except (ContractError,OSError,KeyError,ValueError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','展示附件未通过核验：'+str(error),retryable=True) from error
    raise ApiError(404,'NOT_FOUND','找不到本研究登记的展示附件')
