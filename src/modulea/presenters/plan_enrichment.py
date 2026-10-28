"""新协议A05展示只读归档统计、参数和实际纳入状态，不调用科学环境。"""
from .base import Parts, focus, kpi, param, table


def present(result, ctx):
    """给出实际分类状态与完整统计入口，避免旧前十/前十五文字覆盖新方案。"""
    summary, tables = result['summary'], result['tables']
    parts = Parts()
    for row in tables.get('group_summary', []):
        parts.kpis.append(kpi(row['group'], row.get('significant_count') if row['included'] else '未纳入',
                              '显著条目' if row['included'] else '本方案不执行此类别'))
    parts.params = [param('显著性', summary['主显著性']), param('参数指纹', summary['analysis_parameter_hash'])]
    parts.flow_note_zh = '输入为本研究已批准A03交集；GO三类及KEGG分别BH校正，分母按各类实际注释背景。'
    parts.table = table([('group','类别'),('state_zh','本方案状态'),('background_count','背景基因'),
                         ('effective_count','有效输入'),('tested_count','实际检验'),('significant_count','显著条目')],
                        tables['group_summary'], 'group_summary')
    if summary.get('身份待核验数'):
        parts.focus.append(focus('身份待核验',f"{summary['身份待核验数']}项HGNC缺少唯一一致Entrez，不能批准。",blocks=['A07']))
    parts.special['plan_enrichment'] = {'groups': tables['group_summary'],
        'tables': {key: tables.get(key, []) for key in ('bp_plan_top','cc_plan_top','mf_plan_top','kegg_plan_top','kegg_plan_count_top')},
        'threshold_zh': summary['主显著性'], 'note_zh': '图表按本方案数量截取，完整原统计和未检验原因保留；不使用旧研究图或排名。'}
    return parts
