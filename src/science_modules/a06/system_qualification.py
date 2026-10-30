"""系统准备资格的真实证据派生与独立生产复算，旧人工口袋协议保持。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json
from . import system_preparation as preparation
from . import system_quality

VERSION='A06.system_qualification.1'


def configuration(plan):
    return dict(preparation.configuration(plan),version=VERSION,qualification_rule=system_quality.VERSION,
        predicted_pocket_authority='system_validation',batch_docking_allowed=False)


def source_data(root,sid,inputs):
    """原准备规范完整重验，参数、名单和几何只从真实归档重建。"""
    home=Path(root)/'studies'/sid;source=read_json(verified_file(home,inputs['source_preparation_run']))
    result=read_json(verified_file(home,inputs['source_preparation_result']))
    require(source['study_id']==result['study_id']==sid and source['module_id']=='A06_PREP'
        and source['run_id']==result['run_id'] and source['config'].get('version')==preparation.VERSION,
        '资格来源不是同研究真实系统准备')
    def reject(*args):require(False,'资格来源科学协议不支持')
    preparation.validator(root,reject)(source,result['summary'],result['tables'],result['anomalies'],result['outcome'])
    require(source['inputs']['preparation_fact']==inputs['source_preparation_fact']
        and source['inputs']['system_input_ref']==inputs['system_input_ref'],'资格来源与原固定输入不同')
    fact=read_json(verified_file(home,inputs['source_preparation_fact']))
    fixed=read_json(verified_file(home,inputs['system_input_ref']))['payload'];plan=read_json(verified_file(home,fixed['plan_ref']))['plan']
    request=read_json(verified_file(home,inputs['qualification_request']))
    require(request['schema_version']==VERSION and request['study_id']==sid and request['human_review_written'] is False
        and request['request_hash']==fingerprint(request['request']) and request['request']['expected_preparation_run_id']==source['run_id']
        and request['binding']['source_run']==inputs['source_preparation_run']
        and request['binding']['source_result']==inputs['source_preparation_result']
        and request['binding']['batch_file']==source['batch_file'],'系统资格实际请求或授权与原准备不同')
    return source,result,fact,fixed,plan,request


def reports(fixed,fact,source_rid):
    receptors,decisions=system_quality.qualify(fact)
    summary,tables=preparation.reports(fixed,fact['compounds'],receptors)
    summary.update(science_version=VERSION,source_preparation_run_id=source_rid,
        handoff_blocked=False,qualification_completed=True,
        strict_receptors=sum(r['state']=='ready' and r['quality']=='严格' for r in receptors),
        exploratory_receptors=sum(r['state']=='ready' and r['quality']=='探索' for r in receptors),
        message_zh='真实准备证据系统资格核验完成，严格/探索/NA分列；未执行评分或人工批准')
    tables['system_qualification_decisions']=decisions
    return receptors,summary,tables


def compute(workflow,m,batch,plan,binding,body):
    home=workflow.location(m['study_id']);source=workflow.run(m,body['expected_preparation_run_id'])
    folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'qualification_attempts'/new_id('attempt')
    request={'schema_version':VERSION,'study_id':m['study_id'],'request':deepcopy(body),'request_hash':fingerprint(body),
        'binding':deepcopy(binding),'human_review_written':False,'authority_kind':'system_validation'}
    write_json(folder/'request.json',request);request_ref=file_record(home,folder/'request.json','system_qualification_request')
    inputs={'study_id':m['study_id'],'bound_a00':batch['request']['expected_a00'],'analysis_plan_id':plan['plan_id'],
        'analysis_plan_file':deepcopy(batch['plan_file']),'analysis_parameter_hash':plan['plan']['parameter_hash'],
        'system_input_ref':source['inputs']['system_input_ref'],'source_preparation_run':binding['source_run'],
        'source_preparation_result':binding['source_result'],'source_preparation_fact':source['inputs']['preparation_fact'],
        'qualification_request':request_ref}
    _,result,fact,fixed,actual_plan,_=source_data(workflow.root,m['study_id'],inputs)
    require(actual_plan==plan['plan'],'系统资格方案与原准备方案不同')
    receptors,summary,tables=reports(fixed,fact,source['run_id']);implementations=[]
    for name in (__file__,system_quality.__file__):
        path=Path(name);target=folder/'implementation'/path.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
        implementations.append(file_record(home,target,'system_qualification_implementation'))
    qualified={'schema_version':VERSION,'study_id':m['study_id'],'input_key':fixed['input_key'],'human_review_written':False,
        'source_preparation_run_id':source['run_id'],'source_preparation_fact':inputs['source_preparation_fact'],
        'configuration':configuration(actual_plan),'compounds':deepcopy(fact['compounds']),'receptors':receptors,
        'decisions':tables['system_qualification_decisions'],'implementation_files':implementations}
    write_json(folder/'packet.json',qualified);ref=file_record(home,folder/'packet.json','system_qualified_preparation')
    inputs['qualification_fact']=ref;tables['preparation_packet']=[ref]
    return inputs,configuration(actual_plan),summary,tables,[batch['plan_file'],inputs['system_input_ref'],binding['source_run'],
        binding['source_result'],inputs['source_preparation_fact'],request_ref,ref,*result['files'],*implementations]


def validator(root,previous):
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return previous(run,summary,tables,anomalies,outcome)
        source,result,fact,fixed,plan,request=source_data(root,run['study_id'],run['inputs']);home=Path(root)/'studies'/run['study_id']
        require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['parent_review_ids']=={}
            and run['batch_file']==source['batch_file'] and run['parent_runs']==source['parent_runs']
            and run['parent_validation_records']==request['binding']['parent_validation_records']
            and run['config']==configuration(plan),'系统资格实际父依赖或配置不同')
        receptors,expected,rows=reports(fixed,fact,source['run_id']);ref=run['inputs']['qualification_fact'];rows['preparation_packet']=[ref]
        qualified=read_json(verified_file(home,ref))
        require(qualified['schema_version']==VERSION and qualified['study_id']==run['study_id']
            and qualified['input_key']==fixed['input_key'] and qualified['human_review_written'] is False
            and qualified['source_preparation_run_id']==source['run_id'] and qualified['source_preparation_fact']==run['inputs']['source_preparation_fact']
            and qualified['configuration']==run['config'] and fingerprint((qualified['compounds'],qualified['receptors'],qualified['decisions']))==
                fingerprint((fact['compounds'],receptors,rows['system_qualification_decisions'])),'系统资格事实与原准备证据复算不一致')
        for ref in qualified['implementation_files']:verified_file(home,ref)
        require(fingerprint((summary,tables))==fingerprint((expected,rows)) and anomalies==[] and outcome=='success',
            '系统资格摘要、完整组合或NA与真实证据不同')
    return check
