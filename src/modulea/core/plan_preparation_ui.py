"""新版结构准备只读资格、明确请求和完成回执，科学准备复用原第二版。"""
from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from science_modules.analysis_protocol import checked_plan
from science_modules.plan_stages_contract import binding, context

VERSION='ModuleA.plan_preparation_ui.1'
PREPARATIONS=('A06.plan_preparation.2','A06.plan_preparation.3','A06.plan_reference_preparation.1',
              'A06.plan_reference_preparation.2','A06.plan_reviewable_preparation.1')


def info(workflow,sid):
    """按实际归档版本显示进度，不联网、不预测或计算评分资格。"""
    m,intake,draft=context(workflow,sid)
    if intake.get('analysis_plan_profile')!='ModuleA.analysis_plan.1':return {'supported':False}
    record=workflow.analysis_plan_info(sid)['a06_preparation_input']
    home=workflow.location(sid);params={};scope=None;reference=None
    if record:
        packet=record['packet'];plan_record=read_json(verified_file(home,packet['plan_ref']))
        plan=checked_plan(plan_record['plan'])
        require(plan_record['study_id']==sid and plan['parameter_hash']==packet['analysis_parameter_hash'],
                '结构准备方案与本研究固定输入不一致')
        params=plan['parameters']
        scope={'compounds':packet['compounds'],'receptors':packet['receptors'],'pair_count':packet['pair_count']}
        reference=next(ref for ref in m['analysis_plan_a06_input_records'] if read_json(verified_file(home,ref))['input_id']==record['input_id'])
    rid=m['current'].get('A06_PREP');current=None;version=None;matching=False;active=False;result=None
    if rid:
        run=workflow.run(m,rid);version=run['config'].get('version');result=workflow.result(m,rid)
        active=workflow.active(m,rid)
        # 后续准备从原第二版或参考准备逐层派生，沿归档引用寻找本批固定输入。
        source=run;seen=set()
        while source['run_id'] not in seen:
            seen.add(source['run_id'])
            if source['inputs'].get('a06_plan_input'):
                matching=bool(reference and source['inputs']['a06_plan_input']==reference);break
            parent=source['inputs'].get('source_preparation_run') or source['inputs'].get('reference_preparation_run')
            if not parent:break
            source=read_json(verified_file(home,parent))
            require(source['study_id']==sid and source['module_id']=='A06_PREP','准备来源不属于本研究')
        current={'run_id':rid,'version':version,'active':active,'matches_input':matching,
                 'completed':result is not None,'approved':workflow.approved(m,rid),
                 'summary':result['summary'] if result else None}
    blockers=[]
    if m.get('trashed'):blockers.append('回收站研究只读')
    if not record:blockers.append('请先保存同研究、同方案且已复核的对接固定输入')
    if active and matching and version in PREPARATIONS and result:
        blockers.append('本批准备已归档，请核查下列证据及复核环节，不重复连接或准备')
    snapshot=binding(workflow,m,draft)
    snapshot['preparation_input']=reference
    usable=bool(active and matching and result and not m.get('trashed'))
    reference_stage=usable and version in PREPARATIONS[:2]
    reviewable=usable and version in PREPARATIONS[3:]
    steps=[{'key':'input','label':'固定输入','available':bool(record),'module':'A06_PREP','target':'plan-selection',
            'detail_zh':'已保存完整范围' if record else '成分与受体分别通过后保存'},
           {'key':'prepare','label':'结构与配体准备','available':not blockers,'module':'A06_PREP','target':'plan-preparation',
            'detail_zh':'已归档' if usable else '明确确认后连接本批来源并准备'},
           {'key':'pockets','label':'预测口袋核查','available':reference_stage,'module':'A06_PREP','target':'pockets',
            'detail_zh':'仅核查本批真实证据，不代表真实结合位点'},
           {'key':'references','label':'共晶参考核查与绑定','available':reference_stage,'module':'A06_PREP','target':'a06-reference-evidence',
            'detail_zh':'参考证据须实际核查，缺失保留原因'},
           {'key':'review','label':'准备整体复核','available':reviewable,'module':'A06_PREP','target':'a06-reviewable-preparation',
            'detail_zh':'同批资料复验后由原复核栏明确决定'},
           {'key':'scoring','label':'明确执行评分','available':usable and version==PREPARATIONS[-1],'module':'A06','target':'a06-plan-scoring',
            'detail_zh':'是否可评分以评分区实际条件和人工批准为准'}]
    return {'supported':True,'enabled':not blockers,'blockers':blockers,'input_hash':fingerprint(snapshot),
            'expected_input_id':record['input_id'] if record else '', 'expected_preparation_run_id':rid,
            'parameters':params,'scope':scope,'current':current,'steps':steps,
            'message_zh':'按本批固定范围连接官方原件并准备；失败保留NA及原因，不换对象、不评分或自动批准。'}


def validate(workflow,sid,body):
    """固定全部输入/准备/复核版本，客户端不能注入路径、参数或结果。"""
    fields={'request_id','expected_input_id','expected_preparation_run_id','expected_input_hash','author','note','confirmed'}
    require(isinstance(body,dict) and set(body)==fields,'新版准备入口字段不完整或含未支持选项')
    safe_id(body['request_id'],'planprep');safe_id(body['expected_input_id'],'input')
    require(body['expected_preparation_run_id'] is None or safe_id(body['expected_preparation_run_id'],'run'),'当前准备编号格式错误')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000
        for k in ('author','note')),'请填写结构准备执行人与依据并明确确认，最多2000字')
    value=info(workflow,sid)
    require(value['supported'],'上游研究不支持新版结构准备入口')
    require(not workflow.load(sid).get('trashed'),'回收站研究只读')
    require(body['expected_input_hash']==value['input_hash'] and all(body[k]==value[k] for k in ('expected_input_id','expected_preparation_run_id')),
            '固定输入、准备或复核已改变，请刷新后重新确认')
    require(value['enabled'],'上游条件未就绪：'+'；'.join(value['blockers']))
    return value


def begin_request(workflow,sid,body):
    """公开Workflow锁内追加明确请求，未开始科学计算也保留实际确认。"""
    with write_lock(workflow.root):
        validate(workflow,sid,body);m,_,draft=context(workflow,sid)
        home=workflow.location(sid)
        for ref in m.get('analysis_plan_preparation_ui_requests',[]):
            old=read_json(verified_file(home,ref))
            if old['request']['request_id']==body['request_id']:
                require(old['request_hash']==fingerprint(body),'准备请求编号已用于其他输入或说明，请刷新')
                return ref
        snapshot=binding(workflow,m,draft)
        snapshot['preparation_input']=next(ref for ref in m['analysis_plan_a06_input_records']
            if read_json(verified_file(home,ref))['input_id']==body['expected_input_id'])
        request={'schema_version':VERSION,'study_id':sid,'created_at':now(),'request':dict(body),
                 'request_hash':fingerprint(body),'binding':snapshot}
        require(body['expected_input_hash']==fingerprint(snapshot),'准备输入快照已改变，请刷新')
        path=workflow.location(sid)/'decisions/analysis_plans/preparation_requests'/(new_id('preparation_request')+'.json')
        write_json(path,request);ref=file_record(workflow.location(sid),path,'plan_preparation_request')
        m.setdefault('analysis_plan_preparation_ui_requests',[]).append(ref);workflow.save(m)
        return ref


def finish_request(workflow,sid,reference,run_id):
    """成功回执只绑定科学子进程实际第二版事实包，不伪造运行或复核。"""
    with write_lock(workflow.root):
        m=workflow.load(sid);home=workflow.location(sid)
        require(reference in m.get('analysis_plan_preparation_ui_requests',[]),'准备请求未登记到本研究')
        request=read_json(verified_file(home,reference));run=workflow.run(m,run_id);result=workflow.result(m,run_id)
        require(run['module_id']=='A06_PREP' and run['config'].get('version')==PREPARATIONS[0] and result,
                '准备回执缺少实际第二版结果')
        require(m['current'].get('A06_PREP')==run_id and run['inputs']['a06_plan_input']==request['binding']['preparation_input'],
                '实际准备或固定输入已有后续版本，请刷新核查')
        fact=read_json(verified_file(home,result['tables']['preparation_packet'][0]))
        source=read_json(verified_file(home,run['inputs']['a06_plan_input']))
        require(request['study_id']==sid and fact['request_id']==request['request']['request_id']
                and source['input_id']==request['request']['expected_input_id']
                and fact['author']==request['request']['author'].strip() and fact['note']==request['request']['note'].strip(),
                '实际准备与明确请求不一致')
        receipt={'schema_version':VERSION,'study_id':sid,'created_at':now(),'request':reference,
                 'run_id':run_id,'result_file':m['runs'][run_id]['result_file']}
        path=home/'decisions/analysis_plans/preparation_receipts'/(new_id('preparation_receipt')+'.json')
        write_json(path,receipt);m.setdefault('analysis_plan_preparation_ui_receipts',[]).append(file_record(home,path,'plan_preparation_receipt'))
        workflow.save(m)
        return receipt
