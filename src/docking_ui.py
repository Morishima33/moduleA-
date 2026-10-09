# A06准备资料的只读预览；不另建运行或审核状态。
from contracts import require  # 复用统一错误信息。
from storage import file_record, read_json, verified_file  # 读取前检查资料完整性并转换下载索引。


def load_preview(workflow, study_id):  # 只允许读取本研究当前上游对应的准备资料。
    manifest = workflow.load(study_id)  # 研究编号由统一内核验证。
    index_path = workflow.root / 'environments' / 'A06_previews.json'  # 唯一明确的准备预览索引。
    require(index_path.is_file(), '尚未整理对接准备预览')  # 没有资料不假装已准备。
    index = read_json(index_path)  # 不扫描文件猜最新版。
    require(index.get('schema_version') == 'A06.preview.index.1', '准备预览索引版本不支持')  # 不混用结构。
    reference = index.get('studies', {}).get(study_id)  # 每项研究单独绑定。
    require(reference is not None, '本研究尚无对接准备预览')  # 不借用其他病例。
    plan = read_json(verified_file(workflow.root, reference))  # 指纹改变立即停止。
    version = plan.get('schema_version')  # 读取预览版本以保持历史兼容。
    require(version in ('A06.preview.1', 'A06.receptor.screen.1', 'A06.receptor.audit.1', 'A06.receptor.screen.2', 'A06.receptor.audit.2') and plan.get('study_id') == study_id, '准备资料不属于本研究或版本不支持')  # 同时支持历史与动态筛查。
    if version in ('A06.receptor.screen.1', 'A06.receptor.audit.1', 'A06.receptor.screen.2', 'A06.receptor.audit.2'):  # 新研究先经过通用受体核查关口。
        expected_status = 'pending_receptor_screen_review' if version in ('A06.receptor.screen.1', 'A06.receptor.screen.2') else 'receptor_audit_completed_pending_preparation'  # 两阶段各有明确状态。
        require(plan.get('status') == expected_status and plan.get('handoff_blocked') is True, '受体筛查预览状态不正确')  # 不能把筛查或审计冒充正式A06_PREP。
        parents = plan.get('parent_runs', {})  # 使用显式上游运行号检查版本。
        require(set(parents) == {'A03', 'A03_SELECT', 'A04'}, '受体筛查缺少上游绑定')  # 不依赖A05或旧病例固定对象。
        require(all(manifest['current'].get(key) == value and workflow.active(manifest, value) for key, value in parents.items()), '上游已改变，这份受体筛查已失效，需重新生成')  # 旧筛查不进入新版本。
        for record in plan.get('evidence', []):  # 每项依据都必须保持原指纹。
            verified_file(workflow.root, record)  # 文件缺失或变化立即停止。
        require(bool(plan.get('evidence')) and plan.get('ligand_count') == len(plan.get('ligands', [])), '受体筛查的成分或证据不完整')  # 摘要不能掩盖缺项。
        require(plan.get('final_receptors') == [], '受体核查阶段不得提前生成正式受体')  # 保持结构准备和正式对接边界。
        if version in ('A06.receptor.screen.1', 'A06.receptor.audit.1'):  # 历史版本的计划组合必须保持零。
            require(plan.get('planned_pair_count') == 0, '历史受体核查阶段不得提前生成组合')  # 保持旧契约。
        else:  # 第二版保存动态计划规模但仍不代表已经运行。
            expected_candidates = len(plan.get('candidate_receptors', plan.get('screening_window', [])))  # 审计后排除不可计算对象。
            require(plan.get('planned_pair_count') == plan.get('ligand_count') * expected_candidates, '动态计划组合数与成分和受体数量不一致')  # 只保存计划数量。
        if version in ('A06.receptor.audit.1', 'A06.receptor.audit.2'):  # 核查完成版验证全部窗口都有结论。
            require(len(plan.get('recommended_receptors', [])) >= 5 and len(plan.get('assessments', [])) == len(plan.get('screening_window', [])), '受体核查结论数量不完整')  # 新版允许多于五项严格候选。
        return plan  # 通用筛查页无需套用历史三受体字段。
    require(plan.get('status') == 'draft_not_reviewable', '该入口仅展示待完善准备资料')  # 不冒充已批准运行。
    parents = plan.get('parent_runs', {})  # 使用显式的上游运行号。
    require(set(parents) == {'A03', 'A03_SELECT', 'A04'}, '准备资料缺少上游绑定')  # 不凭文件名推断来源。
    require(all(manifest['current'].get(k) == v and workflow.active(manifest, v) for k, v in parents.items()), '上游已改变，这份准备资料已失效，需重新整理')  # 旧资料不能供新研究使用。
    for record in plan.get('evidence', []):  # 所有展示依据均需存在且完整。
        verified_file(workflow.root, record)  # 不接受被改写或缺失的源文件。
    require(bool(plan.get('evidence')), '准备资料缺少证据索引')  # 不发布无来源清单。
    prepared = plan.get('prepared_receptor_report')  # 新候选包作为可选扩展，兼容旧预览。
    if prepared is not None:  # 有实际产物才验证对应研究与来源。
        report = read_json(verified_file(workflow.root, prepared))  # 校验候选包内容。
        require(report.get('study_id') == study_id and report.get('parent_runs') == parents and report.get('status') == 'draft_not_reviewable', '受体准备包与本研究或上游不符')  # 不能跨研究引用。
        for record in report.get('evidence', []) + report.get('code', []):  # 原始、处理、环境与代码引用都校验。
            verified_file(workflow.root, record)  # 修改或缺失时停止。
        plan['prepared_receptor_results'] = report['results']  # 摘要从同一产物包读取，不维护重复数字。
    prepared_ligands = plan.get('prepared_ligand_report')  # 五配体候选包同样采用可选扩展。
    if prepared_ligands is not None:  # 只有实际生成的候选包才展示。
        ligand_report = read_json(verified_file(workflow.root, prepared_ligands))  # 先校验顶层候选包。
        require(ligand_report.get('schema_version') == 'A06.ligand.preparation.1' and ligand_report.get('study_id') == study_id, '配体准备包不属于本研究或版本不支持')  # 不跨病例复用。
        require(ligand_report.get('parent_runs') == parents and ligand_report.get('status') == 'draft_not_reviewable', '配体准备包与当前上游或状态不符')  # 上游改变立即停止。
        require(ligand_report.get('search_box') is None and ligand_report.get('docking_executed') is False and ligand_report.get('completed_count') == 0, '配体准备包混入未获批准的对接结果')  # 此入口只允许准备资料。
        require(ligand_report.get('planned_count') == len(ligand_report.get('combinations', [])), '组合计划数量不一致')  # 防止摘要与明细脱节。
        for record in ligand_report.get('evidence', []):  # 包内所有来源、结构、日志和代码均须完整。
            verified_file(workflow.root, record)  # 不能只校验顶层JSON。
        plan['prepared_ligand_results'] = ligand_report['results']  # 页面使用单一事实来源。
        plan['docking_combinations'] = ligand_report['combinations']  # 计划清单不含评分。
    box_reference = plan.get('box_proposal')  # 搜索盒方案是独立待确认资料，不属于已批准配置。
    if box_reference is not None:  # 有具体数值方案才展示。
        box_proposal = read_json(verified_file(workflow.root, box_reference))  # 校验顶层方案文件。
        require(box_proposal.get('schema_version') == 'A06.box.proposal.1' and box_proposal.get('study_id') == study_id, '搜索盒方案不属于本研究或版本不支持')  # 不跨病例复用坐标。
        require(box_proposal.get('parent_runs') == parents and box_proposal.get('status') == 'pending_user_confirmation', '搜索盒方案上游或状态不符')  # 已失效或未知状态不能展示为当前。
        require(box_proposal.get('executable') is False and box_proposal.get('config_generated') is False and box_proposal.get('docking_executed') is False, '待确认方案混入可执行配置或对接结果')  # 保持用户决定边界。
        require(box_proposal.get('receptor_report') == plan.get('prepared_receptor_report') and box_proposal.get('ligand_report') == plan.get('prepared_ligand_report'), '搜索盒方案未绑定当前准备包')  # 结构换版后数值必须重算。
        require(len(box_proposal.get('boxes', [])) == 3 and all(box.get('executable') is False for box in box_proposal['boxes']), '搜索盒候选数量或状态不完整')  # 当前三受体均须有单独候选。
        for record in box_proposal.get('evidence', []):  # 参考配体及计算代码均需保持完整。
            verified_file(workflow.root, record)  # 指纹变化立即停止。
        plan['box_proposal_data'] = box_proposal  # 页面从单一机器记录生成摘要。
    authorization_reference = plan.get('box_authorization')  # 用户批准记录与历史候选方案分开保存。
    if authorization_reference is not None:  # 已批准时必须核对其绑定的研究、上游和方案指纹。
        authorization = read_json(verified_file(workflow.root, authorization_reference))  # 授权记录本身不可被改写。
        require(authorization.get('schema_version') == 'A06.box.authorization.1' and authorization.get('status') == 'user_approved', '搜索盒与重对接授权版本或状态不符')  # 不把待确认方案当授权。
        require(authorization.get('study_id') == study_id and authorization.get('parent_runs') == parents, '搜索盒与重对接授权不属于当前研究或上游')  # 上游改变后必须重审。
        require(authorization.get('proposal') == box_reference and authorization.get('approved_items') == ['reference_ligand_envelope_padding_5A', 'seven_pose_integrity_rules', 'three_reference_redocking_top1_rmsd_2A'], '搜索盒与重对接授权未完整绑定当前方案')  # 三项批准不可拆换。
        require(authorization.get('formal_docking_authorized') is False and authorization.get('redocking_execution_authorized') is False, '规则授权不得夹带Vina执行许可')  # 仍需A06_PREP总体复核。
        plan['box_authorization_data'] = authorization  # 页面明确显示已批准，不再次要求用户决定。
    package_reference = plan.get('preparation_package')  # 配置和参考配体形成后作为独立候选包接入。
    if package_reference is not None:  # 只有实际生成的包才显示集中复核摘要。
        package = read_json(verified_file(workflow.root, package_reference))  # 顶层包先通过指纹校验。
        require(package.get('schema_version') == 'A06.preparation.package.1' and package.get('study_id') == study_id and package.get('parent_runs') == parents, 'A06_PREP候选包不属于当前研究、上游或版本')  # 不跨版本复用。
        require(package.get('status') == 'draft_not_reviewable' and package.get('published') is False and package.get('execution_authorized') is False and package.get('vina_invoked') is False, 'A06_PREP候选包混入发布或执行状态')  # 当前只允许准备成果。
        require(package.get('authorization') == authorization_reference and package.get('counts') == {'approved_boxes': 3, 'pose_integrity_rules': 7, 'reference_ligands_prepared': 3, 'redocking_planned': 3, 'redocking_completed': 0, 'formal_planned': 15, 'formal_completed': 0}, 'A06_PREP候选包授权或数量不符')  # 防止摘要掩盖缺项或提前运行。
        verified_file(workflow.root, package.get('config'))  # 主配置也必须保持原指纹。
        for record in package.get('evidence', []):  # 包内结构、配置、日志和代码快照均需完整。
            verified_file(workflow.root, record)  # 任一文件改变均暂停展示。
        plan['preparation_package_data'] = package  # 集中复核使用单一机器事实来源。
        plan['approved_box_configs'] = package['approved_boxes']  # 页面数值来自实际配置包。
        plan['reference_ligand_results'] = package['reference_ligands']  # 显示三份参考配体是否准备成功。
        plan['docking_combinations'] = package['formal_docking_plan']  # 15组计划仍全部未运行。
        known_paths = {record['path'] for record in plan['evidence']}  # 防止同一文件在下载区重复展示。
        for record in package['evidence'] + [package_reference]:  # 将包内文件加入受限下载清单。
            if record['path'] not in known_paths:  # 同一路径只展示一次。
                plan['evidence'].append(record)  # 下载仍须经过完整指纹校验。
                known_paths.add(record['path'])  # 后续重复记录不再加入。
    redocking_reference = plan.get('redocking_report')  # 重对接结果是A06_PREP总体复核后的可选扩展。
    if redocking_reference is not None:  # 只有实际运行完成后才显示诊断结果。
        redocking = read_json(verified_file(workflow.root, redocking_reference))  # 先验证结果包本身。
        execution_authorization = read_json(verified_file(workflow.root, plan.get('redocking_authorization')))  # 诊断必须有独立执行授权。
        require(execution_authorization.get('schema_version') == 'A06.prep.execution.authorization.1' and execution_authorization.get('status') == 'user_approved', '重对接执行授权格式或状态不符')  # 不把规则批准当执行批准。
        require(execution_authorization.get('study_id') == study_id and execution_authorization.get('preparation_package') == package_reference, '重对接执行授权未绑定当前研究和候选包')  # 防止跨包复用。
        require(execution_authorization.get('redocking_execution_authorized') is True and execution_authorization.get('formal_docking_authorized') is False, '重对接授权范围不正确')  # 15组正式对接仍不得夹带。
        require(redocking.get('schema_version') == 'A06.redocking.result.1' and redocking.get('study_id') == study_id and redocking.get('parent_runs') == parents, '重对接结果不属于当前研究、上游或版本')  # 上游变化后旧诊断失效。
        require(redocking.get('preparation_package') == package_reference and redocking.get('authorization') == plan.get('redocking_authorization'), '重对接结果未绑定当前候选包或执行授权')  # 结果输入必须准确。
        require(redocking.get('status') == 'completed_awaiting_review' and redocking.get('summary', {}).get('planned_count') == 3 and len(redocking.get('results', [])) == 3, '重对接结果数量或状态不完整')  # 不把部分运行写成全部完成。
        require(redocking.get('summary', {}).get('formal_docking_completed_count') == 0 and redocking.get('summary', {}).get('formal_docking_authorized') is False, '重对接结果混入正式对接')  # 两个阶段继续分开。
        for record in redocking.get('files', []):  # 命令、日志、姿势和运行快照均须完整。
            verified_file(workflow.root, record)  # 任一被改写即暂停使用。
        plan['redocking_result_data'] = redocking  # 页面摘要使用同一结果事实来源。
        known_paths = {record['path'] for record in plan['evidence']}  # 下载区继续避免重复。
        for record in redocking['files'] + [redocking_reference, plan['redocking_authorization']]:  # 结果与授权均加入追溯清单。
            if record['path'] not in known_paths:  # 同一路径只出现一次。
                plan['evidence'].append(record)  # 下载仍受指纹校验保护。
                known_paths.add(record['path'])  # 更新已登记路径。
    formal_reference = plan.get('formal_docking_report')  # 正式A06结果是诊断之后的可选扩展。
    if formal_reference is not None:  # 十组运行完成后才进入本分支。
        formal_run = manifest['current'].get('A06')  # 正式结果必须是研究当前A06版本。
        require(formal_run, '当前研究缺少A06结果')  # 没有当前版本时停止展示。
        formal = workflow.result(manifest, formal_run)  # 直接读取并核验当前十组或五乘五版本。
        require(formal and formal.get('module_id') == 'A06' and formal.get('study_id') == study_id, '正式对接结果不是当前研究A06版本')  # 拒绝历史或跨研究结果。
        planned = int(formal.get('summary', {}).get('计划组合数', 0))  # 读取当前版本的真实计划组合数。
        require(planned in (10, 25) and len(formal.get('tables', {}).get('combination_results', [])) == planned, '正式对接结果数量或文件不完整')  # 同时支持历史十组和当前二十五组。
        if planned == 10:  # 历史版本继续核对原暂停边界。
            require(formal.get('summary', {}).get('HSP90AA1未运行组合数') == 5, '正式结果未保留HSP90AA1暂停范围')  # 暂停组合不能消失。
        plan['formal_result_data'] = formal  # 页面摘要只使用经过框架核验的结果。
        known_paths = {record['path'] for record in plan['evidence']}  # 继续避免下载清单重复。
        for record in formal.get('files', []):  # 标准结果文件记录相对研究根目录。
            source = workflow.location(study_id) / record['path']  # 转换为项目根目录下的实际文件。
            project_record = file_record(workflow.root, source, record.get('role', 'formal_docking_evidence'))  # 建立受限下载所需项目级索引。
            if project_record['path'] not in known_paths:  # 同一文件只列一次。
                plan['evidence'].append(project_record)  # 下载时仍校验大小和指纹。
                known_paths.add(project_record['path'])  # 更新已登记路径集合。
        if formal_reference['path'] not in known_paths:  # 标准结果JSON本身也供追溯下载。
            plan['evidence'].append(formal_reference)  # 使用已经验证的项目级记录。
    return plan  # 不签署，不修改研究索引。


def dynamic_result_section(result, study_id, workflow=None):  # 展示当前同源动态结果，允许明确绑定的纯图件修订。
    from web import text, table  # 统一转义及表格样式。
    generic = result['tables']['generic_docking']  # 读取已验证契约。
    summary = result['summary']  # 使用真实计划与完成数量。
    source_label = generic.get('reuse_provenance', {}).get('display_label', '缺GeneCards的流程测试')  # 新版标签来自绑定复用事实，历史显示不变。
    body = '<h2>扩展对接结果</h2><p class="notice">' + text(source_label) + '；计划' + str(summary['计划组合数']) + '组，完成' + str(summary['成功组合数']) + '组，NA ' + str(summary['失败组合数']) + '组。主要受体：' + text('、'.join(generic['primary_targets'])) + '。</p>'  # 明确实际来源与解释边界。
    from docking_grouped_heatmap import current_display  # 独立展示版本不改原始A06。
    revised = current_display(workflow, result) if workflow else None  # 不凭修改时间猜新版。
    if revised:  # 使用当前科学结果的用户批准展示修订。
        body += '<img style="width:100%;height:auto" alt="有效对接组合热图" src="/docking-figure?study=' + text(study_id) + '">'  # 新图包含完整图下说明。
    if revised and revised[0].get('omission_explanation'):  # 图下列明没有展示的组合及原因。
        body += '<p class="muted">' + text(revised[0]['omission_explanation']) + '</p>'  # 不改原始科学结果。
    for index, record in enumerate([] if revised else result['files']):  # 有修订时不同时显示灰色旧图。
        if record.get('role') == 'heatmap_png':  # 展示当前运行绑定的热图。
            body += '<img style="width:100%;height:auto" alt="结合能热图" src="/file?study=' + text(study_id) + '&amp;run=' + text(result['run_id']) + '&amp;index=' + str(index) + '">'  # 不扫描目录猜测新图。
    body += '<h3>受体结构与结果解释说明</h3>' + table(result['tables']['receptor_limitations'])  # 热图后立即呈现限制。
    body += '<details><summary>结合能数值与搜索空间参数</summary>' + table(result['tables']['score_matrix']) + table(result['tables']['receptor_setup']) + '</details>'  # 详细数值折叠保留。
    return body  # 不生成复核记录。


def preview_link(workflow, study_id):  # 在原A06_PREP卡片增加一个简短入口。
    from web import text  # 统一HTML转义。
    path = workflow.root / 'environments' / 'A06_previews.json'  # 固定索引位置。
    if not path.is_file() or study_id not in read_json(path).get('studies', {}):  # 未建立资料时不显示虚构成果。
        return ''  # 保持原模块状态说明。
    plan = read_json(verified_file(workflow.root, read_json(path)['studies'][study_id]))  # 读取明确指向的当前预览状态。
    manifest = workflow.load(study_id)  # 读取当前版本以避免沿用历史十组提示。
    current_id = manifest['current'].get('A06')  # 当前指针可能保留失效历史运行。
    current_a06 = workflow.result(manifest, current_id) if current_id and workflow.active(manifest, current_id) else None  # 只有有效A06可以替代准备入口。
    if current_a06 and current_a06.get('tables', {}).get('generic_docking'):  # 当前已发布结果优先于旧筛查预览。
        return '<p><a href="/docking-preview?study=' + text(study_id) + '">查看当前扩展对接结果与结构说明</a></p>'  # 不提示重复复核准备。
    if plan.get('schema_version') in ('A06.receptor.screen.1', 'A06.receptor.audit.1', 'A06.receptor.screen.2', 'A06.receptor.audit.2'):  # 新研究展示当前通用准备阶段。
        audited = plan.get('schema_version') in ('A06.receptor.audit.1', 'A06.receptor.audit.2')  # 兼容历史和动态版本。
        label = '查看受体适用性核查结果' if audited else ('查看受体筛查与' + str(plan['ligand_count']) + '个已确认成分')  # 用户直接看到当前任务。
        note = ('已核查' + str(len(plan.get('candidate_receptors', []))) + '个可计算受体；严格质控组至少5个，其余保留扩展解释。') if audited else '按PPI前10位及第10位边界并列集中核查；完成后才准备结构和搜索盒。'  # 不再写死5个受体。
        return '<p><a href="/docking-preview?study=' + text(study_id) + '">' + label + '</a></p><p class="muted">' + note + '</p>'  # 不显示历史COPD固定数量。
    completed = int(current_a06.get('summary', {}).get('成功组合数', 0)) if current_a06 else 0  # 取得当前真实完成数量。
    label = ('查看' + str(completed) + '组正式对接结果') if completed else ('查看三次重对接诊断结果' if plan.get('redocking_report') else ('查看A06_PREP集中复核资料' if plan.get('preparation_package') else '查看对接准备进度与待定项'))  # 当前人工任务优先于历史准备任务。
    note = ('当前版本已完成' + str(completed) + '组，详细对象数和失败项见结果矩阵。') if completed else ('只读结果；正式对接尚未完成。' if plan.get('redocking_report') else '只读预览；尚未发布A06_PREP，也不会自动运行对接。')  # 新版不从数量反推固定病例。
    return '<p><a href="/docking-preview?study=' + text(study_id) + '">' + label + '</a></p><p class="muted">' + note + '</p>'  # 链接不充当通过按钮。


def _package_review_section(package, table, redocking=None):  # 将A06_PREP整体复核重点集中放在页面前部。
    box_state = '已复核；已用于本次重对接诊断' if redocking else '已批准数值；待A06_PREP总体复核'  # 页面随真实阶段更新。
    box_rows = [{'受体': row['symbol'] + ' / ' + row['pdb'] + ' ' + row['chains'], '参考配体': row['reference_ligand']['code'] + ' ' + row['reference_ligand']['auth_chain'] + ':' + row['reference_ligand']['auth_sequence'], '中心 X/Y/Z（Å）': ' / '.join(str(x) for x in row['center_angstrom']), '尺寸 X/Y/Z（Å）': ' / '.join(str(x) for x in row['size_angstrom']), '执行状态': box_state} for row in package['approved_boxes']]  # 数值批准与执行许可明确分开。
    heading = 'A06_PREP整体配置（已完成总体复核）' if redocking else '本轮必须核验：A06_PREP整体配置'  # 已完成任务不再提示重复审核。
    notice = '三个盒子、三份参考配体和固定参数已完成总体复核，并已按授权执行三次诊断。15组正式对接仍为0组。' if redocking else '请核对三个盒子、三份参考配体和固定参数是否属于本次研究。<br>七项基础检查和三次重对接诊断规则已经批准，无需再次逐条决定。当前Vina运行0次，15组正式对接完成0组。'  # 明确当前边界。
    section = '<h2>' + heading + '</h2><p class="notice"><strong>' + notice + '</strong></p>' + table(box_rows)  # 复核重点随阶段改变。
    reference_state = '已完成本次重对接诊断' if redocking else '已准备，尚未重对接'  # 配体准备状态不滞后。
    reference_rows = [{'受体': row['symbol'] + ' / ' + row['pdb'], '参考配体': row['reference_ligand']['code'], '化学式': row['identity']['formula'], '重原子': row['identity']['heavy_atom_count'], '手性核对': '一致（' + str(len(row['identity']['declared_stereo_centers'])) + '个明确中心）', '准备状态': reference_state} for row in package['reference_ligands']]  # 只展示影响下游的关键事实。
    section += '<h2>三份共晶参考配体</h2>' + table(reference_rows)  # 不要求用户逐原子审核。
    section += '<details><summary>查看已批准的七项基础姿势检查</summary>' + table([{'检查': row['rule'], '失败时处理': row['failure_action']} for row in package['pose_integrity_rules']]) + '</details>'  # 已批准规则保留可追溯展示。
    plan_status = {row['symbol']: ('通过' if row['passed'] else '未通过，受体已暂停') for row in redocking['results']} if redocking else {}  # 诊断完成后引用真实状态。
    section += '<details><summary>查看三次重对接诊断计划</summary>' + table([{'受体': row['symbol'] + ' / ' + row['pdb'], '参考配体': row['reference_ligand']['code'], '判定': 'top-1对称感知重原子RMSD≤2 Å', '失败处理': '暂停该受体，不自动调参', '状态': plan_status.get(row['symbol'], '未运行')} for row in package['redocking_plan']]) + '</details>'  # 计划与结果使用同一对象名称。
    return section  # 其他准备明细随后展示但不抢占重点。


def _redocking_result_section(redocking, table):  # 集中显示本轮唯一必须复核的三条诊断。
    rows = [{'受体': row['symbol'] + ' / ' + row['pdb'], '参考配体': row['reference_ligand']['code'], 'top-1评分（kcal/mol）': row.get('top_1_score_kcal_mol', '未生成'), '对称感知重原子RMSD（Å）': round(row['rmsd_angstrom'], 3) if row.get('rmsd_angstrom') is not None else '未生成', '≤2 Å判定': '通过' if row['passed'] else '未通过', '下一步': '可作为正式对接候选受体' if row['passed'] else '暂停该受体，不自动调参'} for row in redocking['results']]  # 只显示影响下一步的字段。
    summary = redocking['summary']  # 摘要来自不可变结果包。
    body = '<h2>本轮必须核验：三次参考配体重对接诊断</h2><p class="notice"><strong>请确认这三条诊断结果及暂停处理。</strong><br>通过' + str(summary['passed_count']) + '/3；暂停：' + ('、'.join(summary['paused_receptors']) if summary['paused_receptors'] else '无') + '。本轮没有自动调参，也没有运行15组正式对接。</p>' + table(rows, ['受体', '参考配体', 'top-1评分（kcal/mol）', '对称感知重原子RMSD（Å）', '≤2 Å判定', '下一步'])  # 一屏完成集中复核。
    body += '<details><summary>查看计算口径与完整性信息</summary><p>RMSD仅比较真实重原子，考虑分子对称等价原子，不进行刚体重新拟合；氢和G0伪原子不计入。最近受体重原子距离只报告，不设置首版自动阈值。</p>' + table([{'受体': row['symbol'], '输出姿势数': row.get('pose_count', 0), '对称映射数': row.get('rmsd', {}).get('symmetry_mapping_count', '未生成'), '全部原子在盒内': row.get('inside_box', {}).get('passed', False), '最近受体重原子距离（Å）': round(row['minimum_receptor_heavy_atom_distance_angstrom'], 3) if row.get('minimum_receptor_heavy_atom_distance_angstrom') is not None else '未生成'} for row in redocking['results']]) + '</details>'  # 技术细节默认折叠。
    return body  # 其余历史准备资料随后展示。


def _formal_result_section(formal, table):  # 集中显示当前正式结果和本轮唯一复核重点。
    summary = formal['summary']  # 摘要来自统一框架标准结果。
    targets = [key for key in formal['tables']['score_matrix'][0] if key not in ('compound_id', 'compound_name')]  # 从当前矩阵读取真实受体列。
    matrix = [{'成分': row['compound_name'], '成分编号': row['compound_id'], **{target + '（kcal/mol）': row.get(target) if row.get(target) is not None else '未运行' for target in targets}} for row in formal['tables']['score_matrix']]  # 不用零代替缺失组合。
    columns = ['成分', '成分编号'] + [target + '（kcal/mol）' for target in targets]  # 生成与当前矩阵一致的表头。
    planned = int(summary['计划组合数'])  # 读取当前版本计划数量。
    generic = formal.get('tables', {}).get('generic_docking', {})  # 新版从受体明细读取主要与探索范围。
    primary_count = sum(bool(row.get('primary_result')) for row in generic.get('receptors', []))  # 主要受体数量不能从组合数猜测。
    extra = ('；主要结论受体' + str(primary_count) + '个，其余受体仅作扩展或探索解释') if generic else ('；HSP90AA1的5组保持未运行' if planned == 10 else '；五个受体均已通过本次重对接质控')  # 历史提示保持兼容。
    body = '<h2>本轮必须核验：' + str(planned) + '组正式分子对接</h2><p class="notice"><strong>请确认结合能矩阵可作为本次流程测试结果。</strong><br>完成' + str(summary['成功组合数']) + '/' + str(planned) + '组；技术失败' + str(summary['失败组合数']) + '组' + extra + '。无需逐个审核全部姿势。</p>' + table(matrix, columns)  # 一屏显示核心输出。
    body += '<p>评分口径：' + str(summary['评分口径']) + '。本轮没有设置结合能通过阈值；数值只作为候选排序和后续研究依据。</p>'  # 防止将描述性评分解释为实验效应。
    body += '<details><summary>查看' + str(planned) + '组完整性检查摘要</summary>' + table(formal['tables']['combination_results']) + '</details>'  # 技术细节默认折叠。
    return body  # 返回当前重点区。


def preview_page(workflow, study_id):  # 中文展示集中准备资料。
    from web import page, table, text  # 使用现有布局和安全转义。
    manifest = workflow.load(study_id)  # 已发布结果优先读取当前版本。
    current_id = manifest['current'].get('A06')  # 不猜最新版。
    current = workflow.result(manifest, current_id) if current_id and workflow.active(manifest, current_id) else None  # 失效A06不得冒充新版结果。
    if current and current.get('tables', {}).get('generic_docking'):  # 动态版本不再显示过时筛查状态。
        body = '<p><a href="/study?study=' + text(study_id) + '">返回研究，查看A07报告复核</a></p>' + dynamic_result_section(current, study_id, workflow)  # 保留原入口并读取明确图件修订。
        return page('A06 扩展对接结果', body)  # 不代签A07结论。
    plan = load_preview(workflow, study_id)  # 先检查版本与完整性。
    if plan.get('schema_version') in ('A06.receptor.screen.1', 'A06.receptor.audit.1', 'A06.receptor.screen.2', 'A06.receptor.audit.2'):  # 通用流程使用精简的集中筛查页面。
        audited = plan.get('schema_version') in ('A06.receptor.audit.1', 'A06.receptor.audit.2')  # 区分待核查与已核查阶段。
        heading = '受体适用性核查已完成' if audited else '本轮必须核验：受体筛查'  # 首屏显示真实当前状态。
        body = '<p><a href="/study?study=' + text(study_id) + '">返回研究</a></p><p class="notice"><strong>' + heading + '</strong><br>' + text(plan['notice']) + '</p>'  # 首屏只突出当前决定。
        if plan.get('analysis_purpose') == 'workflow_test':  # 研究用途持续传播到对接阶段。
            body += '<p><strong>仅用于流程测试，非正式研究结论</strong></p>'  # 防止缺库测试被误用。
        ligand_rows = [{'成分编号': row['compound_id'], '成分': row['name'], '来源药味': row['herbs'], '入选角色': row['selection_role']} for row in plan['ligands']]  # 七项成分来自已批准A03_SELECT。
        body += '<h2>已接入的对接成分</h2><p>共' + str(plan['ligand_count']) + '个；并列候选和白术代表成分均按已确认决定保留。</p>' + table(ligand_rows)  # 不退回固定五成分逻辑。
        screen_rows = [{'PPI顺序': row['ppi_order'], '靶点': row['symbol'], 'Degree': row['degree'], '并列提示': '同Degree并列' if row['degree_tie'] else '', '已有技术线索': (row['historical_pdb'] + ('；历史重对接RMSD=' + str(round(row['historical_redocking_rmsd_angstrom'], 3)) + ' Å' if row['historical_redocking_rmsd_angstrom'] is not None else '；无参考配体重对接条件')) if row['historical_pdb'] else '无', '本轮状态': row['screen_status']} for row in plan['screening_window']]  # 有PDB但无参考配体时不对空RMSD取小数。
        body += '<h2>按PPI顺序的连续筛查窗口</h2><p class="notice"><strong>历史技术通过不等于本研究自动入选。</strong> 仍须核对蛋白身份、物种、链、结构覆盖、共晶小分子及口袋是否适用于本研究；高位未决对象不能静默跳过。</p>' + table(screen_rows)  # 解释为何不能直接套用旧五靶点。
        if audited:  # 核查完成后集中展示推荐与暂缓理由。
            labels = {'recommended': '推荐进入技术准备', 'strict_candidate': '严格质控候选', 'exploratory_candidate': '扩展或探索候选', 'not_computable': '当前不可计算'}  # 同时解释历史与第二版结论。
            decision_rows = [{'PPI名次': row['ppi_order'], '靶点': row['symbol'], 'Degree': row['degree'], '结构': row.get('pdb', ''), '参考配体': row.get('reference_ligand', ''), '结论': labels.get(row['decision'], '本轮暂缓'), '理由': row['reason']} for row in plan['assessments']]  # 不要求用户翻原始RCSB文件找结论。
            body += '<h2>结构适用性核查结论</h2>' + table(decision_rows)  # 同时展示采用和暂缓对象。
        body += '<h2>当前还差什么</h2>' + table([{'待完成事项': row['item'], '影响与下一步': row['impact']} for row in plan['pending']])  # 下一步集中显示而不要求逐页确认。
        body += '<details><summary>原始结果与历史技术质控证据</summary>'  # 追溯资料默认折叠。
        for number, record in enumerate(plan['evidence']):  # 下载只能引用已登记且通过指纹的文件。
            body += '<p><a href="/docking-preview-file?study=' + text(study_id) + '&amp;index=' + str(number) + '">' + text(record['path'].split('/')[-1]) + '</a></p>'  # 不开放任意路径。
        body += '</details>'  # 结束追溯区。
        return page('A06 受体筛查预览', body)  # 与原工作台保持同一入口和视觉风格。
    heading = '正式对接已完成：下一步集中核验结果矩阵' if plan.get('formal_result_data') else ('诊断已完成：下一步集中核验三条结果' if plan.get('redocking_result_data') else ('配置已准备：下一步集中核验A06_PREP' if plan.get('preparation_package_data') else '准备中：当前无需签署'))  # 只突出当前真正需要的动作。
    body = '<p><a href="/study?study=' + text(study_id) + '">返回研究</a></p><p class="notice"><strong>' + heading + '</strong><br>' + text(plan['notice']) + '</p>'  # 先明确用户当前要做什么。
    if plan.get('analysis_purpose') == 'workflow_test':  # 用途标签不折叠。
        body += '<p><strong>仅用于流程测试，非正式研究结论</strong></p>'  # 不把中性形态例外扩大至正式研究。
    body += '<h2>当前还差什么</h2>' + table([{'待完成事项': row['item'], '影响与下一步': row['impact']} for row in plan['pending']], ['待完成事项', '影响与下一步'])  # 重点放在最上方。
    if plan.get('required_decisions'):  # 只有真实存在的关键问题才要求人工处理。
        body += '<h2>进入A06_PREP前必须确认</h2><p class="notice"><strong>这些事项不处理会阻断对接。</strong></p>' + table([{'对象': row['object'], '必须确认的问题': row['issue'], '当前处理': row['current_action']} for row in plan['required_decisions']], ['对象', '必须确认的问题', '当前处理'])  # 让用户不用从技术明细中寻找重点。
    if plan.get('formal_result_data'):  # 正式运行完成后把十组矩阵置于最前。
        body += _formal_result_section(plan['formal_result_data'], table)  # 用户无需翻页寻找核心结果。
    elif plan.get('redocking_result_data'):  # 诊断完成且尚未正式运行时显示三条诊断。
        body += _redocking_result_section(plan['redocking_result_data'], table)  # 用户无需翻页寻找关键结论。
    if plan.get('preparation_package_data') and not plan.get('formal_result_data'):  # 正式完成后不重复展示过时的零运行说明。
        body += _package_review_section(plan['preparation_package_data'], table, plan.get('redocking_result_data'))  # 已完成的总体复核不再提示重复签署。
    body += '<h2>主候选成分的准备情况</h2>' + table([{'成分': row['name'], 'PubChem编号': row['cid'], '身份核对': row['identity'], '准备状态': row['preparation']} for row in plan['ligands']], ['成分', 'PubChem编号', '身份核对', '准备状态'])  # 不在首页铺开全部技术字段。
    body += '<p>本次已确认使用PubChem中性形态测试，未按特定pH预测电离状态；此决定不自动用于其他研究。</p>'  # 展示已经批准的限定。
    if plan.get('prepared_ligand_results'):  # 实际候选文件形成后显示校验摘要。
        ligand_rows = [{'成分': row['name'], '准备结果': '已生成候选文件' if row['status'] == 'prepared_candidate' else '失败，详见记录', '重原子数': row.get('validation', {}).get('heavy_atom_count', '未通过'), '重原子检查': '身份及坐标保留' if row.get('validation', {}).get('heavy_atoms_preserved') else '未通过'} for row in plan['prepared_ligand_results']]  # 不把准备成功称作对接成功。
        body += '<h2>本次配体准备结果</h2>' + table(ligand_rows) + '<p>五项均沿用本次获准的PubChem中性三维结构；未按特定pH预测电离状态。</p>'  # 限制随结果展示。
        body += '<details><summary>下载本次配体结构文件</summary>'  # 大量文件默认折叠。
        ligand_paths = {record['path'] for row in plan['prepared_ligand_results'] for record in row.get('files', []) if record['path'].endswith(('.sdf', '.pdbqt'))}  # 只使用配体包逐项登记的结构文件。
        for number, record in enumerate(plan['evidence']):  # 下载仍经过有指纹的统一清单。
            if record['path'] in ligand_paths:  # 不依赖文件名猜对象类型。
                body += '<p><a href="/docking-preview-file?study=' + text(study_id) + '&amp;index=' + str(number) + '">' + text(record['path'].split('/')[-1]) + '</a></p>'  # 不开放任意路径。
        body += '</details>'  # 结束配体文件组。
    receptor_title = '已批准本次受体准备方案' if plan.get('prepared_receptor_report') else '受体候选方案（尚未最终选定）'  # 区分方案批准和结果签署。
    body += '<h2>' + receptor_title + '</h2>' + table([{'靶点': row['symbol'], '第一轮Degree': row['degree'], 'PDB': row['pdb'], '拟用作者链': row['chains'], '需要知悉': plan.get('receptor_notes', {}).get(row['symbol'], row['note'])} for row in plan['receptors']], ['靶点', '第一轮Degree', 'PDB', '拟用作者链', '需要知悉'])  # 准备前候选不写成已批准名单。
    if plan.get('prepared_receptor_results'):  # 优先显示本次实际准备是否成功。
        rows = [{'靶点': row['symbol'], '准备结果': '已生成候选文件' if row['status'] == 'prepared_candidate' else '失败，详见记录', '蛋白重原子': row.get('validation', {}).get('heavy_atom_count', '未通过'), '重原子检查': '身份及坐标保留' if row.get('validation', {}).get('heavy_atoms_preserved') else '未通过'} for row in plan['prepared_receptor_results']]  # 不把准备成功称为对接成功。
        box_state = '搜索盒已按本次授权写入候选配置' if plan.get('box_authorization_data') else '搜索盒仍待定'  # 不让旧说明覆盖新授权状态。
        body += '<h2>本次受体准备结果</h2>' + table(rows) + '<p>已按本次授权移除结晶水，未显式建模水介导作用；未按特定pH枚举质子化状态。' + box_state + '，尚未运行对接。</p>'  # 科学局限随结果呈现。
        body += '<details><summary>下载本次受体结构文件</summary>'  # 文件入口明确，技术明细保持折叠。
        receptor_paths = {record['path'] for row in plan['prepared_receptor_results'] for record in row.get('files', []) if record['path'].endswith(('.pdb', '.pdbqt'))}  # 只使用受体包逐项登记的结构文件。
        for number, record in enumerate(plan['evidence']):  # 仍使用统一有指纹的证据清单。
            if record['path'] in receptor_paths:  # 配体PDBQT不会混入受体分组。
                body += '<p><a href="/docking-preview-file?study=' + text(study_id) + '&amp;index=' + str(number) + '">' + text(record['path'].split('/')[-1]) + '</a></p>'  # 不接受任意路径。
        body += '</details>'  # 结束结构下载组。
    if plan.get('docking_combinations') and not plan.get('formal_result_data'):  # 正式完成后不再显示“完成0组”的历史计划。
        relation_labels = {'upstream_record': '上游已有成分—靶点记录', 'exploratory': '探索性组合'}  # 不把探索性关系写成数据库已证实。
        combination_rows = [{'成分': row['compound_name'], '受体': row['target_symbol'] + ' / ' + row['pdb'] + ' ' + row['chains'], '关系依据': relation_labels[row['relation']], '状态': '未运行'} for row in plan['docking_combinations']]  # 不显示空分数为零。
        upstream_count = sum(row['relation'] == 'upstream_record' for row in plan['docking_combinations'])  # 摘要直接由明细计算。
        exploratory_count = len(combination_rows) - upstream_count  # 无上游记录的组合单独计数。
        body += '<h2>计划对接组合</h2><p>共' + str(len(combination_rows)) + '组：' + str(upstream_count) + '组有上游成分—靶点记录，' + str(exploratory_count) + '组为探索性；当前完成0组。探索性不表示不存在结合。</p><details><summary>展开15组计划明细</summary>' + table(combination_rows) + '</details>'  # 用户无需在首屏逐行审核。
    if not plan.get('preparation_package_data') and plan.get('box_proposal_data'):  # 尚未形成配置时才展示历史待确认方案。
        proposal = plan['box_proposal_data']  # 读取已校验的方案。
        box_rows = [{'受体': row['symbol'] + ' / ' + row['pdb'] + ' ' + row['chains'], '参考配体': row['reference_ligand']['code'] + ' ' + row['reference_ligand']['auth_chain'] + ':' + row['reference_ligand']['auth_sequence'], '中心 X/Y/Z（Å）': ' / '.join(str(x) for x in row['candidate_center_angstrom']), '尺寸 X/Y/Z（Å）': ' / '.join(str(x) for x in row['candidate_size_angstrom']), '超过30 Å轴': '是' if row['larger_than_30_angstrom_axis'] else '否'} for row in proposal['boxes']]  # 数值不转成活动配置。
        body += '<h2>下一步只需确认：搜索盒与姿势检查</h2><p class="notice"><strong>当前仍是待确认方案，不会运行对接。</strong><br>建议使用各自共结构参考配体外包络、每侧5 Å；三个盒子的各轴均小于30 Å。</p>' + table(box_rows)  # 关键决定及实际数值放在同一区域。
        body += '<details><summary>查看拟采用的七项基础姿势检查</summary>' + table([{'检查': row['rule'], '失败时处理': row['failure_action']} for row in proposal['pose_integrity_rules']]) + '</details>'  # 技术规则默认折叠。
        recommended = proposal['redocking_options']['recommended']  # 推荐项来自方案记录。
        fastest = proposal['redocking_options']['fastest']  # 最快项保留真实局限。
        body += '<details><summary>比较是否增加三次原配体重对接</summary>' + table([{'方案': recommended['label'] + '（推荐）', '作用': recommended['reason'], '代价或限制': recommended['cost']}, {'方案': fastest['label'], '作用': fastest['reason'], '代价或限制': fastest['limitation']}]) + '<p>推荐诊断规则：' + text(recommended['diagnostic_rule']) + '</p></details>'  # 不在页面代替用户选择。
    if plan.get('structure_inspection'):  # 结构清点作为需要知悉的折叠信息展示。
        columns = ['靶点', 'PDB', '拟用链', '已建模残基', '缺失原子记录', '水分子', '替代构象残基', '距参考配体最近的结构问题', '当前结论']  # 列名直接说明科学含义。
        body += '<details><summary>受体原始坐标与参考位点清点</summary><p>距离仅用于定位问题，不是自动通过阈值；“缺失原子距离”指该残基其余已建模原子到参考配体的最近距离。</p>' + table(plan['structure_inspection'], columns) + '</details>'  # 不把大量技术数量放到首屏。
    if plan.get('preparation_diagnostic'):  # 准备能力诊断与正式受体文件分开显示。
        columns = ['靶点', 'PDB', '诊断结果', '程序提示', '是否形成正式受体']  # 让非技术用户直接看到哪些对象被阻断。
        body += '<details><summary>Meeko受体准备能力诊断</summary><p>诊断使用临时的仅蛋白副本，不采用自动删坏残基或自动选替代构象；临时文件已清理。诊断成功只表示工具能够处理当前蛋白坐标，不等于结构或水处理已获批准。</p>' + table(plan['preparation_diagnostic'], columns) + '</details>'  # 失败原因保留但不挤占首屏。
    body += '<details><summary>暂缓候选及原因</summary>' + table([{'靶点': row['symbol'], '说明': row['reason']} for row in plan['deferred']]) + '</details>'  # 不把暂缓说成无生物学意义。
    parameter_note = '搜索盒和姿势规则已写入A06_PREP候选包；整体复核前仍不执行。' if plan.get('preparation_package_data') else '实际搜索盒及姿势检查规则仍待完成，不会从这些参数自动推断。'  # 随当前阶段显示真实边界。
    body += '<details><summary>已批准的运行参数</summary>' + table([{'参数': key, '值': value} for key, value in plan['known_settings'].items()]) + '<p>' + parameter_note + '</p></details>'  # 说明配置边界。
    body += '<details><summary>原始资料与准备试验记录（追溯时展开）</summary>'  # 大量文件默认折叠。
    for number, record in enumerate(plan['evidence']):  # 下载仅使用当前预览列出的证据。
        body += '<p><a href="/docking-preview-file?study=' + text(study_id) + '&amp;index=' + str(number) + '">' + text(record['path'].split('/')[-1]) + '</a></p>'  # 不提供任意路径访问。
    body += '</details>'  # 结束追溯资料组。
    return page('A06 对接准备预览', body)  # 与统一网页保持一致。
