"""系统获取完整原件后的独立候选协议；原organize与候选数据校验完整复用。"""
from copy import deepcopy
from pathlib import Path
import hashlib
from contracts import fingerprint,require
from storage import file_record,read_json,verified_file

VERSION='A02.system_collection.1'


def configuration():
    """原候选阶段仍禁止交接，不把系统核验当成疾病集合批准。"""
    return {'version':VERSION,'stage':'candidate_collection','score_filter':None,'handoff_blocked':True,
        'acquisition_protocol':'A02.system_acquisition.1','source_profile':'A02.source_profile.3'}


def source_manifest(w,m,ref,record,request):
    """原字节引用完整保存，既有明确范围决定沿当前真实原件链保留。"""
    from disease import source_profile,scope_policy
    from modulea.core.system_disease_sources import resolve
    decisions=[];baseline=None
    if request['binding']['current'].get('A02'):
        original=resolve(w,m,request['binding'],check_reviews=False)
        old=read_json(verified_file(w.location(m['study_id']),original['base_result']))
        refs=[r for r in old['sources'] if r['role']=='source_manifest'];require(len(refs)==1,'当前疾病原件清单不唯一')
        prior=read_json(verified_file(w.location(m['study_id']),refs[0]));decisions=deepcopy(prior.get('scope_decisions',[]));baseline=deepcopy(prior.get('comparison_baseline'))
    return {'datasets':[dict(deepcopy(row['source']),sha256=row['archive']['sha256'],source_record=deepcopy(row['archive'])) for row in record['sources']],
        'scope_decisions':decisions,'previous_a02':request['binding']['current'].get('A02'),'scope_policy':scope_policy(),
        'source_profile':source_profile('A02.source_profile.3'),'comparison_baseline':baseline,'acquisition_record':deepcopy(ref)}


def facts(home,inputs):
    """从登记、获取记录、逐库原文独立重建全部原候选表，不接受通过覆盖。"""
    from disease import CONFIG,organize,validate_disease
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    from modulea.core import system_disease_acquisition as core
    from science_modules.a02.system_acquisition import validate_record
    from science_modules.analysis_protocol import checked_plan
    home=Path(home);w=AnalysisPlanWorkflow(home.parents[1]);m=w.load(inputs['study_id'])
    require(home==w.location(m['study_id']),'疾病候选研究路径不一致')
    record=core.read_record(w,m,inputs['acquisition_record'],kind='record')
    request=core.read_record(w,m,record['request_file'],kind='request');validate_record(home,request,record)
    require(record['state']=='complete' and inputs['analysis_plan_file']==record['plan_file'],'疾病候选不能采用不完整获取或其他方案')
    body=inputs['publication_request']
    require(body['confirmed'] is True and body['expected_record_sha256']==inputs['acquisition_record']['sha256']
        and body['expected_acquisition_request_id']==request['request']['request_id']
        and body['expected_input_hash']==fingerprint(request['binding']),'疾病候选发布确认与完整原件不同')
    plan=read_json(verified_file(home,inputs['analysis_plan_file']));checked_plan(plan['plan'])
    intake=read_json(verified_file(home,inputs['intake_result']))
    require(plan['study_id']==intake['study_id']==m['study_id'] and plan['expected_a00']==intake['run_id']==request['request']['expected_a00']
        and inputs['intake_result']==request['binding']['run_files'][intake['run_id']]['result_file'],'疾病候选不是同登记实际来源')
    expected=source_manifest(w,m,inputs['acquisition_record'],record,request)
    source=read_json(verified_file(home,inputs['source_manifest']));require(fingerprint(source)==fingerprint(expected),'疾病候选原件或范围决定与原获取不同')
    datasets=[]
    for item in source['datasets']:
        raw=verified_file(home,item['source_record']).read_bytes();require(hashlib.sha256(raw).hexdigest()==item['sha256'],'候选来源SHA不同')
        datasets.append(dict(item,data=raw))
    summary,tables,anomalies=organize(datasets,source['scope_decisions'],source['source_profile']['databases'],source['source_profile']['version'])
    require(all(row['availability'] in ('已有候选资料，待核验','已查询但0条精确记录') for row in tables['source_summary']),
        '缺失或失败库不能作为有效空库发布')
    # 仅复用原候选数据校验，不给新运行伪造旧版本或人工授权。
    validate_disease({'config':CONFIG},summary,tables,anomalies,'success' if tables['candidate_records'] else 'empty')
    summary.update(protocol_version=VERSION,analysis_plan_id=plan['plan_id'],analysis_parameter_hash=plan['plan']['parameter_hash'])
    return summary,tables,anomalies


def validator(root,fallback):
    """生产入口独立复算新候选及真实登记依赖，旧候选委托原校验器。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return fallback(run,summary,tables,anomalies,outcome)
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from modulea.core.system_disease_publication import is_active
        w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);home=w.location(run['study_id']);candidate=deepcopy(m)
        candidate['current']['A02']=run['run_id'];candidate['runs'][run['run_id']]={
            'run_file':file_record(home,home/'runs/A02'/run['run_id']/'run.json','run'),'result_file':None}
        require(run['config']==configuration() and is_active(w,candidate,run),'新候选配置或真实登记依赖无效')
        require(fingerprint((summary,tables,anomalies))==fingerprint(facts(home,run['inputs'])),'疾病候选与原件独立整理不同')
        require(outcome==('success' if tables['candidate_records'] else 'empty'),'疾病候选空状态不一致')
    return check
