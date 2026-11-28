"""A02/A03/A04新方案接续：复用冻结科学算法，通过公开Workflow发布，不代签。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint, require
from storage import file_record, new_id, read_json, verified_file, write_json, write_lock
from science_modules.analysis_protocol import checked_plan
from .plan_stages_contract import VERSION, context, plan_reference, validate, verified_request

A03_VERSION='A03.plan_intersection.1'


def a03_facts(home,inputs):
    """交集从本次真实A01/A02原结果重建，保持同HGNC及全部原排序规则。"""
    from intersection_flow import payload_from,build
    record=read_json(verified_file(home,inputs['analysis_plan_file']))
    require(record['study_id']==inputs['study_id'] and record['expected_a00']==inputs['bound_a00']
            and record['plan_id']==inputs['analysis_plan_id'],'A03方案归属不一致')
    plan=checked_plan(record['plan'])
    require(plan['parameter_hash']==inputs['analysis_parameter_hash'],'A03参数指纹不一致')
    verified_request(home,inputs['execution_request_file'],'A03',record['plan_id'],inputs['bound_a00'])
    parents=[read_json(verified_file(home,inputs[key])) for key in ('a01_result','a02_result')]
    require(all(p['study_id']==inputs['study_id'] for p in parents),'A03上游研究归属不一致')
    intake=read_json(verified_file(home,inputs['intake_result']))
    require(intake['study_id']==inputs['study_id'] and intake['run_id']==inputs['bound_a00'],'A03登记来源不一致')
    purpose=intake['summary'].get('analysis_purpose')
    require(purpose in ('formal_research','workflow_test'),'A03登记缺少明确研究用途')
    require(not any(p['summary'].get('analysis_purpose')=='workflow_test' for p in parents) or purpose=='workflow_test',
            '流程测试上游不能混入正式研究')
    payload=payload_from(*parents)
    require(fingerprint(payload)==fingerprint(inputs['payload']),'A03固定输入与实际父结果不一致')
    calc,summary,tables=build(payload)
    summary.update(protocol_version=A03_VERSION,analysis_plan_id=record['plan_id'],analysis_parameter_hash=plan['parameter_hash'],analysis_purpose=purpose)
    if any(parent['summary'].get('identity_exception_protocol') == 'ModuleA.a03_input_review.1' for parent in parents):
        require(purpose == 'workflow_test', '流程测试例外不能进入正式研究交集')
        tables['input_review_limits'] = [
            {'module_id': parent['module_id'], 'temporarily_omitted': len(parent['tables'].get('identity_exception_scope', [])),
             'notice_zh': ' '.join(parent['summary'].get('identity_limitations_zh', []))}
            for parent in parents]
    return calc,summary,tables


def a03_validator(root,fallback):
    """新交集协议核验父结果及方案，旧交集仍委托原校验器。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=A03_VERSION:return fallback(run,summary,tables,anomalies,outcome)
        from intersection_flow import CONFIG
        require(run['config']==dict(CONFIG,version=A03_VERSION),'A03新方案科学配置不一致')
        home=Path(root)/'studies'/run['study_id']
        calc,expected,rows=a03_facts(home,run['inputs'])
        for module,key in (('A01','a01_result'),('A02','a02_result')):
            parent=read_json(verified_file(home,run['inputs'][key]))
            require(parent['run_id']==run['parent_runs'][module],'A03实际父运行不一致')
        require(fingerprint((summary,tables))==fingerprint((expected,rows)),'A03交集或排名与父结果复算不一致')
        require(outcome==('success' if calc['counts']['intersection'] else 'empty'),'A03空结果状态不一致')
    return check


def run_a03(workflow,sid,body,request_ref,progress=None):
    """同一写锁绑定当前方案及两侧批准，追加独立待复核交集和原样韦恩图。"""
    from intersection_flow import CONFIG,payload_from,study_labels,venn_svg
    with write_lock(workflow.root):
        validate(workflow,sid,body)
        manifest,_,draft=context(workflow,sid);home=workflow.location(sid)
        reference,_=plan_reference(workflow,manifest,draft['plan_id'])
        a01,a02=(manifest['current'][key] for key in ('A01','A02'))
        payload=payload_from(workflow.result(manifest,a01),workflow.result(manifest,a02))
        inputs={'study_id':sid,'bound_a00':body['expected_a00'],'analysis_plan_id':draft['plan_id'],
                'analysis_plan_file':reference,'analysis_parameter_hash':draft['plan']['parameter_hash'],
                'intake_result':manifest['runs'][body['expected_a00']]['result_file'],
                'a01_result':manifest['runs'][a01]['result_file'],'a02_result':manifest['runs'][a02]['result_file'],
                'execution_request_file':request_ref,'payload':payload}
        calc,summary,tables=a03_facts(home,inputs)
        run=workflow._begin(manifest,'A03',inputs,dict(CONFIG,version=A03_VERSION),body['reason'])
        path=home/'runs/A03'/run['run_id']/'venn.svg';path.write_text(venn_svg(summary,*study_labels(workflow,manifest,run['run_id'])),encoding='utf8')
        result=workflow._finish(manifest,run['run_id'],summary,tables,['交集及两种排序来自同一原始标准化集合，选择另行确认，不自动批准。'],
            'success' if calc['counts']['intersection'] else 'empty',sources=[reference,request_ref,inputs['intake_result'],inputs['a01_result'],inputs['a02_result']],figures=[file_record(home,path,'figure')])
        workflow.save(manifest)
    return result


def run_a04(workflow,sid,body,request_ref,progress=None):
    """锁外按已确认方案请求STRING，发布前同时复核当前A04和原A03批准。"""
    from .a04.plan_flow import fetch
    with write_lock(workflow.root):
        validate(workflow,sid,body)
        manifest,_,draft=context(workflow,sid)
        a03=manifest['current']['A03'];a04=manifest['current'].get('A04','')
        review=workflow.latest_review(manifest,workflow.run(manifest,a03)['artifact_id'])['review_id']
        targets=workflow.result(manifest,a03)['tables']['intersection_targets']
    folder=workflow.location(sid)/'raw/A04_plan_acquisition'/new_id('attempt')
    write_json(folder/'request.json',{'schema_version':VERSION,'request':body,'expected_a03_review':review,
        'parameter_hash':draft['plan']['parameter_hash']})
    if progress:progress('按本方案STRING置信度获取当前交集网络')
    def evidence(name,value):
        """每次成功响应立即留存，下一请求失败也保留已有来源。"""
        write_json(folder/(name+'.json'),value)
    try:
        bundle=fetch(targets,draft['plan'],evidence=evidence)
    except Exception as error:
        write_json(folder/'error.json',{'error_type':type(error).__name__,'message_zh':str(error),
            'stage':'A04','published':False})
        raise
    bundle['execution_request_file']=request_ref
    bundle['analysis_purpose']=workflow.result(manifest,a03)['summary'].get('analysis_purpose')
    write_json(folder/'source.json',bundle)
    write_json(folder/'acquisition.json',{'schema_version':VERSION,'request':body,'expected_a03_review':review,
        'parameter_hash':draft['plan']['parameter_hash'],'source':file_record(workflow.location(sid),folder/'source.json','ppi_source')})
    return workflow.publish_analysis_plan_a04_network(sid,{'expected_a00':body['expected_a00'],'expected_a03':a03,
        'expected_plan_id':draft['plan_id'],'expected_a04':a04,'expected_a03_review':review,
        'source_file':file_record(workflow.location(sid),folder/'source.json','ppi_source'),'reason':body['reason']})


class _A02Binding:
    """只为本次原A02生产调用补充方案溯源，不改原数据/配置/科学结果。"""
    def __init__(self,workflow,guard):self.workflow,self.guard=workflow,guard
    def __getattr__(self,name):return getattr(self.workflow,name)
    def _begin(self,manifest,module,inputs,config,reason):
        require(module=='A02','A02接续不能发布其他科学模块')
        require(manifest['current'].get('A00')==self.guard['bound_a00'] and not manifest['current'].get('A02'),
                'A02登记或当前版本已改变，请刷新')
        review=self.workflow.latest_review(manifest,self.workflow.run(manifest,self.guard['bound_a00'])['artifact_id'])
        require(review and review['review_id']==self.guard['a00_review_id'],'A02登记复核已改变，请刷新')
        return self.workflow._begin(manifest,module,dict(inputs,plan_stage_binding=self.guard),config,reason)
    def _finish(self,manifest,rid,summary,tables,anomalies,outcome,**kwargs):
        kwargs['sources']=list(kwargs.get('sources') or [])+[self.guard['analysis_plan_file'],self.guard['execution_request_file']]
        return self.workflow._finish(manifest,rid,summary,tables,anomalies,outcome,**kwargs)


def a02_validator(root,fallback):
    """新接续原始候选的附加方案证据独立核验，原五库科学校验完整执行。"""
    def check(run,summary,tables,anomalies,outcome):
        binding=run.get('inputs',{}).get('plan_stage_binding')
        if binding:
            require(binding['schema_version']==VERSION and binding['study_id']==run['study_id']
                    and binding['bound_a00']==run['parent_runs']['A00'] and binding['a00_review_id']==run['parent_review_ids']['A00'],
                    'A02方案接续研究/登记/复核绑定不一致')
            home=Path(root)/'studies'/run['study_id']
            record=read_json(verified_file(home,binding['analysis_plan_file']))
            verified_request(home,binding['execution_request_file'],'A02',binding['analysis_plan_id'],binding['bound_a00'])
            require(record['study_id']==run['study_id'] and record['expected_a00']==binding['bound_a00']
                    and record['plan_id']==binding['analysis_plan_id']
                    and checked_plan(record['plan'])['parameter_hash']==binding['analysis_parameter_hash'],'A02方案记录与实际接续不一致')
        return fallback(run,summary,tables,anomalies,outcome)
    return check


def run_a02(workflow,sid,body,request_ref,progress=None):
    """明确初始化五库候选，保留每库真实失败与缺口，不进行范围/身份批准。"""
    from a02_auto_prepare import new_research_sources
    from disease import run_disease
    with write_lock(workflow.root):
        validate(workflow,sid,body)
        manifest,intake,draft=context(workflow,sid)
        reference,_=plan_reference(workflow,manifest,draft['plan_id'])
        guard={'schema_version':VERSION,'study_id':sid,'bound_a00':body['expected_a00'],
               'analysis_plan_id':draft['plan_id'],'analysis_parameter_hash':draft['plan']['parameter_hash'],
               'analysis_plan_file':reference,'execution_request_file':request_ref}
        guard['a00_review_id']=workflow.latest_review(manifest,workflow.run(manifest,body['expected_a00'])['artifact_id'])['review_id']
    if progress:progress('准备本研究五库候选，失败与未提供分别留存')
    sources,diagnostic=new_research_sources(workflow,manifest,intake)
    proxy=_A02Binding(workflow,guard)
    result=run_disease(proxy,sid,body['expected_a00'],'',sources,body['reason'],profile_version='A02.source_profile.3')
    write_json(workflow.location(sid)/'raw/A02_plan_initialization'/(new_id('attempt')+'.json'),
               {'binding':guard,'diagnostic':diagnostic,'result_run_id':result['run_id']})
    return result
