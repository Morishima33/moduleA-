# 在原A06卡片中展示通用结构方案与后台进度，普通用户不编辑JSON。
from html import escape  # 防止输入破坏页面。
from pathlib import Path  # 固定本机工具位置。
from storage import read_json  # 读取明确配置。
from storage import verified_file  # 草案必须经指纹校验后显示。
from docking_automation import current_plan, job_status, parents, save_plan, start_job  # 统一方案与执行入口。
from contracts import require  # 未确认即停止。


def _input(name, value='', required=False):  # 生成简单文本字段。
    return '<input name="' + escape(name, quote=True) + '" value="' + escape(str(value or ''), quote=True) + '"' + (' required' if required else '') + '>'  # 字段名与内容均转义。


def _hidden(name, value):  # 隐藏字段仍由后台重新校验。
    return '<input type="hidden" name="' + escape(name, quote=True) + '" value="' + escape(str(value), quote=True) + '">'  # 不信任浏览器提交版本。


def controls(workflow, study_id, token):  # 原研究页提供入口与短状态。
    manifest = workflow.load(study_id)  # 每次重新核验当前状态。
    if manifest.get('trashed', False):  # 回收站只读。
        return ''  # 不显示执行按钮。
    try:  # 上游尚未通过时不展示不可操作长表。
        parents(workflow, study_id)  # 校验PPI与选择已通过。
    except ValueError:  # 前序未完成是正常状态。
        return ''  # 原卡片保留等待提示。
    body = '<p><a href="/docking-automation?study=' + escape(study_id) + '">确认结构方案／查看自动化进度</a></p>'  # 页面不塞满结构配置。
    status = job_status(workflow, study_id)  # 明确当前任务。
    if status:  # 有任务才显示。
        labels = {'queued': '已启动', 'running': '正在处理', 'completed': '本阶段完成', 'failed': '需要处理', 'interrupted': '已中断'}  # 不混淆完成与通过。
        body += '<p class="notice"><strong>' + labels[status['state']] + '：</strong>' + escape(status['message']) + '</p>'  # 重点状态直接显示。
    return body  # 同一研究入口。


def settings_page(workflow, study_id, token):  # 集中填写当前研究结构选择和任务编号。
    from docking_generic_prep import prepare_screen  # 明确PPI筛查窗口。
    from hgnc import load_snapshot  # 提示可核验的UniProt身份。
    ids = parents(workflow, study_id)  # 防旧版本。
    screen = prepare_screen(workflow, study_id)['preview']  # 范围固定。
    manifest = workflow.load(study_id)  # 取得当前已验证事实。
    selected = current_plan(workflow, study_id)  # 已保存方案仅在同上游预填。
    old = selected[0] if selected and selected[0]['parent_runs'] == ids else {}  # 不跨疾病版本自动授权。
    generic = {}  # 历史结果只作明确可见的结构建议。
    run_id = manifest['current'].get('A06')  # 当前正式结果。
    if run_id and workflow.active(manifest, run_id):  # 只使用当前有效版本作预填建议。
        generic = workflow.result(manifest, run_id).get('tables', {}).get('generic_docking', {})  # 不扫描其他病例找默认结构。
    status = job_status(workflow, study_id)  # 获取真实后台状态。
    body = '<h2>自动化进度与重点复核</h2><p><a href="/study?study=' + escape(study_id) + '">返回研究页复核模块</a> · <a href="/docking-automation?study=' + escape(study_id) + '">刷新进度</a></p>'  # 关闭再打开仍读取磁盘状态。
    if status:  # 当前任务中文展示。
        label = {'queued': '已启动', 'running': '正在处理', 'completed': '本阶段完成', 'failed': '需要处理', 'interrupted': '已中断'}[status['state']]  # 普通用户使用中文状态。
        body += '<p class="notice"><strong>' + label + '</strong>：' + escape(status['message']) + '</p>'  # 不显示堆栈给普通用户。
        for record in status.get('drafts', []):  # 未发布草案也应明确显示真正阻断原因。
            draft = read_json(verified_file(workflow.location(study_id), record))  # 不凭文件存在解释科学结果。
            if draft.get('schema_version') == 'A06.automation.preparation.1':  # 只展示已知结构的准备事实。
                body += '<h3>未发布准备：请集中处理这些问题</h3><ul>'  # 明确不是正式结果。
                for row in draft['receptors'] + draft['compounds']:  # 两类对象均可导致NA。
                    if row['status'] != 'ready':  # 页面只突出失败项。
                        body += '<li>' + escape(row.get('target', row.get('name', ''))) + '：' + escape(row['error']) + '</li>'  # 用户能找到暂停原因。
                body += '</ul>'  # 其余资料仍保留追溯。
    body += '<p class="notice"><strong>必须人工确认：</strong>每个受体的PDB、作者链、目标UniProt、参考配体或预测口袋以及结构限制；每个成分的CID与使用形态。未明确的对象请暂停并填写原因。保存方案只启动准备，准备结果通过后才进行研究成分对接。</p>'  # 突出科学关口。
    body += '<form method="post" action="/docking-automation-plan">' + _hidden('token', token) + _hidden('study', study_id)  # 使用统一CSRF。
    for key, value in ids.items():  # 冻结上游版本。
        body += _hidden('parent_' + key, value)  # 后台全部比较。
    body += '<h3>成分身份与三维形态</h3><p>使用PubChem原始三维形态，不预测特定pH；这需要本研究明确同意。无法核定的成分保留NA。</p>'  # 不擅自默认中性形态。
    old_compounds = {row['compound_id']: row for row in old.get('compounds', [])}  # 本研究旧方案预填。
    suggestions = {row['compound_id']: row for row in generic.get('compounds', [])}  # 已核验CID仅作提示。
    for index, row in enumerate(screen['ligands']):  # 实际成分数动态。
        item = old_compounds.get(row['compound_id'], {})  # 不要求固定五或七个。
        cid = item.get('cid', suggestions.get(row['compound_id'], {}).get('pubchem_cid', ''))  # 仅明确当前来源CID。
        body += '<fieldset><legend>' + escape(row['name'] + ' / ' + row['compound_id']) + '</legend><label>PubChem CID' + _input('c_' + str(index) + '_cid', cid) + '</label><label>处理方式<select name="c_' + str(index) + '_status"><option value="unavailable">未核定，保留NA</option><option value="use"' + (' selected' if item.get('status') == 'use' else '') + '>使用已核定PubChem原始三维形态</option></select></label><label>身份及形态依据／暂停原因' + _input('c_' + str(index) + '_reason', item.get('reason', ''), True) + '</label></fieldset>'  # 每个对象独立判断。
    body += '<h3>受体结构与位点</h3><p>共晶参考配体填写“代码 作者链 残基号”，如IQO A 444。预测口袋固定P2Rank首位口袋；没有参考配体时不生成RMSD，也不作为主要五个受体。</p>'  # 普通文字输入不要求JSON。
    old_receptors = {row['target']: row for row in old.get('receptors', [])}  # 本研究已确认方案。
    target_suggestions = {row['target']: row for row in generic.get('receptors', [])}  # 当前结果建议。
    mapper, meta = load_snapshot(workflow.root)  # UniProt提示来自已核验HGNC。
    for index, row in enumerate(screen['screening_window']):  # 包括第十位并列。
        item = old_receptors.get(row['symbol'], {})  # 不借历史批准代签新方案。
        prior = target_suggestions.get(row['symbol'], {})  # 已核验结果只作建议。
        uniprots = sorted(key[1] for key, values in mapper.index.items() if key[0] == 'uniprot_ids' and values == {row['target_id']})  # 唯一映射候选。
        prefix = 'r_' + str(index) + '_'  # 与实际顺序固定绑定。
        reference = ' '.join(str(item.get(key, '')) for key in ('reference_code', 'reference_chain', 'reference_sequence')).strip()  # 回填明确字段。
        body += '<fieldset><legend>' + escape(row['symbol']) + '（PPI顺序' + str(row['ppi_order']) + '）</legend><label>PDB ID' + _input(prefix + 'pdb', item.get('pdb_id', prior.get('pdb_id', row.get('historical_pdb', '')))) + '</label><label>作者链，逗号分隔' + _input(prefix + 'chains', ','.join(item.get('chains', prior.get('chains', [])))) + '</label><label>UniProt（HGNC对应：' + escape(','.join(uniprots) or '须核对') + '）' + _input(prefix + 'uniprot', item.get('uniprot', uniprots[0] if len(uniprots) == 1 else '')) + '</label>'  # 只建议唯一官方编号。
        body += '<label>口袋依据<select name="' + prefix + 'pocket"><option value="reference">共晶参考配体</option><option value="p2rank"' + (' selected' if item.get('pocket') == 'p2rank' else '') + '>P2Rank预测首位口袋</option></select></label><label>共晶配体：代码 链 残基号' + _input(prefix + 'reference', reference) + '</label><label>替代构象<select name="' + prefix + 'altloc"><option value="">未指定；发现替代构象则暂停</option><option value="A"' + (' selected' if item.get('altloc') == 'A' else '') + '>本研究明确采用A</option><option value="B"' + (' selected' if item.get('altloc') == 'B' else '') + '>本研究明确采用B</option></select></label>'  # 不默认A。
        body += '<label>解释范围<select name="' + prefix + 'scope"><option value="unavailable">不能计算，保留NA</option><option value="strict"' + (' selected' if item.get('scope') == 'strict' else '') + '>可作为主要受体候选，仍须重对接通过</option><option value="exploratory"' + (' selected' if item.get('scope') == 'exploratory' else '') + '>仅扩展或探索线索</option></select></label><label>结构适用性依据与限制' + _input(prefix + 'reason', item.get('reason', prior.get('structure_limitation', '')), True) + '</label></fieldset>'  # 不把等级写进热图。
    body += '<h3>任务包与复核登记</h3><label>总控明确任务编号，如D006' + _input('package_id', old.get('package_id', ''), True) + '</label><details><summary>其他信息：本机PyMOL位置</summary><label>PyMOL程序完整位置' + _input('pymol', old.get('pymol_executable', ''), True) + '</label></details><label>复核人' + _input('reviewer', '', True) + '</label><label>本研究结构与形态选择依据' + _input('note', '', True) + '</label><label><input type="checkbox" name="confirmed" value="yes" required>确认上述科学选择仅用于当前研究，失败不自动调参或替换对象</label><button>保存方案并自动准备结构与质控</button></form>'  # 首次确认后后台准备。
    if old:  # 已确认方案可重试阶段失败。
        for stage, label, module in [('prepare', '重试结构准备／查看已有结果', None), ('execute', '继续自动对接或精确复用', 'A06_PREP'), ('deliver', '继续生成任务包与双报告', 'A06')]:  # 同一方案已完成时不假称生成新版本。
            if module and (not manifest['current'].get(module) or not workflow.approved(manifest, manifest['current'][module])):  # 未批准不能执行该阶段。
                continue  # 原研究页负责复核。
            if module and stage == 'execute' and workflow.run(manifest, manifest['current'][module])['inputs'].get('automation_plan') != selected[1]:  # 历史准备不能冒充新方案的已批准输入。
                continue  # 先重新准备和复核，页面不提供必然失败的执行按钮。
            body += '<form method="post" action="/docking-automation-start">' + _hidden('token', token) + _hidden('study', study_id) + _hidden('stage', stage) + '<button>' + label + '</button></form>'  # 明确重试入口。
    return body  # 外层继续使用统一页面样式。


def submit(workflow, data):  # 后台转换网页字段，用户不手工编写路径或JSON。
    from docking_generic_prep import prepare_screen  # 当前窗口。
    require(data.get('confirmed') == 'yes', '请明确确认结构与形态选择')  # 未勾选不保存。
    study_id = data.get('study', '')  # 身份由工作流校验。
    screen = prepare_screen(workflow, study_id)['preview']  # 不信任客户端对象名单。
    compounds, receptors = [], []  # 按上游实际顺序构建。
    for index, row in enumerate(screen['ligands']):  # 成分字段动态解析。
        prefix = 'c_' + str(index) + '_'  # 与模板字段一致。
        compounds.append({'compound_id': row['compound_id'], 'cid': data.get(prefix + 'cid', '').strip(), 'status': data.get(prefix + 'status'), 'reason': data.get(prefix + 'reason', '').strip(), 'protonation_policy': 'pubchem_3d_as_provided_no_pH_prediction' if data.get(prefix + 'status') == 'use' else 'not_confirmed'})  # 使用形态明确存档。
    for index, row in enumerate(screen['screening_window']):  # 受体字段动态解析。
        prefix = 'r_' + str(index) + '_'  # 与表单一一对应。
        reference = data.get(prefix + 'reference', '').split()  # 三项身份不能猜缺项。
        require(not reference or len(reference) == 3, '共晶配体请填写：代码 作者链 残基号')  # 不猜链或编号。
        receptor = {'target': row['symbol'], 'pdb_id': data.get(prefix + 'pdb', '').strip().upper(), 'chains': [value.strip() for value in data.get(prefix + 'chains', '').split(',') if value.strip()], 'uniprot': data.get(prefix + 'uniprot', '').strip(), 'pocket': data.get(prefix + 'pocket'), 'altloc': data.get(prefix + 'altloc') or None, 'scope': data.get(prefix + 'scope'), 'reason': data.get(prefix + 'reason', '').strip()}  # 只收明确科学字段。
        if reference:  # 有共晶身份才写字段。
            receptor.update(reference_code=reference[0].upper(), reference_chain=reference[1], reference_sequence=reference[2])  # 完整保存。
        receptors.append(receptor)  # 保留全部失败或探索对象。
    plan = {'compounds': compounds, 'receptors': receptors, 'package_id': data.get('package_id', '').strip(), 'pymol_executable': data.get('pymol', '').strip()}  # 无硬编码方剂或疾病。
    record = save_plan(workflow, study_id, plan, {key: data.get('parent_' + key, '') for key in ('A00', 'A03', 'A03_SELECT', 'A04')}, data.get('reviewer', ''), data.get('note', ''))  # 原子版本校验。
    return start_job(workflow, study_id, 'prepare', record)  # 保存后自动启动准备。
