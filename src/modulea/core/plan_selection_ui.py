"""受体选择、独立复核和A06固定输入的只读资格汇总，不执行科学选择。"""
from contracts import fingerprint
from science_modules.plan_stages_contract import binding, context


def info(workflow,sid):
    """显示实际A04绑定方案，另存草稿不改变本批对象或参数。"""
    m,intake,draft=context(workflow,sid)
    supported=intake.get('analysis_plan_profile')=='ModuleA.analysis_plan.1'
    if not supported:return {'supported':False}
    current=m['current'];a04=current.get('A04','')
    run=workflow.run(m,a04) if a04 else None
    plans=workflow._analysis_plan_records(m)
    plan=next((p for p in plans if run and p['plan_id']==run['config'].get('analysis_plan_id')
               and p['expected_a00']==current.get('A00')),None)
    value=workflow.analysis_plan_info(sid)
    selection=value['a04_selection'];review=value['a04_selection_review'];packet=value['a06_preparation_input']
    base=[]
    if m.get('trashed'):base.append('回收站研究只读')
    if not run or run['config'].get('version')!='A04.plan_network.1':base.append('请先生成新方案A04网络')
    if not a04 or not workflow.approved(m,a04):base.append('请先通过当前A04网络')
    if not plan:base.append('当前网络没有同研究、同登记的方案')
    elif run['config'].get('analysis_parameter_hash')!=plan['plan']['parameter_hash']:base.append('A04网络和方案参数指纹不一致')
    if selection and (not plan or selection['plan_id']!=plan['plan_id']):
        selection=None;review=None;packet=None
    generate=list(base)
    if selection:generate.append('本批已有受体名单，请核对并独立复核，不重复生成')
    reviewing=list(base)
    if not selection:reviewing.append('请先生成本批受体名单')
    preparing=list(base)
    for module in ('A00','A03','A03_SELECT'):
        rid=current.get(module)
        if not rid or not workflow.approved(m,rid):preparing.append('请先通过当前'+module)
    if not selection or not review or review['decision']!='approved':preparing.append('受体名单尚未独立复核通过')
    if selection and not selection['selection']['selected']:preparing.append('本批受体名单为空，不能编制对接输入')
    compound=current.get('A03_SELECT')
    if compound:
        c_run=workflow.run(m,compound)
        if c_run['parent_runs'].get('A03')!=current.get('A03'):preparing.append('成分名单不属于当前A03')
        if not workflow.result(m,compound)['tables'].get('selected'):preparing.append('本批成分名单为空，不能编制对接输入')
        if plan and c_run['config'].get('version')=='A03.plan_selection.1':
            params=plan['plan']['parameters']
            if c_run['config'].get('target_count')!=params['a06.component_count'] or c_run['config'].get('metric')!=params['a06.component_sort']:
                preparing.append('成分目标或排序与本批受体方案不一致，请先按同一方案重新生成并复核')
    if run and run['parent_runs'].get('A03')!=current.get('A03'):preparing.append('A04网络不属于当前A03')
    if packet:preparing.append('本批固定输入已保存，请到新版准备环节核对；无需重复保存')
    snapshot=binding(workflow,m,draft)
    snapshot.update(selection_id=selection['selection_id'] if selection else None,
        selection_review_id=review['review_id'] if review else None,input_id=packet['input_id'] if packet else None)
    return {'supported':True,'input_hash':fingerprint(snapshot),'expected_a00':current.get('A00',''),
        'expected_a03':current.get('A03',''),'expected_a03_select':compound or '', 'expected_a04':a04,
        'expected_plan_id':plan['plan_id'] if plan else '', 'parameter_hash':plan['plan']['parameter_hash'] if plan else '',
        'parameters':plan['plan']['parameters'] if plan else {},
        'newer_draft':bool(plan and draft and plan['plan_id']!=draft['plan_id']),
        'selection':selection,'selection_review':review,'current_input':packet,
        'operations':{'selection':{'enabled':not generate,'blockers':generate},
                      'review':{'enabled':not reviewing,'blockers':reviewing},
                      'input':{'enabled':not preparing,'blockers':preparing}},
        'message_zh':'受体名单按本批A04绑定方案生成，名单复核和固定输入保存分别明确操作；不会自动准备结构或执行评分。'}
