# 五个已批准配体的准备与组合清单；不设搜索盒、不执行对接。
import io  # 从归档文本读取结构。
import math  # 检查坐标与电荷。
import sys  # 留存实际Python版本。
from pathlib import Path  # 使用研究包内路径。
from contracts import require  # 复用明确的拒绝信息。
from storage import read_json, verified_file, write_json, file_record, new_id, now, write_lock  # 统一版本、指纹与锁。
from docking_ui import load_preview  # 校验研究和上游仍有效。
from docking_ligand import prepare_ligand  # 沿用已核对的Meeko准备内核。
from docking_runtime import activate  # 只在项目隔离环境中准备。


def check_ligand_coordinates(sdf, pdbqt, allowed_pseudoatom_types=None):  # 核验原子映射、重原子坐标及有限电荷。
    from rdkit import Chem  # 从原始SDF取得坐标与原子身份。
    mols = list(Chem.ForwardSDMolSupplier(io.BytesIO(sdf.encode('utf-8')), removeHs=False))  # 不隐式丢弃氢。
    require(len(mols) == 1 and mols[0] is not None, '配体原结构无法唯一解析')  # 不随意选择多对象。
    mol = mols[0]  # 使用唯一来源。
    allowed_pseudoatom_types = set(allowed_pseudoatom_types or [])  # 默认不允许伪原子；共晶大环配体须显式传入。
    mapping, atoms = {}, {}  # 分别记录原子回指与实际输出。
    for line in pdbqt.splitlines():  # 解析Meeko明确写出的索引。
        if line.startswith('REMARK INDEX MAP '):  # 原SDF一基编号到PDBQT编号。
            values = [int(x) for x in line.split()[3:]]  # 每两个整数为一组映射。
            require(len(values) % 2 == 0, '配体原子映射不完整')  # 残缺映射不能忽略。
            for source, target in zip(values[::2], values[1::2]):  # 显式处理每一个映射。
                require(source not in mapping and 1 <= source <= mol.GetNumAtoms(), '配体原子映射重复或越界')  # 不让字典覆盖错误。
                mapping[source] = target  # 保留完整回指。
        elif line.startswith(('ATOM  ', 'HETATM')):  # 坐标与电荷必须是真实数值。
            serial = int(line[6:11])  # 原子序号是映射目标。
            values = [float(line[30:38]), float(line[38:46]), float(line[46:54]), float(line[70:76])]  # PDBQT固定字段。
            require(serial not in atoms and all(math.isfinite(x) for x in values), '配体原子重复或数值无效')  # 拒绝坏数据。
            atoms[serial] = (values[:3], line[77:].strip())  # 保存位置与原子类型。
    pseudoatoms = {serial for serial, (_, atom_type) in atoms.items() if atom_type in allowed_pseudoatom_types}  # Meeko大环闭合伪原子没有来源原子映射。
    require(atoms and len(set(mapping.values())) == len(mapping) and set(mapping.values()) == set(atoms) - pseudoatoms, '配体输出原子与映射不一致')  # 除明确许可的伪原子外所有输出都应有来源。
    heavy = [a.GetIdx() + 1 for a in mol.GetAtoms() if a.GetAtomicNum() != 1]  # 非极性氢合并不当作重原子缺失。
    for source in heavy:  # 每个重原子都必须保留。
        require(source in mapping, '配体准备丢失重原子')  # 不能以总数相同掩盖错原子。
        position = mol.GetConformer().GetAtomPosition(source - 1)  # 原三维结构坐标。
        xyz, atom_type = atoms[mapping[source]]  # 按实际映射定位输出。
        require(atom_type and atom_type not in ('H', 'HD') and xyz == [round(x, 3) for x in (position.x, position.y, position.z)], '配体重原子坐标或类型改变')  # 仅按文件精度比较，不设生物学阈值。
    require(sum(t not in ('H', 'HD') and t not in allowed_pseudoatom_types for _, t in atoms.values()) == len(heavy), '配体准备新增重原子')  # 伪原子不计为真实重原子。
    return {'heavy_atom_count': len(heavy), 'output_atom_count': len(atoms), 'pseudoatom_count': len(pseudoatoms), 'pseudoatom_types': sorted({atoms[serial][1] for serial in pseudoatoms}), 'heavy_atoms_preserved': True, 'finite_coordinates_and_charges': True}  # 不表示对接已通过。


def combination_plan(ligands, receptors, evidence_rows):  # 列出待运行组合，关系仅由已归档上游资料判定。
    require(len({x['compound_id'] for x in ligands}) == len(ligands) and len({x['target_id'] for x in receptors}) == len(receptors), '组合对象重复')  # 防止重复计算或误计计划数。
    pairs = []  # 不创建任何虚构评分。
    for ligand in ligands:  # 仅来自已选主候选。
        for receptor in receptors:  # 仅来自已批准受体名单。
            refs = sorted({row['source_ref'] for row in evidence_rows if row['compound_id'] == ligand['compound_id'] and row['target_id'] == receptor['target_id']})  # 用稳定编号匹配，不凭名称相似。
            pairs.append({'compound_id': ligand['compound_id'], 'compound_name': ligand['name'], 'target_id': receptor['target_id'], 'target_symbol': receptor['symbol'], 'pdb': receptor['pdb'], 'chains': receptor['chains'], 'relation': 'upstream_record' if refs else 'exploratory', 'source_refs': refs, 'status': 'not_run', 'score_kcal_mol': None, 'search_box': None})  # 无记录不等于不存在结合，也不伪称已证实。
    return pairs  # 始终是计划清单而非对接结果。


def prepare_ligand_package(workflow, study_id, trial_record):  # 只复用本研究已有明确中性形态和固定准备参数。
    runtime = activate(workflow.root)  # 先核验解释器隔离、工具版本和实际加载位置。
    root = workflow.root  # 独立新项目根。
    with write_lock(root):  # 准备开始前同时核验状态与当前资料。
        plan = load_preview(workflow, study_id)  # 上游改变、受体包损坏均停止。
        manifest = workflow.load(study_id)  # 读取统一研究索引。
        require(not manifest.get('trashed', False) and plan['analysis_purpose'] == 'workflow_test', '只允许本次有效流程测试研究')  # 不扩展至正式研究。
        require(trial_record in plan['evidence'], '配体准备来源不在已核验预览中')  # 不读取来源不明的参数。
        trial = read_json(verified_file(root, trial_record))  # 固定已有参数化资料。
        require(trial['study_id'] == study_id and trial['selection_run'] == plan['parent_runs']['A03_SELECT'], '配体来源不属于当前研究或候选版本')  # 不串用病例。
        ligands = plan['ligands']  # 五个明确选中对象。
        require(len(ligands) == 5 and {x['cid'] for x in ligands} == {x['cid'] for x in trial['results']} and len(trial['results']) == 5, '本次已批准配体清单改变')  # 不能夹带补充候选。
        study = workflow.location(study_id)  # 固定研究包。
        sources = [manifest['runs'][plan['parent_runs'][k]]['result_file'] for k in ('A03', 'A03_SELECT')]  # 显式读取两项上游。
        source_paths = [verified_file(study, x) for x in sources]  # 校验上游结果指纹。
        intersection, selection = [read_json(x) for x in source_paths]  # 关系与名单来源分开。
        require({x['compound_id'] for x in selection['tables']['selected']} == {x['compound_id'] for x in ligands}, '网页候选与上游已选名单不一致')  # 不凭预览替代真实选择。
        run_id = new_id('run')  # 每次准备有独立身份。
        output, raw = study / 'runs' / 'A06_PREP' / run_id, study / 'raw' / run_id  # 沿用已批准研究包目录。
        output.mkdir(parents=True, exist_ok=False)  # 不覆盖历史准备产物。
        raw.mkdir(parents=True, exist_ok=False)  # 原始副本单独留存。
        write_json(output / 'execution.json', {'started_at': now(), 'status': 'preparing_draft', 'study_id': study_id, 'run_id': run_id, 'parent_runs': plan['parent_runs'], 'trial': trial_record})  # 中断也保留来源。
    results, evidence = [], [trial_record, plan['prepared_receptor_report']] + [file_record(root, x, 'upstream_result') for x in source_paths]  # 组合来源可追溯。
    for ligand in ligands:  # 不新增或替换成分。
        item = next(x for x in trial['results'] if x['cid'] == ligand['cid'])  # CID精确回指。
        label = ligand['compound_id'] + '_CID' + str(ligand['cid'])  # 文件名稳定且不依赖长俗名。
        row = dict(ligand, status='failed', files=[], docking_ready=False)  # 成功需要实际检查。
        try:  # 单项失败保留原因，不自动更换结构。
            source_path = verified_file(root, item['source'])  # 检查原始PubChem响应。
            source = read_json(source_path)  # 保留原响应内容。
            require(source['state'] == 'success' and str(source['status']) == '200', '配体来源获取未成功')  # 不把错误页当结构。
            copied = raw / source_path.name  # 沿用内容指纹文件名。
            with copied.open('xb') as stream:  # 不覆盖原始来源。
                stream.write(source_path.read_bytes())  # 保存相同原始字节。
            row['files'].append(file_record(root, copied, 'ligand_source'))  # 来源副本有指纹。
            sdf = source['response_text']  # 不重新下载或另选构象。
            prepared = prepare_ligand(sdf, ligand['cid'], item['prepared']['identity']['inchi_key'], item['prepared']['settings'])  # 完整沿用明确参数。
            require(prepared['identity']['formal_charge'] == 0, '本次授权仅适用已核验中性结构')  # 不自动扩展电离形态。
            row['validation'] = check_ligand_coordinates(sdf, prepared['pdbqt_text'])  # 核对重原子及实际输出。
            for suffix, value in (('.sdf', sdf), ('.pdbqt', prepared['pdbqt_text'])):  # 保存原SDF文本和实际PDBQT。
                with (output / (label + suffix)).open('x', encoding='utf-8', newline='\n') as stream:  # 独立成分文件不互相覆盖。
                    stream.write(value)  # 只写本次实际结果。
            row.update(status='prepared_candidate', identity=prepared['identity'], settings=prepared['settings'], writer_settings=prepared['writer_settings'], meeko_version=prepared['meeko_version'], message=prepared['message'])  # 准备成功不等于允许对接。
        except Exception as error:  # 记录失败，禁止静默修复。
            row['error'] = str(error)  # 人工核验时能找到原因。
        write_json(output / (label + '_log.json'), row)  # 包含调用参数及逐项状态。
        row['files'].extend(file_record(root, x, 'ligand_preparation') for x in sorted(output.glob(label + '*')))  # 日志与结构都入索引。
        evidence.extend(row['files'])  # 网页统一从清单下载。
        results.append(row)  # 不因失败减少计划组合。
    pairs = combination_plan(ligands, plan['receptors'], intersection['tables']['formula_evidence'])  # 所有15组都标记为未运行。
    write_json(output / 'combinations.json', pairs)  # 结构化计划不含执行盒子。
    write_json(output / 'completion.json', {'finished_at': now(), 'prepared': sum(x['status'] == 'prepared_candidate' for x in results), 'failed': sum(x['status'] == 'failed' for x in results), 'published': False})  # 不修改研究复核状态。
    for name in ('docking_ligand_flow.py', 'docking_ligand.py', 'docking_audit.py', 'docking_runtime.py', 'contracts.py', 'storage.py'):  # 保存实际准备逻辑快照。
        with (output / name).open('xb') as stream:  # 每次独立版本。
            stream.write(Path(__file__).with_name(name).read_bytes())  # 源码后续修改不破坏本次追溯。
        evidence.append(file_record(root, output / name, 'code_snapshot'))  # 同样验证代码快照。
    evidence.extend(file_record(root, output / name, 'preparation_record') for name in ('execution.json', 'completion.json', 'combinations.json'))  # 完整执行线索。
    report = {'schema_version': 'A06.ligand.preparation.1', 'study_id': study_id, 'run_id': run_id, 'parent_runs': plan['parent_runs'], 'status': 'draft_not_reviewable', 'analysis_purpose': 'workflow_test', 'created_at': now(), 'runtime': runtime, 'python_executable': sys.executable, 'receptor_report': plan['prepared_receptor_report'], 'protonation_policy': trial['protonation_policy'], 'results': results, 'combinations': pairs, 'planned_count': len(pairs), 'completed_count': 0, 'docking_executed': False, 'search_box': None, 'evidence': evidence}  # 只陈述当前准备事实。
    write_json(output / 'preparation.json', report)  # 保存候选索引，不登记为正式A06_PREP。
    return report, file_record(root, output / 'preparation.json', 'ligand_preparation_manifest')  # 交给现有预览入口引用。
