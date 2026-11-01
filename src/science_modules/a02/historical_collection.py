"""明确历史版本例外的独立五库候选；完整复用原解析和整理，不补造发布版本。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require
from storage import read_json,verified_file,file_record

VERSION='A02.historical_collection.1'


def configuration():
    """新候选永远保持待标准化，不把未知发布版本算作完整。"""
    return {'version':VERSION,'stage':'candidate_collection','score_filter':None,'handoff_blocked':True,
        'historical_exception_protocol':'A02.historical_sources.1','source_profile':'A02.source_profile.3','analysis_purpose':'workflow_test'}


def source_manifest(w,m,ref):
    """原字段、原日期和实际原件不变，单独携带已批准限制。"""
    from modulea.core.historical_disease_sources import read_record
    from disease import metadata,source_profile,scope_policy
    value=read_record(w,m,ref)
    return {'datasets':[dict(metadata(row['source']),sha256=row['archive']['sha256'],source_record=deepcopy(row['archive'])) for row in value['binding']['sources']],
        'scope_decisions':[],'previous_a02':None,'scope_policy':scope_policy(),'source_profile':source_profile('A02.source_profile.3'),
        'comparison_baseline':None,'historical_exception':deepcopy(ref),'source_limitations_zh':[value['notice_zh']]}


def facts(home,inputs):
    """逐件复核原文、正式范围决定和用户例外后调用冻结候选算法。"""
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    from modulea.core.historical_disease_sources import read_record
    from disease import organize,validate_disease,CONFIG,parse_source,metadata
    from source_identity import validate_source_identity
    home=Path(home);w=AnalysisPlanWorkflow(home.parents[1]);m=w.load(inputs['study_id']);value=read_record(w,m,inputs['historical_exception']);binding=value['binding']
    require(home==w.location(m['study_id']) and inputs['analysis_plan_file']==binding['plan_file']
        and inputs['intake_result']==binding['a00_files']['result_file'] and inputs['publication_request']==value['request'],'历史候选不是原明确例外及登记')
    require({Path(ref['path']).name for ref in inputs['implementation_files']}=={'historical_disease_sources.py','historical_collection.py',
        'system_normalization_historical.py','disease.py','disease_io.py','source_identity.py'},'历史候选缺少实际实现快照')
    for ref in inputs['implementation_files']:verified_file(home,ref)
    expected=source_manifest(w,m,inputs['historical_exception']);source=read_json(verified_file(home,inputs['source_manifest']))
    require(source==expected,'历史候选来源或限制与原例外不同')
    summary=read_json(verified_file(home,inputs['intake_result']))['summary'];require(summary['analysis_purpose']=='workflow_test','未知版本例外禁止正式研究')
    datasets=[]
    for row in source['datasets']:
        raw=verified_file(home,row['source_record']).read_bytes();require(row['source_record']['sha256']==row['sha256'],'历史原件指纹不同')
        require(metadata(row)['version']==row['version'],'原数据库版本字段被改写');validate_source_identity(summary,row,raw);parse_source(row,raw)
        datasets.append(dict(row,data=raw))
    summary,tables,anomalies=organize(datasets,[],source['source_profile']['databases'],source['source_profile']['version'])
    require(all(row['availability'] in ('已有候选资料，待核验','已查询但0条精确记录') for row in tables['source_summary']),'缺失或失败不能进入历史例外候选')
    validate_disease({'config':CONFIG},summary,tables,anomalies,'success' if tables['candidate_records'] else 'empty')
    plan=read_json(verified_file(home,binding['plan_file']))
    summary.update(protocol_version=VERSION,analysis_purpose='workflow_test',analysis_plan_id=binding['plan_id'],analysis_parameter_hash=plan['plan']['parameter_hash'],
        database_versions_complete=False,source_version_exception=True,source_limitations_zh=source['source_limitations_zh'])
    tables['source_version_exceptions']=[{'database':row['database'],'version':row['version'],'retrieved_at':row['retrieved_at'],
        'source_sha256':row['sha256'],'notice_zh':value['notice_zh'],'authority_kind':'explicit_user_source_version_exception'} for row in source['datasets'] if row['database'] in ('GeneCards','OMIM')]
    return summary,tables,list(anomalies)+source['source_limitations_zh']


def validator(root,fallback):
    """生产入口独立复算，旧候选及其版本要求保持。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return fallback(run,summary,tables,anomalies,outcome)
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from modulea.core.historical_disease_sources import is_active
        w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);home=w.location(run['study_id']);candidate=deepcopy(m)
        candidate['current']['A02']=run['run_id'];candidate['runs'][run['run_id']]={'run_file':file_record(home,home/'runs/A02'/run['run_id']/'run.json','run'),'result_file':None}
        require(run['config']==configuration() and is_active(w,candidate,run),'历史候选真实例外或登记依赖无效')
        require(fingerprint((summary,tables,anomalies))==fingerprint(facts(home,run['inputs'])),'历史候选与原文独立复算不同')
        require(outcome==('success' if tables['candidate_records'] else 'empty'),'历史候选空状态错误')
    return check
