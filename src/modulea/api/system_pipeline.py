"""统一后台执行的标准库接口：一次批次确认、明确续做及真实流水只读。"""
from contracts import ContractError,require
from storage import read_json,verified_file
from ..core import system_execution,system_pipeline
from .errors import ApiError,from_contract


def info(app,req,sid):
    """只读已有批次与流水；不联网计算、不自动重试或替用户确认。"""
    w=app.kernel.workflow();value=system_pipeline.info(w,sid);value['start']=system_execution.info(w,sid)
    try:system_pipeline.required_inputs(w,w.load(sid))
    except ContractError as error:
        value['start']['enabled']=False;value['start']['blockers'].append(str(error))
    m=w.load(sid);home=w.location(sid);value['busy']=bool(app.tasks.active_for(sid))
    intake=w.result(m,m['current']['A00'])['summary'] if m['current'].get('A00') else {}
    value['study_label_zh']=str(intake.get('formula',''))+' 与 '+str(intake.get('disease',''))
    value['purpose_zh']='流程测试，仅用于技术核验，不作为正式研究结论' if intake.get('analysis_purpose')=='workflow_test' else '研究计算用于提出待验证线索，结论仍需独立复核'
    from science_modules.analysis_protocol import FIELDS
    def parameters(plan):
        return {'parameter_hash':plan['parameter_hash'],'mode_label_zh':'标准自动版' if plan['mode']=='standard' else '个性化版',
            'parameters':[{'key':key,'label_zh':field['label'],'value':plan['parameters'][key],'unit':field.get('unit','')} for key,field in FIELDS.items()]}
    plans=[read_json(verified_file(home,r)) for r in m.get('analysis_plan_records',[])]
    draft=next((p for p in plans if p['plan_id']==value['start']['expected_plan_id']),None)
    if draft:value['start'].update(parameters(draft['plan']))
    labels=dict(zip(system_pipeline.STAGES,('三库标准化','疾病标准化','交集','成分选择','PPI网络','GO与KEGG富集','受体选择','固定结构范围','结构准备','准备资格','对接评分','双报告')))
    for item in value['batches']:
        batch,plan=system_execution.read_batch(w,m,item['batch_file']);item.update(parameters(plan['plan']));blockers=[]
        try:
            system_pipeline.batch_for(w,m,item['batch_id']);system_pipeline.required_inputs(w,m,batch)
        except ContractError as error:blockers.append(str(error))
        if value['busy']:blockers.append('请等待当前研究后台任务结束')
        item['continue_enabled']=not blockers;item['continue_blockers']=blockers
        for entry in item['history']:
            entry['stage_label_zh']=labels.get(entry.get('stage'),'本批执行')
            entry['state_label_zh']=('不适用' if entry.get('state')=='not_applicable' else '阶段已归档') if entry['event']=='stage' else {
                'started':'已登记执行','finished':'报告待结论复核','failed':'执行失败，原件保留'}[entry['event']]
        item['latest_event']=item['history'][-1] if item['history'] else None
    value['automatic_execution_available']=True
    return value


def execute(app,req,sid,*,start=False):
    """HTTP只登记原一次授权并排队，科学处理在独立worker；缺资料仍如实失败。"""
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待本研究当前任务结束')
    w=app.kernel.workflow();body=req.json()
    try:
        require(not w.load(sid).get('trashed'),'回收站研究只读')
        if start:
            m=w.load(sid);original=None
            for ref in m.get(system_execution.BATCHES,[]):
                candidate,_=system_execution.read_batch(w,m,ref)
                if isinstance(body,dict) and candidate['request']['request_id']==body.get('request_id'):original=candidate;break
            # 新确认先查必需五库原件；原确认重试仍按原批绑定的原件核对。
            system_pipeline.required_inputs(w,m,original)
            batch=w.start_analysis_plan_foundation_system_batch(sid,body);m=w.load(sid)
            payload={'batch_id':batch['batch_id'],'expected_input_hash':system_pipeline.state_hash(w,m,batch['file'])}
        else:
            batch=system_pipeline.validate_request(w,sid,body);payload=body
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_system_pipeline',batch['request']['author'],payload)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究当前已有任务；已登记批次保留，可在任务结束后明确续做')
    return {'task':task,'created':True,'batch_id':batch['batch_id'],
        'message_zh':'已提交本批统一后台执行；失败和NA保留，结论仍需独立复核。'},202
