"""新方案报告事实模型：读取真实统计/评分，区分系统范围规则与人工审核，不运行科研计算。"""
from copy import deepcopy
import math
from contracts import fingerprint,require
from science_modules.analysis_protocol import checked_plan
from science_modules.a05.plan_display import check_source
from science_modules.a05.display import english,translate

VERSION='A07.plan_facts.1'
SCOPE_VERSION='A05.plan_automatic_scope.1'
GROUPS=('BP','CC','MF','KEGG')
BOUNDARY='计算结果用于研究假设筛选，不证明临床疗效、通路激活、抑制或体内结合；Vina评分不是实测结合自由能。'


def bilingual(row):
    """只呈现来源中已有的精确核译；缺译保留原英文与明确待核译标记。"""
    original=english(row);zh=row.get('description_zh') or ''
    return {'ID':row['ID'],'english':original,'chinese':zh,'translation_status':'checked' if zh else 'pending',
            'label':original+(' / '+zh if zh else ' / 中文待核译')}


def automatic_enrichment(base,plan,source):
    """按已确定v1.8规则产生系统范围事实，不冒充人工confirmed决定或改完整统计。"""
    plan,groups=check_source(base,plan,source);p=plan['parameters'];tables={};states=[];pending=set()
    assessment=source['assessments'];excluded=[];deferred=[]
    for group in GROUPS:
        included=p['a05.include_kegg' if group=='KEGG' else 'a05.include_go'];raw=groups[group]
        require(included or not raw,'未纳入类别不能出现显著条目')
        require(len({row['ID'] for row in raw})==len(raw),'报告统计存在重复显著编号')
        ordered=sorted(raw,key=lambda row:(float(row['p.adjust']),row['ID']))
        require(all(type(row['p.adjust']) in (int,float) and math.isfinite(row['p.adjust'])
                    and 0<=row['p.adjust']<p['a05.adjusted_p_max'] for row in ordered),'显著表不符合本批严格BH阈值')
        values=[]
        for original in ordered:
            row=translate(original,source['translations']);row.update(bilingual(row))
            if group=='KEGG':
                rule=assessment[row['ID']];require(rule['classification_status'] in ('retain','exclude','uncertain'),'官方分类状态未知')
                row.update(deepcopy(rule))
                if rule['classification_status']=='exclude':excluded.append(row);continue
                if rule['classification_status']=='uncertain':
                    row['defer_reason_zh']='分类或本病身份待判断，依据固定系统范围规则暂不进入主图；'+rule['reason_zh']
                    deferred.append(row);continue
            values.append(row)
        key=group.lower();plot_top=p['a05.kegg_plot_top' if group=='KEGG' else 'a05.go_plot_top']
        table_top=p['a05.kegg_table_top' if group=='KEGG' else 'a05.go_table_top']
        tables[key+'_display']=values[:plot_top];tables[key+'_plan_top']=values[:table_top]
        shown=tables[key+'_display']+tables[key+'_plan_top']
        if group=='KEGG':
            tables['kegg_plan_count_top']=sorted(values,key=lambda row:(-int(row['Count']),float(row['p.adjust']),row['ID']))[:table_top]
            shown+=tables['kegg_plan_count_top']
        pending.update(row['ID'] for row in shown if row['translation_status']=='pending')
        states.append({'group':group,'included':included,'significant_count':len(raw) if included else None,
                       'retained_count':len(values) if included else None,'plot_count':len(tables[key+'_display']) if included else None,
                       'table_count':len(tables[key+'_plan_top']) if included else None})
    tables.update(kegg_excluded=excluded,kegg_deferred=deferred)
    return {'schema_version':SCOPE_VERSION,'study_id':base.get('study_id'),'run_id':base.get('run_id'),
            'authority_kind':'system_scope_rule','rule_basis':'ModuleA.v1.8.20261026',
            'statistical_result_hash':fingerprint(base),'parameter_hash':plan['parameter_hash'],
            'groups':states,'tables':tables,'pending_translations':sorted(pending),
            'classification_source':{'schema_version':source['catalog'].get('schema_version'),'sha256':source['catalog_sha256'],
                                     'classification_version':source['classification_version'],'disease_identity':deepcopy(source['identity'])},
            'statistics_changed':False,'human_review_written':False,'scientific_validation_performed':False,
            'note_zh':'仅派生报告展示范围；原统计/BH保持，未知分类留附录，缺译保留英文标明，不伪造人工审批或科学校验。'}


def docking(packet,configuration,*,preparation_only=False):
    """完整笛卡尔矩阵保留原评分与NA/失败；仅有准备包时不假称已执行Vina。"""
    require(isinstance(packet,dict) and all(key in packet for key in ('compounds','receptors')),'报告缺少实际对接固定范围')
    compounds=deepcopy(packet['compounds']);receptors=deepcopy(packet['receptors'])
    cids=[row['compound_id'] for row in compounds];tids=[row['target_id'] for row in receptors]
    require(all(isinstance(value,str) and value for value in cids+tids) and len(cids)==len(set(cids))
            and len(tids)==len(set(tids)),'报告固定成分或受体编号缺失/重复')
    rows=packet.get('planned_pairs' if preparation_only else 'pairs')
    require(isinstance(rows,list),'报告缺少实际固定组合表')
    expected={(cid,tid) for cid in cids for tid in tids};actual=[];pairs=[]
    for raw in rows:
        require(isinstance(raw,dict) and all(isinstance(raw.get(key),str) for key in ('compound_id','target_id')),'评分组合记录格式错误')
        key=(raw['compound_id'],raw['target_id']);actual.append(key)
        state=raw.get('state');score=raw.get('score')
        require(state in (('ready','NA') if preparation_only else ('completed','failed','NA')),'报告不支持未知组合状态')
        if state=='completed':
            require(type(score) in (int,float) and math.isfinite(score),'已评分组合必须保留有限原始评分')
            require(raw.get('quality') in ('严格','探索'),'已评分组合必须区分实际严格或探索范围')
        else:
            require(score is None,'NA、失败或未计算组合不能填零或借用评分')
            if state in ('failed','NA'):require(isinstance(raw.get('reason_zh'),str) and raw['reason_zh'].strip(),'NA或失败须保留实际原因')
        pairs.append(deepcopy(raw))
    require(len(actual)==len(set(actual)) and set(actual)==expected,'报告完整矩阵缺项、重复或跨范围')
    scored=[row for row in pairs if row['state']=='completed'];failed=[row for row in pairs if row['state']=='failed']
    na=[row for row in pairs if row['state']=='NA'];ready=[row for row in pairs if row['state']=='ready']
    if preparation_only:
        state='waiting' if ready else 'not_applicable'
        reason='仍有可计算对象，等待实际评分分支结束' if ready else '本批准备组合全部NA，对接不适用；原因完整保留'
    elif failed and not scored:state,reason='technical_blocked','实际评分未产生可用结果，保留失败与NA；不能标成完整分析成功'
    elif scored:state,reason=('partial','部分组合有原始评分，其余NA或失败分别保留') if len(scored)<len(pairs) else ('completed','固定完整范围均有实际原始评分')
    else:state,reason='not_applicable','本批无可用评分组合，原NA保持；不虚构成功评分'
    order={(row['compound_id'],row['target_id']):row for row in pairs}
    matrix=[{'compound_id':cid,'cells':[deepcopy(order[(cid,tid)]) for tid in tids]} for cid in cids]
    return {'schema_version':VERSION,'study_id':packet.get('study_id'),'run_id':packet.get('run_id'),
            'state':state,'reason_zh':reason,'preparation_only':preparation_only,
            'compounds':compounds,'receptors':receptors,'pairs':pairs,'matrix':matrix,'configuration':deepcopy(configuration),
            'counts':{'compounds':len(cids),'receptors':len(tids),'pairs':len(pairs),'scored':len(scored),'failed':len(failed),'NA':len(na),'ready':len(ready),
                      'strict_scored':sum(row.get('quality')=='严格' for row in scored),'exploratory_scored':sum(row.get('quality')=='探索' for row in scored)},
            'score_unit':'kcal/mol','note_zh':BOUNDARY,'scientific_validation_performed':False,'human_review_written':False}


def completion(branches):
    """报告等待适用分支结束；空、部分、不适用和关键阻塞都有独立状态，不伪装成功。"""
    require(isinstance(branches,list) and all(isinstance(row,dict) for row in branches),'报告分支事实须为列表')
    require(branches and len({row['branch'] for row in branches})==len(branches),'报告分支缺失或重复')
    allowed={'completed','partial','valid_empty','not_applicable','waiting','technical_blocked'}
    require(all(row.get('state') in allowed and isinstance(row.get('reason_zh'),str) and row['reason_zh'].strip() for row in branches),
            '报告分支状态或依据缺失')
    states={row['state'] for row in branches}
    state='technical_blocked' if 'technical_blocked' in states else 'waiting' if 'waiting' in states else 'partial' if 'partial' in states else 'valid_empty' if 'valid_empty' in states or states=={'not_applicable'} else 'completed'
    return {'schema_version':VERSION,'state':state,'all_applicable_finished':'waiting' not in states,
            'complete_analysis':state=='completed','branches':deepcopy(branches),
            'note_zh':BOUNDARY,'scientific_validation_performed':False,'human_review_written':False}
