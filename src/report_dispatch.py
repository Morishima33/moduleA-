from pathway_review import load_selection, is_current # 原报告入口按本研究批准状态分派。
from report_pathway import report_pathway_record # 同源批准必须验证全部证据。
from pathway_review import selection_token # 审核页提交必须匹配明确的选择版本。
from contracts import require # 不允许跳过人工批准或用旧页面发布。

def selected_record(workflow, manifest): # 未准备或未批准时不纳入可选通路。
    index, data = load_selection(workflow,manifest) # 旧研究没有索引仍可复算。
    if not index or not is_current(workflow,manifest,data) or index['review_status'] != 'approved': return None # 不自动沿用旧选择。
    return report_pathway_record(workflow,manifest) # 有批准才使用严谨报告契约。

def run_reports(workflow, study_id, expected_a07, reason, **kwargs): # 网页和自动衔接共用可选通路分派。
    manifest = workflow.load(study_id) # 读取本次科学与审批版本。
    a06 = manifest.get('current', {}).get('A06')
    if a06 and workflow.run(manifest, a06).get('config', {}).get('schema_version') == 'A06.trial.handoff.1':
        from science_modules.a07.commented_reports import run_reports as generate
        return generate(workflow, study_id, expected_a07, reason, **kwargs)
    record = selected_record(workflow,manifest) # 同时核验批准图件指纹。
    a04 = manifest.get('current', {}).get('A04')
    a05 = manifest.get('current', {}).get('A05')
    from modulea.core.docking_review import review_context
    matrix_info=review_context(workflow,manifest) if manifest.get('matrix_display_records') else None
    if matrix_info and matrix_info['enabled'] and matrix_info['matrix']['ready'] and matrix_info['matrix']['display_version']=='A06.matrix.display.2':
        from science_modules.a07.matrix_reports import run_reports as generate
    elif a04 and a05 and workflow.result(manifest,a04).get('summary',{}).get('selection_version') == 'A04.dual.3' and workflow.result(manifest,a05).get('summary',{}).get('display_version') == 'A05.display.3':
        from science_modules.a07.compact_enrichment_reports import run_reports as generate
    elif a04 and a05 and workflow.result(manifest,a04).get('summary',{}).get('selection_version') == 'A04.dual.3' and workflow.result(manifest,a05).get('summary',{}).get('display_version') == 'A05.display.2':
        from science_modules.a07.enrichment_reports import run_reports as generate
    elif a04 and workflow.result(manifest, a04).get('summary', {}).get('selection_version') == 'A04.dual.3':
        from science_modules.a07.circular_reports import run_reports as generate
    elif a04 and workflow.result(manifest, a04).get('summary', {}).get('selection_version') == 'A04.dual.2':
        from science_modules.a07.first_round_reports import run_reports as generate
    elif a04 and workflow.result(manifest, a04).get('summary', {}).get('selection_version') == 'A04.dual.1':
        from science_modules.a07.dual_reports import run_reports as generate
    else:
        from science_modules.a07.reports import run_reports as generate
    return generate(workflow,study_id,expected_a07,reason,**kwargs) # 完整A07仍待人工复核。

def validator(root): # 新旧报告均按自身保存契约校验。
    from science_modules.a07.matrix_reports import validator as validate # 新校验器兼容已归档旧报告。
    from science_modules.a07.trial_reports import validator as trial_validator
    from science_modules.a07.commented_reports import validator as commented_validator
    return commented_validator(root, trial_validator(root, validate(root))) # 新批注报告保留各版历史校验。

def require_alignment(workflow, manifest, run): # 完整报告批准前核对可选通路最新决定。
    if run.get('config',{}).get('schema_version')=='A07.report.config.22':
        from science_modules.a07.trial_reports import current_export
        require(run['inputs']['a06_trial_export']==current_export(workflow,manifest,'export_validation.json'), '本批原评分图表已更新，请重新生成报告后复核')
        maps = workflow.ranked_maps_for(manifest,run['parent_runs']['A05'])
        require(run['inputs']['a05_ranked_maps']==(maps['record'] if maps else None), '排名通路图已改变，请重新生成报告后复核')
        for record in run['inputs']['compound_name_sources']:
            from storage import verified_file
            verified_file(workflow.location(manifest['study_id']),record)
    if run.get('config',{}).get('schema_version')=='A07.report.config.21':
        from science_modules.a07.trial_reports import current_export
        require(run['inputs']['a06_trial_export']==current_export(workflow,manifest,'export_validation.json'), '本批图表已更新，请重新生成报告后复核')
    if run.get('config',{}).get('schema_version')=='A07.report.config.20':
        require(bool(manifest.get('matrix_display_records')) and run['inputs'].get('a06_matrix_display_source')==manifest['matrix_display_records'][-1], '热图配色版本已改变，请重新生成报告后复核')
    bound = run['inputs'].get('selected_pathway_metadata') # 当前报告实际绑定的通路版本。
    selected = selected_record(workflow,manifest) # 当前仍获批准的通路版本。
    require(bound == selected, '通路选择或批准已改变，当前报告需重新生成后再复核') # 历史报告仍保留但不能代替新修订。

def publish_approved(workflow, data): # 网页明确加入通路时只修订专业报告。
    sid = data.get('study','') # 研究ID继续由内核校验。
    manifest = workflow.load(sid) # 获取当前科学版本。
    index, choice = load_selection(workflow,manifest) # 验证候选及批准索引。
    require(not manifest.get('trashed') and index and selection_token(index) == data.get('expected_selection') and manifest['current'].get('A05') == data.get('expected_a05') and selected_record(workflow,manifest), '通路未认可、已失效或页面版本已改变，请刷新') # 禁止伪造表单强行纳入。
    previous = manifest['current'].get('A07','') # 当前报告只能建立新修订。
    require(previous == data.get('expected_a07',''), '报告版本已改变，请刷新') # 拒绝重复发布。
    kwargs = {'reuse_current_concise':bool(previous and workflow.active(manifest,previous))} # 同源报告保持简略版字节不变。
    if previous and workflow.active(manifest,previous): # 保留当前同源任务包下载。
        inputs = workflow.run(manifest,previous)['inputs'] # 不按目录猜任务包。
        if inputs.get('task_package_index') and inputs.get('task_package_archive'): kwargs['task_package'] = {'index':inputs['task_package_index'],'archive':inputs['task_package_archive']} # 新修订继续绑定原任务包。
    return run_reports(workflow,sid,previous,'用户在网页认可通路后纳入专业详细报告',**kwargs) # 不自动通过完整A07。
