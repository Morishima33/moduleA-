"""只读投影系统批次最终受体名单，保留原顺序、并列及固定输入范围。"""
from copy import deepcopy


def present(selection=None, fixed_input=None, *, source_changed=False):
    """显示已归档事实；不选择受体、不推算交接资格、不生成人工决定。"""
    value = {'schema_version': 'ModuleA.system_selection_view.1', 'read_only': True,
        'archive_state': 'source_changed' if source_changed else 'pending',
        'selection_id': None, 'input_id': None, 'mode': None,
        'requested_count': None, 'actual_count': None, 'boundary_ties_retained': None,
        'compound_count': None, 'pair_count': None, 'selected': [],
        'message_zh': '本批最终受体名单尚未归档，请在统一执行与续做中查看实际进度。',
        'scope_note_zh': '本表展示对接固定名单；全网候选统计见下方。名单固定后，结构或质控失败保留原位置及NA原因。'}
    if source_changed:
        value['message_zh'] = '已有名单的网络来源已变化，请在统一执行与续做中核对当前批次。'
        return value
    if selection is None:
        return value
    payload = selection['payload']
    value.update(archive_state='archived', selection_id=selection['decision_id'],
        mode=payload['mode'], requested_count=payload['requested_count'], actual_count=payload['actual_count'],
        boundary_ties_retained=payload['boundary_ties_retained'], selected=deepcopy(payload['selected']),
        message_zh='本批最终名单已归档。结构质控、实际评分与独立复核分别保留结果。')
    if fixed_input is not None:
        value.update(input_id=fixed_input['decision_id'], compound_count=len(fixed_input['payload']['compounds']),
                     pair_count=fixed_input['payload']['pair_count'])
    return value
