"""从原请求、固定范围和登记检查点分别展示准备、组合与区域进度。"""
import json
from datetime import datetime,timezone
import re

from contracts import ContractError,fingerprint,require
from .errors import ApiError,not_found


def counts(total, reused, new, succeeded, failed):
    """计数口径由后端一次提供；完成数与成功数分别表达。"""
    complete=reused+new
    return {'total':total,'completed':complete,'reused':reused,'new':new,'succeeded':succeeded,
            'failed':failed,'pending':max(total-complete,0) if total is not None else None}


def summarize(fixed, baseline, prepared, inherited, current):
    """复用既有区域选择方法；完整区域组终态后才计为完成组合。"""
    from science_modules.a06.trial_rules import choose_score
    cids=[c['compound_id'] for c in fixed['compounds']];tids=[r['target_id'] for r in fixed['receptors']]
    expected=[(c,t) for c in cids for t in tids]
    prior={(p['compound_id'],p['target_id']):p for p in baseline['pairs']}
    require(set(prior)==set(expected),'进度基线不覆盖固定完整组合')
    receptors={r['target_id']:r for r in prepared}
    start_ready={t for t,r in receptors.items() if r.get('state')=='ready'}
    def merge(source):
        for key,payload in source.items():
            if key.startswith('receptor_') and payload.get('target_id') in tids:
                receptors[payload['target_id']]=payload
    merge(inherited);inherited_ready={t for t,r in receptors.items() if r.get('state')=='ready'}
    merge(current)
    ready={t for t,r in receptors.items() if r.get('state')=='ready'}
    attempted={p['target_id'] for key,p in current.items() if key.startswith('receptor_')
               and p.get('state') in ('ready','NA','failed') and p.get('target_id') in tids}
    prep_terminal=inherited_ready|attempted
    reused_preps=len(inherited_ready);new_preps=len(prep_terminal-inherited_ready)
    prep=counts(len(tids),reused_preps,new_preps,len(ready),len(prep_terminal-ready))
    original_pairs={key for key,p in prior.items() if p['state']=='completed'}
    allfacts=dict(inherited);allfacts.update(current)
    done_pairs=success_pairs=failed_pairs=inherited_pairs=0;reused_pairs=len(original_pairs)
    region_total=region_new=region_reused=region_success=region_failed=0
    unknown=bool(set(tids)-prep_terminal)
    for ordinal,key in enumerate(expected,1):
        if key in original_pairs:continue
        receptor=receptors.get(key[1],{})
        planned=receptor.get('regions')
        if receptor.get('state')=='ready' and not planned:
            unknown=True;continue
        if not planned:continue
        region_total+=len(planned)
        facts=[]
        for index,region in enumerate(planned,1):
            cpkey=f'pair_{ordinal:06d}_region_{index:04d}'
            fact=allfacts.get(cpkey)
            if fact is None or fact.get('retryable') or fact.get('state') not in ('completed','failed'):
                continue
            require(fact.get('region_id')==region['region_id'],'进度区域与预定集合不同')
            facts.append(fact)
            region_new+=int(cpkey in current);region_reused+=int(cpkey not in current)
            region_success+=int(fact['state']=='completed');region_failed+=int(fact['state']=='failed')
        if len(facts)==len(planned):
            inherited_only=all(f'pair_{ordinal:06d}_region_{i:04d}' not in current for i in range(1,len(planned)+1))
            inherited_pairs+=int(inherited_only)
            done_pairs+=int(not inherited_only)
            success_pairs+=int(choose_score(facts,receptor['mode']) is not None)
            failed_pairs+=int(choose_score(facts,receptor['mode']) is None)
    pairs=counts(len(expected),reused_pairs+inherited_pairs,done_pairs,reused_pairs+success_pairs,failed_pairs)
    regions=counts(None if unknown else region_total,region_reused,region_new,region_success,region_failed)
    return {'preparation':prep,'pairs':pairs,'regions':regions,
            'region_total_note_zh':'部分区域集合尚未登记，总数未固定' if unknown else '区域按预定集合计数，与组合数分别展示'}


def info(app,req,task_id):
    """元数据读取保留首次与退出全SHA，当前任务不能借用另一请求的A06。"""
    if req.query:raise ApiError(422,'VALIDATION_FAILED','科学进度不接受额外查询')
    task=app.tasks._raw(task_id)
    if not task:raise not_found('任务')
    if task['kind'] not in ('plan_system_receptor_rescue','plan_system_receptor_rescue_v2'):
        return {'supported':False,'available':False,'message_zh':'本任务沿原阶段进度与日志展示'}
    try:
        from ..core.rescue_read_evidence import json_evidence_scope
        w=app.kernel.read_workflow();sid=task['study_id'];body=json.loads(task['payload'])
        with json_evidence_scope(app.settings.data_root,sid) as evidence:
            manifest=w.load(sid);home=w.location(sid)
            def read(ref):return evidence.reader.read(home,ref)
            matches=[]
            for rid in manifest['runs']:
                run=w.run(manifest,rid)
                if run['config'].get('version') not in ('A06.system_rescue.1','A06.system_rescue.2'):continue
                request=read(run['inputs']['rescue_request'])
                if request['request']['request_id']==body.get('request_id'):
                    require(request['request']==body,'任务与科学运行的完整请求绑定不同')
                    matches.append(run)
            if not matches:return {'supported':True,'available':False,'message_zh':'原任务尚未登记科学运行；请查看排队状态与日志'}
            require(len(matches)==1,'同请求存在多个补救运行')
            run=matches[0];fixed=read(run['inputs']['system_input_ref'])['payload']
            result=read(run['inputs']['source_scoring_result']);baseline=read(result['tables']['scoring_packet'][0])
            prep_result=read(run['inputs']['source_preparation_result'])
            prep=read(prep_result['tables']['preparation_packet'][0])['receptors']
            inherited={};current={};updated=run['created_at'];previous_refs={}
            partial=run['inputs'].get('source_binding',{}).get('partial_recovery') or {}
            for field in ('analysis_plan_receptor_rescue_checkpoints','analysis_plan_receptor_rescue_v2_checkpoints'):
                for ref in manifest.get(field,[]):
                    value=read(ref)
                    if value.get('run_id') not in (run['run_id'],partial.get('run_id')):continue
                    if value['run_id']!=run['run_id'] and ref not in partial.get('checkpoint_refs',[]):continue
                    owner=w.run(manifest,value['run_id'])
                    require(value.get('study_id')==sid and value.get('human_review_written') is False,
                            '进度检查点研究或人工标记不同')
                    chain=(value['run_id'],value['key'])
                    require(value.get('config_hash')==owner['config_hash']
                            and value.get('schema_version')==owner['config']['version']
                            and value.get('previous')==previous_refs.get(chain), '进度检查点配置或登记链不同')
                    previous_refs[chain]=ref
                    for original in value.get('files',[]):evidence.reader.verify(home,original)
                    destination=current if value['run_id']==run['run_id'] else inherited
                    previous=destination.get(value['key'])
                    require(not previous or previous.get('retryable') is True,'已成功检查点不可覆盖')
                    destination[value['key']]=value['payload'];updated=max(updated,value.get('created_at',updated))
            value=summarize(fixed,baseline,prep,inherited,current)
            if manifest['runs'][run['run_id']].get('result_file'):
                final=w.result(manifest,run['run_id'])
                packet=read(final['tables']['scoring_packet'][0])
                rows=packet['pairs'];reused=len(packet.get('reused_pair_keys',[]))
                if 'reused_pair_keys' not in packet:
                    reused=int(packet['summary'].get('reused_scored_pairs',0))
                fresh=len(packet.get('new_pair_keys',[]))
                value['pairs']=dict(counts(len(rows),reused,fresh,sum(p['state']=='completed' for p in rows),
                    sum(p['state']=='failed' for p in rows)),completed=len(rows),pending=0,na=sum(p['state']=='NA' for p in rows))
                value['message_zh']='整批组合终态已归档；NA、有效评分和失败分别保留，仍须独立科研复核'
            require(fingerprint(w.load(sid))==fingerprint(manifest),'进度读取期间登记已改变，请刷新')
            message=value.pop('message_zh','只统计已登记并核验的原件；目录残件不计成功，区域数不作组合成功数')
            return dict(value,supported=True,available=True,run_id=run['run_id'],updated_at=updated,
                current_object_zh=(json.loads(task['progress']) if task.get('progress') else {}).get('step_zh','尚未记录当前对象'),
                estimate_seconds=None,estimate_note_zh='尚无经过核验的同类耗时样本，不估算剩余时间',
                message_zh=message)
    except (ContractError,KeyError,ValueError,TypeError,OSError) as error:
        raise ApiError(503,'ARCHIVE_UNAVAILABLE','科学进度原件尚不能完整核验：'+str(error)) from error
