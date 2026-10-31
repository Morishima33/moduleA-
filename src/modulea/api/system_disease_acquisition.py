"""疾病五库获取的标准库资格、实际逐库事实和明确任务入口；HTTP不采集或解析。"""
from contracts import ContractError
from ..core import system_disease_acquisition as core,system_disease_publication as publication
from .errors import ApiError,from_contract


def info(app,req,sid):
    """逐请求读取原确认及成功检查点；不把缺失、失败或未写整批当零或完成。"""
    w=app.kernel.workflow();m=w.load(sid);value=core.info(w,sid);value['busy']=bool(app.tasks.active_for(sid));value['requests']=[]
    intake=w.result(m,m['current']['A00'])['summary'] if m['current'].get('A00') else {}
    value['disease_identity_zh']=intake.get('mesh_verification',{}).get('preferred_term','')
    groups={kind:[core.read_record(w,m,ref,kind=kind) for ref in m.get(index,[])]
        for kind,index in (('record',core.RECORDS),('source',core.SOURCES),('failure',core.FAILURES))}
    for ref in m.get(core.REQUESTS,[]):
        request=core.read_record(w,m,ref,kind='request');records=[r for r in groups['record'] if r['request_file']==ref]
        ready=[r['source'] for r in groups['source'] if r['request_file']==ref]
        failures=[r for r in groups['failure'] if r['request_file']==ref];latest=records[-1] if records else None;blockers=[]
        try:core.require_current(w,m,request)
        except ContractError as error:blockers.append(str(error))
        if value['busy']:blockers.append('请等待当前研究后台任务结束')
        rows={r['database']:r for r in (latest['sources'] if latest else [])};rows.update({r['database']:r for r in ready})
        display=[]
        for db in core.DATABASES:
            row=rows.get(db)
            display.append({'database':db,'state':row['state'] if row else 'not_recorded',
                'state_label_zh':{'ready':'已核验归档','failed':'获取或核验失败','missing':'尚缺本研究原件'}[row['state']] if row else '尚未形成获取记录',
                'records_text_zh':str(row['parsed_records']) if row and row['state']=='ready' else '未取得有效结果',
                'reason_zh':row['reason_zh'] if row else '尚无本库成功检查点或整批结果，不作为0条记录'})
        pub=publication.info(w,m,request['request']['request_id']) if records else {
            'enabled':False,'blockers':['原件尚未形成完整获取记录'],'published_run_id':None,'request':None}
        if value['busy']:pub['enabled']=False;pub['blockers'].append('请等待当前研究后台任务结束')
        published=w.result(m,pub['published_run_id']) if pub['published_run_id'] else None
        if published:
            # 获取记录本身保留原事实；当前展示不能仍把已发布候选说成尚未发布。
            for item in display:item['reason_zh']=item['reason_zh'].replace('；未发布疾病候选','；对应疾病候选已发布，获取原件保持')
            if blockers and not value['blockers'] and m.get('current_source_staging')==request['binding']['staging_file']:
                blockers=['本次原件已发布候选，原获取确认不再用于补取；需更新资料时请按当前状态重新确认。']
        pub['candidate_count_text_zh']=str(published['summary']['候选记录数']) if published else '尚未发布'
        pub['message_zh']='已发布本研究原始候选；后续标准化和报告请查看执行批次，不代表人工复核通过。' if published else '原件完整后可明确整理候选；候选尚不是标准化疾病基因集合。'
        value['requests'].append({'request_id':request['request']['request_id'],'request':request['request'],
            'plan_id':request['request']['expected_plan_id'],'created_at':request['created_at'],
            'state':latest['state'] if latest else 'not_recorded','state_label_zh':'五库原件完整归档' if latest and latest['state']=='complete'
                else '最近整批原件未齐' if latest else '尚未形成整批记录','display_sources':display,
            'retry_enabled':not blockers,'retry_blockers':blockers,'record_count':len(records),'source_receipt_count':len(ready),
            'failure_count':len(failures),'publication':pub,
            'message_zh':'获取时五库原件完整归档，本次原件已发布候选；后续科学状态见执行批次。' if published else
                latest['message_zh'] if latest else '成功检查点已保存；未形成整批不表示查询完成'})
    if value['busy']:value['enabled']=False;value['blockers'].append('请等待当前研究后台任务结束')
    value['message_zh']='获取只保存疾病原件，不发布A02候选或批准科研结果；GeneCards、OMIM缺失需提供本研究原件。'
    return value


def execute(app,req,sid):
    """严格明确确认后仅排队，实际原件处理与排队后复核交给科学worker。"""
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待本研究当前任务结束')
    try:body=core.validate_request(app.kernel.workflow(),sid,req.json())
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_system_disease_acquisition',body['author'],body)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究当前已有任务，请在任务结束后明确重试')
    return {'task':task,'created':True,'request_id':body['request_id'],
        'message_zh':'已提交疾病原件获取；成功库保留，缺失或失败会使任务失败，不发布A02。'},202


def publish(app,req,sid):
    """明确候选发布只做标准库预检并排队，科学整理在独立worker。"""
    if app.tasks.active_for(sid):raise ApiError(409,'GATE_BLOCKED','请等待本研究当前任务结束')
    try:body=publication.validate_request(app.kernel.workflow(),sid,req.json())
    except ContractError as error:raise from_contract(str(error)) from error
    task,created=app.tasks.submit(sid,'plan_system_disease_publication',body['author'],body)
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究当前已有任务，请在任务结束后明确重试')
    return {'task':task,'created':True,'request_id':body['request_id'],
        'message_zh':'已提交完整疾病原件的候选整理；候选仍需后续标准化，不批准科研结果。'},202
