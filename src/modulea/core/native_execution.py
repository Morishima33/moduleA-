"""新平台A06运行的公开Workflow适配；同一状态/存储/队列，旧Windows运行保持原协议。"""
from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require, safe_id
from storage import new_id, now, read_json, write_json, write_lock
from .bounded_evidence import file_record, verified_file
from .system_receptor_rescue_v2 import SystemReceptorRescueV2Workflow

PREPARATION='A06.platform_preparation.1'
QUALIFIED='A06.platform_qualified_preparation.1'
SCORING='A06.platform_execution.1'
RECORDS='native_execution_records'
CHECKPOINTS='native_execution_checkpoints'


def request(stage, body):
    """新平台必须明确协议；客户端只能绑定原件和确认，不提供工具路径或科学参数。"""
    shared={'request_id','author','note','confirmed','platform_protocol'}
    require(stage in ('prepare','qualify','score'),'原生执行阶段不合法')
    expected=shared | ({'expected_input_id','expected_preparation_run_id'} if stage=='prepare' else
        {'expected_input_id','expected_preparation_run_id','decisions'} if stage=='qualify' else
        {'expected_preparation_run_id','expected_preparation_result_sha256','expected_preparation_review_id','expected_a06_run_id'})
    require(isinstance(body,dict) and set(body)==expected and body['platform_protocol']==SCORING,
            '新平台执行字段或协议不完整')
    safe_id(body['request_id'],{'prepare':'nativeprep','qualify':'nativequal','score':'nativescore'}[stage])
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
            '请明确本次新平台执行及登记人')
    for field in ('expected_preparation_run_id','expected_a06_run_id'):
        if field in body and body[field] is not None:safe_id(body[field],'run')
    if stage in ('prepare','qualify'):safe_id(body['expected_input_id'],'input')
    else:safe_id(body['expected_preparation_review_id'],'review')
    if stage=='qualify':
        from science_modules.a06.plan_pockets import validate_request
        validate_request(pocket_request(body))


def pocket_request(body):
    """本平台请求只转换原决定字段，选择与科学依据完整保留。"""
    return {'request_id':'pocketreq_'+body['request_id'].split('_',1)[1],
        'expected_input_id':body['expected_input_id'],'expected_preparation_run_id':body['expected_preparation_run_id'],
        'reviewer':body['author'],'note':body['note'],'confirmed':body['confirmed'],'decisions':deepcopy(body['decisions'])}


def source(workflow,sid,stage,body):
    """只从当前已确认固定输入或已人工批准原生准备取来源，不迁入旧批准。"""
    m=workflow.load(sid);require(not m.get('trashed'),'回收站研究只读')
    home=workflow.location(sid)
    if stage=='prepare':
        from science_modules.a06.plan_preparation_v2 import current_input
        packet,ref,plan=current_input(workflow,sid,body['expected_input_id'])
        return m,{'a06_plan_input':ref},dict(packet=packet,plan=plan)
    rid=m['current'].get('A06_PREP');continuing_qualification=False
    if stage=='qualify' and rid!=body['expected_preparation_run_id'] and rid:
        current=workflow.run(m,rid)
        require(current['config'].get('version')==QUALIFIED and workflow.active(m,rid)
            and read_json(verified_file(home,current['inputs']['native_request']))['request']==body,
            '当前原生准备已改变')
        rid=body['expected_preparation_run_id']
        continuing_qualification=True
    else:require(rid==body['expected_preparation_run_id'],'当前原生准备已改变')
    prep=workflow.run(m,rid)
    if stage=='qualify':
        require(prep['config'].get('version')==PREPARATION and (continuing_qualification or workflow.active(m,rid)),
                '请核查当前有效原生准备，不能迁入旧批')
        result=workflow.result(m,rid);require(result and result['outcome']=='success','原生准备未完整归档')
        record=read_json(verified_file(home,prep['inputs']['a06_plan_input']))
        from science_modules.a06.plan_preparation_v2 import current_input
        current_input(workflow,sid,body['expected_input_id'])
        require(record['input_id']==body['expected_input_id'],'固定输入已改变')
        refs={'source_preparation_run':m['runs'][rid]['run_file'],'source_preparation_result':m['runs'][rid]['result_file'],
              'a06_plan_input':prep['inputs']['a06_plan_input']}
        fact=read_json(verified_file(home,result['tables']['preparation_packet'][0]))
        from science_modules.a06.plan_pockets import validate_choices
        validate_choices(home,fact,pocket_request(body))
        return m,refs,dict(preparation=prep,result=result,input_record=record,fact=fact)
    require(prep['config'].get('version')==QUALIFIED and workflow.approved(m,rid),
            '须人工整体复核通过本批原生准备，旧Windows批准不能自动迁入')
    result=workflow.result(m,rid);review=workflow.latest_review(m,prep['artifact_id'])
    require(result and result['outcome']=='success' and m['runs'][rid]['result_file']['sha256']==body['expected_preparation_result_sha256']
            and review['review_id']==body['expected_preparation_review_id'],'原生准备结果或批准已改变')
    review_ref=next(ref for ref in m['reviews'] if read_json(verified_file(home,ref))['review_id']==review['review_id'])
    fact=read_json(verified_file(home,result['tables']['preparation_packet'][0]))
    require(any(row['state']=='ready' for row in result['tables']['planned_pairs']),'原生准备尚无可评分组合，NA及原因保留')
    refs={'preparation_run':m['runs'][rid]['run_file'],'preparation_result':m['runs'][rid]['result_file'],
          'preparation_review':review_ref,'a06_plan_input':prep['inputs']['a06_plan_input']}
    from science_modules.a06.plan_preparation_v2 import current_input
    input_record=read_json(verified_file(home,refs['a06_plan_input']))
    current_input(workflow,sid,input_record['input_id'])
    return m,refs,dict(preparation=prep,result=result,fact=fact,review=review,input_record=input_record)


def begin(workflow,sid,stage,body,config):
    """原写锁内登记一次明确请求；中断仍复用同run且固定输入/工具完全相同。"""
    request(stage,body)
    with write_lock(workflow.root):
        m,inputs,data=source(workflow,sid,stage,body)
        home=workflow.location(sid);module='A06' if stage=='score' else 'A06_PREP'
        for entry in m.get(RECORDS,[]):
            value=read_json(verified_file(home,entry['request']))
            if value['request']['request_id']!=body['request_id']:continue
            run=workflow.run(m,entry['run_id'])
            require(value['request']==body and value['config']==config and run['config']==config
                    and value['source_inputs']==inputs and m['current'].get(module)==run['run_id']
                    and workflow.active(m,run['run_id']),'原生请求、工具、输入或当前运行已改变，不能同批恢复')
            for ref in m.get(CHECKPOINTS,[]):
                checkpoint=read_json(verified_file(home,ref))
                if checkpoint['run_id']==run['run_id']:
                    for original in checkpoint['files']:verified_file(home,original)
            return run,bool(m['runs'][run['run_id']].get('result_file')),data
        expected=body['expected_a06_run_id'] if stage=='score' else body['expected_preparation_run_id']
        require(m['current'].get(module)==expected,'当前原生计算版本已改变，请刷新')
        value={'schema_version':SCORING,'study_id':sid,'stage':stage,'request':deepcopy(body),
               'source_inputs':deepcopy(inputs),'config':deepcopy(config),'request_hash':fingerprint(body),
               'created_at':now(),'human_review_written':False}
        path=home/'decisions/native_execution'/(body['request_id']+'.json')
        write_json(path,value);ref=file_record(home,path,'native_execution_request')
        run=workflow._begin(m,module,dict(inputs,native_request=ref),config,'明确新平台运行；全部对象保留，结果待科研复核')
        m.setdefault(RECORDS,[]).append({'request':ref,'run_id':run['run_id']})
        workflow.save(m)
        return run,False,data


def read_object(workflow,sid,run_id,key):
    """沿已有不可变检查点形状核对previous链，成功或稳定NA不可覆盖，残件不用于恢复。"""
    require(isinstance(key,str) and key.replace('_','').isalnum() and len(key)<=150,'原生检查点对象键不合法')
    m=workflow.load(sid);home=workflow.location(sid);run=workflow.run(m,run_id)
    require(run['config'].get('version') in (PREPARATION,QUALIFIED,SCORING),'检查点不是本原生协议')
    previous=None
    for ref in m.get(CHECKPOINTS,[]):
        value=read_json(verified_file(home,ref))
        require(value['schema_version']==SCORING and value['study_id']==sid,'原生检查点归属不同')
        if value['run_id']!=run_id or value['key']!=key:continue
        prefix=f'runs/{run["module_id"]}/{run_id}/native_checkpoints/{key}/'
        require(ref['path'].startswith(prefix) and value['previous']==(previous[0] if previous else None)
                and value['config_hash']==run['config_hash'] and value['human_review_written'] is False,
                '原生检查点路径、配置或登记链不同')
        if previous:require(previous[1]['payload'].get('retryable') is True,'已完成或稳定NA原生对象不可覆盖')
        for original in value['files']:verified_file(home,original)
        previous=(ref,value)
    return previous


class NativeWorkflow(SystemReceptorRescueV2Workflow):
    """新平台在同一Workflow新增明确公开方法，状态与人工批准仍由原内核提供。"""
    def execute_native_preparation(self,sid,body,*,settings,progress=None):
        from science_modules.a06.native_execution import prepare
        return prepare(self,sid,body,settings,progress or (lambda _:None))

    def execute_native_scoring(self,sid,body,*,settings,progress=None):
        from science_modules.a06.native_execution import score
        return score(self,sid,body,settings,progress or (lambda _:None))

    def qualify_native_preparation(self,sid,body,*,settings,progress=None):
        """明确口袋决定后完整复验，追加待整体人工复核版本，不提交批准。"""
        from science_modules.a06.native_execution import qualify
        return qualify(self,sid,body,settings,progress or (lambda _:None))

    def read_native_checkpoint(self,sid,run_id,key):
        return read_object(self,sid,run_id,key)

    def append_native_checkpoint(self,sid,run_id,key,payload,files):
        """原研究索引/写锁/原件核验下追加分对象记录，不新增数据库或调度层。"""
        with write_lock(self.root):
            m=self.load(sid);run=self.run(m,run_id);home=self.location(sid)
            require(m['current'].get(run['module_id'])==run_id and self.active(m,run_id)
                    and not m['runs'][run_id].get('result_file'),'只能登记当前有效未完成原生运行')
            envelope=read_json(verified_file(home,run['inputs']['native_request']))
            _,inputs,_=source(self,sid,envelope['stage'],envelope['request'])
            require(inputs==envelope['source_inputs'],'原生固定输入或批准已改变')
            previous=read_object(self,sid,run_id,key)
            if previous:
                if previous[1]['payload']==payload and previous[1]['files']==files:return previous[0]
                require(previous[1]['payload'].get('retryable') is True,'完成或稳定NA对象不能覆盖')
            for ref in files:verified_file(home,ref)
            folder=home/f'runs/{run["module_id"]}/{run_id}/native_checkpoints/{key}'
            registered={r['path'] for r in m.get(CHECKPOINTS,[])}
            require(not folder.exists() or all(p.relative_to(home).as_posix() in registered for p in folder.glob('*.json')),
                    '原生检查点存在未登记残件，保留待核查')
            path=folder/(new_id('checkpoint')+'.json')
            write_json(path,{'schema_version':SCORING,'study_id':sid,'run_id':run_id,'key':key,
                'config_hash':run['config_hash'],'payload':deepcopy(payload),'files':deepcopy(files),
                'previous':previous[0] if previous else None,'human_review_written':False,'created_at':now()})
            ref=file_record(home,path,'native_execution_checkpoint')
            m.setdefault(CHECKPOINTS,[]).append(ref);self.save(m)
            return ref

    def _active(self,m,run_id):
        """新版本附加明确来源引用检查；旧运行完全委托原判定。"""
        if not super()._active(m,run_id):return False
        run=self.run(m,run_id)
        if run['config'].get('version') not in (PREPARATION,QUALIFIED,SCORING):return True
        try:
            home=self.location(m['study_id'])
            envelope=read_json(verified_file(home,run['inputs']['native_request']))
            require(envelope['config']==run['config'] and envelope['study_id']==m['study_id']
                    and envelope['request_hash']==fingerprint(envelope['request'])
                    and all(run['inputs'][key]==ref for key,ref in envelope['source_inputs'].items()),
                    '原生请求与固定输入不同')
            current=self.analysis_plan_info(m['study_id']).get('a06_preparation_input')
            require(current==read_json(verified_file(home,run['inputs']['a06_plan_input'])),
                    '原生固定输入或选择已改变')
            return True
        except (ValueError,OSError,KeyError,TypeError):return False

    def _begin(self,m,module,*args,**kwargs):
        """本批不接报告生成，明确阻止新平台评分进入旧Word编排。"""
        if module=='A07' and m['current'].get('A06'):
            require(self.run(m,m['current']['A06'])['config'].get('version')!=SCORING,
                    '原生评分本批仅提供只读资料与图表，未接Word报告生成')
        return super()._begin(m,module,*args,**kwargs)
