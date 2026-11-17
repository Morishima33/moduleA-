"""只读验收资料包：核对本运行既有矩阵、图件、来源与构象，不隐式生成图表或Word。"""
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json
from pathlib import PurePosixPath
import zipfile

from contracts import fingerprint,require,ContractError
from .errors import ApiError
from .rescue_evidence import load_bundle,checked_bytes,_artifacts,same_file
from ..core.rescue_presentation_names import chinese_name
from ..core.png_integrity import png_size as _png
from ..core.read_evidence import current_evidence
from ..core.rescue_acceptance_inventory import registered_files as _registered_files, member_plan, presentation_files

ROLES={'plot_a06_rescue_full_png','plot_a06_rescue_full_svg','a06_rescue_matrix_csv','a06_rescue_display_view'}
MAX_REGISTERED_BYTES=512*1024*1024


def _load(app,sid,rid):
    """生产HTTP沿既有精确读代理收集固定输入和packet，直接只读调用仍严格核原件。"""
    settings=getattr(app,'settings',None)
    reader=current_evidence(settings.data_root) if settings else None
    return reader.call(load_bundle,app,sid,rid) if reader else load_bundle(app,sid,rid)


def _presentation(app,req,sid,rid,*,download=False):
    """没有修订参数就保持原链接语义；明确修订必须带完整单值绑定。"""
    if 'revision_id' in req.query:
        from . import rescue_presentations as revised
        revised._query(req,{'revision_id','expected_revision_sha256','expected_input_key'})
        return revised.select(app,req,sid,rid,req.query1('revision_id'))
    if download:
        if set(req.query)!={'expected_input_key'} or any(len(v)!=1 for v in req.query.values()):
            raise ApiError(422,'VALIDATION_FAILED','验收资料下载字段错误')
    elif req.query:raise ApiError(422,'VALIDATION_FAILED','验收资料资格不接受额外参数')
    return None


def _assess_presentation(bundle,presentation,artifacts=None):
    """双语修订只替换展示附件；每个已有评分仍须对应原执行的MODEL 1。"""
    from .rescue_presentations import _revision
    w,m,home,run,result,packet=bundle
    record=presentation['record'];bound=presentation['binding']
    require(record['study_id']==run['study_id'] and record['run_id']==run['run_id']
            and same_file(bound['source']['scoring_packet'],result['tables']['scoring_packet'][0]),
            '验收名称修订与原评分运行不同')
    _registered_files(result['files']);blockers=[]
    if not presentation['matches_input']:blockers.append('所选为历史输入或科研意见下的图表修订，仅供追溯')
    unnamed=[row['target_id'] for row in packet['source_fixed']['receptors'] if not row.get('symbol','').strip()]
    if unnamed:blockers.append('缺少本批实际受体名称：'+'、'.join(unnamed))
    files=[]
    for ref in record['files']:
        row=deepcopy(ref)
        if ref['role'].endswith('_png'):row['image_size']=_png(checked_bytes(home,ref,record['files']))
        files.append(row)
    for index,pair in enumerate(packet['pairs'],1):
        if pair['state']=='completed':
            require(pair.get('execution'),'已评分组合缺少原执行，不能核验MODEL 1或交付资料包')
            values=_artifacts(bundle,pair)
            if artifacts is not None:artifacts[index]={kind:values[0][kind] for kind in ('top1','context')}
    return {'schema_version':'ModuleA.acceptance_bundle.1','study_id':run['study_id'],'run_id':run['run_id'],
            'input_key':packet['summary']['input_key'],'enabled':not blockers,'blockers_zh':blockers,
            'translation_missing_ids':[],'files':files,'read_only':True,
            'presentation_revision':_revision(presentation,presentation['matches_input']),
            'scientific_computation_performed':False,'human_review_written':False,
            'note_zh':'同修订矩阵、名称范围和原MODEL 1已核对；仅原术语或原专名不代表结构身份确认，技术核验不代替科研批准。'}


def assess(bundle,presentation=None):
    """缺译或附件未齐保留具体阻塞；不生成任何缺失图件来掩盖问题。"""
    if presentation is not None:return _assess_presentation(bundle,presentation)
    workflow,manifest,home,run,result,packet=bundle
    _registered_files(result['files'])
    from science_modules.a06 import system_rescue_display as first,system_rescue_display_v2 as second
    render=second if packet['schema_version']=='A06.system_rescue.2' else first
    view=render.build_view(packet);blockers=[]
    missing=[row['compound_id'] for row in packet['source_fixed']['compounds'] if not
             chinese_name(row.get('name_zh') or row.get('name'))]
    unnamed=[row['target_id'] for row in packet['source_fixed']['receptors'] if not row.get('symbol','').strip()]
    if missing:blockers.append('缺少本批已核译中文成分名：'+'、'.join(missing))
    if unnamed:blockers.append('缺少本批实际受体名称：'+'、'.join(unnamed))
    prefix=f"runs/A06/{run['run_id']}/rescue/display/"
    exports={}
    for ref in result['files']:
        role=ref.get('role')
        if role in ROLES or role in ('plot_a06_rescue_focus_png','plot_a06_rescue_focus_svg'):
            if run['config']['version']=='A06.system_rescue.2' and not ref['path'].startswith(prefix):continue
            require(role not in exports or same_file(exports[role],ref),'本批展示附件角色重复指向不同原件')
            exports[role]=ref
    required=set(ROLES)
    if view['initial_focus']['compound_ids'] and view['initial_focus']['target_ids']:
        required|={'plot_a06_rescue_focus_png','plot_a06_rescue_focus_svg'}
    absent=required-set(exports)
    if absent:blockers.append('缺少本批已登记展示附件：'+'、'.join(sorted(absent)))
    evidence=[]
    if not absent:
        require(len({str(PurePosixPath(ref['path']).parent) for ref in exports.values()})==1,
                '完整矩阵、焦点图和CSV不是同一次完整出图尝试')
        raw={role:checked_bytes(home,ref,result['files']) for role,ref in exports.items()}
        saved=json.loads(raw['a06_rescue_display_view'])
        require(fingerprint(saved)==fingerprint(view),'已登记展示JSON与本批矩阵或名称不同')
        rows=list(csv.DictReader(io.StringIO(raw['a06_rescue_matrix_csv'].decode('utf-8-sig'))))
        flat=[(c,t,cell) for c,line in zip(view['table']['rows'],view['table']['cells'])
              for t,cell in zip(view['table']['columns'],line)]
        require(len(rows)==len(flat),'已登记CSV不是本批完整矩阵')
        for row,(compound,target,cell) in zip(rows,flat):
            expected={'compound_id':compound['compound_id'],'target_id':target['target_id'],
                      'compound_name':compound['label'],'symbol':target['symbol'],'score':cell['score_text'],
                      'state':cell['state'],'reason_zh':cell['reason_zh']}
            require(all(row.get(k)==v for k,v in expected.items()),'已登记CSV对象、名称、评分或原因与矩阵不同')
        require(raw['plot_a06_rescue_full_svg']==render.heatmap_svg(view,full=True).encode('utf-8'),
                '完整SVG与同批实际矩阵或名称不同')
        if 'plot_a06_rescue_focus_svg' in raw:
            focused=render.build_view(packet,selected_compounds=view['initial_focus']['compound_ids'],
                                     selected_targets=view['initial_focus']['target_ids'])
            require(raw['plot_a06_rescue_focus_svg']==render.heatmap_svg(focused,full=False).encode('utf-8'),
                    '焦点SVG与同批成功对象或色标不同')
        for role,data in raw.items():
            row=deepcopy(exports[role])
            if role.endswith('_png'):row['image_size']=_png(data)
            evidence.append(row)
    return {'schema_version':'ModuleA.acceptance_bundle.1','study_id':run['study_id'],'run_id':run['run_id'],
            'input_key':packet['summary']['input_key'],'enabled':not blockers,'blockers_zh':blockers,
            'translation_missing_ids':missing,'files':evidence,'read_only':True,
            'scientific_computation_performed':False,'human_review_written':False,
            'note_zh':'资料包只整理本运行已有登记原件，不重算、不补图、不生成Word；技术核验不代替用户科研批准。'}


def info(app,req,sid,rid):
    """只返回本批原件齐备性和缺译门控，不创建导出或任务。"""
    try:
        presentation=_presentation(app,req,sid,rid)
        bundle=presentation['bundle'] if presentation else _load(app,sid,rid)
        value=assess(bundle,presentation)
        from urllib.parse import urlencode
        plan=member_plan(bundle[4],presentation)
        value['registered_source_bytes']=plan['registered_bytes']
        value['archive_required']=plan['registered_bytes']>MAX_REGISTERED_BYTES
        if value['archive_required']:
            value['enabled']=False
            value['blockers_zh'].append('全部原件超过即时打包容量；请使用本修订完整包下载，保留全部证据。'
                                       if presentation else '全部原件超过512MiB内存ZIP预算，请沿原附件逐件下载。')
        query={'expected_input_key':value['input_key']}
        if presentation:query.update(revision_id=presentation['record']['revision_id'],
                                     expected_revision_sha256=presentation['record']['file']['sha256'])
        if presentation:
            value['archive_url']=f'/api/v1/studies/{sid}/runs/{rid}/rescue-presentations/{presentation["record"]["revision_id"]}/acceptance-archives?'+urlencode({
                'expected_revision_sha256':presentation['record']['file']['sha256'],'expected_input_key':value['input_key']})
        value['download_url']=f'/api/v1/studies/{sid}/runs/{rid}/acceptance.zip?'+urlencode(query)
        return value
    except (ContractError,KeyError,ValueError,TypeError,OSError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','验收资料原件无法完整核验：'+str(error)) from error


def download(app,req,sid,rid):
    """每个ZIP成员由实际核验字节写入内存；manifest与成员SHA对应，不复制未登记残件。"""
    try:
        presentation=_presentation(app,req,sid,rid,download=True)
        bundle=presentation['bundle'] if presentation else _load(app,sid,rid)
        w,manifest,home,run,result,packet=bundle;poses={}
        if req.query1('expected_input_key')!=packet['summary']['input_key']:
            raise ApiError(409,'STALE_VERSION','验收资料输入已改变，请刷新')
        members={};inventory=[]
        def add(name,raw,role,registrations=None):
            require(name not in members,'验收资料包成员重复')
            members[name]=raw;inventory.append({'path':name,'bytes':len(raw),'sha256':sha256(raw).hexdigest(),'role':role})
            if registrations is not None:inventory[-1]['registrations']=deepcopy(registrations)
        # 复用既有结果登记，历史原件照实保留；不运行生成器或科学工具。
        plan=member_plan(result,presentation)
        registered,extra=plan['registered'],plan['extra']
        total=plan['registered_bytes']
        require(total<=MAX_REGISTERED_BYTES,'资料包超过512MiB，请按既有附件逐件导出；未触发重算')
        # 先核组合原件预算，再核姿势；只缓存ZIP实际使用的MODEL1/context，不留全模式source。
        value=_assess_presentation(bundle,presentation,poses) if presentation else assess(bundle)
        if not value['enabled']:raise ApiError(409,'GATE_BLOCKED','；'.join(value['blockers_zh']))
        for group in registered:
            ref=group['record']
            add('registered/'+ref['path'],checked_bytes(home,ref,result['files']),ref.get('role','registered'),group['registrations'])
        if presentation:
            from ..core import rescue_presentations as revised_core
            for group in extra:
                ref=group['record'];path=revised_core._verify(w,sid,ref);raw=path.read_bytes()
                require(len(raw)==ref['bytes'] and sha256(raw).hexdigest()==ref['sha256'],'修订资料整理期间原件变化')
                add('presentation/'+ref['path'],raw,ref.get('role','presentation'),group['registrations'])
        for index,pair in enumerate(packet['pairs'],1):
            if pair.get('execution') and pair['state']=='completed':
                if presentation:artifacts=poses[index]
                else:artifacts,_,context=_artifacts(bundle,pair)
                for kind in ('top1','context'):
                    raw,name,_=artifacts[kind];add(f'poses/pair_{index:06d}/{name}',raw,kind)
        add('目录说明.txt',('本资料包来自已登记运行 '+rid+'\nregistered/：原矩阵、图表、来源、参数、失败与执行原件。\n'
            'poses/：按固定组合顺序提取的MODEL 1原字节及实际来源说明；未生成新坐标。\n'
            '验收目录与指纹.json：每个成员的长度、SHA及原运行绑定；同路径同指纹原件只存一份，registrations保留全部原登记关系。\n'
            '技术核验不代表严格质控、人工科研验收或真实整批计算已完成。\n').encode('utf-8'),'readme')
        metadata={'schema_version':value['schema_version'],'study_id':sid,'run_id':rid,'input_key':value['input_key'],
                  'configuration':run['config'],'inputs':run['inputs'],'summary':result['summary'],
                  'files':deepcopy(inventory),'translation_missing_ids':[],'scientific_computation_performed':False,
                  'registered_reference_count':len(result['files']),'registered_unique_file_count':len(registered),
                  'human_review_written':False,'inventory_self_hash_excluded':True,'note_zh':value['note_zh']}
        if presentation:
            metadata['presentation_revision']=deepcopy(value['presentation_revision'])
            metadata['presentation_files']=presentation_files(plan)
        add('验收目录与指纹.json',json.dumps(metadata,ensure_ascii=False,indent=2).encode('utf-8'),'inventory')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in members.items():archive.writestr(name,raw)
        require(fingerprint(w.load(sid))==fingerprint(manifest),'导出期间研究登记已改变，请刷新')
        return ('verified_download',output.getvalue(),rid+'_验收资料.zip','application/zip',False)
    except (ContractError,KeyError,ValueError,TypeError,OSError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','验收资料下载核验失败：'+str(error)) from error
