"""新批次显式复用本研究已归档疾病原件；来源链只读，不移动运行或伪改旧快照。"""
from copy import deepcopy
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json

VERSION='A02.system_source_reuse.1'
COLLECTION_VERSION='A02.system_collection.1'
COLLECTION_REUSE_VERSION='A02.system_source_reuse.2'
HISTORICAL_COLLECTION='A02.historical_collection.1'
HISTORICAL_REUSE='A02.system_source_reuse.3'
NORMALIZED={'A02.system_normalization.1','A02.system_normalization.2','A02.system_normalization.3','A02.system_normalization.4','A02.system_normalization.5'}


def resolve(workflow,m,initial=None,*,check_reviews=True):
    """只循当前明确绑定A02的真实来源引用，不扫描其他历史候选择优或跨研究借用。"""
    home=workflow.location(m['study_id']);binding=initial or m;rid=binding['current'].get('A02')
    require(rid,'请先提供本研究现代五库原始候选')
    files=binding.get('run_files',{}).get(rid,m['runs'].get(rid));require(files and files.get('result_file'),'疾病来源尚无完整原件')
    require(m['runs'].get(rid)==files,'疾病当前来源与原确认运行记录不同')
    current=read_json(verified_file(home,files['run_file']));result=read_json(verified_file(home,files['result_file']))
    require(current['study_id']==result['study_id']==m['study_id'] and current['run_id']==result['run_id']==rid
        and current['module_id']==result['module_id']=='A02','疾病来源不属于本研究真实A02')
    version=current['config'].get('version');reused=version in NORMALIZED
    if reused:
        raw_ref=current['inputs']['base_run'];raw_result=current['inputs']['base_result']
        raw=read_json(verified_file(home,raw_ref));base=read_json(verified_file(home,raw_result));raw_id=raw['run_id']
        require(m['runs'].get(raw_id)=={'run_file':raw_ref,'result_file':raw_result},'疾病来源祖先未登记到同研究')
    else:raw_ref=files['run_file'];raw_result=files['result_file'];raw=current;base=result;raw_id=rid
    raw_version=raw['config'].get('version')
    require(raw_version in ('A02.collect.2',COLLECTION_VERSION,HISTORICAL_COLLECTION) and raw['study_id']==base['study_id']==m['study_id']
        and raw['run_id']==base['run_id']==raw_id and raw['module_id']==base['module_id']=='A02'
        and raw['parent_runs']=={'A00':binding['current']['A00']} and base['summary'].get('source_profile')=='A02.source_profile.3',
        '只支持同登记现代五库原候选的明确来源链，不接受旧标准化或其他研究替代')
    if raw_version==COLLECTION_VERSION:
        from . import system_disease_acquisition as acquisition
        source=acquisition.read_record(workflow,m,raw['inputs']['acquisition_record'],kind='record')
        request=acquisition.read_record(workflow,m,source['request_file'],kind='request')
        require(source['state']=='complete' and request['request']['expected_a00']==binding['current']['A00']
            and raw.get('execution_protocol')==COLLECTION_VERSION and raw['parent_review_ids']=={}
            and raw['execution_authority']=='system_validation' and base['summary'].get('handoff_blocked') is True,
            '系统原候选缺少本研究完整原件、真实系统授权或候选交接门控')
    if raw_version==HISTORICAL_COLLECTION:
        from .historical_disease_sources import read_record,require_current
        exception=read_record(workflow,m,raw['inputs']['historical_exception'])
        if check_reviews:require_current(workflow,m,exception)
        require(raw['inputs']['analysis_plan_file']==exception['binding']['plan_file']
            and raw['parent_runs']=={'A00':exception['binding']['a00_run_id']} and raw['parent_review_ids']=={}
            and raw['execution_authority']=='system_validation' and raw.get('execution_protocol')==HISTORICAL_COLLECTION,
            '历史候选缺少本登记、原方案和真实用户版本例外')
    # 复核只读取真实版本；任何明确暂存/退回都不能借原件复用抹去。
    for source in (current,raw) if check_reviews else ():
        review=workflow.latest_review(m,source['artifact_id'])
        require(not review or review['decision']=='approved','疾病原件或原标准化已有明确人工暂存或退回')
    return {'schema_version':HISTORICAL_REUSE if raw_version==HISTORICAL_COLLECTION else COLLECTION_REUSE_VERSION if raw_version==COLLECTION_VERSION else VERSION,'study_id':m['study_id'],'bound_a00':binding['current']['A00'],
        'source_current_run':deepcopy(files['run_file']),'source_current_result':deepcopy(files['result_file']),
        'base_run':deepcopy(raw_ref),'base_result':deepcopy(raw_result),'base_run_id':raw_id,
        'reused_from_normalized':reused,'human_review_written':False,
        'source_policy_zh':'沿当前A02真实base_run/base_result复用同研究原件，按新批重新标准化' if reused else '采用当前现代五库原候选'}


def create(workflow,m,batch_id,initial):
    """确认新批时追加来源绑定；旧batch、运行、资料和current保持。"""
    value=resolve(workflow,m,initial);require(value['reused_from_normalized'] or value['schema_version'] in (COLLECTION_REUSE_VERSION,HISTORICAL_REUSE),
        '旧原候选直接采用旧分支，不额外生成复用记录')
    value.update(batch_id=batch_id,initial_input_hash=fingerprint(initial))
    folder=workflow.location(m['study_id'])/'decisions/analysis_plans/system_batches'/batch_id/'disease_sources'
    path=folder/(new_id('diseasesource')+'.json');write_json(path,value)
    return file_record(workflow.location(m['study_id']),path,'system_disease_source_binding')


def read(workflow,m,batch,*,check_reviews=True):
    """实际来源必须可由原确认快照独立重建，不能以另存文件偷换候选或旧意见。"""
    ref=batch.get('disease_source_file');require(ref and batch.get('disease_source_protocol') in (VERSION,COLLECTION_REUSE_VERSION,HISTORICAL_REUSE),'新批缺少显式疾病来源协议')
    value=read_json(verified_file(workflow.location(m['study_id']),ref));expected=resolve(workflow,m,batch['initial_binding'],check_reviews=check_reviews)
    expected.update(batch_id=batch['batch_id'],initial_input_hash=fingerprint(batch['initial_binding']))
    require(batch['disease_source_protocol']==expected['schema_version'],'新批疾病来源协议与原候选版本不同')
    require(fingerprint(value)==fingerprint(expected),'原件复用绑定与原确认来源链不一致')
    return value
