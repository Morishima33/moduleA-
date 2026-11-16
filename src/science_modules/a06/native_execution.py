"""新平台A06生产编排：复用原身份/准备/质控/Top1算法，单独协议与工具绑定。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from types import FunctionType

from contracts import fingerprint, require
from storage import new_id, read_json, write_json, write_lock
from modulea.core.bounded_evidence import file_record, verified_file
from modulea.core import native_execution as core
from .native_tools import NativeTools,NativeIO,VERSION,validate_pair
from . import plan_preparation_v2 as preparation
from .plan_score_pair import execute,validate
from .plan_scoring_inputs import ligand_record,receptor_evidence
from .plan_scoring_results import matrix_csv,table_rows
from .native_display import export


def preparation_config(plan,signature):
    """科学参数完全取原已确认方案；新字段只表达平台、实际工具与显式协议。"""
    return dict(preparation.execution_config(plan),version=core.PREPARATION,
        native_protocol=VERSION,native_tools_sha256=signature,scientific_basis='A06.plan_preparation.2')


def preparation_validator(root,previous):
    """复用冻结的完整准备生产校验器，版本/配置由本协议显式绑定，原判断不改。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')==core.QUALIFIED:
            return qualified_validator(root,run,summary,tables,anomalies,outcome)
        if run['config'].get('version')!=core.PREPARATION:return previous(run,summary,tables,anomalies,outcome)
        home=Path(root)/'studies'/run['study_id']
        fact=read_json(verified_file(home,tables['preparation_packet'][0]))
        signature=read_json(verified_file(home,fact['native_signature']))
        require(fingerprint(signature)==run['config']['native_tools_sha256'],'原生准备工具签名不同')
        namespace=dict(preparation.validator.__globals__,VERSION=core.PREPARATION,verified_file=verified_file,
            execution_config=lambda plan:preparation_config(plan,run['config']['native_tools_sha256']))
        factory=FunctionType(preparation.validator.__code__,namespace,'validator',preparation.validator.__defaults__)
        factory(root,previous)(run,summary,tables,anomalies,outcome)
        from modulea.platform_preflight import binary_platform
        system,machine=binary_platform(verified_file(home,fact['vina_binary']))
        require(system==signature['system'] and machine in (signature['machine'],'universal'),
                '原生准备归档二进制与平台/芯片不同')
    return check


def pocket_request(body):
    """本平台请求显式转换到原口袋决定契约；不改变任何选择或判断。"""
    return core.pocket_request(body)


def qualified_values(root,run):
    """重新完整核原准备、来源和明确口袋决定，严格项不改写，NA不补位。"""
    from .plan_pockets import derive
    home=Path(root)/'studies'/run['study_id'];inputs=run['inputs']
    source=read_json(verified_file(home,inputs['source_preparation_run']))
    result=read_json(verified_file(home,inputs['source_preparation_result']))
    require(source['study_id']==run['study_id'] and source['config']['version']==core.PREPARATION
        and result['run_id']==source['run_id'] and result['artifact_id']==source['artifact_id']
        and run['parent_runs']==source['parent_runs'] and run['parent_review_ids']==source['parent_review_ids']
        and inputs['a06_plan_input']==source['inputs']['a06_plan_input'],'原生核查来源或上游批次不同')
    preparation_validator(root,lambda *_:None)(source,result['summary'],result['tables'],result['anomalies'],result['outcome'])
    # 历史重放只核归档决定；当前决定另由Workflow.active和发表前门控重新检查。
    if inputs.get('source_preparation_review') is not None:
        review=read_json(verified_file(home,inputs['source_preparation_review']))
        require(review['decision']=='approved' and review['study_id']==run['study_id']
            and review['run_id']==source['run_id'] and review['artifact_id']==source['artifact_id']
            and review['config_hash']==source['config_hash']
            and review['result_hash']==inputs['source_preparation_result']['sha256'],
            '原生核查绑定的来源人工决定不同')
    envelope=read_json(verified_file(home,inputs['native_request']));body=envelope['request']
    core.request('qualify',body)
    require(body['expected_preparation_run_id']==source['run_id'] and envelope['config']==run['config']
        and envelope['request_hash']==fingerprint(body),'原生核查请求或参数不同')
    fact=read_json(verified_file(home,result['tables']['preparation_packet'][0]))
    record=read_json(verified_file(home,inputs['a06_plan_input']))
    require(body['expected_input_id']==record['input_id'],'原生核查固定输入不同')
    decision={'request':pocket_request(body),'request_hash':fingerprint(pocket_request(body)),
        'decision_id':'pocketreview_'+body['request_id'].split('_',1)[1],'created_at':envelope['created_at']}
    receptors=derive(home,fact,decision)
    summary,tables=preparation.reports(record['packet'],fact['compounds'],receptors)
    require(summary['ready_pairs']>0,'没有通过原严格或明确采用探索规则的组合，保留NA，不能开放整体复核')
    summary.update(handoff_blocked=False,reviewable=True,execution_available=False,
        message_zh='同批原生准备及明确口袋决定已完整复验，待独立人工整体复核；未批准或评分')
    expected_config=dict(source['config'],version=core.QUALIFIED,scientific_basis='A06.plan_preparation.2 + A06.plan_pocket_review.1')
    require(run['config']==expected_config,'原生核查不允许改变准备参数或工具')
    output=dict(fact,schema_version=core.QUALIFIED,receptors=receptors,config=expected_config,
                source_preparation_run_id=source['run_id'],native_request=inputs['native_request'])
    return output,summary,tables


def qualified_validator(root,run,summary,tables,anomalies,outcome):
    """发布和重放都重新生成预期事实；没有自动批准或绕过原身份/区域质控。"""
    fact,expected_summary,expected_tables=qualified_values(root,run)
    refs=tables.get('preparation_packet',[]);home=Path(root)/'studies'/run['study_id']
    require(len(refs)==1 and refs[0]['path']==f'runs/A06_PREP/{run["run_id"]}/native_qualification/packet.json',
            '原生核查事实包归属不同')
    expected_tables['preparation_packet']=refs
    require(summary==expected_summary and tables==expected_tables and anomalies==[] and outcome=='success'
        and read_json(verified_file(home,refs[0]))==fact,'原生核查事实、完整矩阵或摘要不同')


def qualify(workflow,sid,body,settings,progress):
    """显式口袋采用后追加完整科学复验版本，仍由原review入口作人工整体决定。"""
    core.request('qualify',body);tools=NativeTools(settings)
    _,_,data=core.source(workflow,sid,'qualify',body)
    require(data['preparation']['config']['native_tools_sha256']==tools.signature_sha256,'原生准备工具或源码改变，须建立新准备')
    config=dict(data['preparation']['config'],version=core.QUALIFIED,scientific_basis='A06.plan_preparation.2 + A06.plan_pocket_review.1')
    run,repeated,_=core.begin(workflow,sid,'qualify',body,config)
    if repeated:return workflow.result(workflow.load(sid),run['run_id'])
    fact,summary,tables=qualified_values(workflow.root,run)
    home=workflow.location(sid);path=home/'runs/A06_PREP'/run['run_id']/'native_qualification/packet.json'
    if path.exists():require(read_json(path)==fact,'未登记核查残件不同，保留待核查')
    else:write_json(path,fact)
    ref=file_record(home,path,'preparation_packet');tables['preparation_packet']=[ref]
    tools.verify_current()
    with write_lock(workflow.root):
        m=workflow.load(sid);require(m['current']['A06_PREP']==run['run_id'] and workflow.active(m,run['run_id']),'原生核查发表前输入改变')
        result=workflow._finish(m,run['run_id'],summary,tables,[],'success',attachments=[*fact['files'],ref,*run['inputs'].values()])
        workflow.save(m);return result


def prepare(workflow,sid,body,settings,progress):
    """逐来源/成分/受体在原研究索引登记检查点；完整对象恢复，原件改变继续阻断。"""
    core.request('prepare',body)
    tools=NativeTools(settings);adapter=NativeIO(tools);w=adapter.wrap(workflow)
    try:
        _,_,data=core.source(w,sid,'prepare',body)
        config=preparation_config(data['plan'],tools.signature_sha256)
        run,repeated,data=core.begin(w,sid,'prepare',body,config)
        if repeated:return w.result(w.load(sid),run['run_id'])
        home=w.location(sid);folder=home/'runs/A06_PREP'/run['run_id']/'plan_preparation'
        folder.mkdir(parents=True,exist_ok=True)
        # 仅保留原校验器既定归档布局；文件头/平台签名明确证明实际是本机原生二进制。
        binary=folder/'software/vina_1.2.7.exe'
        if not binary.exists():tools.copy_vina(home,binary.parent,name=binary.name)
        require(file_record(home,binary,'vina')['sha256']==tools.profile['vina']['sha256'],'准备Vina快照不同')
        tools.execution_vina=binary
        signature_path=folder/'native_signature.json'
        if not signature_path.exists():write_json(signature_path,tools.signature_value)
        signature_ref=file_record(home,signature_path,'native_tools_signature')
        require(fingerprint(read_json(verified_file(home,signature_ref)))==tools.signature_sha256,'原生工具签名不同')
        saved=w.read_native_checkpoint(sid,run['run_id'],'source')
        if saved:connection=saved[1]['payload']
        else:
            progress('连接本批全部官方来源，失败留因')
            attempt=folder/'sources'/new_id('attempt')
            connection=adapter.bind(preparation.connect)(home,data['packet'],attempt,progress)
            connection['id']=run['run_id']
            refs=[file_record(home,p,'native_source_evidence') for p in attempt.rglob('*') if p.is_file()]
            w.append_native_checkpoint(sid,run['run_id'],'source',connection,refs)
        compounds=[];receptors=[]
        for kind,rows in (('compound',connection['compounds']),('receptor',connection['receptors'])):
            for index,row in enumerate(rows,1):
                key=f'{kind}_{index:06d}'
                saved=w.read_native_checkpoint(sid,run['run_id'],key)
                if saved:value=saved[1]['payload']
                else:
                    progress(f'原生准备 {kind} {index}/{len(rows)}')
                    subset=dict(connection,compounds=[row] if kind=='compound' else [],receptors=[row] if kind=='receptor' else [])
                    attempt=folder/'objects'/key/new_id('attempt')
                    c,r=adapter.bind(preparation.prepare)(home,subset,attempt,Path(settings.science_tools_root or settings.project_root),progress,config)
                    value=(c or r)[0]
                    refs=[file_record(home,p,'native_preparation_evidence') for p in attempt.rglob('*') if p.is_file()]
                    tools.verify_current()
                    w.append_native_checkpoint(sid,run['run_id'],key,value,refs)
                (compounds if kind=='compound' else receptors).append(value)
        summary,tables=preparation.reports(data['packet'],compounds,receptors)
        fact=dict(schema_version=core.PREPARATION,study_id=sid,input_key=data['packet']['input_key'],
            request_id=body['request_id'],author=body['author'].strip(),note=body['note'].strip(),
            connection=connection,config=config,compounds=compounds,receptors=receptors,
            vina_binary=file_record(home,binary,'vina_binary'),vina_sha256=tools.profile['vina']['sha256'],
            native_signature=signature_ref,files=[file_record(home,p,'native_preparation_evidence') for p in folder.rglob('*') if p.is_file()])
        # 完整发表候选也登记为原检查点，发表中断后复用原包，不覆盖或重做准备。
        candidate=w.read_native_checkpoint(sid,run['run_id'],'publication')
        if candidate:
            ref=candidate[1]['payload']['packet'];fact=read_json(verified_file(home,ref))
            summary,tables=preparation.reports(data['packet'],fact['compounds'],fact['receptors'])
        else:
            path=folder/'packet.json'
            require(not path.exists(),'未登记完整准备包残件保留，不能伪装恢复成功')
            write_json(path,fact);ref=file_record(home,path,'preparation_packet')
            w.append_native_checkpoint(sid,run['run_id'],'publication',{'packet':ref},[ref,*fact['files']])
        tables['preparation_packet']=[ref]
        tools.verify_current()
        with write_lock(w.root):
            _,inputs,_=core.source(w,sid,'prepare',body)
            m=w.load(sid);require(w.active(m,run['run_id']) and inputs['a06_plan_input']==run['inputs']['a06_plan_input'],'准备发表前来源改变')
            result=w._finish(m,run['run_id'],summary,tables,[],'success',attachments=[*fact['files'],ref])
            w.save(m)
            return result
    finally:adapter.close()


def scoring_config(prep,signature):
    """新评分沿本批准备的同一参数；每组合单CPU，不增加引擎或改变阈值。"""
    require(prep['config']['native_tools_sha256']==signature,'准备与评分的原生工具/源码签名不同，须明确新准备')
    return dict(version=VERSION,vina_parameters=deepcopy(prep['config']['vina_parameters']),
        cpu_per_pair=1,timeout_seconds=1800,native_tools_sha256=signature,
        source_config_hash=prep['config_hash'],scientific_basis='A06.plan_score_pair.1')


def scoring_rows(home,run,prep_result,prep_fact,rows,binary):
    """独立核完整笛卡尔范围、执行位置、所有模式与实际MODEL1，NA不填零。"""
    expected=[]
    compounds={r['compound_id']:r for r in prep_fact['compounds']}
    receptors={r['target_id']:r for r in prep_fact['receptors']}
    planned=prep_result['tables']['planned_pairs']
    require(len(rows)==len(planned),'原生评分不是完整矩阵')
    for index,(source,supplied) in enumerate(zip(planned,rows),1):
        row=dict(source,execution=None,quality=receptors[source['target_id']]['quality'])
        if source['state']=='ready':
            ref=supplied['execution']
            prefix=f'runs/A06/{run["run_id"]}/native_scoring/pairs/pair_{index:06d}/'
            require(ref['path'].startswith(prefix) and re.fullmatch(r'attempt_[0-9a-f]{32}/execution.json',ref['path'][len(prefix):]),
                    '原生评分执行不属于当前组合')
            evidence=receptor_evidence(receptors[source['target_id']])
            actual=validate_pair(home,ref,binary,ligand_record(compounds[source['compound_id']]),evidence['receptor'],evidence['box'],run['config'])
            row.update(state=actual['state'],score=actual['score'],reason_zh=actual['reason_zh'],execution=ref)
        else:require(source['state']=='NA' and source['score'] is None and source['reason_zh'],'原生NA须保留原因')
        expected.append(row)
    require(fingerprint(expected)==fingerprint(rows),'原生评分与实际执行、范围或原始分数不一致')
    return expected


def score_summary(prep_fact,rows,input_record):
    """数量只来自完整同批组合，严格/探索及NA分别说明。"""
    return {'science_version':VERSION,'pair_count':len(rows),'compound_count':len(prep_fact['compounds']),
        'receptor_count':len(prep_fact['receptors']),'scored_pairs':sum(r['state']=='completed' for r in rows),
        'failed_pairs':sum(r['state']=='failed' for r in rows),'na_pairs':sum(r['state']=='NA' for r in rows),
        'input_key':input_record['packet']['input_key'],'human_review_written':False,
        'message_zh':'本平台新评分完整归档，NA与失败保留；结果仍须独立科研复核'}


def scoring_validator(root,previous):
    """历史读取只核已归档资料，不要求当前电脑还安装同一工具；恢复执行另核实际环境。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return previous(run,summary,tables,anomalies,outcome)
        home=Path(root)/'studies'/run['study_id'];inputs=run['inputs']
        prep=read_json(verified_file(home,inputs['preparation_run']))
        result=read_json(verified_file(home,inputs['preparation_result']))
        review=read_json(verified_file(home,inputs['preparation_review']))
        require(prep['config']['version']==core.QUALIFIED and prep['study_id']==run['study_id']
            and result['run_id']==prep['run_id'] and review['run_id']==prep['run_id']
            and review['decision']=='approved' and review['result_hash']==inputs['preparation_result']['sha256']
            and run['parent_runs']=={'A06_PREP':prep['run_id']}
            and run['parent_review_ids']=={'A06_PREP':review['review_id']},'原生评分来源或批准不同')
        preparation_validator(root,lambda *_:None)(prep,result['summary'],result['tables'],result['anomalies'],result['outcome'])
        fact=read_json(verified_file(home,tables['scoring_packet'][0]))
        source=read_json(verified_file(home,result['tables']['preparation_packet'][0]))
        record=read_json(verified_file(home,inputs['a06_plan_input']))
        require(fact['schema_version']==VERSION and fact['run_id']==run['run_id']
            and fingerprint(fact['configuration'])==fingerprint(run['config'])
            and run['config']==scoring_config(prep,run['config']['native_tools_sha256']), '原生评分协议或参数不同')
        binary=verified_file(home,fact['binary'])
        signature=read_json(verified_file(home,fact['native_signature']))
        require(fingerprint(signature)==run['config']['native_tools_sha256']
                and fact['binary']['sha256']==source['vina_sha256'],'原生评分工具字节不同')
        rows=scoring_rows(home,run,result,source,fact['pairs'],binary)
        require(summary==score_summary(source,rows,record) and summary==fact['summary']
            and tables['native_scores']==table_rows(rows) and anomalies==[]
            and outcome==('success' if summary['scored_pairs'] else 'failed'),'原生评分表或摘要不一致')
        require(verified_file(home,fact['matrix_csv']).read_text('utf-8-sig')==matrix_csv(rows),'原生CSV与完整同批分数不同')
        for ref in fact['files']:verified_file(home,ref)
    return check


def score(workflow,sid,body,settings,progress):
    """原生评分逐组合恢复；完成组不重算，未登记残件阻断，NA完整保留。"""
    core.request('score',body)
    tools=NativeTools(settings);adapter=NativeIO(tools);w=adapter.wrap(workflow)
    try:
        _,_,data=core.source(w,sid,'score',body)
        config=scoring_config(data['preparation'],tools.signature_sha256)
        run,repeated,data=core.begin(w,sid,'score',body,config)
        if repeated:return w.result(w.load(sid),run['run_id'])
        home=w.location(sid);folder=home/'runs/A06'/run['run_id']/'native_scoring'
        folder.mkdir(parents=True,exist_ok=True)
        binary=folder/'software'/('vina.exe' if tools.profile['system']=='Windows' else 'vina')
        if not binary.exists():tools.copy_vina(home,binary.parent,name=binary.name)
        require(file_record(home,binary,'vina')['sha256']==tools.profile['vina']['sha256'],'原生评分Vina字节不同')
        signature_path=folder/'native_signature.json'
        if not signature_path.exists():write_json(signature_path,tools.signature_value)
        signature_ref=file_record(home,signature_path,'native_tools_signature')
        compounds={r['compound_id']:r for r in data['fact']['compounds']}
        receptors={r['target_id']:r for r in data['fact']['receptors']}
        rows=[]
        for index,planned in enumerate(data['result']['tables']['planned_pairs'],1):
            progress(f'原生组合评分 {index}/{len(data["result"]["tables"]["planned_pairs"])}')
            row=dict(planned,quality=receptors[planned['target_id']]['quality'],execution=None)
            if planned['state']=='ready':
                key=f'pair_{index:06d}';saved=w.read_native_checkpoint(sid,run['run_id'],key)
                evidence=receptor_evidence(receptors[planned['target_id']])
                if saved and not saved[1]['payload'].get('retryable'):ref=saved[1]['payload']['execution']
                else:
                    ref=adapter.bind(execute)(home,folder/'pairs'/key/new_id('attempt'),binary,ligand_record(compounds[planned['compound_id']]),
                                              evidence['receptor'],evidence['box'],config)
                    actual=adapter.bind(validate)(home,ref,binary,ligand_record(compounds[planned['compound_id']]),evidence['receptor'],evidence['box'],config)
                    w.append_native_checkpoint(sid,run['run_id'],key,{'execution':ref,
                        'retryable':actual['state']=='failed' and actual['failure_kind'] in ('timeout','launch_error')},[ref,*actual['files']])
                actual=adapter.bind(validate)(home,ref,binary,ligand_record(compounds[planned['compound_id']]),evidence['receptor'],evidence['box'],config)
                row.update(state=actual['state'],score=actual['score'],reason_zh=actual['reason_zh'],execution=ref)
            rows.append(row)
        summary=score_summary(data['fact'],rows,data['input_record'])
        # 图件独立尝试并登记，评分发表中断时复用已登记图件，不覆盖历史或隐式重算。
        display_saved=w.read_native_checkpoint(sid,run['run_id'],'display')
        if display_saved:figures,display_files=display_saved[1]['payload']['figures'],display_saved[1]['payload']['files']
        else:
            packet={'schema_version':VERSION,'study_id':sid,'run_id':run['run_id'],
                'source_fixed':data['input_record']['packet'],'compounds':data['fact']['compounds'],
                'receptors':data['fact']['receptors'],'pairs':[dict(r,source_kind='native') for r in rows],'summary':summary}
            figures,display_files=export(home,packet,folder/'display'/new_id('display'),font_path=str(settings.font_regular))
            w.append_native_checkpoint(sid,run['run_id'],'display',{'figures':figures,'files':display_files},figures+display_files)
        csv_path=folder/'matrix.csv'
        if not csv_path.exists():csv_path.write_text(matrix_csv(rows),encoding='utf-8-sig',newline='')
        require(csv_path.read_text('utf-8-sig')==matrix_csv(rows),'未登记评分CSV残件或原值不同，不能覆盖')
        fact={'schema_version':VERSION,'study_id':sid,'run_id':run['run_id'],'configuration':config,
            'pairs':rows,'summary':summary,'binary':file_record(home,binary,'native_vina'),
            'native_signature':signature_ref,'matrix_csv':file_record(home,csv_path,'native_matrix_csv'),
            'files':[file_record(home,p,'native_scoring_evidence') for p in folder.rglob('*') if p.is_file()]}
        candidate=w.read_native_checkpoint(sid,run['run_id'],'publication')
        if candidate:ref=candidate[1]['payload']['packet'];fact=read_json(verified_file(home,ref))
        else:
            path=folder/'packet.json';require(not path.exists(),'未登记评分事实包残件保留，不能伪装成功')
            write_json(path,fact);ref=file_record(home,path,'scoring_packet')
            w.append_native_checkpoint(sid,run['run_id'],'publication',{'packet':ref},[ref,*fact['files']])
        tools.verify_current()
        with write_lock(w.root):
            _,inputs,_=core.source(w,sid,'score',body)
            m=w.load(sid);require(w.active(m,run['run_id']) and all(run['inputs'][k]==v for k,v in inputs.items()),'原生评分发表前输入已改变')
            result=w._finish(m,run['run_id'],summary,{'scoring_packet':[ref],'native_scores':table_rows(rows)},[],
                'success' if summary['scored_pairs'] else 'failed',attachments=[*fact['files'],ref,*display_files],figures=figures)
            w.save(m);return result
    finally:adapter.close()
