"""本研究明确身份例外的不可变范围与共同证据绑定；不代签或自行采用结构。"""
from copy import deepcopy
from contracts import ContractError, fingerprint, require, safe_id
from storage import file_record, read_json, verified_file, write_json, write_lock

VERSION = 'ModuleA.identity_exception.1'
INDEX = 'analysis_plan_identity_exceptions'
CURRENT = 'current_analysis_plan_identity_exception'
FIELDS = {'request_id','expected_a00','expected_a01','expected_a02','expected_plan_id',
    'expected_input_hash','expected_evidence_sha256','expected_a01_issue_hash','a02_omit_ids',
    'author','note','user_decision','confirmed'}
NOTICE = '仅限本研究本批流程测试：清单内身份仍未解决，明确暂不纳入主集合；原身份、来源和原因保留，不代表完整身份或正式研究结论。'


def guard(w,m,binding=None):
    """新旧原件上的明确人工暂停均否决，不能用身份例外抹去它。"""
    require(not m.get('trashed'),'回收站研究只读')
    ids=set(m['current'].values())
    if binding:ids.update(binding['current'].values())
    for rid in ids:
        review=w.latest_review(m,w.run(m,rid)['artifact_id'])
        require(not review or review['decision']=='approved','已有明确人工暂存或退回，身份例外不能放行')


def context(w,m):
    """标准库固定当前双侧、原方案和原三库；GET不解析新证据或计算映射。"""
    a00,a01,a02=(m['current'].get(key) for key in ('A00','A01','A02'))
    require(a00 and a01 and a02,'请先生成同登记的三库及五库原候选')
    intake=w.result(m,a00)['summary'];one=w.run(m,a01);two=w.run(m,a02)
    require(intake.get('analysis_purpose')=='workflow_test','身份例外仅限流程测试，正式研究禁止使用')
    require(one['config'].get('version')=='A01.system_publication.1'
        and two['config'].get('version')=='A02.historical_collection.1','本版仅支持系统三库及历史五库原候选')
    require(one['parent_runs']==two['parent_runs']=={'A00':a00},'两侧原候选不属于同一登记')
    plan=one['inputs']['analysis_plan_file'];require(plan==two['inputs']['analysis_plan_file'],'两侧原方案不同')
    home=w.location(m['study_id']);value=read_json(verified_file(home,plan))
    require(value['plan_id']==w._analysis_plan_records(m)[-1]['plan_id'],'方案已改变，原清单例外不能继承')
    from .system_component_sources import current
    require(current(w,m,plan_id=value['plan_id'])==one['inputs']['system_source_binding'],'本批三库原件已替换')
    return {'study_id':m['study_id'],'current':{key:m['current'][key] for key in ('A00','A01','A02')},
        'run_files':{key:deepcopy(m['runs'][m['current'][key]]) for key in ('A00','A01','A02')},
        'reviews':deepcopy(m.get('reviews',[])),'plan_file':deepcopy(plan),'plan_id':value['plan_id'],
        'source_binding':deepcopy(one['inputs']['system_source_binding']),'mapping':deepcopy(one['inputs']['mapping'])}


def info(w,sid):
    """只读资格与已登记决定，不把科学诊断当作已采用结果。"""
    m=w.load(sid);blockers=[];binding=None
    try:guard(w,m);binding=context(w,m)
    except ContractError as error:blockers.append(str(error))
    return {'schema_version':VERSION,'enabled':not blockers,'blockers':blockers,'binding':binding,
        'expected_input_hash':fingerprint(binding) if binding else None,
        'history':[dict(read_record(w,m,ref),file=deepcopy(ref)) for ref in m.get(INDEX,[])],
        'message_zh':'仅后台公开Workflow接通；实际登记不发布科学运行或人工复核。'}


def validate_request(w,sid,body,raw):
    """精确内容确认，不接受路径、任意网址、通过标记或未明确的遗漏范围。"""
    import hashlib
    require(isinstance(body,dict) and set(body)==FIELDS,'身份例外字段错误，不接受路径或通过覆盖')
    safe_id(body['request_id'],'identityexceptreq')
    for key in ('expected_a00','expected_a01','expected_a02'):safe_id(body[key],'run')
    safe_id(body['expected_plan_id'],'plan')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=4000
        for k in ('author','note','user_decision')),'请填写真实用户决定、登记人和原因并明确确认')
    require(isinstance(raw,bytes) and 0<len(raw)<=2*1024*1024 and hashlib.sha256(raw).hexdigest()==body['expected_evidence_sha256'],
        '身份补充原件为空、超过2MiB或与明确指纹不同')
    require(isinstance(body['a02_omit_ids'],list)
        and all(isinstance(x,str) and len(x)==24 and all(c in '0123456789abcdef' for c in x) for x in body['a02_omit_ids'])
        and len(body['a02_omit_ids'])==len(set(body['a02_omit_ids'])),
        '疾病身份清单必须逐组明确且不能重复')
    m=w.load(sid);guard(w,m)
    for ref in m.get(INDEX,[]):
        old=read_record(w,m,ref)
        if old['request']['request_id']==body['request_id']:
            require(old['request']==body and m.get(CURRENT)==ref,'请求号或当前例外已改变');return deepcopy(old['binding'])
    binding=context(w,m)
    require(body['expected_input_hash']==fingerprint(binding) and body['expected_plan_id']==binding['plan_id']
        and all(body['expected_'+key.lower()]==rid for key,rid in binding['current'].items()),'身份例外输入或原方案已改变，请刷新')
    issues=w.result(m,binding['current']['A01'])['tables']['identity_decisions']
    require(body['expected_a01_issue_hash']==fingerprint(issues),'成分侧精确身份问题清单已改变')
    return binding


def read_record(w,m,ref):
    """历史记录沿原运行和文件指纹读取，后续科学发布不会改写原范围。"""
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref));binding=value['binding'];body=value['request']
    require(ref in m.get(INDEX,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']==binding['study_id']
        and value['authority_kind']=='explicit_user_identity_exception' and value['human_review_written'] is False
        and body['confirmed'] is True and value['request_hash']==fingerprint(body)
        and body['expected_input_hash']==fingerprint(binding),'身份例外归属、原确认或协议错误')
    require(body['expected_plan_id']==binding['plan_id'] and binding['plan_file'] in m.get('analysis_plan_records',[])
        and all(body['expected_'+key.lower()]==rid for key,rid in binding['current'].items()),'身份例外原方案或两侧运行不同')
    require(read_json(verified_file(home,binding['run_files']['A00']['result_file']))['summary']['analysis_purpose']=='workflow_test',
        '身份例外不能用于正式研究')
    for key,files in binding['run_files'].items():
        require(m['runs'].get(binding['current'][key])==files,'身份例外原运行登记已改变')
        for item in files.values():verified_file(home,item)
    original=read_json(verified_file(home,binding['run_files']['A01']['result_file']))['tables']['identity_decisions']
    require(fingerprint(original)==body['expected_a01_issue_hash'] and value['a01_issue_keys']==sorted(x['issue_key'] for x in original)
        and value['a02_issue_ids']==sorted(body['a02_omit_ids']),'身份例外不是原精确问题清单')
    require(value['mapping']['mapping_file']==binding['mapping']['mapping_file']
        and value['mapping']['mapping_snapshot']==binding['mapping']['mapping_snapshot']
        and value['mapping']['mapping_rule']==binding['mapping']['mapping_rule']=='HGNC.resolve.3'
        and value['mapping']['identity_evidence_files'][:2]==binding['mapping']['identity_evidence_files'][:2],
        '身份例外不能替换HGNC、NCBI快照或映射规则')
    for item in [binding['plan_file'],binding['source_binding'],value['evidence_file'],value['diagnostic_file'],
        *value['mapping']['identity_evidence_files'],*value['implementation_files']]:verified_file(home,item)
    require(value['evidence_file']['sha256']==body['expected_evidence_sha256'],'原补充证据与明确确认不同')
    return value


def register(w,sid,body,raw):
    """科学worker验证精确原件与清单后追加决定；不发布A01/A02或签reviews。"""
    binding=validate_request(w,sid,body,raw);m=w.load(sid);home=w.location(sid)
    for ref in m.get(INDEX,[]):
        old=read_record(w,m,ref)
        if old['request']['request_id']==body['request_id']:return dict(old,file=deepcopy(ref),created=False)
    from science_modules.a01.identity_exception import prepare
    folder=home/'decisions/analysis_plans/identity_exceptions'/body['request_id']
    folder.mkdir(parents=True,exist_ok=True)
    evidence_path=folder/'identity_queries.json'
    if evidence_path.exists():require(evidence_path.read_bytes()==raw,'原请求已留存其他补充证据，不覆盖')
    else:evidence_path.write_bytes(raw)
    evidence_ref=file_record(home,evidence_path,'identity_exception_evidence')
    values=prepare(home,binding,body,evidence_ref)
    with write_lock(w.root):
        latest=w.load(sid);require(validate_request(w,sid,body,raw)==binding,'登记期间输入已改变')
        value={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
            'binding':binding,'authority_kind':'explicit_user_identity_exception','human_review_written':False,
            'evidence_file':evidence_ref,'notice_zh':NOTICE,**values}
        path=folder/'exception.json'
        if path.exists():require(read_json(path)==value,'未完成登记与当前请求或证据不同，不覆盖')
        else:write_json(path,value)
        ref=file_record(home,path,'identity_exception');latest.setdefault(INDEX,[]).append(ref);latest[CURRENT]=ref;w.save(latest)
    return dict(value,file=ref,created=True)


def for_batch(w,m,batch):
    """仅新明确批次消费共同映射，原件、方案和人工意见保持约束。"""
    ref=batch['identity_exception_file'];value=read_record(w,m,ref);guard(w,m,value['binding'])
    require(m.get(CURRENT)==ref and batch['plan_file']==value['binding']['plan_file']
        and batch['staging_file']==value['binding']['source_binding'] and batch['mapping']==value['mapping']
        and batch['request']['expected_a00']==value['binding']['current']['A00'],
        '本批身份例外、原方案、原件或共同映射已改变')
    return value
