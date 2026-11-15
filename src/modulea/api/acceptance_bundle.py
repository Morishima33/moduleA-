"""只读验收资料包：核对本运行既有矩阵、图件、来源与构象，不隐式生成图表或Word。"""
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json
from pathlib import PurePosixPath
import re
import zipfile
import zlib

from contracts import fingerprint,require,ContractError
from .errors import ApiError
from .rescue_evidence import load_bundle,checked_bytes,_artifacts

ROLES={'plot_a06_rescue_full_png','plot_a06_rescue_full_svg','a06_rescue_matrix_csv','a06_rescue_display_view'}


def _png(raw):
    """检查已登记PNG各块CRC和尺寸，不在HTTP进程加载绘图依赖或重画。"""
    require(raw.startswith(b'\x89PNG\r\n\x1a\n'),'登记PNG格式错误')
    at=8;ended=False;size=None
    while at+12<=len(raw):
        count=int.from_bytes(raw[at:at+4],'big');tag=raw[at+4:at+8];chunk=raw[at+8:at+8+count]
        require(at+12+count<=len(raw) and zlib.crc32(tag+chunk)==int.from_bytes(raw[at+8+count:at+12+count],'big'),
                '登记PNG块长度或CRC错误')
        if tag==b'IHDR':size=[int.from_bytes(chunk[:4],'big'),int.from_bytes(chunk[4:8],'big')]
        at+=count+12
        if tag==b'IEND':ended=True;break
    require(ended and at==len(raw) and size and all(x>0 for x in size),'登记PNG缺少完整图像')
    return size


def assess(bundle):
    """缺译或附件未齐保留具体阻塞；不生成任何缺失图件来掩盖问题。"""
    workflow,manifest,home,run,result,packet=bundle
    from science_modules.a06 import system_rescue_display as first,system_rescue_display_v2 as second
    render=second if packet['schema_version']=='A06.system_rescue.2' else first
    view=render.build_view(packet);blockers=[]
    missing=[row['compound_id'] for row in packet['source_fixed']['compounds'] if not
             (row.get('name_zh','').strip() or re.search(r'[\u3400-\u9fff]',row.get('name','')))]
    unnamed=[row['target_id'] for row in packet['source_fixed']['receptors'] if not row.get('symbol','').strip()]
    if missing:blockers.append('缺少本批已核译中文成分名：'+'、'.join(missing))
    if unnamed:blockers.append('缺少本批实际受体名称：'+'、'.join(unnamed))
    prefix=f"runs/A06/{run['run_id']}/rescue/display/"
    exports={}
    for ref in result['files']:
        role=ref.get('role')
        if role in ROLES or role in ('plot_a06_rescue_focus_png','plot_a06_rescue_focus_svg'):
            if run['config']['version']=='A06.system_rescue.2' and not ref['path'].startswith(prefix):continue
            require(role not in exports,'本批展示附件角色重复')
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
    if req.query:raise ApiError(422,'VALIDATION_FAILED','验收资料资格不接受额外参数')
    try:
        value=assess(load_bundle(app,sid,rid))
        value['download_url']=f'/api/v1/studies/{sid}/runs/{rid}/acceptance.zip?expected_input_key='+value['input_key']
        return value
    except (ContractError,KeyError,ValueError,TypeError,OSError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','验收资料原件无法完整核验：'+str(error)) from error


def download(app,req,sid,rid):
    """每个ZIP成员由实际核验字节写入内存；manifest与成员SHA对应，不复制未登记残件。"""
    if set(req.query)!={'expected_input_key'} or any(len(v)!=1 for v in req.query.values()):
        raise ApiError(422,'VALIDATION_FAILED','验收资料下载字段错误')
    try:
        bundle=load_bundle(app,sid,rid);w,manifest,home,run,result,packet=bundle
        value=assess(bundle)
        if req.query1('expected_input_key')!=value['input_key']:
            raise ApiError(409,'STALE_VERSION','验收资料输入已改变，请刷新')
        if not value['enabled']:raise ApiError(409,'GATE_BLOCKED','；'.join(value['blockers_zh']))
        members={};inventory=[]
        def add(name,raw,role):
            require(name not in members,'验收资料包成员重复')
            members[name]=raw;inventory.append({'path':name,'bytes':len(raw),'sha256':sha256(raw).hexdigest(),'role':role})
        # 复用既有结果登记，历史原件照实保留；不运行生成器或科学工具。
        total=sum(ref.get('bytes',0) for ref in result['files'])
        require(total<=512*1024*1024,'资料包超过512MiB，请按既有附件逐件导出；未触发重算')
        for ref in result['files']:
            add('registered/'+ref['path'],checked_bytes(home,ref,result['files']),ref.get('role','registered'))
        for index,pair in enumerate(packet['pairs'],1):
            if pair.get('execution') and pair['state']=='completed':
                artifacts,_,context=_artifacts(bundle,pair)
                for kind in ('top1','context'):
                    raw,name,_=artifacts[kind];add(f'poses/pair_{index:06d}/{name}',raw,kind)
        add('目录说明.txt',('本资料包来自已登记运行 '+rid+'\nregistered/：原矩阵、图表、来源、参数、失败与执行原件。\n'
            'poses/：按固定组合顺序提取的MODEL 1原字节及实际来源说明；未生成新坐标。\n'
            '验收目录与指纹.json：每个成员的长度、SHA及原运行绑定。\n'
            '技术核验不代表严格质控、人工科研验收或真实整批计算已完成。\n').encode('utf-8'),'readme')
        metadata={'schema_version':value['schema_version'],'study_id':sid,'run_id':rid,'input_key':value['input_key'],
                  'configuration':run['config'],'inputs':run['inputs'],'summary':result['summary'],
                  'files':deepcopy(inventory),'translation_missing_ids':[],'scientific_computation_performed':False,
                  'human_review_written':False,'inventory_self_hash_excluded':True,'note_zh':value['note_zh']}
        add('验收目录与指纹.json',json.dumps(metadata,ensure_ascii=False,indent=2).encode('utf-8'),'inventory')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in members.items():archive.writestr(name,raw)
        require(fingerprint(w.load(sid))==fingerprint(manifest),'导出期间研究登记已改变，请刷新')
        return ('verified_download',output.getvalue(),rid+'_验收资料.zip','application/zip',False)
    except (ContractError,KeyError,ValueError,TypeError,OSError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','验收资料下载核验失败：'+str(error)) from error
