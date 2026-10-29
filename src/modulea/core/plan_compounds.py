"""方案成分名单的只读资格与公开Workflow发布服务，HTTP不计算名单。"""
from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, read_json, write_json, write_lock
from science_modules.plan_stages_contract import binding, context, plan_reference


def info(workflow,sid):
    """读取原A03完整排名及实际已保存名单，资格不替代科学选择或人工复核。"""
    manifest,intake,draft=context(workflow,sid)
    supported=intake.get('analysis_plan_profile')=='ModuleA.analysis_plan.1'
    a03=manifest['current'].get('A03','');selected=manifest['current'].get('A03_SELECT','')
    blockers=[]
    if not supported:blockers.append('历史固定研究保持原成分选择')
    if manifest.get('trashed'):blockers.append('回收站研究只读')
    if not draft:blockers.append('当前登记没有有效方案')
    if not a03 or not workflow.approved(manifest,a03):blockers.append('请先通过当前A03')
    source=workflow.result(manifest,a03) if a03 else None
    native=bool(a03 and workflow.run(manifest,a03)['config'].get('version')=='A03.plan_intersection.1')
    if not native:blockers.append('当前A03尚不是新方案交集')
    old=workflow.result(manifest,selected) if selected else None
    current=bool(selected and workflow.active(manifest,selected) and draft
                 and workflow.run(manifest,selected)['config'].get('version')=='A03.plan_selection.1'
                 and workflow.run(manifest,selected)['inputs'].get('analysis_plan_id')==draft['plan_id'])
    if current:blockers.append('本方案已有有效成分名单，请核对或独立复核，不重复生成')
    if draft and native:
        original=next((r for r in workflow._analysis_plan_records(manifest)
                       if r['plan_id']==workflow.run(manifest,a03)['inputs'].get('analysis_plan_id')),None)
        if original and any(original['plan']['parameters'][k]!=draft['plan']['parameters'][k]
                            for k in ('a01.ob_min','a01.dl_min')):
            blockers.append('本方案A01门槛已变化，请先完成对应A01和A03')
    review=workflow.current_docking_review(manifest) if native else None
    pending=[]
    if review:
        pending=[r['compound_id'] for r in review['compounds'] if not r['identity_prechecked']]
        pending.extend(r['compound_id'] for r in review['excluded'])
    snapshot=binding(workflow,manifest,draft)
    snapshot['docking_review']=review
    params=draft['plan']['parameters'] if draft else {}
    return {'supported':supported,'enabled':not blockers,'blockers':blockers,
        'expected_a00':manifest['current'].get('A00',''),'expected_a03':a03,'expected_selection':selected,
        'expected_plan_id':draft['plan_id'] if draft else '', 'expected_input_hash':fingerprint(snapshot),
        'parameter_hash':draft['plan']['parameter_hash'] if draft else '',
        'target_count':params.get('a06.component_count'),'metric':params.get('a06.component_sort'),
        'ranking':(source or {}).get('tables',{}).get('ranking',[]),
        'identity_pending':pending,
        'current':current,'current_summary':(old or {}).get('summary'),
        'current_selected':(old or {}).get('tables',{}).get('selected',[]) if current else [],
        'message_zh':'后台按本方案数量与指标生成完整名单，保留边界并列、不足按实际；生成后仍须独立复核。'}


def validate(workflow,sid,body):
    """显式请求只绑定当前版本，不能提交名单、阈值或复核状态。"""
    fields={'expected_a00','expected_a03','expected_selection','expected_plan_id','expected_input_hash',
            'operator','reason','confirmed'}
    require(isinstance(body,dict) and set(body)==fields,'方案成分选择字段不完整或含未支持选项')
    for key,prefix in (('expected_a00','run'),('expected_a03','run'),('expected_plan_id','plan')):safe_id(body[key],prefix)
    if body['expected_selection']:safe_id(body['expected_selection'],'run')
    require(body['confirmed'] is True,'请明确确认本方案成分选择')
    require(all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('operator','reason')),
            '请填写成分选择执行人和依据，最多2000字')
    value=info(workflow,sid)
    require(not workflow.load(sid).get('trashed'),'回收站研究只读')
    require(value['supported'],'上游研究不支持新方案成分选择')
    require(all(value[k]==body[k] for k in fields if k.startswith('expected_')),'成分选择输入、复核或方案已改变，请刷新')
    require(value['enabled'],'上游条件未就绪：'+'；'.join(value['blockers']))
    return value


def publish(workflow,sid,body):
    """后台同锁复算并发布独立待复核名单；不改变A03、A04或人工reviews。"""
    from science_modules.plan_compounds import configuration,facts
    with write_lock(workflow.root):
        validate(workflow,sid,body)
        manifest,_,draft=context(workflow,sid);home=workflow.location(sid)
        plan_ref,_=plan_reference(workflow,manifest,draft['plan_id'])
        snapshot=binding(workflow,manifest,draft);snapshot['docking_review']=workflow.current_docking_review(manifest)
        request={'schema_version':'A03.plan_selection.request.1','study_id':sid,
                 'request':dict(body),'binding':snapshot}
        path=home/'decisions/analysis_plans/compound_selection_requests'/(new_id('compound_request')+'.json')
        write_json(path,request);request_ref=file_record(home,path,'compound_selection_request')
        inputs={'study_id':sid,'bound_a00':body['expected_a00'],'bound_a03':body['expected_a03'],
            'analysis_plan_id':draft['plan_id'],'analysis_parameter_hash':draft['plan']['parameter_hash'],
            'analysis_plan_file':plan_ref,'a03_result':manifest['runs'][body['expected_a03']]['result_file'],
            'execution_request_file':request_ref}
        summary,tables=facts(home,inputs)
        run=workflow._begin(manifest,'A03_SELECT',inputs,configuration(draft['plan']),body['reason'])
        result=workflow._finish(manifest,run['run_id'],summary,tables,
            ['名单按已确认方案计算；排名不代表药效，化学身份及来源结构准备分别核查。'],
            'success' if tables['selected'] else 'empty',sources=[plan_ref,inputs['a03_result'],request_ref])
        workflow.save(manifest)
        return result
