# A06受体原始坐标清点；不删水、不补缺失片段、不选择替代构象。
import math  # 检查原始坐标与占有率。
from contracts import require  # 统一错误提示。


def inspect_structure(cif_text, expected_pdb, auth_chains):  # 明确文件身份与拟核查链。
    import gemmi  # 由隔离环境提供结构解析。
    require(isinstance(auth_chains, list) and auth_chains and all(isinstance(x, str) and x for x in auth_chains), "须明确核查作者链")  # 不自动取第一链。
    require(len(set(auth_chains)) == len(auth_chains), "作者链重复")  # 防止重复计数。
    block = gemmi.cif.read_string(cif_text).sole_block()  # 不混用多个结构数据块。
    require(str(block.find_value("_entry.id")).upper() == expected_pdb.upper(), "坐标文件PDB身份不符")  # 文件名不作为身份凭据。
    structure = gemmi.make_structure_from_block(block)  # 保留原始残基和原子。
    require(len(structure) == 1, "受体包含多个模型，需明确选择")  # 不默认取第一模型。
    require(set(auth_chains) <= {chain.name for chain in structure[0]}, "坐标中缺少拟用作者链")  # 不按标签链猜测替代。
    categories = {}  # 原文件报告的未观测信息。
    for name in ("pdbx_unobs_or_zero_occ_residues", "pdbx_unobs_or_zero_occ_atoms"):  # 残基与原子分别统计。
        columns = block.get_mmcif_category("_" + name + ".")  # 保留原字段及空值。
        rows = []  # 类别缺失不冒充结构完整。
        if columns:  # 只有原文件确实报告该类别才解析。
            require("auth_asym_id" in columns and len({len(values) for values in columns.values()}) == 1, "未观测记录字段不完整")  # 残缺类别不静默忽略。
            rows = [{key: values[index] for key, values in columns.items()} for index in range(len(columns["auth_asym_id"])) if columns["auth_asym_id"][index] in auth_chains]  # 仅计入拟用链。
        categories[name] = {"category_reported": bool(columns), "records": rows, "record_count": len(rows)}  # 记录数与“原子均完整”不等价。
    chain_rows, waters, other_components, alternates, partial_occupancy = [], [], [], [], []  # 分别留存结构事项。
    for chain_name in auth_chains:  # 按明确选择逐链清点。
        residues = [residue for chain in structure[0] if chain.name == chain_name for residue in chain]  # 包含重复作者链的不同片段。
        polymers = [residue for residue in residues if residue.entity_type == gemmi.EntityType.Polymer]  # 不用ATOM/HETATM代替聚合物身份。
        require(bool(polymers), "拟用链没有可识别的聚合物坐标：" + chain_name)  # 不把仅含水的链当蛋白。
        chain_rows.append({"auth_chain": chain_name, "modeled_polymer_residues": len(polymers), "modeled_polymer_atoms": sum(len(residue) for residue in polymers)})  # 不以此断言结构域完整。
        for residue in residues:  # 每个残基保持原编号。
            identity = {"auth_chain": chain_name, "label_chain": residue.subchain, "residue": residue.name, "auth_sequence": str(residue.seqid)}  # 保留两种链编号。
            for atom in residue:  # 原子数据必须是有限值。
                require(all(math.isfinite(value) for value in (atom.pos.x, atom.pos.y, atom.pos.z, atom.occ)), "结构含无效坐标或占有率")  # 不修补坏数值。
                if atom.occ != 1.0:  # 原样报告，不自行设质量阈值。
                    partial_occupancy.append(dict(identity, atom=atom.name, altloc=atom.altloc if atom.has_altloc() else "", occupancy=atom.occ))  # 供后续判断。
            locations = sorted({atom.altloc for atom in residue if atom.has_altloc()})  # 列出全部替代位置。
            if locations:  # 存在标记时不自动选择。
                alternates.append(dict(identity, locations=locations))  # 不默认A构象。
            if residue.is_water():  # 将水独立列出。
                waters.append(dict(identity, atom_count=len(residue)))  # 不判断是否关键，也不删除。
            elif residue.entity_type != gemmi.EntityType.Polymer:  # 共结构小分子和添加剂均保留。
                other_components.append(dict(identity, atom_count=len(residue)))  # 不自动作为药物口袋。
    return {"pdb_id": expected_pdb.upper(), "auth_chains": auth_chains, "chains": chain_rows, "unobserved": categories, "waters": waters, "other_components": other_components, "alternate_residues": alternates, "partial_occupancy_atoms": partial_occupancy, "gemmi_version": gemmi.__version__, "coordinate_modified": False, "receptor_prepared": False, "docking_ready": False}  # 清点不等于结构准备通过。


def inspect_reference_site(cif_text, ligand_code, ligand_chain, ligand_sequence, receptor_chains):  # 报告结构问题与参考位点的几何关系。
    import gemmi  # 使用与全结构清点一致的解析器。
    require(isinstance(receptor_chains, list) and receptor_chains, "须明确受体链")  # 不在此步自动选链。
    block = gemmi.cif.read_string(cif_text).sole_block()  # 只解析单一原始数据块。
    structure = gemmi.make_structure_from_block(block)  # 保留全部原坐标。
    require(len(structure) == 1, "受体包含多个模型，需明确选择")  # 多模型不默认合并。
    found = [residue for chain in structure[0] for residue in chain if chain.name == ligand_chain and residue.name == ligand_code and str(residue.seqid) == str(ligand_sequence)]  # 按作者链和残基号精确定位。
    require(len(found) == 1, "无法唯一定位参考配体")  # 不任取重复配体。
    ligand_atoms = [atom for atom in found[0] if not atom.element.is_hydrogen]  # 用参考配体重原子定位。
    require(bool(ligand_atoms), "参考配体没有重原子")  # 空坐标不能计算。

    def distance(residue):  # 计算现有残基原子到参考配体的最小距离。
        atoms = [atom for atom in residue if not atom.element.is_hydrogen]  # 不使用未必保存的氢坐标。
        return min((left.pos.dist(right.pos) for left in ligand_atoms for right in atoms), default=None)  # 无原子时如实返回空。

    residues = {}  # 按作者链与序号建立可追溯索引。
    for chain in structure[0]:  # 仅索引本次拟用受体链。
        if chain.name not in receptor_chains:  # 其他链不冒充拟用链。
            continue  # 保留原文件，不进入本次几何汇总。
        for residue in chain:  # 同一作者链可含多个片段。
            residues.setdefault((chain.name, str(residue.seqid.num), residue.name), []).append(residue)  # 不用名称单独合并。

    missing_atom_rows = []  # 报告缺原子所在残基当前坐标与位点的距离。
    columns = block.get_mmcif_category("_pdbx_unobs_or_zero_occ_atoms.")  # 读取来源明确标记的缺失原子。
    if columns:  # 没有类别时不冒充零距离。
        for index, chain_name in enumerate(columns["auth_asym_id"]):  # 每个未观测原子分别保留。
            if chain_name not in receptor_chains:  # 非拟用链不计入本次位点质量。
                continue  # 不改写原文件。
            key = (chain_name, str(columns["auth_seq_id"][index]), columns["auth_comp_id"][index])  # 定位其他已观测原子。
            matches = residues.get(key, [])  # 整个残基也可能无坐标。
            current_distance = min((distance(residue) for residue in matches if distance(residue) is not None), default=None)  # 这不是缺失原子本身距离。
            missing_atom_rows.append({"auth_chain": chain_name, "residue": key[2], "auth_sequence": key[1], "missing_atom": columns["auth_atom_id"][index], "modeled_residue_minimum_distance_angstrom": current_distance})  # 字段名明确限定含义。

    alternate_rows = []  # 替代构象按残基报告。
    for (chain_name, unused_sequence, unused_name), matches in residues.items():  # 不依赖mmCIF行顺序。
        for residue in matches:  # 每个原坐标残基单独检查。
            locations = sorted({atom.altloc for atom in residue if atom.has_altloc()})  # 不默认选A或最高占有率。
            if locations:  # 只报告真实存在的替代位置。
                alternate_rows.append({"auth_chain": chain_name, "residue": residue.name, "auth_sequence": str(residue.seqid), "locations": locations, "minimum_distance_angstrom": distance(residue)})  # 距离用当前全部已观测原子计算。

    water_distances = []  # 口袋水先保留距离，不自动决定删留。
    for chain in structure[0]:  # 配体周围的水可属于独立标签链。
        for residue in chain:  # 所有水都有可追溯作者编号。
            if residue.is_water():  # 其他添加剂不混入水。
                water_distances.append({"auth_chain": chain.name, "auth_sequence": str(residue.seqid), "minimum_distance_angstrom": distance(residue)})  # 无阈值过滤。
    water_distances.sort(key=lambda row: (float("inf") if row["minimum_distance_angstrom"] is None else row["minimum_distance_angstrom"], row["auth_chain"], row["auth_sequence"]))  # 排序只为展示。
    return {"reference_ligand": {"code": ligand_code, "auth_chain": ligand_chain, "auth_sequence": str(ligand_sequence)}, "missing_atoms": missing_atom_rows, "alternate_residues": alternate_rows, "waters_by_distance": water_distances, "distance_filter_applied": False, "coordinate_modified": False, "site_quality_decision": "pending"}  # 原始距离不自动变成通过或排除。
