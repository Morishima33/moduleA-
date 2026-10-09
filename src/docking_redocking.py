# A06参考配体重对接诊断；只执行已授权的三组诊断，不运行正式成分对接。
from copy import deepcopy  # 新预览从旧预览复制，历史文件保持不变。
import io  # 从内存字节读取中文路径下的SDF。
import json  # 保存可复核的命令参数和运行记录。
import math  # 检查评分、坐标和RMSD是否为有限数值。
from pathlib import Path  # 安全定位项目、研究与运行目录。
import subprocess  # 以参数列表调用已固定版本的Vina。
from contracts import require  # 使用项目统一阻断规则。
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock  # 复用不可覆盖与指纹校验。


def _index_map(pdbqt_text):  # 读取Meeko保存的“原始SDF原子→PDBQT原子”映射。
    tokens = []  # 多行映射先合并再成对解析。
    for line in pdbqt_text.splitlines():  # 只读取明确标记的映射行。
        if line.startswith('REMARK INDEX MAP '):  # 其他REMARK不参与身份映射。
            tokens.extend(line.split()[3:])  # 去掉固定行首文字。
    require(tokens and len(tokens) % 2 == 0, '参考配体PDBQT缺少完整原子回指')  # 缺失映射不能计算RMSD。
    mapping = {int(tokens[index]): int(tokens[index + 1]) for index in range(0, len(tokens), 2)}  # 键值均使用文件中的一基编号。
    require(len(mapping) * 2 == len(tokens), '参考配体原子回指含重复来源编号')  # 不接受覆盖后的假完整映射。
    return mapping  # 返回来源原子到姿势原子的唯一关系。


def _poses(pdbqt_text):  # 解析Vina输出的全部模式、评分和坐标。
    poses = []  # 每个MODEL形成一条独立记录。
    current = None  # MODEL之外的说明不属于某个姿势。
    for line in pdbqt_text.splitlines():  # 保留Vina输出顺序。
        if line.startswith('MODEL '):  # 新模式开始。
            require(current is None, 'Vina输出MODEL嵌套错误')  # 损坏文件不能继续。
            current = {'mode': int(line.split()[1]), 'score_kcal_mol': None, 'atoms': {}}  # 模式号来自原文。
        elif current is not None and line.startswith('REMARK VINA RESULT:'):  # 读取本模式原始Vina评分。
            current['score_kcal_mol'] = float(line.split()[3])  # 第一项数值是affinity。
        elif current is not None and line.startswith(('ATOM  ', 'HETATM')):  # 读取姿势内实际原子坐标。
            serial = int(line[6:11])  # PDBQT固定列提供原子序号。
            atom_type = line[77:].strip().split()[0] if line[77:].strip() else ''  # 末列是AutoDock原子类型。
            current['atoms'][serial] = {'x': float(line[30:38]), 'y': float(line[38:46]), 'z': float(line[46:54]), 'atom_type': atom_type}  # 坐标保持Å单位。
        elif current is not None and line.startswith('ENDMDL'):  # 当前姿势结束。
            require(current['score_kcal_mol'] is not None and current['atoms'], 'Vina姿势缺少评分或原子')  # 空模式不是有效结果。
            require(math.isfinite(current['score_kcal_mol']) and all(math.isfinite(atom[key]) for atom in current['atoms'].values() for key in ('x', 'y', 'z')), 'Vina姿势含无效数值')  # NaN和无穷均阻断。
            poses.append(current)  # 结束后才加入完整姿势。
            current = None  # 等待下一个MODEL。
    require(current is None and poses, 'Vina输出没有完整姿势')  # 截断文件不能作为结果。
    require([pose['mode'] for pose in poses] == list(range(1, len(poses) + 1)), 'Vina模式号不连续')  # 明确发现缺页或重排。
    return poses  # 返回全部模式供完整留存。


def _reference_molecule(sdf_bytes):  # 读取唯一的三维参考配体并保留原始原子顺序。
    from rdkit import Chem  # 固定项目环境提供RDKit。
    molecules = list(Chem.ForwardSDMolSupplier(io.BytesIO(sdf_bytes), removeHs=False, sanitize=True, strictParsing=True))  # 避免RDKit对中文路径的兼容问题。
    require(len(molecules) == 1 and molecules[0] is not None, '参考配体SDF不是一个完整结构')  # 不静默取第一条。
    molecule = molecules[0]  # 唯一结构可用于后续映射。
    require(molecule.GetNumConformers() == 1 and molecule.GetConformer().Is3D(), '参考配体SDF缺少唯一三维坐标')  # 二维结构不能作为重对接参照。
    return molecule  # 返回带氢和实验坐标的原分子。


def symmetry_rmsd(sdf_bytes, input_pdbqt_text, top_pose):  # 计算不做刚体拟合的对称感知重原子RMSD。
    from rdkit import Chem  # RDKit仅用于拓扑与对称映射枚举。
    molecule = _reference_molecule(sdf_bytes)  # 使用晶体参考坐标。
    mapping = _index_map(input_pdbqt_text)  # 姿势坐标必须回指到同一SDF原子。
    heavy_original = [atom.GetIdx() for atom in molecule.GetAtoms() if atom.GetAtomicNum() > 1]  # 氢和Meeko伪原子不计入RMSD。
    require(len(heavy_original) == molecule.GetNumHeavyAtoms(), '参考配体重原子计数不一致')  # 防止异常元素被遗漏。
    require(all(index + 1 in mapping and mapping[index + 1] in top_pose['atoms'] for index in heavy_original), 'top-1姿势缺少参考重原子回指')  # 每个真实重原子均须有坐标。
    heavy = Chem.RemoveHs(molecule)  # 对称映射只在真实重原子拓扑中枚举。
    matches = heavy.GetSubstructMatches(heavy, uniquify=False, useChirality=True, maxMatches=1000000)  # 保留手性并枚举分子自同构。
    require(matches, '无法建立参考配体对称映射')  # 没有映射不能退化为原子顺序比较。
    conformer = molecule.GetConformer()  # 读取实验三维坐标。
    rmsd_values = []  # 每个合法自同构产生一个直接坐标RMSD。
    for match in matches:  # 仅改变等价原子配对，不平移或旋转对接姿势。
        squared = 0.0  # 累计三维距离平方。
        for query_index, target_index in enumerate(match):  # query索引对应姿势来源重原子顺序。
            pose_atom = top_pose['atoms'][mapping[heavy_original[query_index] + 1]]  # 取得本姿势的实际坐标。
            reference_atom = conformer.GetAtomPosition(heavy_original[target_index])  # 取得对称映射后的晶体坐标。
            squared += (pose_atom['x'] - reference_atom.x) ** 2 + (pose_atom['y'] - reference_atom.y) ** 2 + (pose_atom['z'] - reference_atom.z) ** 2  # 不进行最佳拟合。
        rmsd_values.append(math.sqrt(squared / len(heavy_original)))  # 按重原子数求均方根。
    best = min(rmsd_values)  # 采用所有合法对称配对中的最小值。
    require(math.isfinite(best), '重对接RMSD不是有限值')  # 无效诊断不能放行。
    return {'rmsd_angstrom': best, 'heavy_atom_count': len(heavy_original), 'symmetry_mapping_count': len(matches), 'alignment_performed': False, 'hydrogen_included': False, 'pseudoatom_included': False}  # 明确指标口径。


def _inside_box(pose, search_box):  # 检查姿势全部输出原子是否仍在已审核搜索盒内。
    center = search_box['center_angstrom']  # 使用候选包内固定中心。
    size = search_box['size_angstrom']  # 使用候选包内固定尺寸。
    lower = [center[index] - size[index] / 2 for index in range(3)]  # 计算各轴下界。
    upper = [center[index] + size[index] / 2 for index in range(3)]  # 计算各轴上界。
    outside = []  # 逐个记录越界原子，不能只给布尔值。
    for serial, atom in pose['atoms'].items():  # 包括氢和G0伪原子，符合“全部配体原子”的批准规则。
        coordinates = [atom['x'], atom['y'], atom['z']]  # 固定XYZ顺序。
        if any(coordinates[index] < lower[index] or coordinates[index] > upper[index] for index in range(3)):  # 不引入未批准的宽容距离。
            outside.append(serial)  # 保存原子序号便于复核。
    return {'passed': not outside, 'outside_atom_serials': outside, 'lower_angstrom': lower, 'upper_angstrom': upper}  # 盒子事实完整留存。


def _minimum_receptor_distance(receptor_text, pose):  # 报告姿势与受体的最近真实重原子距离。
    receptor = []  # 收集受体重原子坐标。
    for line in receptor_text.splitlines():  # PDBQT固定列读取。
        if line.startswith(('ATOM  ', 'HETATM')):  # 只处理坐标记录。
            atom_type = line[77:].strip().split()[0] if line[77:].strip() else ''  # 末列区分氢。
            if atom_type not in ('H', 'HD', 'G0'):  # 氢和伪原子不参与重原子距离。
                receptor.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))  # 保存Å坐标。
    ligand = [(atom['x'], atom['y'], atom['z']) for atom in pose['atoms'].values() if atom['atom_type'] not in ('H', 'HD', 'G0')]  # 姿势同样只取真实重原子。
    require(receptor and ligand, '受体或姿势缺少可计算的真实重原子')  # 空集合不能报告距离。
    distance = min(math.dist(receptor_atom, ligand_atom) for receptor_atom in receptor for ligand_atom in ligand)  # 完整两两比较规模可控。
    require(math.isfinite(distance), '最近重原子距离不是有限值')  # 异常数值阻断。
    return distance  # 首版只报告，不自设通过阈值。


def _record_by_suffix(records, suffix):  # 从已登记文件中精确选一个后缀对象。
    matches = [record for record in records if record['path'].endswith(suffix)]  # 不扫描目录猜最新版。
    require(len(matches) == 1, '对接输入文件无法唯一定位：' + suffix)  # 缺失或重复均停止。
    return matches[0]  # 返回带指纹的明确记录。


def _write_text(path, value):  # 保存一次性文本日志且禁止覆盖。
    path.parent.mkdir(parents=True, exist_ok=True)  # 新运行目录按需建立。
    with path.open('x', encoding='utf-8', newline='') as stream:  # 历史日志不可重写。
        stream.write(value)  # 原样保存标准输出或错误输出。


def _validate_authorization(root, study_id, package_reference, authorization_reference, package):  # 将执行权绑定到准确候选包。
    authorization = read_json(verified_file(root, authorization_reference))  # 先校验授权文件自身指纹。
    require(authorization.get('schema_version') == 'A06.prep.execution.authorization.1' and authorization.get('status') == 'user_approved', 'A06_PREP总体授权记录无效')  # 仅接受当前格式的明确批准。
    require(authorization.get('study_id') == study_id and authorization.get('preparation_package') == package_reference, 'A06_PREP授权未绑定本研究或当前候选包')  # 不跨研究或跨版本复用。
    require(authorization.get('preparation_package_overall_review_approved') is True, 'A06_PREP候选包尚未完成总体复核')  # 先总体复核再诊断。
    require(authorization.get('redocking_execution_authorized') is True and authorization.get('authorized_diagnostic_count') == 3, '未授权执行三次参考配体重对接')  # 数量必须恰好三次。
    require(authorization.get('formal_docking_authorized') is False, '本入口不得夹带正式15组对接授权')  # 诊断与正式执行分开。
    require(authorization.get('parent_runs') == package.get('parent_runs'), '授权上游与候选包不一致')  # 上游版本变化必须重审。
    return authorization  # 返回供结果引用的已验证授权。


def run_redocking(root, study_id, package_reference, authorization_reference):  # 执行三组独立诊断并建立不可覆盖结果包。
    root = Path(root).resolve()  # 固定新项目根目录。
    with write_lock(root):  # 授权复核、执行和结果指针在同一写锁内完成。
        from workflow import Workflow  # 延后导入以避免科学子进程启动时循环依赖。
        workflow = Workflow(root)  # 读取统一研究索引和批准状态。
        manifest = workflow.load(study_id)  # 核对真实当前研究。
        package = read_json(verified_file(root, package_reference))  # 使用用户刚复核的准确候选包。
        require(package.get('schema_version') == 'A06.preparation.package.1' and package.get('study_id') == study_id, 'A06_PREP候选包身份或格式不符')  # 防止跨研究输入。
        require(package.get('status') == 'draft_not_reviewable' and package.get('published') is False and package.get('vina_invoked') is False, '候选包状态已改变，不能重复执行')  # 历史候选不重复运行。
        require(package.get('counts', {}).get('redocking_planned') == 3 and package.get('counts', {}).get('redocking_completed') == 0, '重对接计划数量或状态不符')  # 仅接受完整未运行计划。
        require(package.get('formal_docking_plan') and all(row.get('status') == 'not_run' and row.get('score_kcal_mol') is None for row in package['formal_docking_plan']), '候选包混入正式对接结果')  # 15组仍须完全未运行。
        for module, run_id in package['parent_runs'].items():  # 上游必须仍是当前已批准版本。
            require(manifest['current'].get(module) == run_id and workflow.approved(manifest, run_id), 'A06_PREP上游已变化或失效：' + module)  # 旧候选不能继续执行。
        _validate_authorization(root, study_id, package_reference, authorization_reference, package)  # 核验对话授权的机器记录。
        environment_record = next(record for record in package['evidence'] if record.get('role') == 'vina_environment')  # 候选包证据清单固定Vina环境记录。
        environment = read_json(verified_file(root, environment_record))  # 读取实际版本和可执行文件指纹。
        executable_record = next(record for record in package['evidence'] if record.get('role') == 'vina_executable')  # 必须来自包内证据清单。
        executable = verified_file(root, executable_record)  # 每次执行前重新校验二进制。
        require(environment.get('requested_release') == '1.2.7' and environment.get('sha256') == executable_record['sha256'], 'Vina版本或二进制指纹与候选包不一致')  # 不静默换程序。
        config_data = read_json(verified_file(root, package['config']))  # 读取候选包的固定参数来源。
        vina_parameters = config_data['vina_parameters']  # 不从Vina默认值补参数。
        require(vina_parameters == {'scoring': 'vina', 'exhaustiveness': 8, 'num_modes': 9, 'energy_range_kcal_mol': 3, 'seed': 1}, 'Vina参数不等于已批准配置')  # 参数变化必须重新核验。
        run_id = new_id('run')  # 新诊断获得独立运行编号。
        folder = root / 'studies' / study_id / 'runs' / 'A06_PREP' / run_id  # 结果归入本研究A06准备阶段。
        folder.mkdir(parents=True, exist_ok=False)  # 不与候选包或其他诊断合并。
        run_record = {'schema_version': 'A06.redocking.run.1', 'study_id': study_id, 'run_id': run_id, 'analysis_purpose': package['analysis_purpose'], 'preparation_package': package_reference, 'authorization': authorization_reference, 'parent_runs': package['parent_runs'], 'vina_environment': environment_record, 'vina_executable': executable_record, 'vina_parameters': vina_parameters, 'formal_docking_authorized': False, 'authorized_diagnostic_count': 3, 'created_at': now()}  # 先固定本次输入和边界。
        write_json(folder / 'run.json', run_record)  # 执行前形成不可变运行快照。
        results = []  # 三个受体各自独立判定。
        for plan in package['redocking_plan']:  # 严格使用候选包内三条计划。
            symbol = plan['symbol']  # 文件名前缀只来自已审核靶点符号。
            ligand_code = plan['reference_ligand']['code']  # 参考配体身份来自已审核计划。
            prefix = symbol + '_' + plan['pdb'] + '_' + ligand_code  # 可读文件名不充当身份主键。
            receptor_record = _record_by_suffix(plan['receptor_files'], '_' + plan['pdb'] + '_A.pdbqt')  # 唯一定位受体PDBQT。
            ligand_pdbqt_record = _record_by_suffix(plan['ligand_files'], '_reference.pdbqt')  # 唯一定位参考配体PDBQT。
            ligand_sdf_record = _record_by_suffix(plan['ligand_files'], '_reference.sdf')  # 唯一定位晶体参考SDF。
            receptor_path = verified_file(root, receptor_record)  # 执行前校验受体内容。
            ligand_pdbqt_path = verified_file(root, ligand_pdbqt_record)  # 执行前校验配体输入。
            ligand_sdf_path = verified_file(root, ligand_sdf_record)  # RMSD前校验参考结构。
            output_path = folder / (prefix + '_redocked.pdbqt')  # Vina输出只写入本次新目录。
            arguments = [str(executable), '--receptor', str(receptor_path), '--ligand', str(ligand_pdbqt_path), '--center_x', str(plan['search_box']['center_angstrom'][0]), '--center_y', str(plan['search_box']['center_angstrom'][1]), '--center_z', str(plan['search_box']['center_angstrom'][2]), '--size_x', str(plan['search_box']['size_angstrom'][0]), '--size_y', str(plan['search_box']['size_angstrom'][1]), '--size_z', str(plan['search_box']['size_angstrom'][2]), '--scoring', vina_parameters['scoring'], '--exhaustiveness', str(vina_parameters['exhaustiveness']), '--num_modes', str(vina_parameters['num_modes']), '--energy_range', str(vina_parameters['energy_range_kcal_mol']), '--seed', str(vina_parameters['seed']), '--out', str(output_path)]  # 参数列表避免命令行转义改变值。
            command_record = {'executable': executable_record, 'receptor': receptor_record, 'ligand_pdbqt': ligand_pdbqt_record, 'reference_sdf': ligand_sdf_record, 'search_box': plan['search_box'], 'parameters': vina_parameters, 'arguments_without_absolute_paths': ['vina_1.2.7_win.exe', '--receptor', receptor_record['path'], '--ligand', ligand_pdbqt_record['path'], '--center_x', str(plan['search_box']['center_angstrom'][0]), '--center_y', str(plan['search_box']['center_angstrom'][1]), '--center_z', str(plan['search_box']['center_angstrom'][2]), '--size_x', str(plan['search_box']['size_angstrom'][0]), '--size_y', str(plan['search_box']['size_angstrom'][1]), '--size_z', str(plan['search_box']['size_angstrom'][2]), '--scoring', vina_parameters['scoring'], '--exhaustiveness', str(vina_parameters['exhaustiveness']), '--num_modes', str(vina_parameters['num_modes']), '--energy_range', str(vina_parameters['energy_range_kcal_mol']), '--seed', str(vina_parameters['seed']), '--out', output_path.name]}  # 可迁移命令记录不泄漏电脑路径。
            write_json(folder / (prefix + '_command.json'), command_record)  # 每项输入在执行前固定。
            completed = subprocess.run(arguments, cwd=folder, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)  # 捕获实际退出码和完整日志。
            _write_text(folder / (prefix + '_stdout.txt'), completed.stdout)  # 标准输出单独留存。
            _write_text(folder / (prefix + '_stderr.txt'), completed.stderr)  # 标准错误单独留存。
            process_ok = completed.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0  # 对应批准的进程完整规则。
            if not process_ok:  # 单个受体失败时只暂停该受体。
                results.append({'symbol': symbol, 'target_id': plan['target_id'], 'pdb': plan['pdb'], 'reference_ligand': plan['reference_ligand'], 'status': 'execution_failed_receptor_paused', 'passed': False, 'return_code': completed.returncode, 'rmsd_angstrom': None, 'failure_action': plan['diagnostic']['failure_action'], 'automatic_tuning_performed': False, 'formal_docking_performed': False})  # 不读取旧输出补结果。
                continue  # 其他受体仍可独立诊断。
            poses = _poses(output_path.read_text(encoding='utf-8'))  # 解析本次真实输出。
            rmsd = symmetry_rmsd(ligand_sdf_path.read_bytes(), ligand_pdbqt_path.read_text(encoding='utf-8'), poses[0])  # 只以top-1作批准判定。
            inside = _inside_box(poses[0], plan['search_box'])  # 检查top-1全部输出原子。
            minimum_distance = _minimum_receptor_distance(receptor_path.read_text(encoding='utf-8'), poses[0])  # 最近重原子距离只报告。
            identity_passed = rmsd['heavy_atom_count'] == plan['reference_ligand']['heavy_atom_count']  # 重原子数量须与计划一致。
            diagnostic_passed = rmsd['rmsd_angstrom'] <= plan['diagnostic']['pass_if_at_most']  # 使用已批准≤2 Å规则。
            passed = process_ok and bool(poses) and identity_passed and inside['passed'] and diagnostic_passed  # 所有必要检查共同决定放行。
            status = 'reproduced' if passed else 'not_reproduced_receptor_paused'  # 未通过时不自动调参。
            results.append({'symbol': symbol, 'target_id': plan['target_id'], 'pdb': plan['pdb'], 'reference_ligand': plan['reference_ligand'], 'status': status, 'passed': passed, 'return_code': completed.returncode, 'pose_count': len(poses), 'poses': [{'mode': pose['mode'], 'score_kcal_mol': pose['score_kcal_mol']} for pose in poses], 'top_1_score_kcal_mol': poses[0]['score_kcal_mol'], 'rmsd': rmsd, 'rmsd_angstrom': rmsd['rmsd_angstrom'], 'rmsd_threshold_angstrom': plan['diagnostic']['pass_if_at_most'], 'inside_box': inside, 'ligand_identity_passed': identity_passed, 'minimum_receptor_heavy_atom_distance_angstrom': minimum_distance, 'failure_action': plan['diagnostic']['failure_action'], 'automatic_tuning_performed': False, 'formal_docking_performed': False, 'output_file': file_record(root, output_path, 'redocking_pose')})  # 保留全部模式评分和关键检查。
        require(len(results) == 3 and {row['symbol'] for row in results} == {'AKT1', 'HSP90AA1', 'MAPK1'}, '重对接诊断结果数量或对象不完整')  # 不允许少跑后写成完成。
        files = [file_record(root, path, 'redocking_evidence') for path in sorted(folder.iterdir()) if path.is_file() and path.name != 'redocking_result.json']  # 收集本次所有命令、日志、输出和运行快照。
        summary = {'planned_count': 3, 'completed_count': sum(row['return_code'] == 0 for row in results), 'passed_count': sum(row['passed'] for row in results), 'paused_receptors': [row['symbol'] for row in results if not row['passed']], 'all_reproduced': all(row['passed'] for row in results), 'formal_docking_completed_count': 0, 'formal_docking_authorized': False, 'automatic_tuning_performed': False}  # 摘要不把失败或未运行填成零分。
        report = {'schema_version': 'A06.redocking.result.1', 'study_id': study_id, 'run_id': run_id, 'analysis_purpose': package['analysis_purpose'], 'status': 'completed_awaiting_review', 'preparation_package': package_reference, 'authorization': authorization_reference, 'parent_runs': package['parent_runs'], 'vina_environment': environment_record, 'vina_parameters': vina_parameters, 'diagnostic_rule': {'metric': 'symmetry_aware_heavy_atom_rmsd_angstrom', 'pose': 'top_1', 'pass_if_at_most': 2.0, 'alignment_performed': False}, 'summary': summary, 'results': results, 'files': files, 'created_at': now()}  # 诊断结果仍待用户查看，不自动授权正式对接。
        write_json(folder / 'redocking_result.json', report)  # 完整结果最后发布。
        report_reference = file_record(root, folder / 'redocking_result.json', 'redocking_result')  # 形成不可变索引记录。
        preview_index_path = root / 'environments' / 'A06_previews.json'  # 原索引是唯一当前准备指针。
        preview_index = read_json(preview_index_path)  # 不扫描治理目录猜当前预览。
        previous_reference = preview_index['studies'][study_id]  # 保存旧预览引用供来源追溯。
        previous_preview = read_json(verified_file(root, previous_reference))  # 校验旧预览没有被改写。
        next_preview = deepcopy(previous_preview)  # 新状态写入新文件而非覆盖历史。
        next_preview['notice'] = '三次参考配体重对接诊断已完成；请集中查看RMSD和暂停对象。15组正式对接仍未授权、未运行。'  # 页面先说明当前唯一审核任务。
        next_preview['pending'] = [{'item': '集中复核三次重对接诊断', 'impact': '确认可复现的受体是否进入正式对接；未通过者保持暂停。'}, {'item': '正式15组对接执行授权', 'impact': '本次尚未授权；诊断复核后再单独决定。'}]  # 不重复要求已完成内容。
        next_preview['redocking_authorization'] = authorization_reference  # 绑定本轮用户授权。
        next_preview['redocking_report'] = report_reference  # 页面读取真实结果包。
        next_preview['previous_preview'] = previous_reference  # 新旧预览形成明确链条。
        next_preview_path = root / 'governance' / 'A06准备预览_重对接诊断已完成待复核_20260922.json'  # 文件名表达用途与阶段。
        write_json(next_preview_path, next_preview)  # 不覆盖配置待审的历史预览。
        preview_index['studies'][study_id] = file_record(root, next_preview_path, 'a06_preview')  # 当前指针切换到诊断结果页。
        write_json(preview_index_path, preview_index, replace=True)  # 唯一索引允许原子替换。
        return report_reference  # 调用方可据此复核实际结果。


if __name__ == '__main__':  # 提供明确参数的维护入口。
    import argparse  # 命令行只接收研究和两份有指纹记录文件。
    parser = argparse.ArgumentParser(description='执行已授权的三次A06参考配体重对接诊断')  # 说明本入口不跑正式对接。
    parser.add_argument('--root', required=True)  # 项目根必须明确。
    parser.add_argument('--study', required=True)  # 研究编号必须明确。
    parser.add_argument('--package-record', required=True)  # JSON文字形式的候选包文件记录。
    parser.add_argument('--authorization-record', required=True)  # JSON文字形式的执行授权文件记录。
    arguments = parser.parse_args()  # 不使用环境变量隐式取值。
    result = run_redocking(arguments.root, arguments.study, json.loads(arguments.package_record), json.loads(arguments.authorization_record))  # 运行并返回结果指纹。
    print(json.dumps(result, ensure_ascii=False))  # 仅输出小型结果索引。
