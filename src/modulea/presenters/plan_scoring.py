"""新方案评分只读展示：同批完整组合、NA/失败与严格/探索来源。"""
from .base import Parts, clean, kpi, param, table


def present(result, ctx):
    """所有数字直接读取已校验摘要，不在展示层重新计算分值或资格。"""
    summary = result['summary']
    parts = Parts()
    parts.kpis = clean([kpi('固定组合', summary['pair_count'], '已批准成分×受体，含NA'),
                       kpi('有效评分', summary['scored_pairs'], '同批原始Top-1'),
                       kpi('评分失败', summary['failed_pairs']), kpi('准备NA', summary['na_pairs']),
                       kpi('严格组合', summary['strict_scored_pairs']),
                       kpi('探索组合', summary['exploratory_scored_pairs'])])
    parts.flow_note_zh = summary['message_zh']
    parts.params = clean([param('评分单位', summary['score_unit']),
                          param('来源准备', summary['source_preparation_run_id']),
                          param('方案参数指纹', summary['analysis_parameter_hash'])])
    parts.table = table([('compound_id', '成分'), ('target_id', '受体'), ('state_zh', '计算状态'),
                         ('score', 'Vina评分（kcal/mol）'), ('quality', '准备类别'), ('reason_zh', 'NA或失败原因')],
                        result['tables']['plan_scoring_pairs'], 'plan_scoring_pairs')
    return parts
