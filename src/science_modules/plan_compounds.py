"""方案成分选择的独立科学协议：读取实际A03排序，不沿用旧固定前五。"""
from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require
from storage import read_json, verified_file
from science_modules.analysis_protocol import checked_plan

VERSION = 'A03.plan_selection.1'


def select(summary, tables, plan):
    """按方案目标和指定指标保留完整边界并列；零交集和不足分别留因。"""
    plan=checked_plan(plan)
    target=plan['parameters']['a06.component_count']
    metric=plan['parameters']['a06.component_sort']
    ranking=deepcopy(tables['ranking'])
    require(isinstance(ranking,list) and len({r['compound_id'] for r in ranking})==len(ranking),
            'A03完整成分排序缺失或编号重复')
    for row in ranking:
        require(all(isinstance(row[key],int) and not isinstance(row[key],bool) and row[key]>=0
                    for key in ('intersection_count','mixed_degree')), 'A03成分指标不是非负整数')
        require(row['in_network'] is (row['intersection_count']>0), 'A03成分入图状态与实际交集数不一致')
    ranking.sort(key=lambda r:(-r[metric],r['compound_id']))
    eligible=[r for r in ranking if r['in_network']]
    cutoff=eligible[min(target,len(eligible))-1][metric] if eligible else None
    chosen=[r for r in eligible if r[metric]>=cutoff] if eligible else []
    ties=len(chosen)>min(target,len(eligible))
    selected=[]
    for row in chosen:
        item=deepcopy(row)
        item['selection_role']='边界并列纳入' if ties and row[metric]==cutoff else '方案排序入选'
        item['selection_score']=row[metric]
        selected.append(item)
    identifiers={r['compound_id'] for r in selected}
    excluded=[{'compound_id':r['compound_id'],'name':r['name'],
               'reason_zh':'无交集关系，不进入对接名单' if not r['in_network'] else '低于本方案排序范围'}
              for r in ranking if r['compound_id'] not in identifiers]
    purpose=summary.get('analysis_purpose')
    require(purpose in ('workflow_test','formal_research'),'A03原结果缺少明确研究用途')
    result={'protocol_version':VERSION,'analysis_purpose':purpose,'主候选数':len(selected),
            '目标成分数':target,'合格成分数':len(eligible),'边界并列额外纳入数':max(0,len(selected)-target),
            '排序指标':metric,'截断值':cutoff,'候选不足':len(eligible)<target,
            '选择策略':'按方案排序、保留边界并列、不足按实际','handoff_blocked':False}
    return result,{'selected':selected,'excluded':excluded,'ranking':ranking}


def facts(home,inputs):
    """离线复算核验方案、实际父结果和明确确认的原始输入快照。"""
    record=read_json(verified_file(home,inputs['analysis_plan_file']))
    plan=checked_plan(record['plan'])
    require(record['study_id']==inputs['study_id'] and record['expected_a00']==inputs['bound_a00']
            and record['plan_id']==inputs['analysis_plan_id']
            and plan['parameter_hash']==inputs['analysis_parameter_hash'],'成分选择方案归属或参数不一致')
    a03=read_json(verified_file(home,inputs['a03_result']))
    request=read_json(verified_file(home,inputs['execution_request_file']))
    require(a03['study_id']==inputs['study_id'] and a03['run_id']==inputs['bound_a03']
            and a03['summary'].get('protocol_version')=='A03.plan_intersection.1', '成分选择不是本研究新方案交集')
    body=request['request'];binding=request['binding']
    require(request['schema_version']=='A03.plan_selection.request.1' and request['study_id']==inputs['study_id']
            and body['confirmed'] is True and body['expected_a03']==a03['run_id']
            and body['expected_a00']==inputs['bound_a00'] and body['expected_plan_id']==record['plan_id']
            and body['expected_input_hash']==fingerprint(binding)
            and binding['current']['A03']==a03['run_id'] and binding['study_id']==inputs['study_id']
            and binding['a00']==inputs['bound_a00'] and binding['plan_id']==record['plan_id']
            and binding['parameter_hash']==plan['parameter_hash'],'成分选择明确确认与实际输入不一致')
    summary,tables=select(a03['summary'],a03['tables'],plan)
    review=binding.get('docking_review')
    if review:
        pending={r['compound_id'] for r in review['compounds'] if not r['identity_prechecked']}
        pending.update(r['compound_id'] for r in review['excluded'])
        require(not {r['compound_id'] for r in tables['selected']}&pending,
                '方案入选成分存在身份或来源待补，不能换入低排名对象代替')
    summary.update(analysis_plan_id=record['plan_id'],analysis_parameter_hash=plan['parameter_hash'])
    return summary,tables


def configuration(plan):
    """新配置只固化目标、指标和并列规则，不修改旧选择版本。"""
    plan=checked_plan(plan)
    return {'version':VERSION,'target_count':plan['parameters']['a06.component_count'],
            'metric':plan['parameters']['a06.component_sort'],'keep_boundary_ties':True,
            'replace_unavailable':False}


def validator(root,fallback):
    """仅核验新选择；历史固定五项及人工补充仍使用原科学校验器。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return fallback(run,summary,tables,anomalies,outcome)
        home=Path(root)/'studies'/run['study_id'];inputs=run['inputs']
        expected,rows=facts(home,inputs)
        plan=read_json(verified_file(home,inputs['analysis_plan_file']))['plan']
        request=read_json(verified_file(home,inputs['execution_request_file']))
        require(run['config']==configuration(plan) and run['parent_runs']['A03']==inputs['bound_a03']
                and run['parent_review_ids']['A03']==request['binding']['reviews']['A03'],
                '成分选择配置或实际父运行/复核不一致')
        require(fingerprint((summary,tables))==fingerprint((expected,rows)), '成分名单或完整排序与本方案复算不一致')
        require(outcome==('success' if rows['selected'] else 'empty'),'成分选择空结果状态不一致')
    return check
