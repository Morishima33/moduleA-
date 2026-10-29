"""同一次系统批次的受体名单与固定准备输入；独立于人工选择复核记录。"""
from copy import deepcopy
from pathlib import Path
from contracts import ContractError,fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution as execution

VERSION='ModuleA.system_decision.1'
INDEX='analysis_plan_system_decisions'
FAILURES='analysis_plan_system_decision_failures'
STAGES={'A04_SELECTION':{'A04'},'A06_INPUT':{'A00','A03','A03_SELECT','A04'}}


def read_record(workflow,m,ref):
    """只读核验完整历史归档，不计算科学名单，不把旧记录视为当前有效。"""
    home=workflow.location(m['study_id']);require(ref in m.get(INDEX,[]),'系统选择记录未登记')
    value=read_json(verified_file(home,ref))
    require(value.get('schema_version')==VERSION and value.get('study_id')==m['study_id']
        and value.get('stage') in STAGES and value.get('state')=='completed'
        and value.get('authority_kind')=='system_validation' and value.get('human_review_written') is False,
        '系统选择记录不能冒充人工批准')
    safe_id(value['decision_id'],'systemdecision')
    batch,plan=execution.read_batch(workflow,m,value['binding']['batch_file'])
    require(value['batch_id']==batch['batch_id'] and value['request']['batch_id']==batch['batch_id']
        and value['request']['stage']==value['stage'] and value['binding']['plan_file']==batch['plan_file']
        and value['request_hash']==fingerprint(value['request']) and value['input_hash']==fingerprint(value['binding'])
        and value['payload_hash']==fingerprint(value['payload']),'系统选择授权、请求或输入指纹无效')
    require(set(value['binding']['parent_runs'])==STAGES[value['stage']]
        and set(value['binding']['parent_validation_records'])==STAGES[value['stage']], '系统选择真实父依赖缺失')
    for module,rid in value['binding']['parent_runs'].items():
        require(value['binding']['parent_files'][module]==m['runs'][rid],'系统选择历史来源已改变')
        for source in value['binding']['parent_files'][module].values():
            if source:verified_file(home,source)
    for module,source in value['binding']['parent_validation_records'].items():
        from .system_validation import read_receipt
        receipt=read_receipt(workflow,m,source)
        require(receipt['passed'] and receipt['module_id']==module and receipt['run_id']==value['binding']['parent_runs'][module],
            '系统选择原规范回执未通过或父运行不一致')
    for source in value['implementation_files']:verified_file(home,source)
    require(value['implementation_files'],'系统选择缺少实际实现源码')
    if value['stage']=='A06_INPUT':
        selected=read_record(workflow,m,value['binding']['selection_ref'])
        require(selected['stage']=='A04_SELECTION' and selected['batch_id']==value['batch_id'],'固定输入选择不属于同批')
        require(value['payload']['schema_version']=='A06.system_preparation_input.1'
            and value['payload']['human_reviews']=={} and value['payload']['human_review_written'] is False,
            '系统准备输入不能制造选择复核或人工签名')
        packet=value['payload'];core={key:item for key,item in packet.items() if key not in
            ('input_key','pair_count','structure_preparation_state','execution_available')}
        require(packet['runs']==value['binding']['parent_runs'] and packet['validation_records']==value['binding']['parent_validation_records']
            and packet['plan_ref']==batch['plan_file'] and packet['batch_file']==value['binding']['batch_file']
            and packet['a04_system_selection_ref']==value['binding']['selection_ref']
            and packet['receptors']==selected['payload']['selected'] and packet['input_key']==fingerprint(core)
            and packet['pair_count']==len(packet['compounds'])*len(packet['receptors']), '系统固定输入与实际依赖或受体名单不一致')
    else:
        require(value['payload']['network_run_id']==value['binding']['parent_runs']['A04']
            and value['payload']['analysis_parameter_hash']==plan['plan']['parameter_hash'], '系统受体名单与网络或方案不一致')
    return value


def active(workflow,m,value):
    """当前资格只消费真实规范回执；草稿更新不更换批次，人工暂存仍否决。"""
    try:
        execution.require_batch(workflow,m,value['binding']['batch_file'])
        parents=value['binding']['parent_runs']
        require(all(m['current'].get(key)==rid for key,rid in parents.items()),'系统选择上游已改变')
        require(execution.parent_records(workflow,m,parents)==value['binding']['parent_validation_records'],'系统选择父回执已改变')
        if value['stage']=='A06_INPUT':require(active(workflow,m,read_record(workflow,m,value['binding']['selection_ref'])),'系统受体选择已失效')
        return True
    except ContractError:return False


def current(workflow,m,batch_id,stage):
    values=[(ref,read_record(workflow,m,ref)) for ref in m.get(INDEX,[])]
    matches=[(ref,value) for ref,value in values if value['batch_id']==batch_id and value['stage']==stage]
    return matches[-1] if matches else (None,None)


def info(workflow,sid,batch_id):
    """无任务副作用的内部系统选择摘要；完整执行界面尚未开放。"""
    m=workflow.load(sid);items=[]
    for stage in STAGES:
        ref,value=current(workflow,m,batch_id,stage)
        items.append({'stage':stage,'current':dict(value,file=ref) if value else None,
            'active':bool(value and active(workflow,m,value))})
    return {'schema_version':VERSION,'items':items,'automatic_execution_available':False}


def _execute(workflow,sid,body):
    require(isinstance(body,dict) and set(body)=={'batch_id','stage','expected_decision_id'},'系统选择请求字段错误，不接受客户端名单或批准')
    safe_id(body['batch_id'],'systembatch');require(body['stage'] in STAGES,'系统选择尚未支持此阶段')
    if body['expected_decision_id'] is not None:safe_id(body['expected_decision_id'],'systemdecision')
    m=workflow.load(sid);home=workflow.location(sid)
    batch_ref=next((r for r in m.get(execution.BATCHES,[]) if execution.read_batch(workflow,m,r)[0]['batch_id']==body['batch_id']),None)
    require(batch_ref,'找不到本研究系统批次');batch,plan=execution.require_batch(workflow,m,batch_ref)
    old_ref,old=current(workflow,m,batch['batch_id'],body['stage'])
    if old:
        require(old['request']==body and active(workflow,m,old),'本批系统选择已生成或失效，不静默替换')
        return dict(old,file=old_ref,created=False)
    require(body['expected_decision_id'] is None,'系统选择当前版本已改变')
    parents={key:m['current'].get(key) for key in STAGES[body['stage']]};require(all(parents.values()),'系统选择上游未齐')
    execution.ensure_parents(workflow,sid,parents);m=workflow.load(sid)
    for module,rid in parents.items():
        if module!='A00':
            run=workflow.run(m,rid)
            require(run.get('execution_protocol')==execution.VERSION and run.get('batch_file')==batch_ref,'系统选择要求同批真实系统执行结果')
    binding={'batch_file':deepcopy(batch_ref),'plan_file':deepcopy(batch['plan_file']),'parent_runs':parents,
        'parent_files':{key:deepcopy(m['runs'][rid]) for key,rid in parents.items()},
        'parent_validation_records':execution.parent_records(workflow,m,parents),'selection_ref':None}
    if body['stage']=='A06_INPUT':
        selected_ref,selected=current(workflow,m,batch['batch_id'],'A04_SELECTION')
        require(selected and active(workflow,m,selected),'请先生成本批真实系统受体选择')
        binding['selection_ref']=deepcopy(selected_ref)
    from science_modules.a06 import system_input as science
    implementation=[(path,path.read_bytes()) for path in science.implementation_files()]
    payload=science.facts(workflow,m,body['stage'],binding,plan['plan'])
    # 不从调用者validator取科学结论；生产事实函数重建完整名单和固定输入。
    science.validate(workflow,m,body['stage'],binding,plan['plan'],payload)
    with write_lock(workflow.root):
        latest=workflow.load(sid);execution.require_batch(workflow,latest,batch_ref)
        require(active(workflow,latest,{'stage':body['stage'],'binding':binding}),'计算期间系统选择上游或人工决定已改变')
        require(current(workflow,latest,batch['batch_id'],body['stage'])[1] is None,'系统选择已由其他任务生成')
        require(all(path.read_bytes()==raw for path,raw in implementation),'系统选择计算期间实现源码已改变')
        decision_id=new_id('systemdecision');folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'decisions'/decision_id
        implementations=[]
        for path,raw in implementation:
            target=folder/'implementation'/path.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            implementations.append(file_record(home,target,'system_decision_implementation'))
        value={'schema_version':VERSION,'study_id':sid,'decision_id':decision_id,'batch_id':batch['batch_id'],'stage':body['stage'],
            'authority_kind':'system_validation','human_review_written':False,'state':'completed',
            'request':deepcopy(body),'request_hash':fingerprint(body),'binding':binding,'input_hash':fingerprint(binding),
            'payload':payload,'payload_hash':fingerprint(payload),'implementation_files':implementations,'created_at':now(),
            'note_zh':'一次明确批次派生的系统选择，不生成人工选择审核，不代表结构已经准备或评分。'}
        target=folder/'decision.json';write_json(target,value);ref=file_record(home,target,'system_decision')
        latest.setdefault(INDEX,[]).append(ref);workflow.save(latest)
    return dict(value,file=ref,created=True)


def execute(workflow,sid,body):
    """只经公开Workflow写入；合法批次失败独立留存，不发布伪名单。"""
    try:return _execute(workflow,sid,body)
    except Exception as error:
        if isinstance(body,dict) and set(body)=={'batch_id','stage','expected_decision_id'} and body.get('stage') in STAGES:
            with write_lock(workflow.root):
                m=workflow.load(sid);home=workflow.location(sid)
                ref=next((r for r in m.get(execution.BATCHES,[]) if execution.read_batch(workflow,m,r)[0]['batch_id']==body.get('batch_id')),None)
                if ref and not m.get('trashed'):
                    batch,_=execution.read_batch(workflow,m,ref)
                    value={'schema_version':VERSION,'study_id':sid,'batch_id':batch['batch_id'],'batch_file':ref,'stage':body['stage'],
                        'state':'failed','request':deepcopy(body),'error_type':type(error).__name__,'error_zh':str(error),
                        'human_review_written':False,'created_at':now()}
                    target=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'decision_failures'/(new_id('attempt')+'.json')
                    write_json(target,value);m.setdefault(FAILURES,[]).append(file_record(home,target,'system_decision_failure'));workflow.save(m)
        raise
