"""明确问题清单的身份例外科学适配；旧HGNC、三库及疾病标准化规则保持。"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlencode
from contracts import fingerprint,require
from storage import file_record,read_json,verified_file,write_json

VERSION='A01.system_publication.2'


def mapper_for(home,mapping):
    """同批两侧读取同一三份原件，不联网、不按名称猜测或改HGNC版本。"""
    from hgnc import HgncMap
    from identity_sources import IdentityEvidence
    evidence=IdentityEvidence(*(verified_file(home,r).read_bytes() for r in mapping['identity_evidence_files']))
    mapper=HgncMap(verified_file(home,mapping['mapping_file']).read_bytes(),rule=mapping['mapping_rule'],supplement=evidence)
    require(mapper.digest==mapping['mapping_snapshot'] and evidence.digest==mapping['identity_evidence_snapshot'],
        '本批共同映射或身份补充证据指纹不同')
    return mapper


def disease_diagnostic(home,binding,mapper):
    """只沿原五库候选及原系统直接范围规则诊断；不写范围决定或标准化结果。"""
    from mesh_identity import validate_mesh_identity
    from normalization import compute
    base=read_json(verified_file(home,binding['run_files']['A02']['result_file']))
    intake=read_json(verified_file(home,binding['run_files']['A00']['result_file']))
    identity=validate_mesh_identity(intake['summary'])
    terms={str(x).strip().casefold() for x in [identity['preferred_term'],*identity.get('entry_terms',[])]}
    scopes={row['scope_id']:row['scope'] if row['scope']!='pending' else 'direct'
        if row['disease_id'].strip().casefold()==identity['mesh_id'].casefold() or row['disease_term'].strip().casefold() in terms
        else 'pending' for row in base['tables']['scope_groups']}
    _,tables,_=compute(base,mapper,'A02',scopes,False,None,'workflow_test',identity)
    return tables['identity_issues']


def validate_queries(original,package,issues):
    """补充包必须保留原前缀，仅接受本批问题精确编号的完整官方查询集合。"""
    require(isinstance(package,dict) and set(package)==set(original)|{'queries'}
        and all(package[key]==original[key] for key in original if key!='queries'), '补充包不得替换旧来源字段')
    prior=original.get('queries',[]);queries=package.get('queries')
    require(isinstance(queries,list) and queries[:len(prior)]==prior,'原查询证据被删改或重排')
    eids=sorted({x['raw_id'] for x in issues if x['raw_id'].startswith('ENSG')})
    hids=sorted({hid for x in issues for hid in x['candidate_ids'].split('|') if hid})
    genes=sorted({x['ncbi_gene_id'] for x in issues if x['ncbi_gene_id']},key=int)
    expected=[('https://rest.ensembl.org/info/data',None),('https://rest.ensembl.org/lookup/id',{'ids':eids}),
        ('https://rest.ensembl.org/archive/id',{'id':eids})]
    expected += [(url,None) for eid in eids for url in ('https://rest.ensembl.org/xrefs/id/'+eid,
        'https://rest.genenames.org/fetch/ensembl_gene_id/'+eid)]
    expected += [('https://rest.genenames.org/fetch/hgnc_id/'+hid,None) for hid in hids]
    if genes:expected.append(('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?'+urlencode({'db':'gene','id':','.join(genes),'retmode':'json'}),None))
    new=queries[len(prior):]
    require(len(new)==len(expected) and sorted(fingerprint((q.get('url'),q.get('payload'))) for q in new)
        ==sorted(fingerprint(row) for row in expected),'补充查询不是本批精确编号完整集合，不能附加其他网址或遗漏')
    for q in new:
        require(q['status']=='ok' and q['http_status']==200 and isinstance(q['retrieved_at'],str) and q['retrieved_at']
            and hashlib.sha256(q['response_text'].encode('utf8')).hexdigest()==q['response_sha256'], '补充查询失败、日期缺失或原响应指纹不符')
        data=json.loads(q['response_text']);url=q['url']
        if url.endswith('/lookup/id'):
            require(isinstance(data,dict) and set(data)==set(eids),'现行精确编号响应不完整')
            for eid,row in data.items():
                require(row is None or row.get('id')==eid and row.get('species')=='homo_sapiens' and row.get('object_type')=='Gene',
                    '现行查询返回其他编号、物种或对象类型')
        elif url.endswith('/archive/id'):
            require(isinstance(data,list) and len(data)==len(eids) and {x.get('id') for x in data}==set(eids),'历史精确编号响应不完整')
        elif '/xrefs/id/' in url:require(isinstance(data,list),'精确交叉编号响应结构错误')
        elif 'rest.genenames.org/fetch/' in url:
            response=data.get('response',{});docs=response.get('docs')
            require(isinstance(docs,list) and response.get('numFound')==len(docs),'HGNC精确查询响应不完整')
            if '/hgnc_id/' in url:require(len(docs)==1 and docs[0].get('hgnc_id')==url.rsplit('/',1)[1],'HGNC编号响应不一致')
            else:require(all(x.get('ensembl_gene_id')==url.rsplit('/',1)[1] for x in docs),'HGNC返回其他Ensembl编号')
        elif 'esummary.fcgi?' in url:
            result=data.get('result',{});require(set(result.get('uids',[]))==set(genes),'NCBI精确编号响应不完整')
            require(all(str(result[gid].get('uid'))==gid and result[gid].get('organism',{}).get('taxid')==9606 for gid in genes),
                'NCBI补查不是原人类精确编号')
        elif url.endswith('/info/data'):require(isinstance(data.get('releases'),list) and data['releases'],'Ensembl未提供实际发布信息')
    return new


def prepare(home,binding,body,evidence_ref):
    """核查原资料与新官方包，再确认用户明确清单恰好覆盖剩余问题。"""
    original=read_json(verified_file(home,binding['mapping']['identity_evidence_files'][2]))
    package=read_json(verified_file(home,evidence_ref));old_mapper=mapper_for(home,binding['mapping'])
    old_issues=disease_diagnostic(home,binding,old_mapper);queries=validate_queries(original,package,old_issues)
    mapping=deepcopy(binding['mapping']);mapping['identity_evidence_files'][2]=dict(evidence_ref,role='identity_source')
    from identity_sources import IdentityEvidence
    blobs=[verified_file(home,ref).read_bytes() for ref in mapping['identity_evidence_files']]
    mapping['identity_evidence_snapshot']=IdentityEvidence(*blobs).digest
    mapper=mapper_for(home,mapping);issues=disease_diagnostic(home,binding,mapper)
    require(sorted(body['a02_omit_ids'])==sorted(x['issue_id'] for x in issues),
        '实际疾病未决组与用户明确清单不同，不能多略过、漏掉或沿用旧证据')
    original_run=read_json(verified_file(home,binding['run_files']['A01']['run_file']))
    original_result=read_json(verified_file(home,binding['run_files']['A01']['result_file']))
    from .system_source_binding import facts as original_facts
    inputs=deepcopy(original_run['inputs']);inputs['mapping']=mapping
    _,tables,_=original_facts(home,inputs)
    keys=sorted(x['issue_key'] for x in original_result['tables']['identity_decisions'])
    require(fingerprint(original_result['tables']['identity_decisions'])==body['expected_a01_issue_hash']
        and {x['issue_key'] for x in tables['identity_decisions']}<=set(keys),'原A01或新证据后身份范围超出用户清单')
    folder=home/evidence_ref['path'];folder=folder.parent
    diagnostic={'version':'ModuleA.identity_exception.1','binding_hash':fingerprint(binding),'mapping':mapping,
        'original_a02_issues':old_issues,'a02_remaining_issues':issues,'a01_remaining_issues':tables['identity_decisions'],
        'official_supplement_queries':len(queries),'scientific_result_published':False}
    path=folder/'diagnostic.json'
    if path.exists():require(read_json(path)==diagnostic,'原请求诊断与当前原件不同，不覆盖')
    else:write_json(path,diagnostic)
    implementations=[]
    import normalization,hgnc,identity_sources
    from . import system_source_binding,plan_flow
    from modulea.core import identity_exceptions
    from science_modules.a02 import system_normalization_identity
    for source in [Path(__file__),*(Path(module.__file__) for module in (normalization,hgnc,identity_sources,
            system_source_binding,plan_flow,identity_exceptions,system_normalization_identity))]:
        target=folder/'implementation'/source.name;target.parent.mkdir(exist_ok=True)
        if target.exists():require(target.read_bytes()==source.read_bytes(),'未完成例外的实现已改变，请使用新请求')
        else:target.write_bytes(source.read_bytes())
        implementations.append(file_record(home,target,'identity_exception_implementation'))
    return {'mapping':mapping,'a01_issue_keys':keys,'a02_issue_ids':sorted(x['issue_id'] for x in issues),
        'diagnostic_file':file_record(home,path,'identity_exception_diagnostic'),'implementation_files':implementations}


def configuration(plan):
    """新行为显式第二版，原来源与科学参数继续保留。"""
    from .system_source_binding import configuration as original
    return dict(original(plan),version=VERSION,identity_exception_protocol='ModuleA.identity_exception.1')


def facts(home,inputs):
    """原三库事实复算后仅标记已明确的问题不采用，既有正常关系与结构不猜改。"""
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    from modulea.core import identity_exceptions as core
    from .system_source_binding import facts as original
    home=Path(home);w=AnalysisPlanWorkflow(home.parents[1]);m=w.load(inputs['study_id'])
    value=core.read_record(w,m,inputs['identity_exception_file']);binding=value['binding']
    require(inputs['analysis_purpose']=='workflow_test' and inputs['mapping']==value['mapping']
        and inputs['system_source_binding']==binding['source_binding'] and inputs['analysis_plan_file']==binding['plan_file']
        and inputs['bound_a00']==binding['current']['A00'],'A01身份例外不适用本批原件、方案或共同映射')
    summary,tables,anomalies=original(home,inputs)
    pending=tables['identity_decisions'];require({x['issue_key'] for x in pending}<=set(value['a01_issue_keys']),
        '实际A01身份问题超出原明确清单')
    require(not summary['完整性待核项数'],'身份例外不豁免三库完整性')
    tables['identity_decisions']=[dict(row,decision='本次测试明确不采用',authority_kind='explicit_user_identity_exception') for row in pending]
    tables['identity_exception_scope']=[{'module_id':'A01','issue_id':key,'action':'omit_from_this_test_only',
        'request_id':value['request']['request_id'],'reason_zh':value['request']['note'],'notice_zh':value['notice_zh']} for key in value['a01_issue_keys']]
    summary.update(component_source_profile=VERSION,identity_exception_protocol=core.VERSION,
        identity_limitations_zh=[value['notice_zh']],handoff_blocked=False,candidate_only=False,
        **{'未决身份组数':len(pending),'本批未处理身份组数':0,'明确暂不采用身份组数':len(pending),
            '资料阶段':'本批身份例外流程测试；未决对象仍留存，尚未人工总体复核'})
    return summary,tables,list(anomalies)+[value['notice_zh']]


def validator(root,fallback):
    """生产规范完整重建新结果；旧系统第一版及人工版本不改变。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return fallback(run,summary,tables,anomalies,outcome)
        home=Path(root)/'studies'/run['study_id'];inputs=run['inputs']
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from modulea.core.system_execution import is_active
        w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);candidate=deepcopy(m)
        candidate['current']['A01']=run['run_id']
        candidate['runs'][run['run_id']]={'run_file':file_record(home,home/'runs/A01'/run['run_id']/'run.json','run'),'result_file':None}
        require(is_active(w,candidate,run),'A01身份例外缺少本研究真实批次、父回执或已被人工暂停')
        from .plan_flow import plan_record
        _,plan=plan_record(home,inputs)
        require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['parent_review_ids']=={}
            and run['config']==configuration(plan) and inputs['bound_a00']==run['parent_runs']['A00'],
            'A01身份例外执行授权、原参数或依赖不同')
        batch=read_json(verified_file(home,run['batch_file']))
        require(batch['identity_exception_file']==inputs['identity_exception_file'] and batch['mapping']==inputs['mapping'],
            'A01例外不是本批明确共同映射')
        require(fingerprint((summary,tables,anomalies))==fingerprint(facts(home,inputs)) and outcome=='success',
            'A01身份例外结果与原件及明确清单复算不一致')
    return check
