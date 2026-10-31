"""完整疾病原件的显式候选发布；采用真实A00系统证据，原人工批准语义保持。"""
from copy import deepcopy
from contracts import SCHEMA_VERSION,ContractError,fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_disease_acquisition as acquisition,system_execution as execution,system_validation as validation

VERSION='A02.system_collection.1'
FIELDS={'request_id','expected_acquisition_request_id','expected_record_sha256','expected_input_hash','author','note','confirmed'}


def acquisition_for(w,m,request_id):
    """只选指定请求最近的实际整批，不用较早成功掩盖较新失败。"""
    found=[]
    for ref in m.get(acquisition.RECORDS,[]):
        value=acquisition.read_record(w,m,ref,kind='record')
        request=acquisition.read_record(w,m,value['request_file'],kind='request')
        if request['request']['request_id']==request_id:found.append((ref,value,request))
    require(found,'本研究尚无该疾病获取整批记录');return found[-1]


def published(w,m,record_ref):
    """核对当前候选或其显式标准化祖先，不能扫描任意历史冒充已绑定。"""
    if not m['current'].get('A02'):return None
    from .system_disease_sources import resolve
    value=resolve(w,m);run=w.run(m,value['base_run_id'])
    return run if run['config'].get('version')==VERSION and run['inputs']['acquisition_record']==record_ref else None


def info(w,m,request_id):
    """标准库只读发布资格；完整原件与候选结果明确区分。"""
    ref,record,request=acquisition_for(w,m,request_id);blockers=[];bound=None
    try:bound=published(w,m,ref)
    except ContractError:pass
    if bound:blockers.append('本次疾病原件已发布候选，无需重复发布')
    if record['state']!='complete':blockers.append('疾病五库原件未齐，不能发布候选')
    if not bound:
        try:acquisition.require_current(w,m,request)
        except ContractError as error:blockers.append(str(error))
    plans=w._analysis_plan_records(m)
    if not plans or plans[-1]['plan_id']!=request['request']['expected_plan_id']:blockers.append('方案已改变，请按当前方案重新核验原件')
    if m.get('trashed'):blockers.append('回收站研究只读')
    return {'enabled':not blockers,'blockers':blockers,'published_run_id':bound['run_id'] if bound else None,'request':{
        'expected_acquisition_request_id':request_id,'expected_record_sha256':ref['sha256'],
        'expected_input_hash':fingerprint(acquisition.snapshot(w,m))}}


def validate_request(w,sid,body):
    """严格明确确认，拒绝客户端名单、路径、范围或通过标记。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'疾病候选发布字段错误，不接受名单、路径或通过覆盖')
    safe_id(body['request_id'],'diseasepublishreq');safe_id(body['expected_acquisition_request_id'],'diseaseacqreq')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
        '请填写疾病候选发布登记人和说明并明确确认')
    m=w.load(sid);require(not m.get('trashed'),'回收站研究只读')
    for rid in m['runs']:
        run=w.run(m,rid)
        if run['config'].get('version')==VERSION and run['inputs']['publication_request']['request_id']==body['request_id']:
            require(run['inputs']['publication_request']==body,'疾病发布请求号已用于其他内容')
            bound=published(w,m,run['inputs']['acquisition_record'])
            require(bound and bound['run_id']==rid,'疾病候选或登记、人工意见已改变，请刷新')
            execution.parent_records(w,m,run['parent_runs'])
            review=w.latest_review(m,run['artifact_id']);require(not review or review['decision']=='approved','疾病候选已有明确人工暂存或退回')
            return deepcopy(body)
    ref,record,request=acquisition_for(w,m,body['expected_acquisition_request_id'])
    value=info(w,m,body['expected_acquisition_request_id']);require(value['enabled'],'疾病候选发布条件未齐：'+'；'.join(value['blockers']))
    require(ref['sha256']==body['expected_record_sha256'] and body['expected_input_hash']==fingerprint(acquisition.snapshot(w,m)),
        '疾病获取记录或发布输入已改变，请刷新')
    return deepcopy(body)


def is_active(w,m,run):
    """仅新候选协议采用真实登记回执，不使原候选自动成为可交接集合。"""
    try:
        require(not m.get('trashed') and run['execution_protocol']==VERSION and run['module_id']=='A02'
            and run['config']['version']==VERSION and m['current'].get('A02')==run['run_id'],'疾病候选协议或当前版本错误')
        record=acquisition.read_record(w,m,run['inputs']['acquisition_record'],kind='record')
        request=acquisition.read_record(w,m,record['request_file'],kind='request');body=run['inputs']['publication_request']
        require(record['state']=='complete' and body['confirmed'] is True and body['expected_record_sha256']==run['inputs']['acquisition_record']['sha256']
            and body['expected_acquisition_request_id']==request['request']['request_id']
            and body['expected_input_hash']==fingerprint(request['binding']) and run['inputs']['analysis_plan_file']==record['plan_file'],
            '疾病候选不是明确确认的完整原件和原方案')
        require(run['parent_runs']=={'A00':request['request']['expected_a00']}
            and run['execution_authority']=='system_validation' and run['parent_review_ids']=={}
            and run['parent_validation_records']==execution.parent_records(w,m,run['parent_runs']),
            '疾病候选缺少同登记真实系统依赖')
        artifacts=[w.run(m,run['parent_runs']['A00'])['artifact_id']]
        require(run['parent_artifact_ids']==artifacts and run['config_hash']==fingerprint(run['config'])
            and run['input_hash']==fingerprint({'inputs':run['inputs'],'parents':artifacts}),'疾病候选运行指纹不一致')
        return True
    except ContractError:return False


def publish(w,sid,body):
    """锁外解析整理完整原件，短锁重核后经真实生产校验器发布独立候选。"""
    validate_request(w,sid,body);m=w.load(sid);home=w.location(sid)
    for rid in m['runs']:
        run=w.run(m,rid)
        if run['config'].get('version')==VERSION and run['inputs']['publication_request']['request_id']==body['request_id']:return w.result(m,rid)
    ref,record,request=acquisition_for(w,m,body['expected_acquisition_request_id'])
    parents={'A00':request['request']['expected_a00']};execution.ensure_parents(w,sid,parents)
    proofs=execution.parent_records(w,w.load(sid),parents)
    from science_modules.a02.system_collection import configuration,source_manifest,facts
    folder=home/'raw/A02_system_collection'/new_id('publication');source=source_manifest(w,m,ref,record,request)
    path=folder/'disease_sources.json';write_json(path,source);source_ref=file_record(home,path,'source_manifest')
    inputs={'study_id':sid,'publication_request':deepcopy(body),'acquisition_record':deepcopy(ref),
        'analysis_plan_file':deepcopy(record['plan_file']),'source_manifest':source_ref,
        'intake_result':deepcopy(m['runs'][parents['A00']]['result_file'])}
    summary,tables,anomalies=facts(home,inputs);outcome='success' if tables['candidate_records'] else 'empty'
    with write_lock(w.root):
        validate_request(w,sid,body);m=w.load(sid);acquisition.require_current(w,m,request)
        require(proofs==execution.parent_records(w,m,parents),'疾病候选整理期间登记回执或人工决定改变')
        rid=new_id('run');config=configuration();artifacts=[w.run(m,parents['A00'])['artifact_id']]
        run={'schema_version':SCHEMA_VERSION,'study_id':sid,'module_id':'A02','run_id':rid,'artifact_id':new_id('artifact'),
            'parent_runs':parents,'parent_artifact_ids':artifacts,'parent_review_ids':{},'parent_validation_records':proofs,
            'execution_protocol':VERSION,'execution_authority':'system_validation','inputs':inputs,'config':config,
            'input_hash':fingerprint({'inputs':inputs,'parents':artifacts}),'config_hash':fingerprint(config),'reason':body['note'],
            'code_version':w.code_version,'environment_version':fingerprint(w.environment),'environment':deepcopy(w.environment),'created_at':now()}
        run_path=home/'runs/A02'/rid/'run.json';write_json(run_path,run)
        m['runs'][rid]={'run_file':file_record(home,run_path,'run'),'result_file':None};m['current']['A02']=rid
        validation.canonical_validator(w.root,'A02')(run,summary,tables,anomalies,outcome)
        result=w._finish(m,rid,summary,tables,anomalies,outcome,sources=[ref,record['request_file'],record['plan_file'],
            inputs['intake_result'],source_ref,*proofs.values(),*[r['archive'] for r in record['sources']]])
        w.save(m);return result
