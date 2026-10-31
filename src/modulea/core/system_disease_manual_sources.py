"""新方案未批准登记的疾病原件预上传：标准库资格与公开Workflow原子回执。"""
from copy import deepcopy
import hashlib
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json

VERSION='A02.system_manual_source.1'
INDEX='analysis_plan_system_manual_source_records'
FIELDS={'request_id','expected_a00','expected_plan_id','expected_input_hash','author','note','confirmed','source'}
SOURCE_FIELDS={'database','format','query','retrieved_at','version','encoding','name','query_quoted','export_completeness'}
FORMATS={'GeneCards':('genecards_csv','detailed_txt','tsv'),'OMIM':('omim_xlsx_v2','omim','tsv')}
MAX_BYTES=16*1024*1024


def snapshot(w,m,plan_ref):
    """固定实际登记、原方案与暂存状态；不把科学批准字段混入上传确认。"""
    rid=m['current']['A00'];artifact=w.run(m,rid)['artifact_id'];home=w.location(m['study_id'])
    return {'study_id':m['study_id'],'a00':rid,'a00_files':deepcopy(m['runs'][rid]),'plan_file':deepcopy(plan_ref),
        'staging_file':deepcopy(m.get('current_source_staging')),'trashed':bool(m.get('trashed')),
        'reviews':[deepcopy(ref) for ref in m.get('reviews',[]) if read_json(verified_file(home,ref))['artifact_id']==artifact]}


def info(w,sid):
    """只核验已登记文件和元信息；未解析的原件不显示成正式基因数量。"""
    from . import system_disease_acquisition as acquisition
    from intake_sources import current,identity
    base=acquisition.info(w,sid);m=w.load(sid);rid=m['current'].get('A00');blockers=list(base['blockers'])
    plans=w._analysis_plan_records(m) if base['supported'] else [];plan_ref=None
    if plans and plans[-1]['expected_a00']==rid:plan_ref=m['analysis_plan_records'][-1]
    summary=w.result(m,rid)['summary'] if rid else {};staged=current(w,m);sources=[]
    if rid and w.approved(m,rid):blockers.append('登记已人工复核通过，请使用原A02来源上传入口')
    if staged:
        require(staged['study_id']==sid and staged['version'] in ('A00.preupload.1','A00.preupload.2'),'手动原件暂存归属或版本错误')
        if staged['a00_run_id']==rid and staged['identity_hash']==identity(summary):
            for row in staged['datasets']:
                verified_file(w.location(sid),row['source_record'])
                if row['database'] in FORMATS:
                    source={k:deepcopy(row.get(k)) for k in ('database','name','query','retrieved_at','version','format','bytes','sha256','source_record')}
                    source['status_zh']='已预上传；版本待核' if str(row.get('version','')).casefold() in ('','unknown','未知','未注明') else '已预上传，待明确核验五库'
                    sources.append(source)
    return {'schema_version':VERSION,'supported':base['supported'],'enabled':not blockers,'blockers':blockers,
        'expected_a00':rid,'expected_plan_id':base['expected_plan_id'],
        'expected_input_hash':fingerprint(snapshot(w,m,plan_ref)) if rid and plan_ref else None,
        'disease_identity_zh':summary.get('mesh_verification',{}).get('preferred_term',''),
        'sources':sources,'formats':deepcopy(FORMATS),'message_zh':'上传只保存本研究原件，不批准登记或生成疾病候选；补齐后请明确核验五库。'}


def read_record(w,m,ref):
    """回执必须对应本研究实际暂存、原始文件、明确请求和真实登记核验。"""
    from . import system_validation
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref));body=value['request']
    require(ref in m.get(INDEX,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']
        and value['human_review_written'] is False and value['a02_published'] is False,'手动原件回执未登记或归属错误')
    require(value['request_hash']==fingerprint(body) and body['confirmed'] is True
        and value['binding']['a00']==body['expected_a00'] and value['binding']['study_id']==m['study_id']
        and body['expected_input_hash']==fingerprint(value['binding']),'手动原件回执不同于原明确确认')
    require(value['binding']['plan_file'] in m.get('analysis_plan_records',[]),'手动原件方案未登记')
    plan=read_json(verified_file(home,value['binding']['plan_file']))
    require(plan['study_id']==m['study_id'] and plan['expected_a00']==body['expected_a00']
        and plan['plan_id']==body['expected_plan_id'],'手动原件方案与实际登记不同')
    require(value['staging_file'] in m.get('source_staging_versions',[]),'手动原件未进入真实暂存历史')
    staged=read_json(verified_file(home,value['staging_file']));rows=[r for r in staged['datasets'] if r['database']==body['source']['database']]
    from intake_sources import identity
    require(staged['identity_hash']==identity(w.result(m,body['expected_a00'])['summary']),
        '手动原件身份与原登记不同')
    require(staged['study_id']==m['study_id'] and staged['a00_run_id']==body['expected_a00'] and len(rows)==1
        and rows[0]['source_record']==value['source_file'] and rows[0]['sha256']==value['upload_sha256']
        and rows[0]['bytes']==value['upload_bytes'],'手动原件回执与实际字节或登记不同')
    require(all(rows[0].get(key)==body['source'][key] for key in SOURCE_FIELDS),'手动原件回执元信息与实际暂存不同')
    verified_file(home,value['source_file']);proof=system_validation.read_receipt(w,m,value['a00_validation'])
    require(proof['passed'] and proof['module_id']=='A00' and proof['run_id']==body['expected_a00'],'手动原件缺少真实登记核验')
    return value


def previous(w,m,body):
    """同请求不重复上传，也不能以原请求号恢复已被替换的旧库文件。"""
    for ref in m.get(INDEX,[]):
        value=read_record(w,m,ref)
        if value['request']['request_id']==body['request_id']:
            require(value['request']==body,'手动上传请求编号已用于其他内容')
            review=w.latest_review(m,w.run(m,body['expected_a00'])['artifact_id'])
            require(not review or review['decision']=='approved','登记已有明确人工暂存或退回，不能重交上传请求')
            from intake_sources import current
            staged=current(w,m);rows=[r for r in (staged or {}).get('datasets',[]) if r['database']==body['source']['database']]
            require(m['current'].get('A00')==body['expected_a00'] and staged and staged['a00_run_id']==body['expected_a00']
                and len(rows)==1 and rows[0]['source_record']==value['source_file'],'该原件已被替换或登记已改变，请刷新后确认')
            return dict(value,file=deepcopy(ref),created=False)
    return None


def validate_request(w,sid,body):
    """HTTP与科学worker共用严格资格校验；这里不解析文件或生成科学回执。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'手动原件请求字段错误，不接受路径、来源地址或通过覆盖')
    for key,prefix in (('request_id','manualsourceq'),('expected_a00','run'),('expected_plan_id','plan')):safe_id(body[key],prefix)
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
        '请填写上传登记人、说明并明确确认')
    source=body['source'];require(isinstance(source,dict) and set(source)==SOURCE_FIELDS,'手动原件元信息字段错误')
    require(all(isinstance(source[k],str) and 0<len(source[k].strip())<=2000 for k in SOURCE_FIELDS),'手动原件元信息缺失或过长')
    require(source['database'] in FORMATS and source['format'] in FORMATS[source['database']],'该库或格式不支持新登记预上传')
    require(source['query_quoted'] in ('yes','no','unknown') and source['export_completeness'] in ('complete','partial','unknown'),
        '检索引号或导出完整性状态无效')
    require(all(source[k]==source[k].strip() for k in SOURCE_FIELDS),'手动原件元信息请去除首尾空白')
    require(source['encoding'] in ('utf-8-sig','gbk') and '/' not in source['name'] and '\\' not in source['name'],
        '文件编码或原文件名不合法')
    m=w.load(sid);require(not m.get('trashed'),'回收站研究只读')
    old=previous(w,m,body)
    if old:return deepcopy(body)
    value=info(w,sid);require(value['enabled'],'手动原件上传条件未齐：'+'；'.join(value['blockers']))
    require(all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'手动原件或方案已改变，请刷新后确认')
    return deepcopy(body)


def stage(w,sid,body,data):
    """公开Workflow内部：冻结预上传器持原锁，原件与明确回执同次保存。"""
    validate_request(w,sid,body);require(isinstance(data,bytes) and 0<len(data)<=MAX_BYTES,'上传原件为空或超出16MiB边界')
    digest=hashlib.sha256(data).hexdigest();m=w.load(sid);old=previous(w,m,body)
    if old:
        require(old['upload_sha256']==digest and old['upload_bytes']==len(data),'手动上传请求编号已用于不同文件')
        return old
    from . import system_execution
    system_execution.ensure_parents(w,sid,{'A00':body['expected_a00']})
    m=w.load(sid);validate_request(w,sid,body);plan_ref=m['analysis_plan_records'][-1];binding=snapshot(w,m,plan_ref)
    proof=system_execution.parent_records(w,m,{'A00':body['expected_a00']})['A00']
    outcome={}
    def guard(latest):
        validate_request(w,sid,body)
        require(snapshot(w,latest,plan_ref)==binding,'上传期间登记、原件或人工意见已改变，请刷新')
    def publish(latest):
        staged_ref=latest['current_source_staging'];staged=read_json(verified_file(w.location(sid),staged_ref))
        source=next(r for r in staged['datasets'] if r['database']==body['source']['database'])
        require(source['sha256']==digest and source['bytes']==len(data),'实际暂存字节不同于本次上传')
        value={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
            'binding':binding,'a00_validation':proof,'staging_file':deepcopy(staged_ref),'source_file':deepcopy(source['source_record']),
            'upload_sha256':digest,'upload_bytes':len(data),'human_review_written':False,'a02_published':False,'created_at':now()}
        path=w.location(sid)/'decisions/analysis_plans/manual_sources'/(new_id('manualsource')+'.json');write_json(path,value)
        ref=file_record(w.location(sid),path,'system_disease_manual_source');latest.setdefault(INDEX,[]).append(ref)
        outcome.update(value,file=ref,created=True)
    from science_modules.a02.manual_staging import stage as stage_original
    stage_original(w,sid,body['expected_a00'],dict(body['source'],data=data),guard,publish)
    read_record(w,w.load(sid),outcome['file']);return outcome
