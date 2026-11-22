"""从当前归档解释复核阻塞项、责任和处理入口，不改变复核许可。"""


def blockers(view, result, study_id):
    """沿页面已经提供的入口定位当前问题。"""
    review = view['review']
    if not review.get('can_review') or 'approved' in review['allowed_decisions'] or not result:
        return []
    module = view['module']['module_id']
    tables = result['tables']
    summary = result['summary']
    sections = []
    pipeline = f'#/system-pipeline/{study_id}'
    files = {row['name']: row['key'] for row in view.get('files', [])}

    def add(title, owner, action, section=None, href=None, table=None, rows=(), keys=()):
        examples = [' · '.join(str(row[key]) for key in keys if row.get(key)) for row in rows[:4]]
        sections.append(dict(title_zh=title, owner_zh=owner, action_zh=action, examples=[x for x in examples if x],
                             section_id=section, href=href, file_key=files.get(f'{table}.csv')))

    technical = '技术核查可交给 Codex；未决的研究选择由你确认'
    if module == 'A01':
        missing = [r for r in tables.get('source_coverage', []) if r.get('complete') is False]
        system = view.get('special', {}).get('system_component_publication')
        evidence = 'component-source-evidence' if system and system.get('identity_tools_available') else 'module-details'
        if missing:
            add(f'{len(missing)} 项药味来源完整性待核', '由技术人员排查资料获取',
                '查看缺失的库和药味，补齐该来源后生成新结果。', None if system else 'module-source-inputs',
                pipeline if system else None, 'source_coverage', missing, ('database', 'herb', 'availability'))
        for table, title, keys in (
            ('tcmsp_source_issues', 'TCMSP 原件字段待核', ('herb', 'compound_id', 'source_line', 'reason')),
            ('tcmsp_identity_issues', 'TCMSP 基因身份待核', ('raw_symbol', 'symbol', 'raw_id', 'reason')),
            ('identity_issues', '基因身份待核', ('database', 'raw_symbol', 'raw_id', 'candidate_ids', 'reason')),
        ):
            rows = tables.get(table) or []
            if rows:
                add(f'{len(rows)} 项{title}', technical,
                    '先核对原件及官方编号。能唯一证实的保留依据，仍无法唯一核实的集中给你决定。',
                    evidence, table=table, rows=rows, keys=keys)
    elif module == 'A02':
        rows = [row for row in tables.get('scope_groups', []) if row.get('scope') == 'pending']
        if rows:
            add(f'{len(rows)} 组疾病条目待确认范围', '由你确认本病范围，资料可交给 Codex 整理',
                '逐组检查数据库、疾病名称和编号，保存本病、亚型或排除决定。',
                'disease-scope-review' if view.get('disease_scope') else None,
                None if view.get('disease_scope') else pipeline,
                'scope_groups', rows, ('database', 'disease_term', 'disease_id'))
        elif view.get('normalization'):
            normalization = view['normalization']
            preview = normalization.get('preview')
            add('身份核查预览已完成' if preview else '尚未生成疾病标准化结果', technical,
                normalization.get('disabled_reason_zh') or
                ('在核查表确认处理方式并生成标准化结果。' if preview else '先运行基因身份核查，再确认处理方式并生成标准化结果。'),
                'normalization-confirmation' if preview else 'normalization-review')
        elif not sections:
            add('当前疾病候选尚未标准化', technical,
                '在统一执行页查看当前批次缺少的前置条件，完成后再核查标准化结果。', href=pipeline)
    elif module == 'A04':
        rows = tables.get('identity_unresolved') or tables.get('identity_issues') or []
        if rows:
            add(f'{len(rows)} 项 STRING 基因映射待核', technical,
                '对照 HGNC 与 STRING 编号，核查缺失或不唯一的映射；未决项由你确认处理范围。',
                'module-focus', table='identity_unresolved' if tables.get('identity_unresolved') else 'identity_issues',
                rows=rows, keys=('symbol', 'target_id', 'reason', 'reason_zh'))
    elif module == 'A05':
        detail = view['state'].get('reason_zh')
        if detail and detail.startswith('需完成：'):
            add(detail.split('；')[0], technical,
                '在富集核对区逐项核对译名或展示范围，再提交整体复核。',
                'module-enrichment-confirmation' if view.get('enrichment_display') else 'module-focus')
    elif module in ('A06_PREP', 'A06'):
        rows = [row for row in tables.get('receptor_preparation', [])
                if row.get('state') not in ('ready', 'completed') and (row.get('reason_zh') or row.get('symbol'))]
        if module == 'A06' and summary.get('成功组合数') == 0:
            add('本批没有成功评分', '由技术人员排查准备和评分失败',
                '查看受体准备与组合结果里的具体失败原因。补齐证据后处理受影响的组合。',
                'module-automatic-results' if view.get('automatic_docking') else 'module-results',
                table='receptor_preparation', rows=rows, keys=('symbol', 'target_id', 'reason_zh'))
        else:
            add('准备证据或位点条件尚待核查', technical,
                '查看本批受体、成分及位点说明。技术失败可交给 Codex 排查，需要你确认的科学选择会单列。',
                'module-preparation' if view.get('docking_preparation') or view.get('docking_coverage') else 'module-results',
                table='receptor_preparation', rows=rows, keys=('symbol', 'target_id', 'reason_zh'))
    if not sections:
        add('需要核对本批归档中的阻塞原因', '由技术人员排查',
            '查看本批结果明细或把当前模块发给我核查。定位原因后再提交通过。', 'module-details')
    return sections
