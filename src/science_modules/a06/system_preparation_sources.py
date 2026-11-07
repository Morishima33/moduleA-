"""第三版系统准备：精确原来源补救与原逐对象恢复，科学质控不变。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import hashlib,shutil
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json
from . import system_preparation as original,source_preparation as legacy

VERSION='A06.system_preparation.3'
CODE_NAMES=('science_modules/a06/system_preparation.py','science_modules/a06/system_input.py',
 'science_modules/a06/plan_preparation_v2.py','science_modules/a06/plan_quality_engine_v2.py',
 'science_modules/a06/plan_input.py','science_modules/a06/automatic_sources.py','science_modules/a06/automatic_engine.py',
 'science_modules/a06/quality_engine.py','science_modules/a06/two_pass.py','docking_ligand.py','docking_audit.py',
 'docking_receptor.py','docking_p2rank.py','docking_reference_ligand.py','docking_redocking.py','docking_top10_execute.py',
 'science_modules/a06/system_preparation_incremental.py','modulea/core/system_preparation_checkpoints.py',
 'science_modules/a06/system_preparation_sources.py','modulea/core/system_preparation_checkpoints_v2.py',
 'science_modules/a06/compound_sources_v2.py','science_modules/a06/compound_recovery.py',
 'science_modules/a06/source_preparation.py','science_modules/a06/source_context.py',
 'science_modules/a06/source_replay.py')


def configuration(plan):
    """只新增恢复协议，原准备参数、阈值和名单政策不变。"""
    from modulea.core.system_preparation_checkpoints_v2 import VERSION as CHECKPOINTS
    return dict(original.configuration(plan),version=VERSION,object_checkpoint_protocol=CHECKPOINTS)


def reports(packet,compounds,receptors):
    """复用原完整组合事实，仅声明当前执行版本。"""
    summary,tables=original.reports(packet,compounds,receptors);summary['science_version']=VERSION
    from .compound_sources_v2 import structure_counts
    summary.update(structure_counts(compounds))
    tables['source_diagnostics']=diagnostics(compounds,receptors)
    return summary,tables


def diagnostics(compounds,receptors):
    """网页、表格沿用同一原原因，阶段未知时不猜测成名称失败。"""
    return [dict(object_type=kind,object_id=row[key],reason_zh=row['reason_zh'],
        failure_stage=row.get('failure_stage','preparation' if kind=='compound' else 'pocket_environment'),
        failure_code=row.get('failure_code','preparation_unavailable' if kind=='compound' else 'quality_not_passed'),
        retryable=row.get('retryable',False))
        for kind,key,rows in (('compound','compound_id',compounds),('receptor','target_id',receptors))
        for row in rows if row['state']=='NA']


def evidence(home,folder):
    """即时保留本对象请求、原件和失败诊断，不覆盖半成品。"""
    return [file_record(home,p,'preparation_object_evidence') for p in folder.rglob('*') if p.is_file()]


def session(w,m,batch,batch_ref,input_ref,packet,config,executable):
    """固定同批参数、实际工具与全部科学实现，兼容性变化不另起会话掩盖。"""
    from modulea.core import system_preparation_checkpoints_v2 as checkpoints
    home=w.location(m['study_id']);src=Path(__file__).resolve().parents[2]
    implementation={name:(src/name).read_bytes() for name in CODE_NAMES}
    binding={'input_hash':fingerprint(packet),'configuration':config,'vina_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'implementation_sha256':{name:hashlib.sha256(raw).hexdigest() for name,raw in implementation.items()}}
    previous=checkpoints.find_session(w,m,batch_ref,input_ref,binding)
    if previous:return previous
    folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'acquisition/A06_PREP'/new_id('prepsession')
    binary=folder/'software/vina_1.2.7.exe';binary.parent.mkdir(parents=True,exist_ok=False);shutil.copyfile(executable,binary)
    snapshots=[]
    for name,raw in implementation.items():
        target=folder/'code'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        snapshots.append(file_record(home,target,'preparation_implementation'))
    return checkpoints.register(w,m['study_id'],batch_ref,input_ref,binding,folder,file_record(home,binary,'vina_binary'),snapshots)


def connect_object(w,sid,session_ref,value,packet,kind,index,progress):
    """成功来源逐件复验复用，未连接来源仅在明确续做时重试，固定对象不替换。"""
    from modulea.core import system_preparation_checkpoints_v2 as cp
    m=w.load(sid);cp.active(w,m,value);previous=cp.latest(w,m,session_ref,'source',kind,index)
    key='compounds' if kind=='compound' else 'receptors'
    if previous and previous[1]['payload'][key][0]['state']=='connected':return previous
    home=w.location(sid);folder=home/value['folder']/'objects'/kind/str(index)/'sources'/new_id('attempt')
    from .source_context import bound_sources
    identities=bound_sources(w,m,packet) if kind=='compound' else {}
    subset=dict(packet,source_identities=identities,compounds=[packet['compounds'][index]] if kind=='compound' else [],
        receptors=[packet['receptors'][index]] if kind=='receptor' else [])
    connection=legacy.connect(home,subset,folder,progress);connection['id']=value['session_id']
    require(len(connection[key])==1 and not connection['receptors' if kind=='compound' else 'compounds'],'单对象来源改变了固定范围')
    if kind=='compound':
        connection[key][0]['original_sources']=deepcopy(identities[packet['compounds'][index]['compound_id']])
    return cp.append(w,sid,session_ref,'source',kind,index,connection,evidence(home,folder))


def prepare_object(w,sid,session_ref,value,kind,index,source_ref,connection,tools,progress):
    """来源和准备分别恢复；受体每个原顺序候选完成后立即保存实际尝试证据。"""
    from modulea.core import system_preparation_checkpoints_v2 as cp
    m=w.load(sid);cp.active(w,m,value);previous=cp.latest(w,m,session_ref,'preparation',kind,index)
    if previous and previous[1]['dependencies'][:1]==[source_ref]:return previous
    home=w.location(sid);folder=home/value['folder']/'objects'/kind/str(index)/'preparation'/new_id('attempt')
    attempt_refs=[]
    def attempt(root,source,row,spec,round_no,requested_folder,runtime,notify,**kwargs):
        """仅缓存真实完成的候选尝试，未完成目录留存且另名重试；不改结构顺序。"""
        candidate_index=int(Path(requested_folder).name.split('_')[-1])-1
        require(row['candidates'][candidate_index]['spec']==spec,'受体候选与原顺序不同')
        old=cp.latest(w,w.load(sid),session_ref,'attempt','receptor',index,candidate_index)
        if old:
            ref,saved=old;require(saved['dependencies']==[source_ref],'受体已完成尝试的来源改变')
            trace=saved['payload'];require(trace['candidate']==row['candidates'][candidate_index],'受体恢复候选不同')
            actual=legacy.assess_plan_attempt(spec,trace['evidence'],row,round_no,value['configuration'])
            require(actual==trace['assessment'],'受体已存质控结论与实际证据不同')
        else:
            destination=home/value['folder']/'objects/receptor'/str(index)/'candidate_attempts'/new_id('attempt')
            result=legacy.attempt(root,source,row,spec,round_no,destination,runtime,notify,**kwargs)
            trace={'candidate':deepcopy(row['candidates'][candidate_index]),'evidence':result,
                'assessment':legacy.assess_plan_attempt(spec,result,row,round_no,value['configuration'])}
            ref,saved=cp.append(w,sid,session_ref,'attempt','receptor',index,trace,evidence(home,destination),[source_ref],candidate_index)
            progress('已保存受体候选尝试：'+row['target_id']+' / '+str(candidate_index+1))
        attempt_refs.append(ref);return deepcopy(trace['evidence'])
    calculate=FunctionType(legacy.prepare.__code__,dict(vars(legacy),attempt=attempt),legacy.prepare.__name__)
    compounds,receptors=calculate(home,connection,folder,tools,progress,value['configuration'])
    rows=compounds if kind=='compound' else receptors
    if kind=='compound':rows[0]['original_sources']=deepcopy(connection['compounds'][0]['original_sources'])
    if kind=='compound' and rows[0]['state']=='NA':
        source=connection['compounds'][0]
        rows[0].update({key:source[key] for key in ('failure_stage','failure_code','retryable') if key in source})
        if source['state']=='connected':rows[0].update(failure_stage='preparation',failure_code='parameterization_failed',retryable=False)
    if kind=='receptor' and rows[0]['state']=='NA':
        source=connection['receptors'][0]
        rows[0].update({key:source[key] for key in ('failure_stage','failure_code','retryable') if key in source})
    require(len(rows)==1,'单对象准备未返回原固定对象')
    return cp.append(w,sid,session_ref,'preparation',kind,index,rows[0],evidence(home,folder),[source_ref,*attempt_refs])


def compute(w,m,batch,record,batch_ref,tools,progress):
    """逐对象即时归档，不等整包；全包发布核查失败时仅复验已登记完整事实。"""
    from modulea.core import system_decisions,system_preparation_checkpoints_v2 as cp
    sid=m['study_id'];home=w.location(sid);input_ref,fixed=system_decisions.current(w,m,batch['batch_id'],'A06_INPUT')
    require(fixed,'请先生成本批系统固定准备范围');packet,plan=original.read_input(w,m,input_ref,batch_ref)
    require(packet['pair_count']>0,'本批固定准备范围为空，不启动结构工具')
    tools=Path(tools);binary=legacy._version(tools);config=configuration(plan)
    session_ref,value=session(w,m,batch,batch_ref,input_ref,packet,config,binary)
    for ref in w.load(sid).get(cp.PACKETS,[]):
        saved=cp.read_packet(w,w.load(sid),ref)
        if saved['session_ref']==session_ref:return output(w,m,batch,record,batch_ref,input_ref,packet,config,session_ref,ref,saved['fact'])
    connections={'id':value['session_id'],'compounds':[],'receptors':[],'files':[]};compounds=[];receptors=[];object_records=[]
    for kind,rows,prepared in (('compound',packet['compounds'],compounds),('receptor',packet['receptors'],receptors)):
        for index,row in enumerate(rows):
            source_ref,source=connect_object(w,sid,session_ref,value,packet,kind,index,progress)
            prepared_ref,result=prepare_object(w,sid,session_ref,value,kind,index,source_ref,source['payload'],tools,progress)
            key='compounds' if kind=='compound' else 'receptors';connections[key].extend(source['payload'][key]);connections['files'].extend(source['payload']['files'])
            prepared.append(result['payload']);object_records.extend([source_ref,*result['dependencies'][1:],prepared_ref])
            progress('已保存准备对象：'+str(row.get('compound_id',row.get('target_id'))))
    folder=home/value['folder']/'packets'/new_id('attempt');destination=folder/'software/vina_1.2.7.exe'
    destination.parent.mkdir(parents=True,exist_ok=False);shutil.copyfile(verified_file(home,value['vina_binary']),destination)
    fact={'schema_version':VERSION,'study_id':sid,'system_input_ref':input_ref,'batch_file':batch_ref,'input_key':packet['input_key'],
        'attempt_path':folder.relative_to(home).as_posix(),'config':config,'connection':connections,'compounds':compounds,'receptors':receptors,
        'session_ref':session_ref,'object_records':object_records,'vina_binary':file_record(home,destination,'vina_binary'),
        'vina_sha256':value['vina_sha256'],'vina_version_stdout':'AutoDock Vina v1.2.7','human_review_written':False,
        'files':evidence(home,home/value['folder'])}
    path=folder/'packet.json';write_json(path,fact);fact_ref=file_record(home,path,'preparation_packet')
    completed_ref,_=cp.complete(w,sid,session_ref,fact_ref,object_records)
    return output(w,m,batch,record,batch_ref,input_ref,packet,config,session_ref,completed_ref,fact_ref)


def output(w,m,batch,record,batch_ref,input_ref,packet,config,session_ref,completed_ref,fact_ref):
    """每次仅从实际完整事实重建摘要，来源包含对象检查点与真实恢复会话。"""
    fact=read_json(verified_file(w.location(m['study_id']),fact_ref));summary,tables=reports(packet,fact['compounds'],fact['receptors'])
    tables['preparation_packet']=[fact_ref]
    inputs={'study_id':m['study_id'],'bound_a00':batch['request']['expected_a00'],'analysis_plan_id':record['plan_id'],
        'analysis_plan_file':batch['plan_file'],'analysis_parameter_hash':packet['analysis_parameter_hash'],
        'system_input_ref':input_ref,'preparation_fact':fact_ref,'preparation_session':session_ref,'preparation_completed':completed_ref}
    return inputs,config,summary,tables,[],[batch_ref,input_ref,batch['plan_file'],session_ref,completed_ref,fact_ref,*fact['files']],{'outcome':'success'}


def validator(root,previous):
    """逐对象来源链重建再调用原完整科学复算，恢复不能绕过任何身份或质控。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return previous(run,summary,tables,anomalies,outcome)
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from modulea.core import system_preparation_checkpoints_v2 as cp
        w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);home=w.location(run['study_id']);inputs=run['inputs']
        packet,plan=original.read_input(w,m,inputs['system_input_ref'],run['batch_file']);expected_config=configuration(plan)
        require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['parent_review_ids']=={}
            and run['execution_authority']=='system_validation' and run['config']==expected_config
            and anomalies==[] and outcome=='success','逐对象准备协议或配置不符')
        session=cp.read_session(w,m,inputs['preparation_session']);completed=cp.read_packet(w,m,inputs['preparation_completed'])
        require(completed['session_ref']==inputs['preparation_session'] and completed['fact']==inputs['preparation_fact']
            and session['configuration']==expected_config and session['system_input_ref']==inputs['system_input_ref']
            and session['batch_file']==run['batch_file'],'逐对象准备不是同批实际完整包')
        require(inputs['analysis_plan_file']==packet['plan_ref'] and inputs['analysis_parameter_hash']==plan['parameter_hash']
            and all(run['parent_runs'][key]==packet['runs'][key] for key in ('A03','A03_SELECT','A04'))
            and run['parent_validation_records']==session['parent_validation_records']
            and set(session['binding']['implementation_sha256'])==set(CODE_NAMES),'逐对象准备实际父依赖、方案或实现快照不同')
        fact=read_json(verified_file(home,inputs['preparation_fact']))
        require(fact['schema_version']==VERSION and fact['study_id']==run['study_id'] and fact['human_review_written'] is False
            and fact['session_ref']==inputs['preparation_session'] and fact['object_records']==completed['object_records']
            and fact['config']==expected_config and fact['input_key']==packet['input_key']
            and fact['batch_file']==run['batch_file'] and fact['system_input_ref']==inputs['system_input_ref']
            and fact['vina_sha256']==session['vina_sha256'],'逐对象准备事实与固定范围不同')
        sources={'compounds':[],'receptors':[]};prepared={'compounds':[],'receptors':[]};source_files=[]
        records=[(ref,cp.read_object(w,m,ref)) for ref in completed['object_records']]
        for kind,rows in (('compound',packet['compounds']),('receptor',packet['receptors'])):
            key='compounds' if kind=='compound' else 'receptors'
            for index,row in enumerate(rows):
                selected=[(ref,v) for ref,v in records if v['object_type']==kind and v['object_index']==index]
                origin=[(ref,v) for ref,v in selected if v['stage']=='source'];done=[(ref,v) for ref,v in selected if v['stage']=='preparation']
                require(len(origin)==len(done)==1 and done[0][1]['dependencies'][0]==origin[0][0],'完整包缺少单对象来源与准备检查点')
                sources[key].extend(origin[0][1]['payload'][key]);source_files.extend(origin[0][1]['payload']['files']);prepared[key].append(done[0][1]['payload'])
                if kind=='receptor':
                    traces=[v['payload'] for ref,v in selected if v['stage']=='attempt']
                    require(traces==done[0][1]['payload']['attempts'],'受体完整包尝试不等于实际逐候选检查点')
        require(fingerprint((sources['compounds'],sources['receptors'],source_files,prepared['compounds'],prepared['receptors']))==
            fingerprint((fact['connection']['compounds'],fact['connection']['receptors'],fact['connection']['files'],fact['compounds'],fact['receptors'])),
            '完整准备包与逐对象真实检查点不同')
        from .source_context import bound_sources
        from .source_replay import validate as validate_sources
        originals=bound_sources(w,m,packet)
        for connected,prepared in zip(fact['connection']['compounds'],fact['compounds']):
            require(connected['original_sources']==prepared['original_sources']==originals[connected['compound_id']],
                '准备来源关系数与本批A01原始来源不同')
        validate_sources(home,packet,fact['connection'],originals)
        original.validate_evidence(home,packet,fact,expected_config)
        expected,rows=reports(packet,fact['compounds'],fact['receptors']);rows['preparation_packet']=[inputs['preparation_fact']]
        require(tables['preparation_packet']==[inputs['preparation_fact']] and fingerprint((summary,tables))==fingerprint((expected,rows)),
            '逐对象准备摘要或NA范围与实际证据不同')
    return check
