"""疾病五库原件获取：原采集器/身份/解析复用，缺失与失败独立留存而不发布候选。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require
from storage import file_record,new_id,now,read_json,verified_file,write_json
from disease import metadata,parse_source
from source_identity import validate_source_identity

VERSION='A02.system_acquisition.1'
DATABASES=('GeneCards','OMIM','TTD','PharmGKB','OTP')


def intake(home,request):
    """实际原登记与NLM身份来自已确认归档，不接收用户自拟查询词。"""
    rid=request['binding']['current']['A00']
    return read_json(verified_file(home,request['binding']['run_files'][rid]['result_file']))['summary']


def validate_source(home,row,request):
    """按既有解析及检索身份规则读取原文，不以来源存在或零行推断获取成功。"""
    require(row['state']=='ready' and row['database'] in DATABASES and row['mode'] in ('existing','downloaded'),
        '疾病原件来源状态无效')
    source=row['source'];require(source==metadata(source) and source['database']==row['database']
        and source['format']!='source_failure' and source['source_status']!='query_failed','失败或元数据异常不能当有效疾病来源')
    require(source['version'].casefold() not in ('','unknown','未知','未注明'),'疾病来源版本待核，不能采用原件')
    if row['mode']=='downloaded':require(row['database'] in ('TTD','PharmGKB','OTP'),'受限资料不能伪装自动获取')
    raw=verified_file(home,row['archive']).read_bytes();validate_source_identity(intake(home,request),source,raw)
    if row.get('reused_from_source'):
        origin=read_json(verified_file(home,row['reused_from_source']));old=origin['source']
        original_request=read_json(verified_file(home,origin['request_file']))
        require(origin['schema_version']==VERSION and origin['study_id']==request['study_id']
            and original_request['binding']['current']['A00']==request['binding']['current']['A00']
            and old['database']==row['database'] and old['source']==source and old['archive']==row['archive'],
            '疾病成功原件复用不是同研究同登记来源')
    rows=parse_source(source,raw)
    require(type(row['parsed_records']) is int and row['parsed_records']==len(rows),'疾病原件解析数量不同')
    return rows


def existing_sources(w,m,request):
    """当前五库原候选可复用，当前同登记预上传优先；不扫描其他研究或历史择优。"""
    from intake_sources import current,identity
    from modulea.core import system_disease_sources
    home=w.location(m['study_id']);slots={}
    if m['current'].get('A02'):
        resolved=system_disease_sources.resolve(w,m);base=w.result(m,resolved['base_run_id'])
        manifests=[r for r in base['sources'] if r['role']=='source_manifest'];require(len(manifests)==1,'疾病原候选来源清单不唯一')
        source=read_json(verified_file(home,manifests[0]))
        require(source['source_profile']['version']=='A02.source_profile.3','疾病原候选不是现代五库来源')
        for row in source['datasets']:
            if row.get('format')!='source_failure' and row.get('source_status')!='query_failed':slots[row['database']]=row
    staged=current(w,m)
    if staged and staged.get('a00_run_id')==m['current']['A00'] and staged.get('identity_hash')==identity(intake(home,request)):
        require(staged['study_id']==m['study_id'] and len({r['database'] for r in staged['datasets']})==len(staged['datasets']),
            '疾病预上传来源研究不同或同库重复')
        for row in staged['datasets']:slots[row['database']]=row
    require(set(slots)<=set(DATABASES),'疾病来源含不属于当前现代五库的资料')
    return slots


def fetch_source(database,summary):
    """复用原三项固定官方采集器和MeSH精确词规则，受限库仅使用已提供原件。"""
    import a02_auto_prepare as original
    if database=='OTP':return original._otp_source(summary)
    if database=='TTD':return original._ttd_source(summary)
    require(database=='PharmGKB','此库不能自动获取')
    terms=original._terms(summary)
    return original.fetch_pharmgkb(terms),{'terms':terms}


def collect(w,m,request,request_ref,recovered,source_ready,progress):
    """每库成功立即保存，原文先归档后解析；单库失败不撤销成功库或伪造零结果。"""
    from modulea.core.system_disease_acquisition import require_current
    sid=m['study_id'];home=w.location(sid);folder=home/'raw/A02_system_acquisition'/request['request']['request_id']
    existing=existing_sources(w,m,request);summary=intake(home,request);output=[]
    # 补上传受限资料后必须新确认，但同登记成功系统原文可独立验SHA后复用。
    reusable={}
    from modulea.core import system_disease_acquisition as core
    for ref in reversed(m.get(core.SOURCES,[])):
        previous=core.read_record(w,m,ref,kind='source');row=previous['source'];db=row['database']
        previous_request=core.read_record(w,m,previous['request_file'],kind='request')
        if db not in reusable and previous_request['binding']['current']['A00']==request['binding']['current']['A00']:
            reusable[db]=(ref,row)
    for db in DATABASES:
        require_current(w,w.load(sid),request)
        if db in recovered:
            validate_source(home,recovered[db],request);output.append(deepcopy(recovered[db]));continue
        if db not in existing and db in reusable:
            ref,old=reusable[db];row=dict(deepcopy(old),mode='existing',reused_from_source=deepcopy(ref),
                reason_zh='复用本研究同登记已成功获取的疾病原文；逐件指纹和原解析重新核验')
            validate_source(home,row,request);source_ready(row);output.append(row);continue
        if db not in existing and db in ('GeneCards','OMIM'):
            output.append({'database':db,'state':'missing','mode':'manual','source':None,'archive':None,
                'reason_zh':'尚未提供本研究'+db+'原始资料；受限资料未自动获取，不作为0条结果'});continue
        detail={};raw_ref=None
        try:
            if db in existing:
                source=metadata(existing[db]);raw_ref=deepcopy(existing[db]['source_record']);raw=verified_file(home,raw_ref).read_bytes();mode='existing'
            else:
                progress('获取本研究疾病来源 '+db)
                item,detail=fetch_source(db,summary);require(item['database']==db,'实际疾病采集器返回了其他数据库')
                location=folder/'responses'/new_id('source');location.mkdir(parents=True,exist_ok=False)
                raw=location/'original.bin';raw.write_bytes(item['data']);raw_ref=file_record(home,raw,'disease_source_original')
                source=metadata(item);write_json(location/'source.json',source);raw=verified_file(home,raw_ref).read_bytes();mode='downloaded'
            rows=parse_source(source,raw)
            row={'database':db,'state':'ready','mode':mode,'source':source,'archive':raw_ref,'parsed_records':len(rows),
                'reason_zh':'本研究原件已按既有解析和检索身份规则核验；未发布疾病候选','diagnostic':detail}
            validate_source(home,row,request);source_ready(row);output.append(row)
        except Exception as error:
            location=folder/'failures'/new_id('sourcefailure')
            failure={'database':db,'error_type':type(error).__name__,'error_zh':str(error),'created_at':now(),'archive':raw_ref}
            if hasattr(error,'source_trace'):
                import a02_auto_prepare as original
                evidence=original._failure(db,error);path=location/'source_trace.json';path.parent.mkdir(parents=True,exist_ok=False);path.write_bytes(evidence['data'])
            write_json(location/'failure.json',failure)
            output.append({'database':db,'state':'failed','mode':'existing' if db in existing else 'downloaded','source':None,
                'archive':None,'reason_zh':str(error) or type(error).__name__,'error_type':type(error).__name__})
    implementations=[]
    import a02_auto_prepare,disease,source_identity
    for original in (Path(__file__),Path(a02_auto_prepare.__file__),Path(disease.__file__),Path(source_identity.__file__)):
        target=folder/'implementations'/new_id('implementation')/original.name;target.parent.mkdir(parents=True,exist_ok=False);target.write_bytes(original.read_bytes())
        implementations.append(file_record(home,target,'disease_acquisition_implementation'))
    plan=read_json(verified_file(home,request['plan_file']))
    return {'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'plan_file':request['plan_file'],
        'analysis_parameter_hash':plan['plan']['parameter_hash'],'sources':output,
        'files':[file_record(home,p,'disease_acquisition_evidence') for p in folder.rglob('*') if p.is_file()],
        'implementation_files':implementations,'state':'complete' if all(r['state']=='ready' for r in output) else 'incomplete',
        'human_review_written':False,'a02_published':False,'current_sources_changed':False,'created_at':now(),
        'message_zh':'五库原件已核验归档，尚未发布疾病候选' if all(r['state']=='ready' for r in output)
            else '五库原件未齐；缺失和失败分别保留，不作为0条结果'}


def validate_record(home,request,result):
    """完整解析原文和逐库恢复事实独立重核，不信任客户端或调用方通过标志。"""
    require(result['schema_version']==VERSION and result['study_id']==request['study_id'] and result['a02_published'] is False
        and result['human_review_written'] is False and result['current_sources_changed'] is False,'疾病获取不能伪发布或人工批准')
    require(read_json(verified_file(home,result['request_file']))==request and result['plan_file']==request['plan_file']
        and result['analysis_parameter_hash']==read_json(verified_file(home,result['plan_file']))['plan']['parameter_hash'],
        '疾病原件获取请求、方案或参数不同')
    require([r['database'] for r in result['sources']]==list(DATABASES),'疾病原件缺库或重复')
    receipts=[read_json(verified_file(home,ref)) for ref in result['source_receipts']]
    require(len({row['source']['database'] for row in receipts})==len(receipts),'疾病来源恢复记录同库重复')
    for row in receipts:require(row['request_file']==result['request_file'] and row['source'] in result['sources']
        and row['human_review_written'] is False and row['a02_published'] is False,'疾病逐库恢复记录与本批不同')
    for row in result['sources']:
        if row['state']=='ready':
            validate_source(home,row,request);require(any(saved['source']==row for saved in receipts),'疾病成功来源缺少实际检查点')
        else:require(row['state'] in ('missing','failed') and row['reason_zh'] and row['archive'] is None,'疾病缺失或失败不能伪成功')
    require(result['state']==('complete' if all(r['state']=='ready' for r in result['sources']) else 'incomplete'),'疾病获取总体状态不同')
    for ref in result['files']+result['implementation_files']:verified_file(home,ref)
