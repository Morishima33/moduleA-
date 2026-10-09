# A06结构身份预检；只报告可核对事实，不代替位点或人工批准。
import io  # 从归档原文读取SDF。
import math  # 拒绝非有限坐标。
import json  # 解析官方JSON回应。
from contracts import require  # 使用项目统一错误提示。
from storage import read_json, verified_file  # 每次使用前校验来源指纹。


def source_body(root, reference):  # 仅接受完整成功的来源。
    record = read_json(verified_file(root, reference))  # 校验路径、大小与内容。
    require(record.get('state') == 'success' and record.get('status') == 200, '结构来源未成功，不能作为空结果继续')  # 失败与无结果区分。
    require(isinstance(record.get('response_text'), str), '结构来源缺原文')  # 不用派生字段冒充原件。
    return record['response_text']  # 返回原始数据文本。


def ligand_identity(sdf_text, expected_cid, expected_key):  # 核对单一三维化学对象。
    from rdkit import Chem, rdBase  # 由独立结构环境提供。
    from rdkit.Chem import rdMolDescriptors  # 从实际结构计算分子式。
    molecules = list(Chem.ForwardSDMolSupplier(io.BytesIO(sdf_text.encode('utf-8')), removeHs=False, sanitize=True, strictParsing=True))  # 不静默取第一条记录。
    require(len(molecules) == 1 and molecules[0] is not None, 'SDF不是一个可解析的完整结构')  # 多结构必须明确选择。
    mol = molecules[0]  # 此时仅存在一个对象。
    require(mol.HasProp('PUBCHEM_COMPOUND_CID') and mol.GetProp('PUBCHEM_COMPOUND_CID').strip() == str(expected_cid), 'SDF的PubChem编号不符')  # 核对文件内编号。
    require(mol.GetNumConformers() == 1 and mol.GetConformer().Is3D(), '缺少单一三维构象')  # 不把二维图当作三维。
    require(all(math.isfinite(v) for p in mol.GetConformer().GetPositions() for v in p), '结构坐标含无效数值')  # 不接受NaN或无穷。
    require(len(Chem.GetMolFrags(mol)) == 1, '结构包含多个不相连组分，需核对')  # 盐或混合物不自动拆分。
    key = Chem.MolToInchiKey(mol)  # 从文件实际连接与立体标记计算。
    require(key == expected_key and bool(key), 'SDF连通结构或立体身份与官方记录不符')  # 全InChIKey比较。
    coordinate_mol = Chem.Mol(mol)  # 只修改内存副本，不改来源。
    Chem.RemoveStereochemistry(coordinate_mol)  # 清除原标记后从坐标复核。
    Chem.AssignStereochemistryFrom3D(coordinate_mol, replaceExistingTags=True)  # 按三维坐标重新判断立体关系。
    coordinate_key = Chem.MolToInchiKey(coordinate_mol)  # 独立于SDF原立体标签。
    require(coordinate_key == expected_key, '三维坐标的立体身份与官方记录不符')  # 不只信文件标签。
    stereo = Chem.FindPotentialStereo(mol)  # 同时检查原子与双键等潜在立体要素。
    unspecified = sum(str(item.specified) != 'Specified' for item in stereo)  # 未指定或未知都记录。
    require(unspecified == 0, '结构存在未明确立体信息，需要核对')  # 不自动选异构体。
    return {'cid': int(expected_cid), 'inchi_key': key, 'coordinate_inchi_key': coordinate_key, 'formula': rdMolDescriptors.CalcMolFormula(mol), 'formal_charge': Chem.GetFormalCharge(mol), 'atom_count': mol.GetNumAtoms(), 'heavy_atom_count': mol.GetNumHeavyAtoms(), 'stereo_elements': len(stereo), 'unspecified_stereo': unspecified, 'rdkit_version': rdBase.rdkitVersion, 'identity_check': 'matched', 'docking_ready': False}  # 身份相同不代表已准备好对接。


def receptor_identity(entity, expected_uniprot, expected_chain):  # 从具体实体核查目标链，不默认第一链。
    ids = entity.get('rcsb_polymer_entity_container_identifiers', {})  # 官方实体身份。
    polymer = entity.get('entity_poly', {})  # 序列与差异信息。
    require(ids.get('uniprot_ids') == [expected_uniprot], '受体实体缺少唯一对应的目标UniProt身份')  # 错链或融合多身份不能静默通过。
    require(expected_chain in ids.get('auth_asym_ids', []), '指定受体链不属于该目标实体')  # 使用明确的作者链编号。
    taxa = {x.get('ncbi_taxonomy_id') for x in entity.get('rcsb_entity_source_organism', [])}  # 看来源物种，不看表达宿主。
    require(taxa == {9606}, '受体来源不是已明确的人类蛋白')  # 不把昆虫表达系统误认物种。
    require(polymer.get('rcsb_entity_polymer_type') == 'Protein', '该实体不是蛋白质')  # DNA不能作蛋白受体。
    differences = {k: polymer.get(k) for k in ['rcsb_mutation_count', 'rcsb_conflict_count', 'rcsb_insertion_count', 'rcsb_deletion_count', 'rcsb_non_std_monomer_count']}  # 未提供留空，不补零。
    return {'pdb_id': ids.get('entry_id'), 'entity_id': ids.get('entity_id'), 'uniprot': expected_uniprot, 'auth_chain': expected_chain, 'label_chains': ids.get('asym_ids', []), 'sequence_differences': differences, 'nonstandard_residues': polymer.get('rcsb_non_std_monomers', []), 'identity_check': 'matched', 'site_approved': False, 'docking_ready': False}  # 突变和位点适用性仍需另外核验。

def receptor_geometry(cif_text, ligand_code, auth_chain, auth_sequence):  # 定位指定参考配体，保留全部邻近资料供判断。
    import gemmi  # 使用固定版本解析mmCIF。
    block = gemmi.cif.read_string(cif_text).sole_block()  # 不把多数据块静默合并。
    structure = gemmi.make_structure_from_block(block)  # 保留来源坐标和链。
    require(len(structure) == 1, '结构包含多个模型，须明确采用模型')  # 不默认第一模型。
    found = [(chain, residue) for chain in structure[0] for residue in chain if chain.name == auth_chain and residue.name == ligand_code and str(residue.seqid) == str(auth_sequence)]  # 作者链和残基号精确定位。
    require(len(found) == 1, '无法唯一定位所指定的共结构参考配体')  # 重复或缺失不能随意选。
    selected = found[0][1]  # 唯一配体残基。
    atoms = [atom for atom in selected if not atom.element.is_hydrogen]  # 几何范围采用重原子。
    require(bool(atoms) and all(not atom.has_altloc() for atom in atoms), '参考配体缺重原子或有待选择的替代构象')  # 不混合不同构象。
    positions = [(atom.pos.x, atom.pos.y, atom.pos.z) for atom in atoms]  # 保存实际坐标。
    require(all(math.isfinite(v) for position in positions for v in position), '参考配体坐标无效')  # 残缺数值不能继续。
    lower = [min(position[i] for position in positions) for i in range(3)]  # 原配体各轴下界。
    upper = [max(position[i] for position in positions) for i in range(3)]  # 原配体各轴上界。
    neighbors = []  # 不用未批准距离阈值筛掉潜在重要成分。
    for chain in structure[0]:  # 遍历包括重复作者链片段的全部链。
        for residue in chain:  # 每个残基分别留存距离。
            if chain.name == auth_chain and residue.name == ligand_code and str(residue.seqid) == str(auth_sequence):  # 当前参考配体不和自身比较。
                continue  # 跳过自身。
            heavy = [atom for atom in residue if not atom.element.is_hydrogen]  # 氢位置不主导接触距离表。
            if not heavy:  # 无可计算原子不能编造距离。
                continue  # 保留原文件供进一步查看。
            distance = min(a.pos.dist(b.pos) for a in atoms for b in heavy)  # 计算真实最小重原子距离，不设纳入阈值。
            neighbors.append({'auth_chain': chain.name, 'label_chain': residue.subchain, 'residue': residue.name, 'auth_sequence': str(residue.seqid), 'het_flag': residue.het_flag, 'minimum_distance_angstrom': distance, 'alternate_atoms': sum(a.has_altloc() for a in heavy)})  # 把水和其他添加剂也列出。
    tags = ['auth_asym_id', 'auth_seq_id', 'auth_comp_id']  # 来源中的未观测残基信息。
    missing = [dict(zip(tags, list(row))) for row in block.find('_pdbx_unobs_or_zero_occ_residues.', tags)]  # 不把未观测等同于自动可删。
    connection_tags = ['conn_type_id', 'ptnr1_auth_asym_id', 'ptnr1_label_comp_id', 'ptnr1_auth_seq_id', 'ptnr2_auth_asym_id', 'ptnr2_label_comp_id', 'ptnr2_auth_seq_id']  # 显式记录共价和配位等连接。
    connections = [dict(zip(connection_tags, list(row))) for row in block.find('_struct_conn.', connection_tags)]  # 不用接触列表代替连接类型。
    return {'ligand_code': ligand_code, 'auth_chain': auth_chain, 'auth_sequence': str(auth_sequence), 'reference_heavy_atoms': len(atoms), 'reference_bounds_angstrom': {'lower': lower, 'upper': upper}, 'resolution_angstrom': structure.resolution, 'neighbor_residues': sorted(neighbors, key=lambda row: (row['minimum_distance_angstrom'], row['auth_chain'], row['auth_sequence'])), 'unobserved_residues': missing, 'explicit_connections': connections, 'gemmi_version': gemmi.__version__, 'box_defined': False, 'docking_ready': False}  # 配体边界不是对接搜索盒。
