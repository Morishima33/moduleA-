"""本平台新评分的只读摘要；独立字段分派，完整NA与原始分值保留。"""
from .base import Parts,clean,kpi,param,table


def present(result,ctx):
    """只展示本批归档数量和明细，不沿旧协议猜测缺失字段。"""
    summary=result['summary'];parts=Parts()
    parts.kpis=clean([kpi(label,summary[key]) for key,label in (
        ('pair_count','固定组合'),('scored_pairs','有效评分'),('failed_pairs','评分失败'),
        ('na_pairs','准备NA'),('compound_count','固定成分记录'),('receptor_count','固定受体'))])
    parts.flow_note_zh=summary['message_zh']
    parts.params=clean([param('科学协议',summary['science_version']),param('固定范围指纹',summary['input_key'])])
    states={'completed':'评分完成','failed':'评分失败','NA':'准备NA'}
    rows=[dict(row,state_zh=states[row['state']]) for row in result['tables']['native_scores']]
    parts.table=table([('compound_id','成分'),('target_id','受体'),('state_zh','实际状态'),
        ('score','Vina评分（kcal/mol）'),('quality','准备类别'),('reason_zh','NA或失败原因')],rows,'native_scores')
    return parts
