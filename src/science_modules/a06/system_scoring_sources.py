"""第二版系统资格来源的真实评分；原Top1、NA和逐组合恢复科学规则保持。"""
from copy import deepcopy
from pathlib import Path
import shutil,subprocess
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json
from .plan_score_pair import execute as execute_pair,validate as validate_pair
from .plan_scoring_inputs import ligand_record
from .plan_scoring_results import matrix_csv,table_rows

VERSION='A06.system_scoring.3'


def check_tools(tools):
    from .plan_preparation_v2 import _version
    return _version(Path(tools))


def configuration(preparation):
    return {'version':VERSION,'vina_version':'1.2.7','vina_parameters':deepcopy(preparation['config']['vina_parameters']),
        'analysis_parameter_hash':preparation['inputs']['analysis_parameter_hash'],'source_config_hash':preparation['config_hash'],
        'cpu_per_pair':1,'parallel_pairs':1,'timeout_seconds':1800,'automatic_approval':False}


def derive(root,sid,inputs):
    from .system_qualification_sources import validator,VERSION as QUALIFICATION
    home=Path(root)/'studies'/sid;prep=read_json(verified_file(home,inputs['preparation_run']))
    result=read_json(verified_file(home,inputs['preparation_result']))
    require(prep['module_id']=='A06_PREP' and prep['config'].get('version')==QUALIFICATION
        and prep['study_id']==result['study_id']==sid and prep['run_id']==result['run_id'],'系统评分来源不是实际同研究资格准备')
    def reject(*args):require(False,'系统评分准备协议不能回退')
    validator(root,reject)(prep,result['summary'],result['tables'],result['anomalies'],result['outcome'])
    require(inputs['system_input_ref']==prep['inputs']['system_input_ref'] and inputs['analysis_plan_file']==prep['inputs']['analysis_plan_file'],
        '系统评分固定输入或原方案不同')
    request=read_json(verified_file(home,inputs['scoring_request']))
    require(request['schema_version']==VERSION and request['study_id']==sid and request['human_review_written'] is False
        and request['request_hash']==fingerprint(request['request']) and request['batch_file']==prep['batch_file']
        and request['request']['expected_preparation_run_id']==prep['run_id'],'系统评分缺少实际同批明确授权')
    fixed=read_json(verified_file(home,inputs['system_input_ref']))['payload']
    fact=read_json(verified_file(home,prep['inputs']['qualification_fact']))
    return {'preparation':prep,'preparation_result':result,'input':fixed,'request':request,'config':configuration(prep),
        'compounds':fact['compounds'],'receptors':fact['receptors'],'planned_pairs':result['tables']['planned_pairs']}


def receptor_evidence(row):
    require(row['state']=='ready' and row['quality'] in ('严格','探索'),'系统受体未具备真实资格')
    attempt=row.get('system_qualified_attempt');require(attempt and attempt['assessment']['state']=='ready'
        and attempt['assessment']['quality']==row['quality'],'系统受体资格不能唯一对应实际搜索区域')
    return attempt['evidence']


def expected_rows(home,data,pairs,binary,run_id):
    require(len(pairs)==len(data['planned_pairs']),'系统评分组合数不完整')
    compounds={r['compound_id']:r for r in data['compounds']};receptors={r['target_id']:r for r in data['receptors']};rows=[]
    for index,(planned,supplied) in enumerate(zip(data['planned_pairs'],pairs),1):
        receptor=receptors[planned['target_id']];row=dict(planned,quality=receptor['quality'],execution=None)
        if planned['state']=='ready':
            ref=supplied.get('execution');prefix=f'runs/A06/{run_id}/system_scoring/scores/pair_{index:06d}/'
            require(ref and ref['path'].startswith(prefix) and ref['path'].endswith('/execution.json')
                and '/' not in ref['path'][len(prefix):-len('/execution.json')],'系统评分执行证据不属于实际组合')
            evidence=receptor_evidence(receptor)
            value=validate_pair(home,ref,binary,ligand_record(compounds[planned['compound_id']]),evidence['receptor'],evidence['box'],data['config'])
            row.update(state=value['state'],score=value['score'],reason_zh=value['reason_zh'],execution=ref)
        else:require(planned['state']=='NA' and planned['score'] is None and planned['reason_zh'],'系统评分不能把未核实输入填零')
        rows.append(row)
    require(fingerprint(rows)==fingerprint(pairs),'系统评分与同批实际Top1证据不同')
    return rows


def original_summary(data,rows):
    scored=[r for r in rows if r['state']=='completed']
    return {'science_version':VERSION,'compound_count':len(data['compounds']),'receptor_count':len(data['receptors']),
        'pair_count':len(rows),'ready_input_pairs':sum(r['state']=='ready' for r in data['planned_pairs']),
        'scored_pairs':len(scored),'failed_pairs':sum(r['state']=='failed' for r in rows),'na_pairs':sum(r['state']=='NA' for r in rows),
        'strict_scored_pairs':sum(r['quality']=='严格' for r in scored),'exploratory_scored_pairs':sum(r['quality']=='探索' for r in scored),
        'handoff_blocked':not scored,'automatic_approval':False,'score_unit':'kcal/mol','input_key':data['input']['input_key'],
        'analysis_parameter_hash':data['config']['analysis_parameter_hash'],'source_preparation_run_id':data['preparation']['run_id'],
        'message_zh':'同批真实Vina评分和NA已归档，未生成人工批准' if scored else '本批评分未产生可用结果，失败和NA保留'}


def summary(data, rows):
    """分别统计固定来源行和实际核实结构，不改变组合范围。"""
    from .compound_sources_v2 import structure_counts
    return dict(original_summary(data, rows), **structure_counts(data['compounds']))


def result_tables(data,rows,ref):
    from .system_preparation_sources import diagnostics
    reasons=diagnostics(data['compounds'],data['receptors'])
    reasons.extend(dict(object_type='pair',object_id=row['compound_id']+' / '+row['target_id'],
        failure_stage='scoring',failure_code='scoring_execution_failed',retryable=False,reason_zh=row['reason_zh'])
        for row in rows if row['state']=='failed')
    return {'scoring_packet':[ref],'plan_scoring_pairs':table_rows(rows),'source_diagnostics':reasons}


def compute(workflow,sid,run,tools,progress):
    """只计算未完成组合，完成原件先按原命令/输入/Top1复验，失败诊断不变成成功。"""
    home=workflow.location(sid);data=derive(workflow.root,sid,run['inputs']);folder=home/'runs/A06'/run['run_id']/'system_scoring'
    executable=check_tools(tools);binary=folder/'software/vina.exe'
    if binary.exists():require(binary.read_bytes()==executable.read_bytes(),'恢复时固定Vina字节已改变')
    else:binary.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(executable,binary)
    implementations=[]
    from . import plan_score_pair
    for path in (Path(__file__),Path(plan_score_pair.__file__)):
        destination=folder/'code'/path.name;destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():require(destination.read_bytes()==path.read_bytes(),'未完成评分的实际实现已改变，不能静默续算')
        else:destination.write_bytes(path.read_bytes())
        implementations.append(file_record(home,destination,'system_scoring_implementation'))
    compounds={r['compound_id']:r for r in data['compounds']};receptors={r['target_id']:r for r in data['receptors']};rows=[];recovered=[]
    for index,planned in enumerate(data['planned_pairs'],1):
        m=workflow.load(sid);require(workflow.active(m,run['run_id']),'评分过程中实际准备或人工决定已改变，停止后续组合')
        receptor=receptors[planned['target_id']];row=dict(planned,quality=receptor['quality'],execution=None)
        if planned['state']=='ready':
            evidence=receptor_evidence(receptor);pair_folder=folder/'scores'/f'pair_{index:06d}'
            candidates=list(pair_folder.glob('*/execution.json')) if pair_folder.exists() else []
            require(len(candidates)<=1,'同组合存在多个完整执行结果，不能静默择优')
            if candidates:
                ref=file_record(home,candidates[0],'scoring_execution')
                value=validate_pair(home,ref,binary,ligand_record(compounds[planned['compound_id']]),evidence['receptor'],evidence['box'],run['config'])
                recovered.append(ref)
            else:
                progress(f'执行本批评分组合 {index}/{len(data["planned_pairs"])}')
                ref=execute_pair(home,pair_folder/new_id('attempt'),binary,ligand_record(compounds[planned['compound_id']]),
                    evidence['receptor'],evidence['box'],run['config']);value=read_json(verified_file(home,ref))
            row.update(state=value['state'],score=value['score'],reason_zh=value['reason_zh'],execution=ref)
        rows.append(row)
    stats=summary(data,rows);matrix=folder/'matrix.csv'
    if matrix.exists():require(matrix.read_text('utf-8-sig')==matrix_csv(rows),'已有评分矩阵与实际组合不一致')
    else:matrix.write_text(matrix_csv(rows),encoding='utf-8-sig',newline='')
    recovery={'schema_version':'A06.system_scoring_recovery.1','study_id':sid,'run_id':run['run_id'],'reused_executions':recovered,
        'only_unfinished_pairs_executed':True,'human_review_written':False}
    recovery_path=folder/'recoveries'/(new_id('recovery')+'.json');write_json(recovery_path,recovery);recovery_ref=file_record(home,recovery_path,'system_scoring_recovery')
    files=[file_record(home,p,'system_scoring_evidence') for p in folder.rglob('*') if p.is_file() and p.name!='packet.json']
    packet={'schema_version':VERSION,'study_id':sid,'run_id':run['run_id'],'inputs':run['inputs'],'configuration':run['config'],
        'binary':file_record(home,binary,'scoring_vina'),'pairs':rows,'summary':stats,'matrix_csv':file_record(home,matrix,'scoring_matrix_csv'),
        'files':files,'recovery':recovery_ref,'implementation_files':implementations}
    packet_path=folder/'packets'/(new_id('packet')+'.json');write_json(packet_path,packet);packet_ref=file_record(home,packet_path,'system_scoring_packet')
    return stats,result_tables(data,rows,packet_ref),[
        run['batch_file'],*run['parent_validation_records'].values(),*data['preparation_result']['files'],*files,packet_ref]


def validator(root,previous):
    def check(run,stats,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return previous(run,stats,tables,anomalies,outcome)
        home=Path(root)/'studies'/run['study_id'];data=derive(root,run['study_id'],run['inputs'])
        require(run['config']==data['config'] and run.get('execution_protocol')=='ModuleA.system_execution.1'
            and run['parent_runs']=={'A06_PREP':data['preparation']['run_id']} and run['parent_review_ids']=={}
            and run['batch_file']==data['preparation']['batch_file']==data['request']['batch_file']
            and run['parent_validation_records']==data['request']['parent_validation_records'],'系统评分真实准备、回执或参数不同')
        require(len(tables.get('scoring_packet',[]))==1,'系统评分缺少实际执行包')
        ref=tables['scoring_packet'][0];require(ref['path'].startswith(f'runs/A06/{run["run_id"]}/system_scoring/packets/'),'系统评分包路径不同')
        packet=read_json(verified_file(home,ref));require(packet['schema_version']==VERSION and packet['study_id']==run['study_id']
            and packet['run_id']==run['run_id'] and packet['inputs']==run['inputs'] and packet['configuration']==run['config'],'系统评分包归属不同')
        binary=verified_file(home,packet['binary'])
        require(packet['binary']['path']==f'runs/A06/{run["run_id"]}/system_scoring/software/vina.exe','系统评分工具快照位置不同')
        from .plan_quality_engine_v2 import tool_path
        version=subprocess.run([tool_path(binary),'--version'],capture_output=True,text=True,timeout=20)
        require(version.returncode==0 and version.stdout.strip()=='AutoDock Vina v1.2.7','系统评分固定工具版本不同')
        rows=expected_rows(home,data,packet['pairs'],binary,run['run_id']);expected=summary(data,rows)
        require(fingerprint(stats)==fingerprint(expected)==fingerprint(packet['summary'])
            and fingerprint(tables)==fingerprint(result_tables(data,rows,ref)) and anomalies==[]
            and outcome==('success' if expected['scored_pairs'] else 'failed'),'系统评分统计或NA与实际构型回算不同')
        require(verified_file(home,packet['matrix_csv']).read_text('utf-8-sig')==matrix_csv(rows),'完整系统评分矩阵与原值不同')
        for source in packet['files']:verified_file(home,source)
        required=[packet['binary'],packet['matrix_csv'],packet['recovery'],*packet['implementation_files']]
        for row in rows:
            if row['execution']:
                required.extend([row['execution'],*read_json(verified_file(home,row['execution']))['files']])
        # 文件角色可不同，实际相对路径、长度和SHA必须完整覆盖本批评分证据。
        actual={(ref['path'],ref['bytes'],ref['sha256']) for ref in packet['files']}
        require(all((ref['path'],ref['bytes'],ref['sha256']) in actual for ref in required),'系统评分包遗漏实际命令、构型或恢复证据')
        recovery=read_json(verified_file(home,packet['recovery']));require(recovery['run_id']==run['run_id']
            and recovery['study_id']==run['study_id'] and recovery['only_unfinished_pairs_executed'] is True
            and recovery['human_review_written'] is False,'系统组合续算证据与本批不同')
        for source in recovery['reused_executions']:
            require(source in [r['execution'] for r in rows if r['execution']],'续算借用了非本批组合')
    return check
