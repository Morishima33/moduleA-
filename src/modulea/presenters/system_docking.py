"""系统批次结构准备及评分只读适配，完整NA和本批名称均来自实际归档。"""
from .base import Parts,clean,kpi,param,table

SCORING=('A06.system_scoring.1','A06.system_scoring.2','A06.system_scoring_paths.1','A06.system_scoring.3')
PATH_REPAIR=('A06.system_qualification_paths.1','A06.system_scoring_paths.1')
VERSIONS=('A06.system_preparation.1','A06.system_preparation.2','A06.system_qualification.1',
    'A06.system_qualification.2','A06.system_qualification_paths.1','A06.system_preparation.3','A06.system_qualification.3',*SCORING)


def present(result,packet):
    """固定范围与完整长表交叉展示；不重算评分、准备资格或人工批准。"""
    s=result['summary'];t=result['tables'];parts=Parts();scoring=s['science_version'] in SCORING
    compounds={r['compound_id']:r for r in packet['compounds']};receptors={r['target_id']:r for r in packet['receptors']}
    rows=[dict(row,compound_name=compounds[row['compound_id']].get('name') or row['compound_id'],
        target_name=receptors[row['target_id']].get('symbol') or row['target_id'])
        for row in t['plan_scoring_pairs' if scoring else 'planned_pairs']]
    parts.kpis=clean([kpi('固定组合',s['pair_count'],'本批固定成分×受体，含NA'),
        kpi('固定成分记录',s.get('compound_count'),'本批固定候选条目数，不等同原始来源关系数或独立结构数'),
        kpi('有效评分' if scoring else '准备可用',s['scored_pairs' if scoring else 'ready_pairs']),
        kpi('准备NA',s['na_pairs']),kpi('评分失败',s.get('failed_pairs')),
        kpi('严格组合' if scoring else '严格受体',s.get('strict_scored_pairs' if scoring else 'strict_receptors')),
        kpi('探索组合' if scoring else '探索受体',s.get('exploratory_scored_pairs' if scoring else 'exploratory_receptors')),
        kpi('来源记录',s.get('source_record_count'),'本批原始来源关系记录'),
        kpi('已核实独立结构',s.get('verified_structure_count'),'同一结构可对应多条来源记录；不改变固定候选顺序'),
        kpi('已核实来源记录',s.get('verified_record_count'),'保留全部已核实来源关系'),
        kpi('待核结构记录',s.get('pending_structure_records'),'保留原对象与未决原因，不按独立结构数代替')])
    # 来源阶段与原因只采用归档原字段，旧批未登记的分类不猜补。
    if t.get('source_diagnostics'):
        parts.special['source_diagnostics']=[dict(row) for row in t['source_diagnostics']]
    parts.flow_note_zh=s['message_zh']+('；本批修订的继续操作由独立后台任务处理。' if s['science_version'] in PATH_REPAIR else
        '；如需续做，从研究登记页打开“统一执行与续做”，不会重复已完成对象。')
    parts.params=clean([param('固定范围指纹',s['input_key']),param('原方案参数指纹',s['analysis_parameter_hash'])])
    parts.table=table([('compound_name','成分'),('target_name','受体'),('state_zh' if scoring else 'state','实际状态'),
        ('score','Vina评分（kcal/mol）'),('quality','准备类别'),('reason_zh','NA或失败原因')],rows,
        'plan_scoring_pairs' if scoring else 'planned_pairs')
    if scoring:
        values=[r['score'] for r in rows if r['state']=='completed' and r['score'] is not None]
        if values:
            lookup={(r['compound_id'],r['target_id']):r for r in rows}
            parts.special['heatmap']={'unit':'kcal/mol','orientation':'rows=compounds, columns=receptors',
                'color_rule_zh':'数值越负红色越深，越不负蓝色越深；NA保留，不设通用结合能阈值',
                'min':min(values),'max':max(values),'omitted':[],
                'receptors':[{'name':r['target_id'],'display_name':r.get('symbol') or r['target_id'],'order':i,'role_zh':r.get('candidate_grade',''),
                    'status_zh':r.get('symbol') or r['target_id']} for i,r in enumerate(packet['receptors'])],
                'rows':[{'compound_id':c['compound_id'],'compound_name':c.get('name') or c['compound_id'],
                    'cells':[{'receptor':r['target_id'],'value':lookup[(c['compound_id'],r['target_id'])]['score']}
                        for r in packet['receptors']]} for c in packet['compounds']]}
    else:
        receptor_rows=[dict(r,state_zh={'ready':'准备可用','NA':'准备NA','failed':'准备失败',
            'pending':'待核查'}.get(r['state'],r['state'])) for r in t['receptor_preparation']]
        parts.table=table([('target_id','受体'),('symbol','基因'),('state_zh','实际状态'),('quality','准备类别'),
            ('reason_zh','准备依据或NA原因')],receptor_rows,'receptor_preparation')
    return parts.as_dict()
