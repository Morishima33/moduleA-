"""系统授权三库获取的原件核验与完整/失败事实；不发布科学A01或改旧上传关口。"""
from copy import deepcopy
from pathlib import Path
import tempfile
from contracts import fingerprint,require
from storage import file_record,new_id,now,read_json,verified_file,write_json
from . import uploads,plan_acquisition
from .plan_screening import screening_parameters

VERSION='A01.system_acquisition.1'


def validate_source(home,row,request,plan,herbs):
    """临时目录重验原ZIP与既有解析规则，不在归档目录改写派生元数据。"""
    db=row['database'];source=row['source'];require(db in uploads.DATABASES and source['database']==db and source['format']=='source_zip',
        '获取来源数据库或格式不同')
    require(isinstance(source.get('version'),str) and source['version'].strip().casefold() not in ('','unknown','未知','未注明'),
        '来源版本未明确，不能采用原件')
    context=source.get('analysis_plan_source');parameters=screening_parameters(plan)
    if context is not None:
        expected={key:context[key] for key in ('schema_version','binding','database','herbs','screening_parameters')}
        require(context['binding_hash']==fingerprint(expected) and context['binding']['study_id']==request['study_id']
            and context['binding']['a00_run']==request['binding']['a00'] and context['database']==db and context['herbs']==herbs,
            '自动获取原件不是当前研究/登记/药味的固定请求')
    if row['mode']=='downloaded':
        require(source['version']==plan_acquisition.VERSION and context is not None
            and context['schema_version']==plan_acquisition.VERSION
            and context['binding']['a01_run']==request['binding']['a01'],'新自动获取缺少实际采集协议或原A01绑定')
    automatic_herb=db=='HERB' and context is not None
    if automatic_herb:
        from .acquisition import HERB_API
        require(source['source_url']==HERB_API,'自动HERB来源不是既有固定接口')
    raw=verified_file(home,row['archive']).read_bytes()
    with tempfile.TemporaryDirectory(prefix='system_source_verify_') as temp:
        folder=Path(temp);uploads.unpack(raw,folder,max_compressed=(64 if automatic_herb else 16)*1024*1024)
        uploads.validate_package(folder,db,herbs);meta=read_json(folder/'modulea_source.json')
        if db=='TCMSP':
            collected=meta.get('screening_parameters')
            if collected is not None:require(collected==parameters,'TCMSP采集门槛与当前方案不一致')
            elif str(source.get('version','')).startswith('A01.acquisition.'):
                require(parameters=={'ob_min':30,'dl_min':.18},'旧默认来源不适用于新TCMSP门槛')
            if context is not None:require(context.get('screening_parameters')==parameters and collected==parameters,
                'TCMSP获取原件与方案筛选参数不同')
    return True


def existing_slots(workflow,m,request,plan,herbs):
    """已有原件逐件核验，参数不同只视为待补取，损坏绑定不能以重下掩盖。"""
    ref=request['binding']['staging_file'];home=workflow.location(m['study_id'])
    if ref is None:return {}
    value=read_json(verified_file(home,ref))
    if value['a00_run_id']!=request['binding']['a00']:return {}
    require(value['study_id']==m['study_id'] and value['herbs']==herbs,'已有三库清单的研究或药味不同')
    require(len({s['database'] for s in value['datasets']})==len(value['datasets']),'已有三库清单重复')
    rows={};requested=screening_parameters(plan)
    for source in value['datasets']:
        require(source['database'] in uploads.DATABASES,'已有三库含未知数据库')
        verified_file(home,source['source_record'])
        for ref in source['files']:verified_file(home,ref)
        directory=(home/source['folder']).resolve();require(directory.is_relative_to(home.resolve()),'原件目录越界')
        meta=read_json(directory/'modulea_source.json')
        # 与既有plan_flow门槛完全一致，不把另一门槛采集结果冒充本批。
        if source['database']=='TCMSP':
            collected=meta.get('screening_parameters')
            if collected is not None and collected!=requested:continue
            if collected is None and str(source.get('version','')).startswith('A01.acquisition.') and requested!={'ob_min':30,'dl_min':.18}:continue
        row={'database':source['database'],'state':'ready','mode':'existing','source':deepcopy(source),
            'archive':deepcopy(source['source_record']),'reason_zh':'复用本研究同登记、同方案适用的已归档原件'}
        validate_source(home,row,request,plan,herbs);rows[source['database']]=row
    return rows


def source_herbs(workflow,m,request):
    """只使用已确认登记的实际药味，不读取后来另存的草稿。"""
    from components import parse_herbs
    return parse_herbs(workflow.result(m,request['binding']['a00'])['summary']['herbs'])


def collect(workflow,m,request,request_ref,plan_record,previous,progress,opener,sleeper,source_ready):
    """逐库原件先保存再校验；单库失败保留成功库，不写三库当前清单或科学运行。"""
    from modulea.core.system_acquisition import require_current
    sid=m['study_id'];home=workflow.location(sid);plan=plan_record['plan']
    herbs=source_herbs(workflow,m,request);folder=home/'raw/A01_system_acquisition'/request['request']['request_id']
    rows=existing_slots(workflow,m,request,plan,herbs);saved={r['database']:r for r in previous['sources'] if r['state']=='ready'} if previous else {}
    output=[]
    for db in uploads.DATABASES:
        require_current(workflow,workflow.load(sid),request)
        if db in rows:output.append(rows[db]);continue
        if db in saved:
            validate_source(home,saved[db],request,plan,herbs);output.append(deepcopy(saved[db]));continue
        try:
            progress('获取本研究 '+db+' 官方原件')
            binding={'study_id':sid,'a00_run':request['binding']['a00'],'a01_run':request['binding']['a01']}
            source=plan_acquisition.acquire_for_plan(db,herbs,folder/'collector_cache',binding,plan,
                progress=progress,opener=opener,sleeper=sleeper)
            location=folder/'responses'/new_id('source');location.mkdir(parents=True,exist_ok=False)
            archive=location/'original.zip';archive.write_bytes(source['data'])
            metadata={key:deepcopy(value) for key,value in source.items() if key!='data'};write_json(location/'source.json',metadata)
            row={'database':db,'state':'ready','mode':'downloaded','source':metadata,'archive':file_record(home,archive,'acquired_source_zip'),
                'reason_zh':'实际采集包按原ZIP安全、药味、完整性和当前门槛规则核验；未发布A01'}
            validate_source(home,row,request,plan,herbs);source_ready(row);output.append(row)
        except Exception as error:
            output.append({'database':db,'state':'failed','mode':'downloaded','error_type':type(error).__name__,
                'reason_zh':str(error),'source':None,'archive':None})
    implementations=[]
    for path in (Path(__file__),Path(plan_acquisition.__file__),Path(uploads.__file__)):
        destination=folder/'implementations'/new_id('implementation')/path.name;destination.parent.mkdir(parents=True,exist_ok=False)
        destination.write_bytes(path.read_bytes());implementations.append(file_record(home,destination,'system_acquisition_implementation'))
    files=[file_record(home,p,'system_acquisition_evidence') for p in folder.rglob('*') if p.is_file()]
    return {'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'plan_file':request['plan_file'],
        'analysis_parameter_hash':plan['parameter_hash'],'herbs':herbs,'sources':output,'files':files,'implementation_files':implementations,
        'state':'complete' if all(r['state']=='ready' for r in output) else 'partial_failure','human_review_written':False,
        'a01_published':False,'current_sources_changed':False,'created_at':now(),
        'message_zh':'三库原件已核验归档，尚未绑定科学发布' if all(r['state']=='ready' for r in output) else '部分来源获取失败；成功原件和失败诊断保留，不是零结果'}


def validate_record(home,request,result):
    """独立从实际ZIP和当前绑定方案复核，不信任客户端或调用方通过标记。"""
    require(result['schema_version']==VERSION and result['study_id']==request['study_id'] and result['human_review_written'] is False
        and result['a01_published'] is False and result['current_sources_changed'] is False,'来源获取不能伪装科学发布或人工批准')
    actual=read_json(verified_file(home,result['request_file']));plan=read_json(verified_file(home,result['plan_file']))
    require(fingerprint(actual)==fingerprint(request) and result['plan_file']==request['plan_file']
        and plan['plan_id']==request['request']['expected_plan_id'] and result['analysis_parameter_hash']==plan['plan']['parameter_hash'],
        '原件获取请求或方案与实际记录不同')
    from components import parse_herbs
    intake=read_json(verified_file(home,request['binding']['a00_files']['result_file']))['summary']
    require(result['herbs']==parse_herbs(intake['herbs']) and [r['database'] for r in result['sources']]==list(uploads.DATABASES),
        '来源获取药味或三库完整顺序不同')
    for ref in result['files']+result['implementation_files']:verified_file(home,ref)
    receipts=[read_json(verified_file(home,ref)) for ref in result['source_receipts']]
    for receipt in receipts:
        require(receipt['schema_version']==VERSION and receipt['request_file']==result['request_file']
            and receipt['plan_file']==result['plan_file'] and receipt['human_review_written'] is False
            and receipt['a01_published'] is False and receipt['source'] in result['sources'],
            '逐库恢复记录与本批实际来源不同')
    for row in result['sources']:
        if row['state']=='ready':
            validate_source(home,row,request,plan['plan'],result['herbs'])
            if row['mode']=='downloaded':require(any(r['source']==row for r in receipts),'成功原件缺少实际逐库恢复记录')
        else:require(row['state']=='failed' and row['archive'] is None and row['error_type'] and row['reason_zh'],'失败原件不能伪成功或空结果')
    require(result['state']==('complete' if all(r['state']=='ready' for r in result['sources']) else 'partial_failure'),
        '来源总体状态与逐库实际结果不同')
