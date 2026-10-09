# 自动化科学内核：从已确认方案准备对象，再运行或复用，最后形成同源交付。
from pathlib import Path  # 使用项目与研究相对位置。
import json  # 读取RCSB及PubChem原回应。
import shutil  # 原样归档来源及复用文件。
import sys  # 留存实际解释器版本。
import zipfile  # 建立完整研究任务ZIP。
from contracts import fingerprint, require  # 科学输入不明确即阻断。
from storage import file_record, now, read_json, verified_file, write_json, write_lock  # 使用统一归档规则。
from docking_automation import PREP_SCHEMA, assert_current  # 共用冻结上游检查。
from docking_top10_execute import VINA, _box_from_lines, _current_redock, _ligand_lines, _meeko_settings, _prepare_receptor_cli, _protein_pdb, _run, _vina_arguments, _write_text  # 只复用已验收内核，不使用病例对象常量。


def validate_preparation(root, run, summary, tables, anomalies, outcome):  # 专门校验通用准备结果，不套用已跑完的病例事实包。
    from docking_generic_prep import _screen_rows  # 唯一PPI窗口算法。
    root = Path(root)  # 项目根。
    study = root / 'studies' / run['study_id']  # 准备来源必须属于本研究。
    prep = read_json(verified_file(study, run['inputs']['automation_preparation']))  # 指纹绑定准备事实。
    plan = read_json(verified_file(study, run['inputs']['automation_plan']))  # 人工结构方案。
    require(prep['schema_version'] == PREP_SCHEMA and prep['study_id'] == run['study_id'] == plan['study_id'] and prep['plan_record'] == run['inputs']['automation_plan'], '通用准备身份、版本或方案不一致')  # 禁止跨研究。
    require(all(prep['parent_runs'].get(key) == value for key, value in run['parent_runs'].items()), '准备事实与运行上游不一致')  # 绑定当前上游快照。
    for record in prep['files']:  # 所有准备输入与质控证据完整。
        verified_file(study, record)  # 任一改变则停止。
    manifest = read_json(study / 'manifest.json')  # 历史索引保留所有运行。
    selection = read_json(verified_file(study, manifest['runs'][run['parent_runs']['A03_SELECT']]['result_file']))  # 明确选择来源。
    ppi = read_json(verified_file(study, manifest['runs'][run['parent_runs']['A04']]['result_file']))  # 明确PPI来源。
    require([row['compound_id'] for row in prep['compounds']] == [row['compound_id'] for row in selection['tables']['selected']], '通用准备成分与批准选择不同')  # 数量不能固定。
    require([row['target'] for row in prep['receptors']] == [row['symbol'] for row in _screen_rows(ppi['tables']['round1'], {})], '通用准备没有完整覆盖PPI前十位及并列')  # 不能静默删除失败受体。
    strict = [row['target'] for row in prep['receptors'] if row['status'] == 'ready' and row['scope'] == 'strict' and isinstance(row['rmsd'], (int, float)) and 0 <= row['rmsd'] <= 2.0]  # 从实际事实重新计算。
    require(len(strict) >= 5 and prep['strict_qc_passed_targets'] == strict and prep['primary_targets'] == strict[:5], '通用准备主要五受体不满足当前重对接质控')  # 不能通过历史RMSD凑数。
    require(outcome == 'success' and summary.get('handoff_blocked') is False and summary.get('计划组合数') == len(prep['compounds']) * len(prep['receptors']), '通用准备摘要或交接状态不正确')  # 数量必须可复算。
    diagnostics = tables.get('receptor_diagnostics', [])  # 页面集中显示受体问题。
    require([row.get('受体') for row in diagnostics] == [row['target'] for row in prep['receptors']], '准备诊断表与事实包不同源')  # 不手抄诊断。


def _publish(workflow, request, module, inputs, config, reason, summary, tables, anomalies, outcome, **records):  # 最后一次核验和版本发布在同一个锁内完成。
    with write_lock(workflow.root):  # 长计算不占锁，完整发布才短暂占锁。
        assert_current(workflow, request)  # 防止检查与写入之间上游发生变化。
        manifest = workflow.load(request['study_id'])  # 读取当前唯一索引。
        run = workflow._begin(manifest, module, inputs, config, reason)  # 使用统一工作流内部原子接口。
        result = workflow._finish(manifest, run['run_id'], summary, tables, anomalies, outcome, **records)  # 科学校验通过后才完整提交。
        workflow.save(manifest)  # 只保存完整结果的当前指针。
    return result  # 不产生半发布版本。


def _capture(workflow, folder, url, label):  # 获取官方原文并保存研究内独立引用。
    from docking_sources import capture  # 只允许官方白名单。
    from docking_audit import source_body  # 失败不能转成零记录。
    response, reference = capture(workflow.root, url)  # 原始响应全量归档。
    destination = folder / 'raw' / (label + '.json')  # 当前任务原始来源。
    destination.parent.mkdir(parents=True, exist_ok=True)  # 创建原始目录。
    shutil.copy2(verified_file(workflow.root, reference), destination)  # 保存完全相同字节。
    body = source_body(workflow.root, reference)  # 来源完整且成功才继续。
    return body  # JSON或坐标原文。


def _software(workflow, folder):  # 固定软件及执行内核，避免复用只看输入文件。
    from docking_runtime import activate  # 核验-I -S及全部包版本。
    runtime = activate(workflow.root)  # 不静默加载电脑其他包。
    executable = workflow.root / 'environments' / 'vina_1.2.7' / 'vina_1.2.7_win.exe'  # 已审定Vina版本。
    require(executable.is_file(), '未找到固定Vina 1.2.7程序')  # 软件缺失不能发布NA假计算。
    version = _run([str(executable), '--version'], folder, folder / 'vina_version.txt', folder / 'vina_version_stderr.txt')  # 核对实际版本。
    require(version.returncode == 0 and '1.2.7' in version.stdout, 'Vina实际版本与方案不同')  # 新版本必须另行审定。
    snapshots = folder / 'code'  # 每个任务保留执行源码。
    snapshots.mkdir(parents=True, exist_ok=False)  # 不覆盖历史。
    names = ('docking_automation.py', 'docking_automation_compute.py', 'docking_top10_execute.py', 'docking_ligand.py', 'docking_audit.py', 'docking_formal.py', 'docking_redocking.py', 'docking_reference_ligand.py', 'docking_p2rank.py', 'docking_contract.py')  # 追溯所有直接科学内核。
    for name in names:  # 逐个保存实际字节。
        shutil.copy2(workflow.root / 'src' / name, snapshots / name)  # 代码后续修改不破坏此轮追溯。
    return {'runtime': runtime, 'vina_executable': file_record(workflow.root, executable, 'vina_executable'), 'parameters': VINA, 'kernel_sha256': fingerprint({name: file_record(workflow.root, snapshots / name, 'code')['sha256'] for name in names}), 'python': sys.version}  # 输入、工具与算法共同决定复用资格。


def _identity(workflow, folder, spec, target_id):  # 从官方实体核对每一条作者链。
    from hgnc import load_snapshot  # 使用当前已锁定HGNC来源。
    from docking_audit import receptor_identity  # 唯一UniProt、人类及蛋白类型核查。
    mapper, metadata = load_snapshot(workflow.root)  # 不自行猜基因—蛋白转换。
    require(mapper.index[('uniprot_ids', spec['uniprot'])] == {target_id}, '拟用UniProt与本研究HGNC靶点不唯一一致')  # 不能由用户错误输入改变靶点身份。
    entry = json.loads(_capture(workflow, folder, f"https://data.rcsb.org/rest/v1/core/entry/{spec['pdb_id']}", spec['target'] + '_entry'))  # 获取所有实体编号。
    entities = []  # 不默认第一实体。
    for entity_id in entry['rcsb_entry_container_identifiers']['polymer_entity_ids']:  # 每个聚合物实体都可核对。
        entity = json.loads(_capture(workflow, folder, f"https://data.rcsb.org/rest/v1/core/polymer_entity/{spec['pdb_id']}/{entity_id}", spec['target'] + '_entity_' + str(entity_id)))  # 原回应留存。
        entities.append(entity)  # 根据作者链定位。
    rows = []  # 每条链独立结果。
    for chain in spec['chains']:  # 全部链不能省略。
        matches = [entity for entity in entities if chain in entity.get('rcsb_polymer_entity_container_identifiers', {}).get('auth_asym_ids', [])]  # 官方作者链映射。
        require(len(matches) == 1, '作者链无法唯一映射到RCSB实体：' + chain)  # 同名不能随便选。
        entity = matches[0]  # 唯一对象。
        if spec['scope'] == 'strict':  # 主要受体使用唯一目标身份。
            row = receptor_identity(entity, spec['uniprot'], chain)  # 沿用严格身份核验。
        else:  # 探索结构可以保留已明确限制的嵌合身份。
            ids = entity['rcsb_polymer_entity_container_identifiers']  # 实体身份来源。
            require(spec['uniprot'] in ids.get('uniprot_ids', []) and {value.get('ncbi_taxonomy_id') for value in entity.get('rcsb_entity_source_organism', [])} == {9606} and entity.get('entity_poly', {}).get('rcsb_entity_polymer_type') == 'Protein', '探索结构仍须对应目标人类蛋白')  # 探索不允许对错蛋白。
            row = {'auth_chain': chain, 'uniprot_ids': ids.get('uniprot_ids', []), 'exploratory_identity': True, 'structure_limitation': spec['reason']}  # 限制不能隐去。
        rows.append(row)  # 留存所有链的身份。
    return rows  # 调用者继续结构完整性核查。


def _prepare_receptor(workflow, folder, spec, target_id):  # 根据人工选择生成单项实际结构与质控。
    from docking_receptor import inspect_structure  # 原始结构清点。
    from docking_reference_ligand import prepare_reference_ligand  # 官方拓扑与共晶重原子坐标。
    from docking_p2rank import run_twice  # 固定P2Rank首位口袋重复验证。
    target = spec['target']  # 已确认HGNC符号。
    result = dict(spec, status='failed', rmsd=None, box=None, error='')  # 失败不会消失。
    if spec['scope'] == 'unavailable':  # 用户核定无法计算的对象。
        result['error'] = spec['reason']  # 保留NA依据。
        return result  # 不造结构。
    result['identity'] = _identity(workflow, folder, spec, target_id)  # 蛋白身份先核对。
    cif = _capture(workflow, folder, f"https://files.rcsb.org/download/{spec['pdb_id']}.cif", target + '_cif')  # 完整mmCIF来源。
    inspection = inspect_structure(cif, spec['pdb_id'], spec['chains'])  # 禁止默认多模型。
    write_json(folder / (target + '_structure_inspection.json'), inspection)  # 保存占有率、缺失及替代构象。
    pdb = _capture(workflow, folder, f"https://files.rcsb.org/download/{spec['pdb_id']}.pdb", target + '_pdb')  # 不转换时隐式改作者链。
    pdb_path = _write_text(folder / 'raw' / (target + '.pdb'), pdb, 'ascii')  # 原始PDB字节文本。
    protein = _protein_pdb(pdb_path, set(spec['chains']), spec.get('altloc'))  # 未授权替代构象即暂停。
    if spec['pocket'] == 'reference':  # 基于明确共晶配体建立搜索盒。
        import gemmi  # 核查共价连接，避免把共价配体当非共价参考。
        block = gemmi.cif.read_string(cif).sole_block()  # 唯一数据块。
        connections = block.get_mmcif_category('_struct_conn.')  # 官方连接记录。
        for index, kind in enumerate(connections.get('conn_type_id', [])):  # 有连接表时逐行核对。
            if not str(kind).startswith('covale'):  # 非共价类型不作共价阻断。
                continue  # 继续检查。
            for side in ('ptnr1', 'ptnr2'):  # 参考配体可能在任意一端。
                matches = all(str(connections.get(side + '_' + key, [''] * len(connections['conn_type_id']))[index]) == str(value) for key, value in [('label_comp_id', spec['reference_code']), ('auth_asym_id', spec['reference_chain']), ('auth_seq_id', spec['reference_sequence'])])  # 三项共同定位。
                require(not matches, '参考配体有共价连接，不适用当前非共价重对接；请另行核定口袋')  # 不自动换配体。
        reference = _ligand_lines(pdb_path, spec['reference_code'], spec['reference_chain'], spec['reference_sequence'], spec.get('altloc'))  # 定位唯一构象。
        box = _box_from_lines(reference)  # 共晶外包络加5Å。
        ccd = _capture(workflow, folder, f"https://files.rcsb.org/ligands/download/{spec['reference_code']}.cif", target + '_ccd')  # 官方键表与电荷。
        prepared = prepare_reference_ligand(ccd, reference, spec['reference_code'], spec['reference_chain'], spec['reference_sequence'], _meeko_settings())  # 固定重原子坐标并核验拓扑。
        ref_sdf = _write_text(folder / 'receptors' / (target + '_reference.sdf'), prepared['sdf_text'])  # 实验姿势来源。
        ref_pdbqt = _write_text(folder / 'receptors' / (target + '_reference.pdbqt'), prepared['pdbqt_text'], 'ascii')  # 重对接输入。
        result.update(reference_sdf=file_record(workflow.location(spec['study_id']), ref_sdf, 'reference_sdf'), reference_pdbqt=file_record(workflow.location(spec['study_id']), ref_pdbqt, 'reference_pdbqt'))  # 可复算引用。
    else:  # 无参考配体使用已批准预测规则。
        predicted_input = _write_text(folder / 'receptors' / (target + '_p2rank_input.pdb'), protein, 'ascii')  # 预测与准备使用相同链及构象。
        pocket = run_twice(workflow.root / 'environments' / 'p2rank_2.5', predicted_input, folder / (target + '_p2rank'), target, workflow.root)  # 两次原始结果均留存。
        box = pocket['box']  # 不手工抄坐标。
        result['pocket_record'] = file_record(workflow.location(spec['study_id']), folder / (target + '_p2rank') / 'pocket.json', 'predicted_pocket')  # 来源纳入指纹。
    receptor = _prepare_receptor_cli(workflow.root, protein, box, target + '_' + spec['pdb_id'], folder)  # 不调缺失修复参数。
    result.update(box=box, receptor_record=file_record(workflow.location(spec['study_id']), receptor, 'receptor'), structure_inspection=inspection)  # 保存准备输入。
    if spec['pocket'] == 'reference':  # 每个本研究参考配体实际重对接。
        rmsd, output = _current_redock(workflow.root / 'environments' / 'vina_1.2.7' / 'vina_1.2.7_win.exe', receptor, ref_pdbqt, ref_sdf, box, target, folder)  # 固定Vina与Top1RMSD。
        result.update(rmsd=rmsd, redocking_output=file_record(workflow.location(spec['study_id']), output, 'redocking_output'))  # 不是历史RMSD。
        require(rmsd <= 2.0, '本研究Top1重对接RMSD超过2Å，不自动调参')  # 质控失败该受体NA。
    result['status'] = 'ready'  # 通过当前检查才可计算。
    return result  # 后续还需整体配置复核。


def prepare(workflow, request, folder, progress):  # 形成A06_PREP待复核，不进行研究成分对接。
    from docking_ligand import prepare_ligand  # 原始3D身份核查与准备。
    from docking_ligand_flow import check_ligand_coordinates  # 确认未丢重原子。
    plan = read_json(verified_file(workflow.location(request['study_id']), request['plan']))  # 冻结方案。
    software = _software(workflow, folder)  # 固定工具和内核指纹。
    study = workflow.location(request['study_id'])  # 独立研究资料。
    prep = {'schema_version': PREP_SCHEMA, 'study_id': request['study_id'], 'parent_runs': request['parent_runs'], 'plan_record': request['plan'], 'software': software, 'compounds': [], 'receptors': [], 'primary_targets': [], 'strict_qc_passed_targets': [], 'created_at': now()}  # 准备不含结合能。
    selected = workflow.result(workflow.load(request['study_id']), request['parent_runs']['A03_SELECT'])['tables']['selected']  # 成分显示名称从上游取得。
    for spec, source in zip(plan['compounds'], selected):  # 顺序已在保存方案时核对。
        progress('准备成分：' + source['name'])  # 真实进度。
        row = dict(spec, name=source['name'], status='failed', error=spec['reason'])  # 不可计算成分仍在矩阵。
        try:  # 每项结构失败保留，不影响其他对象事实。
            require(spec['status'] == 'use', spec['reason'])  # 未核定形态不计算。
            props = json.loads(_capture(workflow, folder, f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{spec['cid']}/property/InChIKey/JSON", source['compound_id'] + '_properties'))['PropertyTable']['Properties']  # 官方化学身份。
            require(len(props) == 1 and str(props[0]['CID']) == str(spec['cid']), 'PubChem返回身份不唯一一致')  # 不自动换CID。
            sdf = _capture(workflow, folder, f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{spec['cid']}/SDF?record_type=3d", source['compound_id'] + '_3d')  # 官方3D原件。
            value = prepare_ligand(sdf, spec['cid'], props[0]['InChIKey'], _meeko_settings())  # 完整立体身份与形态保持。
            coordinates = check_ligand_coordinates(sdf, value['pdbqt_text'])  # 坐标回指核验。
            sdf_path = _write_text(folder / 'ligands' / (source['compound_id'] + '.sdf'), sdf)  # 来源坐标。
            pdbqt_path = _write_text(folder / 'ligands' / (source['compound_id'] + '.pdbqt'), value['pdbqt_text'], 'ascii')  # 准备输入。
            row.update(status='ready', identity=value['identity'], validation=coordinates, sdf_record=file_record(study, sdf_path, 'ligand_sdf'), ligand_record=file_record(study, pdbqt_path, 'ligand'), error='')  # 成功不自动批准。
        except Exception as error:  # 身份和网络失败如实存档。
            row['error'] = str(error)  # NA原因。
        prep['compounds'].append(row)  # 失败成分不会消失。
    from docking_generic_prep import _screen_rows  # 同一PPI窗口规则。
    ppi = workflow.result(workflow.load(request['study_id']), request['parent_runs']['A04'])  # 本研究PPI。
    screen = _screen_rows(ppi['tables']['round1'], {})  # 不依赖历史证据排名。
    for spec, source in zip(plan['receptors'], screen):  # 全窗口与并列保留。
        progress('准备受体并核对当前重对接：' + spec['target'])  # 每项单独进度。
        row = dict(spec, study_id=request['study_id'], status='failed', rmsd=None, box=None, error='')  # 初始化失败态。
        try:  # 准备失败保留全部来源日志。
            row = _prepare_receptor(workflow, folder, row, source['target_id'])  # 官方身份、结构、盒子和RMSD。
        except Exception as error:  # 不修改科学参数重试。
            row.update(status='failed', error=str(error), box=None, rmsd=None)  # 无合格结果不伪造盒子。
        row['ppi_rank'] = source['ppi_order']  # 使用本研究PPI名次。
        row['target_id'] = source['target_id']  # 原始成分—靶点关系使用稳定HGNC身份匹配。
        prep['receptors'].append(row)  # 高位失败不会被删除。
    prep['strict_qc_passed_targets'] = [row['target'] for row in prep['receptors'] if row['status'] == 'ready' and row['scope'] == 'strict' and row['rmsd'] is not None and row['rmsd'] <= 2.0]  # 真正通过者。
    prep['primary_targets'] = prep['strict_qc_passed_targets'][:5]  # 按PPI原序选择主要五项。
    prep['files'] = [file_record(study, path, 'preparation_evidence') for path in sorted(folder.rglob('*')) if path.is_file() and path.name not in ('status.json', 'worker_stdout.txt', 'worker_stderr.txt', 'request.json')]  # 只固定已经完成且不再写入的证据。
    write_json(folder / 'preparation.json', prep)  # 即使不足五项也留存计算事实。
    require(len(prep['primary_targets']) == 5, '严格质控通过受体不足五个；准备事实已保留，请讨论是否检查第11—15位，不自动补齐')  # 不发布不满足主结果的准备。
    assert_current(workflow, request)  # 发布前检查上游。
    reference = file_record(study, folder / 'preparation.json', 'automation_preparation')  # 固定准备产物。
    purpose = workflow.result(workflow.load(request['study_id']), request['parent_runs']['A00'])['summary'].get('analysis_purpose', 'formal_research')  # 从登记传播真实用途。
    diagnostics = [{'受体': row['target'], 'PDB': row.get('pdb_id', ''), 'RMSD_A': row['rmsd'], '诊断通过': row['target'] in prep['strict_qc_passed_targets'], '主要结果': row['target'] in prep['primary_targets'], '质控状态': row['status'], '结构限制': row['reason'], '失败原因': row['error']} for row in prep['receptors']]  # 突出必审问题。
    result = _publish(workflow, request, 'A06_PREP', {'automation_preparation': reference, 'automation_plan': request['plan']}, {'schema_version': PREP_SCHEMA, 'mode': 'automation_preparation', 'analysis_purpose': purpose}, '按用户结构方案自动准备并完成当前研究重对接，等待对象与配置复核', {'analysis_purpose': purpose, '受体数': len(prep['receptors']), '成分数': len(prep['compounds']), '计划组合数': len(prep['receptors']) * len(prep['compounds']), '主要受体数': 5, 'handoff_blocked': False}, {'receptor_diagnostics': diagnostics}, ['请重点确认结构限制、配体形态及NA原因；准备通过后才运行研究成分对接。'], 'success', sources=[reference, request['plan']], attachments=prep['files'])  # 发布与科学输入核验一次原子完成。
    return {'message': 'A06对象及配置已生成，请复核；通过并继续后自动对接或复用。', 'run_id': result['run_id']}  # 停在人工关口。


def pair_key(prep, receptor, compound):  # 按全部科学输入精确判断组合复用。
    return fingerprint({'contract': 'A06.pair.cache.1', 'receptor': receptor['receptor_record']['sha256'], 'ligand': compound['ligand_record']['sha256'], 'sdf_identity': compound['identity'], 'pdb': receptor['pdb_id'], 'chains': receptor['chains'], 'box': receptor['box'], 'parameters': VINA, 'software': prep['software']})  # 不只按名称或分数比较。


def _reuse(workflow, key, study, destination):  # 只复用已登记完整成功组合，失败不缓存。
    index_path = workflow.root / 'environments' / 'A06_pair_cache.json'  # 明确内容寻址索引。
    if not index_path.exists():  # 尚无通用缓存。
        return None  # 真正计算。
    record = read_json(index_path).get('pairs', {}).get(key)  # 不扫描旧目录猜结果。
    if not record:  # 不同输入无缓存。
        return None  # 执行新组合。
    source = read_json(verified_file(workflow.root, record))  # 缓存来源指纹必须完整。
    require(source['key'] == key, '缓存组合指纹不一致')  # 损坏不能静默使用。
    row = dict(source['row'])  # 原评分保持不变。
    for field, value in list(row.items()):  # 全部结构、姿势与命令归档。
        if field.endswith('_record') and isinstance(value, dict):  # 只复制明确文件引用。
            path = verified_file(workflow.root, value)  # 核对原字节。
            target = destination / (field + '_' + path.name)  # 稳定角色前缀防同名冲突。
            shutil.copy2(path, target)  # 同源复制而非重新计算。
            row[field] = file_record(study, target, value['role'])  # 新研究独立引用。
    row['reuse_provenance'] = {'cache_record': record, 'original_study': source['study_id'], 'original_calculated_at': source['calculated_at'], 'new_vina_calculation': False}  # 不把复用日期冒充原计算日期。
    return row  # 姿势还需当前盒子复核。


def _check_pose(receptor_path, ligand_path, sdf_heavy, box, all_path):  # 研究姿势与重对接共用Top1规则。
    from docking_formal import _input_atoms, _pose_identity  # 原子类型和序号一致。
    from docking_redocking import _poses, _inside_box, _minimum_receptor_distance  # 固定盒内与距离检查。
    poses = _poses(all_path.read_text('ascii'))  # 保存所有模式原件。
    require(poses and poses[0]['mode'] == 1, '输出缺少Top1姿势')  # 不取最低有效模式替代。
    identity = _pose_identity(poses[0], _input_atoms(ligand_path.read_text('ascii')), sdf_heavy)  # 真实SDF重原子数。
    inside = _inside_box(poses[0], {'center_angstrom': box['center'], 'size_angstrom': box['size']})  # 当前搜索盒。
    require(identity['passed'] and inside['passed'], 'Top1未通过身份或盒内检查，保留NA，不换第二姿势')  # 不补造有效结果。
    return poses[0], len(poses), _minimum_receptor_distance(receptor_path.read_text('ascii'), poses[0])  # 报告原评分。


def execute(workflow, request, folder, progress):  # 在准备已批准后运行动态全矩阵。
    from docking_contract import validate_generic_result, receptor_limitation_table, receptor_setup_table, score_matrix_table  # 同一事实包生成所有表。
    from docking_dynamic_heatmap import export  # 既定红蓝动态热图。
    study = workflow.location(request['study_id'])  # 当前独立研究。
    manifest = workflow.load(request['study_id'])  # 准备批准来自真实记录。
    prep_run = workflow.run(manifest, request['parent_runs']['A06_PREP'])  # 精确准备版本。
    require(prep_run['config'].get('schema_version') == PREP_SCHEMA, '历史准备版本保持原入口；请生成通用自动化准备后再运行')  # 不默默迁移历史病例。
    prep = read_json(verified_file(study, prep_run['inputs']['automation_preparation']))  # 准备事实。
    for record in prep['files']:  # 所有来源及结构仍完整。
        verified_file(study, record)  # 修改任一文件即暂停。
    software = _software(workflow, folder)  # 当前执行环境再次核验。
    require(software == prep['software'], '准备与执行软件或内核不同，请重新准备')  # 输入和算法必须一致。
    planned, completed, failed, cache_entries = [], [], [], {}  # 全部组合固定覆盖。
    formula_evidence = workflow.result(manifest, request['parent_runs']['A03'])['tables'].get('formula_evidence', [])  # 不把矩阵计算等同于原数据库已支持的关系。
    generic = {'contract_version': 'A06.generic.result.2', 'analysis_purpose': prep_run['config']['analysis_purpose'], 'compounds': [{'compound_id': row['compound_id'], 'name': row['name'], 'pubchem_cid': row.get('cid', '')} for row in prep['compounds']], 'receptors': [], 'primary_targets': prep['primary_targets'], 'strict_qc_passed_targets': prep['strict_qc_passed_targets'], 'vina_parameters': VINA, 'automatic_parameter_tuning': False, 'planned_pairs': planned, 'completed_pairs': completed, 'failed_pairs': failed}  # 动态合同与旧结果兼容。
    for receptor in prep['receptors']:  # 按PPI顺序生成受体事实。
        ready = receptor['status'] == 'ready'  # 判断实际准备成功。
        rmsd = receptor['rmsd'] if ready else None  # 失败无可报告RMSD。
        generic['receptors'].append({'target': receptor['target'], 'pdb_id': receptor.get('pdb_id', ''), 'chains': receptor.get('chains', []), 'reference_ligand': (receptor.get('reference_code', '') + ' ' + receptor.get('reference_chain', '') + ':' + str(receptor.get('reference_sequence', ''))) if receptor.get('pocket') == 'reference' else '无参考配体', 'center': receptor['box']['center'] if ready else None, 'size': receptor['box']['size'] if ready else None, 'redocking_rmsd_A': rmsd, 'qc_status': '严格质控通过' if receptor['target'] in prep['strict_qc_passed_targets'] else ('探索性可运行' if ready else '失败，组合为NA'), 'ppi_rank': receptor['ppi_rank'], 'pocket_basis': '共晶参考配体外包络各方向外扩5Å' if receptor.get('pocket') == 'reference' else 'P2Rank 2.5首位口袋相邻重原子外包络各方向外扩5Å', 'structure_limitation': receptor['reason'] + ('；' + receptor['error'] if receptor['error'] else ''), 'interpretation_scope': '主要结果' if receptor['target'] in prep['primary_targets'] else ('扩展或探索线索' if ready else '不得解释结合能'), 'primary_result': receptor['target'] in prep['primary_targets'], 'redocking_status': ('passed' if rmsd is not None else 'not_applicable_no_reference_ligand') if ready else 'failed_not_computable'})  # 热图不显示ABC。
        for compound in prep['compounds']:  # 全笛卡尔积。
            progress('对接或精确复用：' + receptor['target'] + ' × ' + compound['name'])  # 用户看到具体组合。
            refs = sorted({row['source_ref'] for row in formula_evidence if row['compound_id'] == compound['compound_id'] and row['target_id'] == receptor['target_id']})  # 精确回指本研究原关系。
            pair = {'target': receptor['target'], 'compound_id': compound['compound_id'], 'compound_name': compound['name'], 'relation': 'upstream_record' if refs else 'exploratory', 'source_refs': refs}  # 无原始关系明确标作探索。
            planned.append(pair)  # 失败对象也计计划。
            if not ready or compound['status'] != 'ready':  # 准备失败不运行Vina。
                failed.append(dict(pair, reason=receptor['error'] or compound['error']))  # 不填零。
                continue  # 保留NA。
            pair_folder = folder / 'pairs' / (receptor['target'] + '_' + compound['compound_id'])  # 每组独立路径。
            pair_folder.mkdir(parents=True, exist_ok=False)  # 不覆盖。
            key = pair_key(prep, receptor, compound)  # 精确复用键。
            try:  # 任何复用文件或姿势失败都保留诊断。
                receptor_path = verified_file(study, receptor['receptor_record'])  # 当前受体。
                ligand_path = verified_file(study, compound['ligand_record'])  # 当前配体。
                row = _reuse(workflow, key, study, pair_folder)  # 优先完整成功缓存。
                if row is None:  # 未匹配组合真实计算。
                    output = pair_folder / 'all_poses.pdbqt'  # 全部模式原件。
                    command = _vina_arguments(workflow.root / 'environments' / 'vina_1.2.7' / 'vina_1.2.7_win.exe', receptor_path, ligand_path, receptor['box'], output)  # 固定参数。
                    command_path = pair_folder / 'command.json'  # 可复算命令。
                    write_json(command_path, {'parameters': VINA, 'search_box': receptor['box'], 'receptor': receptor['receptor_record'], 'ligand': compound['ligand_record'], 'arguments': command, 'calculated_at': now(), 'pair_key': key})  # 保存真实输入。
                    process = _run(command, pair_folder, pair_folder / 'stdout.txt', pair_folder / 'stderr.txt')  # 实际执行。
                    require(process.returncode == 0 and output.is_file(), 'Vina执行失败：' + str(process.returncode))  # 不读残缺输出。
                    pose, count, distance = _check_pose(receptor_path, ligand_path, compound['identity']['heavy_atom_count'], receptor['box'], output)  # 只用Top1。
                    selected = _write_text(pair_folder / 'selected_top1_pose.pdbqt', output.read_text('ascii').split('ENDMDL', 1)[0] + 'ENDMDL\n', 'ascii')  # 同源固定姿势。
                    row = dict(pair, score_kcal_mol=pose['score_kcal_mol'], selected_mode=1, pose_count=count, minimum_receptor_distance_A=distance, pose_record=file_record(study, selected, 'selected_pose'), all_poses_record=file_record(study, output, 'all_poses'), receptor_record=receptor['receptor_record'], ligand_record=compound['ligand_record'], ligand_sdf_record=compound['sdf_record'], command_record=file_record(study, command_path, 'command'), log_record=file_record(study, pair_folder / 'stdout.txt', 'log'), calculated_at=now())  # 所有角色齐备。
                else:  # 复用仍须核对当前姿势与盒子。
                    _check_pose(receptor_path, ligand_path, compound['identity']['heavy_atom_count'], receptor['box'], verified_file(study, row['all_poses_record']))  # 不只信缓存分数。
                    row.update(pair)  # 显示名与本研究一致，原评分不变。
                completed.append(row)  # 完成事实。
                cache_row = dict(row)  # 缓存把引用统一为项目相对位置。
                for field, record in row.items():  # 所有文件来源均验证。
                    if field.endswith('_record') and isinstance(record, dict):  # 只处理文件角色。
                        cache_row[field] = file_record(workflow.root, verified_file(study, record), record['role'])  # 跨研究精确复用。
                cache_path = pair_folder / 'cache_entry.json'  # 缓存只指向不可变成功事实。
                write_json(cache_path, {'key': key, 'study_id': request['study_id'], 'calculated_at': row.get('calculated_at', row.get('reuse_provenance', {}).get('original_calculated_at')), 'row': cache_row})  # 原计算时间保留。
                cache_entries[key] = file_record(workflow.root, cache_path, 'pair_cache')  # 完成后统一登记。
            except Exception as error:  # NA保留原输出和失败原因。
                failed.append(dict(pair, reason=str(error)))  # 不静默重新计算或换模式。
    require(completed, '本次没有通过姿势核验的组合；事实与日志保留，不发布伪空结果')  # 全失败不同于无对象。
    generic['outcome'] = 'partial' if failed else 'success'  # 描述真实覆盖。
    reused = sum('reuse_provenance' in row for row in completed)  # 统计复用与新计算，不混淆。
    if reused:  # 只有真实复用才写复用说明。
        generic['reuse_provenance'] = {'reused_pair_count': reused, 'newly_calculated_pair_count': len(completed) - reused, 'new_compound_docking_executed': len(completed) > reused, 'source_boundary': '本研究采用A02已复核的实际数据库资料；评分复用只适用于科学输入与工具完全一致的组合。'}  # 两报告读取真实混合来源。
    generic['evidence_files'] = [file_record(study, path, 'execution_evidence') for path in sorted(folder.rglob('*')) if path.is_file() and path.name not in ('status.json', 'worker_stdout.txt', 'worker_stderr.txt', 'request.json')]  # 固定执行资料。
    write_json(folder / 'generic_docking.json', generic)  # 候选事实不可变。
    validate_generic_result(generic)  # 核对数量、失败与受体全覆盖。
    progress('生成同源动态热图并发布待复核结果')  # 实际执行进度。
    heatmap = export(folder / 'generic_docking.json', folder / 'figures', 'A06_结合能热图')  # 不使用日期猜图。
    assert_current(workflow, request)  # 上游变化则不发布。
    generic_reference = file_record(study, folder / 'generic_docking.json', 'generic_docking_candidate')  # 唯一数据来源。
    metadata_path = folder / 'figures' / 'A06_结合能热图.json'  # 导出器固定名称。
    heatmap_reference = file_record(study, metadata_path, 'heatmap_metadata')  # 图件与事实绑定。
    metadata = read_json(metadata_path)  # SVG和PNG同源。
    figures = [file_record(study, metadata_path.parent / item['path'], item['role']) for item in metadata['files']]  # 全图指纹。
    summary = {'analysis_purpose': generic['analysis_purpose'], '计划组合数': len(planned), '成功组合数': len(completed), '失败组合数': len(failed), '主要受体数': 5, '复用组合数': sum('reuse_provenance' in row for row in completed), 'handoff_blocked': False}  # 数量由实际明细生成。
    result = _publish(workflow, request, 'A06', {'generic_candidate': generic_reference, 'heatmap_metadata': heatmap_reference}, {'schema_version': 'A06.formal.config.3', 'mode': 'automation_dynamic', 'analysis_purpose': generic['analysis_purpose'], 'vina_parameters': VINA, 'automatic_tuning_performed': False}, '已复核对象与配置后自动对接或精确复用，等待结果复核', summary, {'generic_docking': generic, 'receptor_setup': receptor_setup_table(generic), 'receptor_limitations': receptor_limitation_table(generic), 'score_matrix': score_matrix_table(generic)}, ['主要结论只使用五个严格质控受体；失败保留NA，评分不等同于实验效果。'], generic['outcome'], sources=[generic_reference], figures=figures, attachments=[heatmap_reference] + generic['evidence_files'])  # 网页、热图、报告共用事实包。
    with write_lock(workflow.root):  # 缓存索引只登记成功完整组合。
        cache_path = workflow.root / 'environments' / 'A06_pair_cache.json'  # 唯一复用索引。
        cache = read_json(cache_path) if cache_path.exists() else {'schema_version': 'A06.pair.cache.index.1', 'pairs': {}}  # 首次建立。
        cache['pairs'].update(cache_entries)  # 其他研究键保留。
        write_json(cache_path, cache, replace=True)  # 原子保存索引。
    return {'message': 'A06矩阵和热图已生成，请复核；通过并继续后生成任务包与双报告。', 'run_id': result['run_id']}  # 停在结果关口。


def deliver(workflow, request, folder, progress):  # A06通过后自动生成任务包并接入双报告。
    from docking_task_package_v2 import build  # 通用PyMOL固定姿势任务包。
    from report_dispatch import run_reports, selected_record  # 通用报告事实包。
    study = workflow.location(request['study_id'])  # 独立归档。
    plan = read_json(verified_file(study, request['plan']))  # 总控明确任务编号及软件位置。
    a06_id = request['parent_runs']['A06']  # 当前已通过结果。
    generic = workflow.result(workflow.load(request['study_id']), a06_id)['tables']['generic_docking']  # 动态对象事实。
    progress('制作固定姿势PyMOL文件与可复算任务包')  # 不重新对接。
    from docking_task_package_v2 import _safe_name  # 沿用既定任务包命名。
    a00 = workflow.result(workflow.load(request['study_id']), request['parent_runs']['A00'])['summary']  # 名称来自已复核登记。
    name = f"{_safe_name(plan['package_id'])}_{_safe_name(a00['formula'])}_{_safe_name(a00['disease'])}_{len(generic['planned_pairs'])}pairs"  # 不扫描目录猜任务编号。
    package = study / 'task_packages' / name  # 最终位置唯一明确。
    if not package.exists():  # 首次制作先在当前任务内完成，半包不发布。
        draft = build(workflow.root, request['study_id'], a06_id, plan['package_id'], plan['pymol_executable'], output_parent=folder / 'task_package_draft')  # 失败草案归于任务历史。
        assert_current(workflow, request)  # 长PyMOL导出后检查上游。
        with write_lock(workflow.root):  # 只在完整后移入最终任务目录。
            require(not package.exists(), '任务编号已被另一个交付使用，请核对')  # 不覆盖同名历史。
            package.parent.mkdir(parents=True, exist_ok=True)  # 固定研究任务包目录。
            draft.rename(package)  # 同盘原子移动完整包。
    index = read_json(package / 'package_index.json')  # 最后索引表示任务包完整。
    require(index['study_id'] == request['study_id'] and index['source_a06_run'] == a06_id and index['package_id'] == plan['package_id'], '任务编号已用于其他A06版本，请明确新的任务编号')  # 重试只复用完全相同交付。
    for record in index['files']:  # 打包前校验每个文件。
        verified_file(package, record)  # 残缺包不得传报告。
    archive = package.with_suffix('.zip')  # 同名ZIP表示同一稳定任务包。
    if not archive.exists():  # 重试沿用已完整包，不重新制作或覆盖。
        draft_archive = folder / (name + '.zip')  # ZIP草案也留在当前任务。
        with zipfile.ZipFile(draft_archive, 'x', zipfile.ZIP_DEFLATED) as stream:  # 新建完整压缩包。
            for path in sorted(package.rglob('*')):  # 确定性顺序。
                if path.is_file():  # 仅打包实际产物。
                    stream.write(path, package.name + '/' + path.relative_to(package).as_posix())  # 文件保留同一根目录。
        with zipfile.ZipFile(draft_archive) as stream:  # 完整后才发布。
            require(stream.testzip() is None, '任务ZIP草案校验失败')  # 失败不覆盖成品。
        draft_archive.rename(archive)  # 原子发布完整ZIP。
    with zipfile.ZipFile(archive) as stream:  # 交付前完整性检查。
        require(stream.testzip() is None, '任务ZIP校验失败')  # 不发布损坏ZIP。
        expected = {package.name + '/' + path.relative_to(package).as_posix(): path for path in package.rglob('*') if path.is_file()}  # 全部交付文件固定集合。
        require(set(stream.namelist()) == set(expected) and all(stream.read(name) == path.read_bytes() for name, path in expected.items()), '任务ZIP与同源文件不一致')  # 旧ZIP不得冒充新包。
    task = {'index': file_record(study, package / 'package_index.json', 'docking_task_package_index'), 'archive': file_record(study, archive, 'docking_task_package_archive')}  # 报告强绑定来源。
    write_json(folder / 'task_package.json', task)  # 重试与追溯的完成记录。
    assert_current(workflow, request)  # 长导出期间上游变化不得发报告。
    progress('生成专业详细版和临床简略版报告')  # 实際同源报告。
    current = workflow.load(request['study_id'])  # 读取报告当前指针。
    previous = current['current'].get('A07')  # 后台完成凭证写入前意外退出时允许安全重试。
    if previous and workflow.active(current, previous):  # 已发布报告只按明确运行和输入判断复用。
        prior_run = workflow.run(current, previous)  # 读取不可变运行。
        if prior_run['inputs'].get('task_package_index') == task['index'] and prior_run['inputs'].get('task_package_archive') == task['archive'] and prior_run['inputs'].get('selected_pathway_metadata') == selected_record(workflow, current) and all(current['current'].get(key) == value for key, value in prior_run['parent_runs'].items()):  # 不同上游或任务包不能沿用。
            return {'message': '同一任务包与A07双报告已生成，请完成最后结论复核。', 'run_id': previous, 'task_package': task}  # 不生成重复报告版本。
    result = run_reports(workflow, request['study_id'], current['current'].get('A07', ''), 'A06复核通过后自动汇总任务包、热图和双报告', task_package=task)  # 不自动批准最终结论。
    return {'message': '任务包与A07双报告已生成，请完成最后结论复核。', 'run_id': result['run_id'], 'task_package': task}  # 结论仍归用户确认。
