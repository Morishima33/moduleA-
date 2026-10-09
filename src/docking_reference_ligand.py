# 共晶参考配体准备；保留实验重原子坐标并使用RCSB化学组件键表。
import math  # 检查所有坐标和数值有限。
from contracts import require  # 使用项目统一拒绝规则。


def _component_tables(ccd_text, expected_code):  # 从官方化学组件定义读取原子、键和身份。
    import gemmi  # 使用项目固定CIF解析器。
    block = gemmi.cif.read_string(ccd_text).sole_block()  # 每个组件文件必须只有一个数据块。
    atom = block.get_mmcif_category('_chem_comp_atom.')  # 读取包含电荷和理想坐标的原子表。
    bond = block.get_mmcif_category('_chem_comp_bond.')  # 读取明确键级，避免按距离猜键。
    component = block.get_mmcif_category('_chem_comp.')  # 读取化学式和总电荷。
    require(component.get('id') == [expected_code], 'RCSB化学组件身份不符')  # 不按文件名替代内容身份。
    required_atoms = {'atom_id', 'type_symbol', 'charge', 'pdbx_stereo_config', 'pdbx_model_Cartn_x_ideal', 'pdbx_model_Cartn_y_ideal', 'pdbx_model_Cartn_z_ideal'}  # 建模所需原子字段。
    required_bonds = {'atom_id_1', 'atom_id_2', 'value_order'}  # 建模所需键字段。
    require(required_atoms <= set(atom) and required_bonds <= set(bond), 'RCSB化学组件缺少原子或键字段')  # 缺字段时不降级猜测。
    require(component.get('formula') and component.get('pdbx_formal_charge'), 'RCSB化学组件缺少化学式或总电荷')  # 身份校验必须完整。
    return atom, bond, component  # 交给构建函数统一核对。


def _element_symbol(value):  # 将RCSB常见的大写元素字段转换为化学工具接受的标准大小写。
    symbol = str(value).strip()  # 去掉字段两侧空白，避免把格式字符当成元素名。
    require(symbol and symbol.isalpha() and len(symbol) <= 2, 'RCSB化学组件含无效元素符号')  # 只接受一至二字母的普通元素符号。
    return symbol[0].upper() + symbol[1:].lower()  # 例如CL转为Cl，同时保持C、N等单字母元素不变。


def _experimental_coordinates(pdb_text, expected_code, expected_chain, expected_sequence):  # 精确读取晶体中选定配体的重原子坐标。
    import gemmi  # 沿用固定结构解析器。
    structure = gemmi.read_pdb_string(pdb_text)  # 读取已从原始mmCIF提取的参考配体。
    require(len(structure) == 1, '参考配体坐标必须只有一个模型')  # 不自动选择模型。
    found = [(chain, residue) for chain in structure[0] for residue in chain if chain.name == expected_chain and residue.name == expected_code and str(residue.seqid) == str(expected_sequence)]  # 代码、作者链和编号同时匹配。
    require(len(found) == 1, '参考配体坐标无法唯一定位')  # 防止取错同名配体。
    atoms = [atom for atom in found[0][1] if not atom.element.is_hydrogen]  # 重对接比较以重原子为基础。
    require(bool(atoms) and all(not atom.has_altloc() for atom in atoms), '参考配体缺少重原子或存在替代构象')  # 不混合不同占有构象。
    coordinates = {}  # 用RCSB原子名完成确定映射。
    for atom in atoms:  # 每个实验重原子必须独立登记。
        name = atom.name.strip()  # PDB原子名空格不属于身份。
        values = (atom.pos.x, atom.pos.y, atom.pos.z)  # 保存原始晶体坐标。
        require(name not in coordinates and all(math.isfinite(value) for value in values), '参考配体原子名重复或坐标无效')  # 字典覆盖会破坏映射。
        coordinates[name] = values  # 原子名是化学组件和坐标之间的共同键。
    return coordinates  # 不根据空间距离补原子。


def build_reference_molecule(ccd_text, pdb_text, expected_code, expected_chain, expected_sequence):  # 合并官方拓扑和实验坐标形成可准备分子。
    from rdkit import Chem, rdBase  # 使用项目固定RDKit。
    from rdkit.Chem import rdMolDescriptors  # 独立计算分子式。
    from rdkit.Geometry import Point3D  # 明确写入三维坐标。
    atom, bond, component = _component_tables(ccd_text, expected_code)  # 先确认化学组件身份和字段。
    coordinates = _experimental_coordinates(pdb_text, expected_code, expected_chain, expected_sequence)  # 再取得唯一晶体构象。
    heavy_rows = [index for index, element in enumerate(atom['type_symbol']) if element != 'H']  # PDB通常只提供重原子。
    atom_index = {atom['atom_id'][row]: index for index, row in enumerate(heavy_rows)}  # 保留官方原子名到RDKit序号映射。
    require(len(atom_index) == len(heavy_rows) and set(atom_index) == set(coordinates), '化学组件与晶体重原子不能一一对应')  # 不容许缺失、多余或别名猜测。
    editable = Chem.RWMol()  # 按官方表建立空分子。
    for row in heavy_rows:  # 原子顺序固定为RCSB化学组件顺序。
        current = Chem.Atom(_element_symbol(atom['type_symbol'][row]))  # 使用RCSB元素并规范为标准大小写。
        current.SetFormalCharge(int(atom['charge'][row]))  # 使用逐原子形式电荷。
        current.SetProp('atom_name', atom['atom_id'][row])  # 保留后续RMSD原子回指。
        editable.AddAtom(current)  # 每个重原子只加入一次。
    bond_types = {'SING': Chem.BondType.SINGLE, 'DOUB': Chem.BondType.DOUBLE, 'TRIP': Chem.BondType.TRIPLE, 'AROM': Chem.BondType.AROMATIC}  # 支持RCSB标准键级。
    for row in range(len(bond['atom_id_1'])):  # 遍历包括氢键在内的完整官方键表。
        first, second = bond['atom_id_1'][row], bond['atom_id_2'][row]  # 取得两端官方原子名。
        if first in atom_index and second in atom_index:  # 氢稍后由明确价态统一补入。
            require(bond['value_order'][row] in bond_types, '化学组件出现未支持的键级')  # 不把未知键当单键。
            editable.AddBond(atom_index[first], atom_index[second], bond_types[bond['value_order'][row]])  # 只按官方键表连边。
    molecule = editable.GetMol()  # 完成重原子连接图。
    ideal = Chem.Conformer(len(heavy_rows))  # 理想坐标仅用于核定绝对手性。
    ideal.Set3D(True)  # 明确标记三维构象。
    for index, row in enumerate(heavy_rows):  # 写入每个官方理想重原子坐标。
        ideal.SetAtomPosition(index, Point3D(float(atom['pdbx_model_Cartn_x_ideal'][row]), float(atom['pdbx_model_Cartn_y_ideal'][row]), float(atom['pdbx_model_Cartn_z_ideal'][row])))  # 不用晶体坐标猜官方手性定义。
    molecule.AddConformer(ideal)  # 临时绑定理想构象。
    Chem.SanitizeMol(molecule)  # 依据明确键级检查价态和芳香性。
    Chem.AssignAtomChiralTagsFromStructure(molecule, confId=0, replaceExistingTags=True)  # 从官方理想构象恢复手性标签。
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)  # 计算CIP标签供逐中心核对。
    declared = {}  # 保存RCSB明确声明的手性中心。
    for row in heavy_rows:  # 不把N状态误认手性声明。
        if atom['pdbx_stereo_config'][row] in {'R', 'S'}:  # 只核对明确R或S。
            current = molecule.GetAtomWithIdx(atom_index[atom['atom_id'][row]])  # 找到同名RDKit原子。
            require(current.HasProp('_CIPCode') and current.GetProp('_CIPCode') == atom['pdbx_stereo_config'][row], '理想结构手性与RCSB声明不一致')  # 不继续使用错立体结构。
            declared[atom['atom_id'][row]] = atom['pdbx_stereo_config'][row]  # 留存逐中心结果。
    experimental = Chem.Conformer(len(heavy_rows))  # 用晶体坐标替换理想构象。
    experimental.Set3D(True)  # 明确标记三维实验构象。
    for name, index in atom_index.items():  # 原子名精确回填坐标。
        experimental.SetAtomPosition(index, Point3D(*coordinates[name]))  # 重原子位置保持原始实验值。
    molecule.RemoveConformer(0)  # 理想构象不进入重对接文件。
    molecule.AddConformer(experimental)  # 唯一构象改为实验构象。
    coordinate_check = Chem.Mol(molecule)  # 独立副本用于坐标手性复核。
    Chem.RemoveStereochemistry(coordinate_check)  # 避免继承标签掩盖坐标问题。
    Chem.AssignAtomChiralTagsFromStructure(coordinate_check, confId=0, replaceExistingTags=True)  # 单独从晶体坐标判断手性。
    Chem.AssignStereochemistry(coordinate_check, cleanIt=True, force=True)  # 生成坐标对应CIP结果。
    for name, expected in declared.items():  # 每个明确手性中心均须一致。
        current = coordinate_check.GetAtomWithIdx(atom_index[name])  # 按原子名定位同一中心。
        require(current.HasProp('_CIPCode') and current.GetProp('_CIPCode') == expected, '晶体坐标手性与RCSB声明不一致')  # 不以理想构象替换实验姿势。
    molecule = Chem.AddHs(molecule, addCoords=True)  # 在固定重原子坐标基础上显式补氢。
    require(molecule.GetNumHeavyAtoms() == len(heavy_rows), '补氢过程改变了重原子数量')  # 防止结构被意外重写。
    formula = rdMolDescriptors.CalcMolFormula(molecule)  # 从实际分子复算化学式。
    require(formula == component['formula'][0].replace(' ', ''), '准备分子化学式与RCSB组件不一致')  # 氢数或价态错误立即停止。
    require(Chem.GetFormalCharge(molecule) == int(component['pdbx_formal_charge'][0]), '准备分子总电荷与RCSB组件不一致')  # 不静默改变电离状态。
    require(all(math.isfinite(value) for point in molecule.GetConformer().GetPositions() for value in point), '准备分子坐标含无效数值')  # 氢坐标也必须可用。
    molecule.SetProp('_Name', expected_code + '_experimental_pose')  # 文件内标题明确这是实验姿势。
    molecule.SetProp('RCSB_COMPONENT_ID', expected_code)  # 保留官方组件身份。
    molecule.SetProp('EXPERIMENTAL_AUTH_CHAIN', expected_chain)  # 保存作者链。
    molecule.SetProp('EXPERIMENTAL_AUTH_SEQUENCE', str(expected_sequence))  # 保存作者残基号。
    sdf_text = Chem.MolToMolBlock(molecule) + '\n$$$$\n'  # 生成只含一个对象的可追溯SDF。
    return molecule, sdf_text, {'component_id': expected_code, 'name': component.get('name', [''])[0], 'formula': formula, 'formal_charge': Chem.GetFormalCharge(molecule), 'atom_count': molecule.GetNumAtoms(), 'heavy_atom_count': molecule.GetNumHeavyAtoms(), 'declared_stereo_centers': declared, 'experimental_coordinates_preserved': True, 'rdkit_version': rdBase.rdkitVersion}  # 身份通过不等于已完成重对接。


def prepare_reference_ligand(ccd_text, pdb_text, expected_code, expected_chain, expected_sequence, settings):  # 生成重对接输入但不调用Vina。
    from meeko import MoleculePreparation, PDBQTWriterLegacy, __version__  # 使用项目固定Meeko。
    molecule, sdf_text, identity = build_reference_molecule(ccd_text, pdb_text, expected_code, expected_chain, expected_sequence)  # 先完成拓扑、坐标和手性核对。
    require(isinstance(settings, dict) and settings, '参考配体准备参数必须完整传入')  # 不在函数内补默认设置。
    preparation = MoleculePreparation(**settings)  # 与五个候选配体使用同一固定准备参数。
    setups = preparation.prepare(molecule)  # 仅准备PDBQT，不运行对接。
    require(len(setups) == 1, '参考配体准备生成多个对象')  # 不任意选择一个结果。
    pdbqt_text, success, message = PDBQTWriterLegacy.write_string(setups[0], add_index_map=True, remove_smiles=False, bad_charge_ok=False)  # 保留原子映射并拒绝坏电荷。
    require(success and bool(pdbqt_text.strip()), '参考配体PDBQT准备失败：' + str(message))  # 空输出不能进入诊断计划。
    require('REMARK INDEX MAP ' in pdbqt_text and 'TORSDOF' in pdbqt_text, '参考配体PDBQT缺少原子回指或可转动键信息')  # RMSD必须能映射回实验重原子。
    from docking_ligand_flow import check_ligand_coordinates  # 复用正式配体的坐标与映射检查。
    validation = check_ligand_coordinates(sdf_text, pdbqt_text, allowed_pseudoatom_types={'G0'})  # 允许Meeko大环闭合专用G0伪原子，但不计入真实重原子。
    require(validation['heavy_atom_count'] == identity['heavy_atom_count'], '参考配体PDBQT重原子数量不一致')  # 双重核对身份。
    return {'sdf_text': sdf_text, 'pdbqt_text': pdbqt_text, 'identity': identity, 'validation': validation, 'settings': settings, 'writer_settings': {'add_index_map': True, 'remove_smiles': False, 'bad_charge_ok': False}, 'meeko_version': __version__, 'message': str(message), 'status': 'prepared_for_redocking_review', 'redocking_executed': False}  # 准备完成仍需A06_PREP总体复核。
