"""真实科学校验回执：独立于人工reviews，只记录规范验证器实际执行，不授予旧流程批准。"""
from copy import deepcopy
from pathlib import Path
import hashlib
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock

VERSION='ModuleA.system_validation.1'
INDEX='analysis_plan_system_validation_records'
REQUESTS='analysis_plan_system_validation_requests'
FIELDS={'request_id','expected_run_id','expected_input_hash'}


def canonical_validator(root,module):
    """取生产规范实现，登记补充使用原契约；不接受用户提供的validator。"""
    if module=='A00':
        from science_modules.system_checks import intake
        return intake
    from .kernel import full_workflow
    return full_workflow(root).validators.get(module)


def read_receipt(workflow,m,reference):
    """核验完整历史系统回执/请求/代码/结果，不把历史通过自动当当前可用。"""
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,reference))
    require(value.get('schema_version')==VERSION and value.get('study_id')==m['study_id']
            and value.get('authority_kind')=='system_validation' and type(value.get('passed')) is bool,
            '系统校验回执版本、研究或结果类型无效')
    safe_id(value['validation_id'],'sysvalidation');safe_id(value['request_id'],'syscheckreq')
    require(value.get('human_review_written') is False and value.get('grants_legacy_approval') is False,'系统校验回执不能冒充人工批准')
    require(value['request_file'] in m.get(REQUESTS,[]),'系统校验请求未登记到本研究')
    request=read_json(verified_file(home,value['request_file']))
    require(request.get('schema_version')==VERSION and request.get('study_id')==m['study_id']
            and request['request_hash']==fingerprint(value['request'])==fingerprint(request['request'])
            and value['request']['request_id']==value['request_id'],'系统校验请求与回执不一致')
    rid=value['run_id'];run=workflow.run(m,rid);result=workflow.result(m,rid);snapshot=value['binding']
    require(run['module_id']==value['module_id'] and snapshot['study_id']==m['study_id']
            and snapshot['module_id']==value['module_id'] and result is not None
            and snapshot['run_file']==m['runs'][rid]['run_file'] and snapshot['result_file']==m['runs'][rid]['result_file']
            and value['input_hash']==fingerprint(snapshot)==value['request']['expected_input_hash']
            and value['request']['expected_run_id']==rid,'系统校验未绑定真实运行、结果和原请求')
    require(hashlib.sha256(verified_file(home,value['validator_code']).read_bytes()).hexdigest()==value['validator_sha256'],
            '系统验证器源码指纹不一致')
    for ref in (snapshot['run_file'],snapshot['result_file'],snapshot['a00_result']):verified_file(home,ref)
    for refs in snapshot['parent_files'].values():
        for ref in refs.values():
            if ref is not None:verified_file(home,ref)
    for run_id,refs in snapshot['dependency_files'].items():
        require(m['runs'].get(run_id)==refs,'系统回执所绑定的历史依赖已改变')
        for ref in refs.values():
            if ref is not None:verified_file(home,ref)
    checks=value.get('checks');require(isinstance(checks,list) and checks and all(isinstance(row,dict) and row.get('name')
        and type(row.get('passed')) is bool for row in checks) and value['passed']==all(row['passed'] for row in checks),
        '系统校验回执缺少实际检查结论')
    require(value.get('scientific_status')==scientific_status(result,value['passed']),'系统校验不能将失败、NA或关键待核改成成功')
    return value


def scientific_status(result,passed):
    """规范一致与科学执行结论分列；通过校验不消除失败或原交接阻塞。"""
    blocked=bool(result['summary'].get('handoff_blocked'))
    return {'result_outcome':result['outcome'],'handoff_blocked':blocked,
            'ready_for_successor':bool(passed and result['outcome']!='failed' and not blocked),
            'note_zh':'校验只检查本模块记录与证据一致；失败、NA及原交接阻塞仍按实际结果处理。'}


def binding(workflow,sid,rid):
    """固定实际当前运行、结果、完整父输入和原人工记录；绝不制造替代审核。"""
    m=workflow.load(sid);run=workflow.run(m,rid);home=workflow.location(sid)
    require(not m.get('trashed'),'回收站研究只读')
    require(m['current'].get(run['module_id'])==rid,'待校验运行已改变，请刷新')
    result=workflow.result(m,rid);require(result is not None,'运行尚未完整归档，不能校验')
    a00=m['current'].get('A00');intake=workflow.result(m,a00)['summary'] if a00 else {}
    require(intake.get('analysis_plan_profile')=='ModuleA.analysis_plan.1','仅新方案研究支持独立系统校验协议')
    require(all(m['current'].get(module)==parent for module,parent in run['parent_runs'].items()),'待校验运行的上游已改变')
    dependency_files={};visiting=set()
    def visit(run_id):
        """逐层核对真实依赖，不允许当前父运行仍指向已替换祖先。"""
        require(run_id not in visiting,'运行依赖存在循环')
        if run_id in dependency_files:return
        visiting.add(run_id);parent=workflow.run(m,run_id)
        require(m['current'].get(parent['module_id'])==run_id,'待校验运行的上游已改变，请刷新')
        require(workflow.result(m,run_id) is not None,'上游运行尚未完整归档，不能校验')
        dependency_files[run_id]=deepcopy(m['runs'][run_id])
        for value in parent['parent_runs'].values():visit(value)
        visiting.remove(run_id)
    visit(rid)
    for ref in m.get('reviews',[]):verified_file(home,ref)
    value={'study_id':sid,'module_id':run['module_id'],'run_file':deepcopy(m['runs'][rid]['run_file']),
           'result_file':deepcopy(m['runs'][rid]['result_file']),'a00_result':deepcopy(m['runs'][a00]['result_file']),
           'inputs':deepcopy(run['inputs']),'parent_runs':deepcopy(run['parent_runs']),
           'parent_files':{module:deepcopy(m['runs'][parent]) for module,parent in run['parent_runs'].items()},
           'dependency_files':dependency_files,
           'reviews':deepcopy(m.get('reviews',[])),'config_hash':run['config_hash'],'input_hash':run['input_hash']}
    return m,run,result,value


def request(workflow,sid,rid):
    """只读取得实际指纹，不计算、联网或生成校验记录。"""
    _,run,_,snapshot=binding(workflow,sid,rid)
    return {'module_id':run['module_id'],'expected_run_id':rid,'expected_input_hash':fingerprint(snapshot)}


def validate_request(workflow,sid,body):
    """HTTP与后台共用只读校验；字段或输入变化不产生任务和记录。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'系统校验请求字段不完整或含未支持选项')
    safe_id(body['request_id'],'syscheckreq');safe_id(body['expected_run_id'],'run')
    value=request(workflow,sid,body['expected_run_id'])
    require(body['expected_input_hash']==value['expected_input_hash'],'系统校验输入或复核已改变，请刷新')
    return value


def info(workflow,sid):
    """只读当前模块资格及历史校验，GET不导入科学环境、不执行验证器。"""
    m=workflow.load(sid);a00=m['current'].get('A00')
    intake=workflow.result(m,a00) if a00 else None
    supported=bool(intake and intake['summary'].get('analysis_plan_profile')=='ModuleA.analysis_plan.1')
    history=[]
    for ref in m.get(INDEX,[]):
        value=read_receipt(workflow,m,ref);status=value['scientific_status']
        label='证据校验未通过' if not value['passed'] else '证据一致；计算失败' if status['result_outcome']=='failed' else '证据一致；原条件仍阻塞' if status['handoff_blocked'] else '证据校验通过'
        history.append(dict(value,file=deepcopy(ref),label_zh=label))
    items=[]
    if supported:
        from contracts import ContractError
        for module,rid in m['current'].items():
            blockers=[];expected=None
            try:
                value=request(workflow,sid,rid)
                expected={key:value[key] for key in ('expected_run_id','expected_input_hash')}
            except ContractError as error:blockers.append(str(error))
            current=[row for row in history if row['run_id']==rid and expected
                     and row['input_hash']==expected['expected_input_hash']]
            items.append({'module_id':module,'run_id':rid,'enabled':not blockers,'blockers':blockers,
                          'request':expected,'current':current[-1] if current else None})
    return {'schema_version':VERSION,'supported':supported,'items':items,'history':history,
            'message_zh':'独立系统校验将真实复算已归档结果；与人工复核分开，失败和NA不会改成成功。'}


def validate_run(workflow,sid,body):
    """公开Workflow委托：真实规范验证器在锁外执行，回执与原件锁内绑定，失败如实保存。"""
    validate_request(workflow,sid,body)
    with write_lock(workflow.root):
        m,run,result,snapshot=binding(workflow,sid,body['expected_run_id']);home=workflow.location(sid)
        require(body['expected_input_hash']==fingerprint(snapshot),'系统校验输入或复核已改变，请刷新')
        for ref in m.get(INDEX,[]):
            old=read_receipt(workflow,m,ref)
            if old['request_id']==body['request_id']:
                require(old['request']==body,'校验请求编号已用于其他输入')
                return old
        for ref in m.get(REQUESTS,[]):
            old=read_json(verified_file(home,ref))
            require(old['request']['request_id']!=body['request_id'],'该校验请求已受理，尚无终态回执，不重复执行')
        # 验证器由生产注册表取得，不能由请求或调用者自选lambda假校验。
        validator=canonical_validator(workflow.root,run['module_id'])
        require(validator is not None,'本模块尚未登记系统科学校验器，不能生成通过回执')
        identity={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),'created_at':now()}
        folder=home/'decisions/analysis_plans/system_validations';path=folder/'requests'/(body['request_id']+'.json')
        write_json(path,identity);request_ref=file_record(home,path,'system_validation_request')
        m.setdefault(REQUESTS,[]).append(request_ref);workflow.save(m)
        source=Path(validator.__code__.co_filename);source_bytes=source.read_bytes();source_hash=hashlib.sha256(source_bytes).hexdigest()
    passed=False;error=None
    try:
        validator(run,result['summary'],result['tables'],result['anomalies'],result['outcome'])
        require(hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,'验证器在校验期间改变')
        passed=True
    except Exception as failure:error=f'{type(failure).__name__}: {failure}'
    with write_lock(workflow.root):
        current,_,_,current_binding=binding(workflow,sid,body['expected_run_id'])
        require(fingerprint(current_binding)==body['expected_input_hash'],'校验期间输入或复核已改变，不发布通过回执')
        validation_id=new_id('sysvalidation');target=folder/validation_id
        implementation=target/'validator.py';implementation.parent.mkdir(parents=True,exist_ok=False);implementation.write_bytes(source_bytes)
        receipt={'schema_version':VERSION,'validation_id':validation_id,'study_id':sid,'module_id':run['module_id'],
                 'run_id':run['run_id'],'authority_kind':'system_validation','request_id':body['request_id'],'request':deepcopy(body),
                 'request_file':request_ref,'binding':snapshot,'input_hash':fingerprint(snapshot),'passed':passed,
                 'scientific_status':scientific_status(result,passed),
                 'validator_code':file_record(home,implementation,'system_validator_source'),'validator_sha256':source_hash,
                 'checks':[{'name':'实际规范科学验证器 '+run['module_id'],'passed':passed,'error_zh':error}],
                 'created_at':now(),'error_zh':error,'human_review_written':False,'grants_legacy_approval':False,
                 'note_zh':'系统校验回执独立归档，不创建人工签名、不写reviews、不改变当前运行，也不替旧流程批准。'}
        path=target/'validation.json';write_json(path,receipt);ref=file_record(home,path,'system_validation_record')
        current.setdefault(INDEX,[]).append(ref);workflow.save(current)
    return receipt
