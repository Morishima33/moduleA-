"""单研究流程测试的未知数据库版本例外；精确绑定旧原件，不伪造版本或科研复核。"""
from copy import deepcopy
from pathlib import Path
from contracts import SCHEMA_VERSION, ContractError, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from . import system_disease_acquisition as acquisition, system_execution as execution

VERSION = 'A02.historical_sources.1'
COLLECTION = 'A02.historical_collection.1'
INDEX = 'analysis_plan_historical_disease_sources'
FIELDS = {'request_id','expected_a00','expected_plan_id','expected_input_hash','expected_source_hashes','author','note','user_decision','confirmed'}
UNKNOWN = ('','unknown','未知','未注明')
NOTICE = '仅限本项流程测试：GeneCards、OMIM历史原件的数据库发布版本未知；保留原日期和指纹，不代表五库版本完整、完整检索或正式科研结论。'


def context(w,m,plan_ref=None):
    """只读本登记、明确方案和当前两份原件及同登记三项成功获取，不扫描其他研究。"""
    from intake_sources import current,identity
    sid=m['study_id'];home=w.location(sid);a00=m['current'].get('A00')
    require(a00 and m.get('workflow_profile')=='A00.preupload.2','仅支持新版研究登记的历史原件例外')
    summary=w.result(m,a00)['summary'];require(summary.get('analysis_purpose')=='workflow_test','历史版本例外仅限流程测试，正式研究禁止使用')
    plan_ref=plan_ref or (m.get('analysis_plan_records') or [None])[-1];require(plan_ref,'请先保存分析方案')
    plan=read_json(verified_file(home,plan_ref))
    require(plan_ref in m['analysis_plan_records'] and plan['study_id']==sid and plan['expected_a00']==a00,'例外方案与当前登记不同')
    staged=current(w,m);require(staged and staged['study_id']==sid and staged['a00_run_id']==a00
        and staged['identity_hash']==identity(summary),'请先提供本登记的GeneCards和OMIM原件')
    slots=[]
    for db in acquisition.DATABASES:
        if db in ('GeneCards','OMIM'):
            choices=[row for row in staged['datasets'] if row['database']==db];require(len(choices)==1,'历史手动原件缺失或重复：'+db)
            source=deepcopy(choices[0]);require(str(source.get('version','')).casefold() in UNKNOWN,'此入口仅处理明确未知发布版本的历史原件：'+db)
            verified_file(home,source['source_record'])
            slots.append({'database':db,'source':source,'archive':deepcopy(source['source_record']),'manual':True})
        else:
            found=None
            for ref in reversed(m.get(acquisition.SOURCES,[])):
                value=acquisition.read_record(w,m,ref,kind='source');request=acquisition.read_record(w,m,value['request_file'],kind='request')
                if value['source']['database']==db and request['request']['expected_a00']==a00:
                    found=(ref,value);break
            require(found,'请先成功获取本登记的'+db+'原件；缺失不作为0条')
            ref,value=found;source=value['source'];require(str(source['source']['version']).casefold() not in UNKNOWN,'公共来源版本仍须完整：'+db)
            slots.append({'database':db,'source':deepcopy(source['source']),'archive':deepcopy(source['archive']),
                'manual':False,'source_receipt':deepcopy(ref)})
    return {'study_id':sid,'a00_run_id':a00,'a00_files':deepcopy(m['runs'][a00]),'plan_file':deepcopy(plan_ref),
        'plan_id':plan['plan_id'],'staging_file':deepcopy(m['current_source_staging']),'sources':slots}


def guard(w,m):
    """例外不覆盖回收站或登记、疾病侧明确人工暂停/退回。"""
    require(not m.get('trashed'),'回收站研究只读')
    for key in ('A00','A02'):
        rid=m['current'].get(key);review=w.latest_review(m,w.run(m,rid)['artifact_id']) if rid else None
        require(not review or review['decision']=='approved',key+'已有明确人工暂存或退回，不能使用版本例外')


def read_record(w,m,ref):
    """标准库核对历史批准范围与每份原件，不要求历史指针仍为当前。"""
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref));binding=value['binding'];body=value['request']
    require(ref in m.get(INDEX,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']==binding['study_id']
        and value['human_review_written'] is False and value['database_versions_rewritten'] is False
        and value['authority_kind']=='explicit_user_source_version_exception','历史版本例外归属或协议错误')
    require(body['confirmed'] is True and value['request_hash']==fingerprint(body) and body['expected_input_hash']==fingerprint(binding)
        and body['expected_a00']==binding['a00_run_id'] and body['expected_plan_id']==binding['plan_id']
        and body['user_decision'].strip(),'历史版本例外与用户明确决定不同')
    plan=read_json(verified_file(home,binding['plan_file']));summary=read_json(verified_file(home,binding['a00_files']['result_file']))['summary']
    require(plan['study_id']==m['study_id'] and plan['plan_id']==binding['plan_id'] and plan['expected_a00']==binding['a00_run_id']
        and binding['a00_files']==m['runs'][binding['a00_run_id']] and summary['analysis_purpose']=='workflow_test','例外不属于原流程测试登记或方案')
    staged=read_json(verified_file(home,binding['staging_file']));require(staged['study_id']==m['study_id'] and staged['a00_run_id']==binding['a00_run_id'],'例外原件暂存归属不同')
    require([r['database'] for r in binding['sources']]==list(acquisition.DATABASES),'历史例外不能缺库或放宽其他库')
    hashes={}
    for row in binding['sources']:
        verified_file(home,row['archive'])
        if row['manual']:
            require(row['database'] in ('GeneCards','OMIM') and row['source'] in staged['datasets']
                and row['source']['source_record']==row['archive'] and str(row['source']['version']).casefold() in UNKNOWN,'例外改变了原手动文件或版本')
            hashes[row['database']]=row['archive']['sha256']
        else:
            source=acquisition.read_record(w,m,row['source_receipt'],kind='source')
            request=acquisition.read_record(w,m,source['request_file'],kind='request')
            require(request['request']['expected_a00']==binding['a00_run_id'] and row['source']==source['source']['source']
                and row['archive']==source['source']['archive'] and row['database']==source['source']['database']
                and str(row['source']['version']).casefold() not in UNKNOWN,'公共原件不是同登记已成功且有版本的真实来源')
    require(hashes==body['expected_source_hashes'] and set(hashes)=={'GeneCards','OMIM'} and value['notice_zh']==NOTICE,
        '例外必须只绑定两份明确原件并保留版本限制')
    return value


def info(w,sid):
    """只读当前可用原件和明确例外，不解析或联网。"""
    m=w.load(sid);blockers=[];binding=None
    try:
        guard(w,m);binding=context(w,m)
        if m['current'].get('A02'):blockers.append('本登记已有疾病结果；此入口仅用于首次历史原件候选，后续沿原来源链复用')
    except ContractError as error:blockers.append(str(error))
    return {'schema_version':VERSION,'supported':m.get('workflow_profile')=='A00.preupload.2','enabled':binding is not None and not blockers,
        'blockers':blockers,'expected_a00':binding['a00_run_id'] if binding else None,'expected_plan_id':binding['plan_id'] if binding else None,
        'expected_input_hash':fingerprint(binding) if binding else None,'expected_source_hashes':{r['database']:r['archive']['sha256'] for r in binding['sources'] if r['manual']} if binding else {},
        'sources':binding['sources'] if binding else [],'records':[dict(read_record(w,m,r),file=deepcopy(r)) for r in m.get(INDEX,[])],
        'notice_zh':NOTICE}


def validate_request(w,sid,body):
    """严格限定确认、原件指纹和真实用户决定；不接受版本覆盖、地址或名单。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'历史版本例外字段错误，不接受版本、路径、URL或通过标记')
    safe_id(body['request_id'],'historicaldiseaseq');safe_id(body['expected_a00'],'run');safe_id(body['expected_plan_id'],'plan')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note','user_decision')),
        '请记录用户明确决定、登记人及说明并主动确认')
    m=w.load(sid);guard(w,m)
    for ref in m.get(INDEX,[]):
        value=read_record(w,m,ref)
        if value['request']['request_id']==body['request_id']:
            require(value['request']==body and context(w,m,value['binding']['plan_file'])==value['binding'],'例外请求或原件已改变，请刷新')
            return deepcopy(body)
    value=info(w,sid);require(value['enabled'],'历史版本例外条件未齐：'+'；'.join(value['blockers']))
    require(all(body[k]==value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash','expected_source_hashes')),'历史原件、方案或登记已改变，请刷新')
    return deepcopy(body)


def require_current(w,m,value):
    """已保存例外只供原登记原方案原文件使用，不外推到新草稿或正式用途。"""
    guard(w,m);binding=value['binding']
    require(context(w,m,binding['plan_file'])==binding,
        '历史版本例外的登记、方案或原件已改变，请刷新后重新决定')


def publish(w,sid,body):
    """记录用户真实例外后由生产规范整理候选；不批准身份或运行下游。"""
    validate_request(w,sid,body);m=w.load(sid);home=w.location(sid)
    for rid in m['runs']:
        run=w.run(m,rid)
        if run['config'].get('version')==COLLECTION and run['inputs']['publication_request']['request_id']==body['request_id']:
            require(m['current'].get('A02')==rid,'原历史候选已由新结果替换，请沿当前来源核对');return w.result(m,rid)
    binding=context(w,m);execution.ensure_parents(w,sid,{'A00':binding['a00_run_id']})
    with write_lock(w.root):
        validate_request(w,sid,body);m=w.load(sid)
        existing=next((ref for ref in m.get(INDEX,[]) if read_record(w,m,ref)['request']['request_id']==body['request_id']),None)
        if existing:ref=existing;value=read_record(w,m,ref)
        else:
            value={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),'binding':binding,
                'authority_kind':'explicit_user_source_version_exception','human_review_written':False,'database_versions_rewritten':False,'notice_zh':NOTICE,'created_at':now()}
            path=home/'decisions/analysis_plans/historical_disease_sources'/body['request_id']/'exception.json'
            if path.exists():
                saved=read_json(path)
                require(saved.get('request')==body and saved.get('binding')==binding,'未完成例外请求与当前内容不同，不能覆盖历史')
                value=saved
            else:write_json(path,value)
            ref=file_record(home,path,'historical_disease_source_exception');m.setdefault(INDEX,[]).append(ref)
            read_record(w,m,ref);w.save(m)
    from science_modules.a02.historical_collection import facts,configuration,source_manifest
    folder=home/'raw/A02_historical_collection'/new_id('publication');path=folder/'disease_sources.json'
    source=source_manifest(w,m,ref);write_json(path,source);source_ref=file_record(home,path,'source_manifest')
    implementation_files=[];science_root=Path(__file__).resolve().parents[2]
    for implementation in (Path(__file__),science_root/'science_modules/a02/historical_collection.py',
            science_root/'science_modules/a02/system_normalization_historical.py',science_root/'disease.py',science_root/'disease_io.py',science_root/'source_identity.py'):
        saved=folder/'implementation'/implementation.name;saved.parent.mkdir(parents=True,exist_ok=True)
        with saved.open('xb') as stream:stream.write(implementation.read_bytes())
        implementation_files.append(file_record(home,saved,'historical_disease_implementation'))
    inputs={'study_id':sid,'historical_exception':deepcopy(ref),'publication_request':deepcopy(body),'analysis_plan_file':deepcopy(binding['plan_file']),
        'intake_result':deepcopy(binding['a00_files']['result_file']),'source_manifest':source_ref,'implementation_files':implementation_files}
    summary,tables,anomalies=facts(home,inputs);parents={'A00':binding['a00_run_id']};proofs=execution.parent_records(w,w.load(sid),parents)
    with write_lock(w.root):
        m=w.load(sid);require_current(w,m,value);require(not m['current'].get('A02'),'疾病候选已改变，请刷新')
        require(proofs==execution.parent_records(w,m,parents),'登记核验已改变，请刷新')
        rid=new_id('run');config=configuration();artifacts=[w.run(m,parents['A00'])['artifact_id']]
        run={'schema_version':SCHEMA_VERSION,'study_id':sid,'module_id':'A02','run_id':rid,'artifact_id':new_id('artifact'),'parent_runs':parents,
            'parent_artifact_ids':artifacts,'parent_review_ids':{},'parent_validation_records':proofs,'execution_protocol':COLLECTION,
            'execution_authority':'system_validation','inputs':inputs,'config':config,'config_hash':fingerprint(config),
            'input_hash':fingerprint({'inputs':inputs,'parents':artifacts}),'reason':'本研究明确历史版本例外，仅流程测试候选，未批准结果',
            'code_version':w.code_version,'environment_version':fingerprint(w.environment),'environment':deepcopy(w.environment),'created_at':now()}
        run_path=home/'runs/A02'/rid/'run.json';write_json(run_path,run)
        m['runs'][rid]={'run_file':file_record(home,run_path,'run'),'result_file':None};m['current']['A02']=rid
        from .system_validation import canonical_validator
        outcome='success' if tables['candidate_records'] else 'empty';canonical_validator(w.root,'A02')(run,summary,tables,anomalies,outcome)
        result=w._finish(m,rid,summary,tables,anomalies,outcome,sources=[ref,source_ref,binding['plan_file'],inputs['intake_result'],*proofs.values(),*[r['archive'] for r in binding['sources']],*implementation_files])
        w.save(m);return result


def is_active(w,m,run):
    """只认可原例外与真实登记系统证据；仍不授予候选交接资格。"""
    try:
        require(run['module_id']=='A02' and run['execution_protocol']==COLLECTION and run['config']['version']==COLLECTION
            and m['current'].get('A02')==run['run_id'] and run['parent_review_ids']=={} and run['execution_authority']=='system_validation','历史候选协议不正确')
        value=read_record(w,m,run['inputs']['historical_exception']);require_current(w,m,value)
        require(run['parent_runs']=={'A00':value['binding']['a00_run_id']} and run['parent_validation_records']==execution.parent_records(w,m,run['parent_runs'])
            and run['inputs']['publication_request']==value['request'] and run['config_hash']==fingerprint(run['config'])
            and run['parent_artifact_ids']==[w.run(m,value['binding']['a00_run_id'])['artifact_id']]
            and run['input_hash']==fingerprint({'inputs':run['inputs'],'parents':run['parent_artifact_ids']}),'历史候选原依赖或指纹不同')
        return True
    except ContractError:return False
