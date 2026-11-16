"""本平台评分矩阵与MODEL1原字节只读导出；不启动工具、不写文件或科研决定。"""
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlencode

from contracts import ContractError,fingerprint,require
from storage import read_json
from modulea.core.bounded_evidence import verified_file
from modulea.core.native_execution import SCORING,QUALIFIED
from .errors import ApiError,from_contract


def _binding(manifest,rid,prep_id):
    """读取前后固定本运行和实际来源准备登记，历史不借当前新版本。"""
    return fingerprint({'study_id':manifest['study_id'],'run':manifest['runs'].get(rid),
                        'preparation':manifest['runs'].get(prep_id)})


def archive(workflow,manifest,run,result):
    """从登记原件核同批完整范围、实际命令、原子身份和MODEL1，不调用科学工具。"""
    from science_modules.a06.native_execution import scoring_rows,score_summary
    from science_modules.a06.plan_scoring_results import table_rows
    sid=manifest['study_id'];home=workflow.location(sid);rid=run['run_id']
    require(run['study_id']==sid and run['module_id']=='A06' and run['config']['version']==SCORING,
            '不是本研究本平台评分运行')
    prep_id=run['parent_runs'].get('A06_PREP');registered=manifest['runs'].get(prep_id,{})
    require(registered.get('run_file')==run['inputs']['preparation_run']
        and registered.get('result_file')==run['inputs']['preparation_result'], '原生评分准备未按本研究实际登记绑定')
    preparation=read_json(verified_file(home,registered['run_file']))
    prepared=read_json(verified_file(home,registered['result_file']))
    review=read_json(verified_file(home,run['inputs']['preparation_review']))
    require(preparation['study_id']==sid and preparation['run_id']==prepared['run_id']==prep_id
        and preparation['config']['version']==QUALIFIED
        and review['study_id']==sid and review['run_id']==prep_id and review['artifact_id']==preparation['artifact_id']
        and review['decision']=='approved' and review['result_hash']==registered['result_file']['sha256']
        and review['config_hash']==preparation['config_hash']
        and run['parent_review_ids']=={'A06_PREP':review['review_id']}
        and preparation['inputs']['a06_plan_input']==run['inputs']['a06_plan_input'], '原生评分来源、范围或实际批准不同')
    record=read_json(verified_file(home,run['inputs']['a06_plan_input']))
    source=read_json(verified_file(home,prepared['tables']['preparation_packet'][0]))
    refs=result['tables'].get('scoring_packet',[])
    require(len(refs)==1 and refs[0] in result['files'],'原生评分缺少唯一已登记事实包')
    fact=read_json(verified_file(home,refs[0]))
    require(fact['study_id']==sid and fact['run_id']==rid and fact['schema_version']==SCORING
        and fact['configuration']==run['config'] and fact['summary']==result['summary']
        and source['input_key']==record['packet']['input_key']==result['summary']['input_key'], '原生矩阵与本批运行或固定输入不同')
    signature=read_json(verified_file(home,fact['native_signature']))
    binary=verified_file(home,fact['binary'])
    require(fingerprint(signature)==run['config']['native_tools_sha256']==preparation['config']['native_tools_sha256']
        and fact['binary']['sha256']==source['vina_sha256'], '原生评分工具、源码或准备来源不同')
    rows=scoring_rows(home,run,prepared,source,fact['pairs'],binary)
    require(table_rows(rows)==result['tables']['native_scores']
        and score_summary(source,rows,record)==result['summary'], '原生矩阵、计数或实际执行不一致')
    return fact,source,record


def _links(sid,rid,index,input_key,execution_ref,execution):
    """下载绑定同一实际执行与原姿势SHA，不把所有模式冒充Top1。"""
    query=urlencode({'expected_input_key':input_key,'expected_execution_sha256':execution_ref['sha256'],
                     'expected_pose_sha256':execution['pose']['sha256']})
    base=f'/api/v1/studies/{sid}/runs/{rid}/native/pairs/{index}/'
    return [{'label_zh':label,'url':base+suffix+'?'+query,'name':suffix,
             'sha256':execution['pose']['sha256']} for suffix,label in (
             ('top1.pdbqt','Top-1构象'),('context.json','同构象评分与指纹说明'))]


def apply(workflow,manifest,run,result,response):
    """复用已确认矩阵几何与实际本批名称，所有组合保留；仅追加只读展示。"""
    from science_modules.a06.native_display import renderer
    from .system_rescue_view import _download,OBSOLETE
    fact,source,record=archive(workflow,manifest,run,result)
    packet={**fact,'source_fixed':record['packet'],'compounds':source['compounds'],'receptors':source['receptors'],
            'pairs':[dict(row,source_kind='native') for row in fact['pairs']]}
    view=renderer()['build_view'](packet);sid=manifest['study_id'];home=workflow.location(sid)
    view.update(input_key=record['packet']['input_key'],downloads=[],figures=[])
    by_pair={(row['compound_id'],row['target_id']):(index,row) for index,row in enumerate(fact['pairs'],1)}
    for matrix in (view['table'],view['heatmap']):
        for line in matrix['cells']:
            for cell in line:
                index,row=by_pair[cell['compound_id'],cell['target_id']];cell['downloads']=[]
                if row['state']=='completed':
                    execution=read_json(verified_file(home,row['execution']))
                    cell['downloads']=_links(sid,run['run_id'],index,view['input_key'],row['execution'],execution)
    # 初始焦点仅过滤显示范围；完整表、NA、原始数值与所有来源关系仍在view.table。
    focus=view['initial_focus'];full=view['table']
    view['heatmap']={**full,'rows':[r for r in full['rows'] if r['compound_id'] in focus['compound_ids']],
        'columns':[r for r in full['columns'] if r['target_id'] in focus['target_ids']],
        'cells':[[cell for cell in line if cell['target_id'] in focus['target_ids']]
                 for row,line in zip(full['rows'],full['cells']) if row['compound_id'] in focus['compound_ids']]}
    for item in response.get('files',[]):
        role=item.get('role','')
        if not (role.startswith('plot_a06_native_') or role in ('a06_native_matrix_csv','a06_native_display_view','native_matrix_csv')):continue
        link=_download(sid,item,response['files'],item.get('name') or Path(item['path']).name)
        if link:
            view['downloads'].append(link)
            if role.endswith('_png'):view['figures'].append(dict(link,image_url=link['url']+'&inline=1',role=role))
    response['special'].pop('heatmap',None)
    response['special']['native_scores']=view
    # 已完成的新协议结果不能显示旧候选/试算阶段入口及“尚未开始”提示。
    for key in OBSOLETE:response[key]=None
    response['review']['continue'].update(available=False,note_zh='本平台评分结果待独立科研复核；本批不生成Word。')


def top1(app,req,sid,rid,number,kind):
    """严格绑定组合编号和三个指纹，导出生产校验通过的MODEL1原字节或同构象说明。"""
    expected={'expected_input_key','expected_execution_sha256','expected_pose_sha256'}
    if set(req.query)!=expected or any(len(v)!=1 for v in req.query.values()):
        raise ApiError(422,'VALIDATION_FAILED','构象下载只接受固定输入、执行及姿势指纹各一个')
    if kind not in ('top1.pdbqt','context.json') or len(str(number))>8 or not str(number).isdigit() or int(number)<1:
        raise ApiError(404,'NOT_FOUND','找不到本批原始组合')
    w=app.kernel.read_workflow();m=w.load(sid);entry=m['runs'].get(rid)
    if not entry or not entry.get('result_file'):raise ApiError(404,'NOT_FOUND','没有本研究已归档评分运行')
    try:
        run=w.run(m,rid);result=w.result(m,rid);prep_id=run['parent_runs'].get('A06_PREP')
        before=_binding(m,rid,prep_id);fact,source,record=archive(w,m,run,result)
        if int(number)>len(fact['pairs']):raise ApiError(404,'NOT_FOUND','找不到本批原始组合')
        row=fact['pairs'][int(number)-1]
        if row['state']!='completed':raise ApiError(409,'GATE_BLOCKED','本组合未形成有效评分与Top-1；NA或失败原因保持')
        home=w.location(sid);execution=read_json(verified_file(home,row['execution']));ref=execution['pose']
        if (req.query1('expected_input_key')!=record['packet']['input_key']
            or req.query1('expected_execution_sha256')!=row['execution']['sha256']
            or req.query1('expected_pose_sha256')!=ref['sha256']):
            raise ApiError(409,'STALE_VERSION','本批输入、评分执行或原始姿势已改变，请刷新后下载')
        raw=verified_file(home,ref).read_bytes()
        require(len(raw)==ref['bytes'] and sha256(raw).hexdigest()==ref['sha256'],'构象读取期间原始字节改变')
        selected=[];started=False
        for line in raw.splitlines(keepends=True):
            if line.startswith(b'MODEL ') and line.split()[1]==b'1':started=True
            if started:selected.append(line)
            if started and line.startswith(b'ENDMDL'):break
        require(selected and selected[-1].startswith(b'ENDMDL'),'原始MODEL1构象不完整')
        value=b''.join(selected)
        require(before==_binding(w.load(sid),rid,prep_id),'构象下载期间本运行或来源准备登记改变')
        name=f'{rid}_pair_{int(number):06d}_'
        if kind=='top1.pdbqt':return 'download',value,name+kind,'chemical/x-pdbqt'
        context={'schema_version':'ModuleA.native_top1.1','study_id':sid,'run_id':rid,'pair_number':int(number),
            'compound_id':row['compound_id'],'target_id':row['target_id'],'score':row['score'],'score_unit':'kcal/mol',
            'input_key':record['packet']['input_key'],'execution_sha256':row['execution']['sha256'],
            'source_pose_sha256':ref['sha256'],'top1_sha256':sha256(value).hexdigest(),'top1_bytes':len(value),
            'top_mode':1,'configuration':run['config'],'read_only':True,'coordinates_source':'saved_vina_model_1_exact_bytes'}
        from science_modules.a06.plan_scoring_inputs import receptor_evidence
        receptor=next(r for r in source['receptors'] if r['target_id']==row['target_id'])
        context['box']=receptor_evidence(receptor)['box']
        return 'download',json.dumps(context,ensure_ascii=False,indent=2).encode('utf-8'),name+kind,'application/json; charset=utf-8'
    except ContractError as error:raise from_contract(str(error)) from error
