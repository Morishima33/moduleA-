"""接续已确认的扩展筛查操作；只生成同研究草稿，不保存名单或批准。"""
from contracts import require

VERSION = 'A06.extended_scope.1'
EXPANDED_COUNT = 15


def context(workflow, manifest):
    """前五主候选规则保持；前十五仅是供核对的扩展建议，并列完整列出。"""
    a03 = manifest['current'].get('A03')
    require(a03, '请先生成本研究A03结果')
    tables = workflow.result(manifest, a03)['tables']
    rows = [r for r in tables.get('ranking', []) if r.get('in_network') and r.get('intersection_count', 0) > 0]
    require(len({r['compound_id'] for r in rows}) == len(rows), '本研究成分排名编号重复')
    rows = sorted(rows, key=lambda r: (-r['intersection_count'], r['compound_id']))
    blocked = set()
    draft = workflow.current_docking_review(manifest)
    if draft:
        blocked = {r['compound_id'] for r in draft['compounds'] if not r['identity_prechecked']}
        blocked.update(r['compound_id'] for r in draft['excluded'])
    eligible = [r for r in rows if r['compound_id'] not in blocked]
    required = min(EXPANDED_COUNT, len(rows))
    proposal = eligible[:required]
    boundary = []
    if proposal:
        cutoff = proposal[-1]['intersection_count']
        boundary = [r for r in eligible if r['intersection_count'] == cutoff]
        proposal = [r for r in eligible if r['intersection_count'] >= cutoff]
    default = {r['compound_id'] for r in tables.get('suggestions', [])}
    proposed_ids = [r['compound_id'] for r in proposal]
    reasons = {r['compound_id']: f"按本研究交集覆盖原名次{r.get('main_rank', '未编号')}，拟纳入扩展结构筛查；不改变主候选排序和PPI结论。"
               for r in proposal if r['compound_id'] not in default}
    selection = manifest['current'].get('A03_SELECT')
    selected = []
    current = False
    approved = False
    if selection:
        run = workflow.run(manifest, selection)
        current = run['parent_runs'].get('A03') == a03 and workflow.active(manifest, selection)
        if current:
            selected = workflow.result(manifest, selection)['tables']['selected']
            approved = workflow.approved(manifest, selection)
    ids = [r.get('compound_id') for r in selected]
    complete_ids = all(isinstance(cid, str) and bool(cid) for cid in ids)
    ready = bool(approved and required and complete_ids and len(ids) >= required and len(ids) == len(set(ids))
                 and set(ids) <= {r['compound_id'] for r in eligible})
    reason = '' if ready else f"扩展筛查尚未接齐：本研究需核查至少{required}个可用成分，当前已保存{len(ids)}个；请在成分核查页载入扩展草稿、核对后保存并独立复核。"
    if not required:
        reason = '本研究暂无可用于扩展筛查的成分，请先核对A03输入。'
    if required and len(ids) >= required and not approved:
        reason = '扩展名单已保存，尚未独立复核通过；请先完成A03_SELECT复核。'
    if not complete_ids:
        reason = '历史选择缺少成分稳定编号，仅供只读追溯；不能按名称猜测并进入新计算。'
    return {'schema_version': VERSION, 'study_id': manifest['study_id'], 'a03_run': a03,
            'selection_run': selection, 'primary_limit': 5, 'expanded_target': EXPANDED_COUNT,
            'required_count': required, 'available_count': len(eligible), 'selected_count': len(ids),
            'approved': approved, 'ready': ready, 'reason_zh': reason,
            'proposed_ids': proposed_ids, 'manual_reasons': reasons,
            'boundary_count': len(boundary), 'proposed_count': len(proposal),
            'note_zh': '前五主候选与完整扩展筛查分开。草稿只用本研究A03排名，保留截断并列；可逐项调整。载入不保存、不批准、不计算。'}


def require_ready(workflow, manifest):
    scope = context(workflow, manifest)
    require(scope['ready'], scope['reason_zh'])
    return scope
