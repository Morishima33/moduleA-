"""系统授权的实际科学输入适配；函数内部才加载科学实现，不改变原算法或参数。"""
from copy import deepcopy
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json


def a01(workflow,m,batch,plan):
    """使用原三库方案事实和规范配置，只将执行授权改为独立系统协议。"""
    from components import parse_herbs
    from mesh_identity import validate_mesh_identity
    from science_modules.a01.plan_flow import facts,configuration
    sid=m['study_id'];home=workflow.location(sid);intake=workflow.result(m,batch['request']['expected_a00'])['summary']
    require(intake.get('analysis_purpose') in ('workflow_test','formal_research'),'登记缺少明确用途')
    inputs={'study_id':sid,'bound_a00':batch['request']['expected_a00'],'staging_file':deepcopy(batch['staging_file']),
        'herbs':parse_herbs(intake['herbs']),'analysis_purpose':intake['analysis_purpose'],
        'disease_identity':validate_mesh_identity(intake) if intake['analysis_purpose']=='formal_research' else None,
        'analysis_plan_id':plan['plan_id'],'analysis_plan_file':deepcopy(batch['plan_file']),
        'analysis_parameter_hash':plan['plan']['parameter_hash'],'mapping':deepcopy(batch['mapping'])}
    summary,tables,anomalies=facts(home,inputs);source=read_json(verified_file(home,inputs['staging_file']))
    sources=[batch['plan_file'],batch['staging_file'],inputs['mapping']['mapping_file'],*inputs['mapping']['identity_evidence_files']]
    for slot in source['datasets']:sources.extend([slot['source_record'],*slot['files']])
    return inputs,configuration(plan['plan']),summary,tables,anomalies,sources


def a03(workflow,m,batch,plan,batch_ref,body):
    """显式批次授权派生阶段请求，沿用原交集事实及图，不伪造逐阶段人工点击。"""
    from science_modules.plan_stages import a03_facts,A03_VERSION
    from science_modules.plan_stages_contract import VERSION as STAGES_VERSION
    from intersection_flow import CONFIG,payload_from,venn_svg
    sid=m['study_id'];home=workflow.location(sid);a00=batch['request']['expected_a00']
    a01,a02=(m['current'][key] for key in ('A01','A02'));binding={'study_id':sid,'a00':a00,'plan_id':plan['plan_id'],
        'parameter_hash':plan['plan']['parameter_hash'],'current':deepcopy(m['current']),
        'authorization_kind':'delegated_system_batch','authorization_file':deepcopy(batch_ref)}
    request={'schema_version':STAGES_VERSION,'study_id':sid,'binding':binding,'request':{
        'stage':'A03','expected_a00':a00,'expected_plan_id':plan['plan_id'],'expected_input_hash':fingerprint(binding),
        'operator':batch['request']['author'],'reason':batch['request']['note'],'confirmed':True},
        'confirmation_basis':'原一次明确批次授权派生，不表示另一次人工点击','system_batch_file':deepcopy(batch_ref)}
    path=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'derived_requests'/(new_id('stage_request')+'.json')
    write_json(path,request);request_ref=file_record(home,path,'plan_stage_request');m.setdefault('analysis_plan_stage_requests',[]).append(request_ref)
    inputs={'study_id':sid,'bound_a00':a00,'analysis_plan_id':plan['plan_id'],'analysis_plan_file':deepcopy(batch['plan_file']),
        'analysis_parameter_hash':plan['plan']['parameter_hash'],'intake_result':deepcopy(m['runs'][a00]['result_file']),
        'a01_result':deepcopy(m['runs'][a01]['result_file']),'a02_result':deepcopy(m['runs'][a02]['result_file']),
        'execution_request_file':request_ref,'payload':payload_from(workflow.result(m,a01),workflow.result(m,a02))}
    _,summary,tables=a03_facts(home,inputs);intake=workflow.result(m,a00)['summary']
    return inputs,dict(CONFIG,version=A03_VERSION),summary,tables,[
        '交集及排序取同批标准化原结果；系统依赖校验不表示人工批准。'],[
        batch['plan_file'],request_ref,inputs['intake_result'],inputs['a01_result'],inputs['a02_result']],venn_svg(summary,intake['formula'],intake['disease'])
