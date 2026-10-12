"""A06来源原件只读核查：复用冻结身份与坐标清点，不准备结构、不产生对接评分。"""
from copy import deepcopy
from contracts import require


def inspect_ligand_source(text, approved, official):
    """比对已确认化学身份、最新官方属性和原始三维；不更换异构体或电离形态。"""
    from docking_audit import ligand_identity

    expected = approved["official_evidence"]["properties"]
    require(str(official["CID"]) == str(approved["cid"]), "官方属性CID与已确认成分不符")
    for key in ("InChIKey", "MolecularFormula"):
        require(official[key] == expected[key], "当前官方化学身份与已确认来源冲突：" + key)
    result = ligand_identity(text, approved["cid"], expected["InChIKey"])
    require(result["formula"] == expected["MolecularFormula"], "来源SDF分子式与已确认身份不符")
    return result


def inspect_experimental_source(text, metadata, spec, entities, ccd=None):
    """明确PDB、目标人类链、替代构象、缺失及共晶定位；只报告，不自动选择构象。"""
    import gemmi
    from docking_audit import receptor_identity
    from docking_receptor import inspect_structure, inspect_reference_site

    identities = []
    for chain in spec["chains"]:
        matches = [
            e for e in entities
            if chain in e.get("rcsb_polymer_entity_container_identifiers", {}).get("auth_asym_ids", [])
            and metadata["uniprot"] in e.get("rcsb_polymer_entity_container_identifiers", {}).get("uniprot_ids", [])
        ]
        require(len(matches) == 1, "目标作者链不能唯一对应当前UniProt：" + chain)
        identities.append(receptor_identity(matches[0], metadata["uniprot"], chain))
    block = gemmi.cif.read_string(text).sole_block()
    columns = block.get_mmcif_category("_struct_ref_seq_dif.")
    differences = [
        {k: values[i] for k, values in columns.items()}
        for i, chain in enumerate(columns.get("pdbx_pdb_strand_id", []))
        if chain in spec["chains"]
    ]
    conflicts = [
        r for r in differences
        if "conflict" in str(r.get("details", "")).lower()
        or "mutation" in str(r.get("details", "")).lower()
    ]
    require(not conflicts, "来源坐标存在目标序列冲突或突变，继续待补")
    raw = inspect_structure(text, spec["pdb_id"], spec["chains"])
    result = {"identity": identities, "structure": raw, "reference": None, "sequence_differences": differences,
              "coordinate_modified": False, "receptor_prepared": False, "docking_ready": False}
    if spec.get("pocket") != "reference":
        return result
    site = inspect_reference_site(
        text, spec["reference_code"], spec["reference_chain"],
        spec["reference_sequence"], spec["chains"],
    )
    block = gemmi.cif.read_string(text).sole_block()
    structure = gemmi.make_structure_from_block(block)
    found = [
        residue for chain in structure[0] for residue in chain
        if chain.name == spec["reference_chain"] and residue.name == spec["reference_code"]
        and str(residue.seqid) == str(spec["reference_sequence"])
    ]
    require(len(found) == 1, "参考配体无法唯一定位")
    atom_names = sorted({atom.name for atom in found[0] if not atom.element.is_hydrogen})
    expected_heavy = (ccd or {}).get("rcsb_chem_comp_info", {}).get("atom_count_heavy")
    require(isinstance(expected_heavy, int), "参考配体官方字典缺少重原子数")
    connections = block.get_mmcif_category("_struct_conn.")
    covalent = []
    for i in range(len(connections.get("id", []))):
        row = {k: values[i] for k, values in connections.items()}
        for partner in ("ptnr1", "ptnr2"):
            if (row.get(partner + "_label_comp_id") == spec["reference_code"]
                and row.get(partner + "_auth_asym_id") == spec["reference_chain"]
                and str(row.get(partner + "_auth_seq_id")) == str(spec["reference_sequence"])
                and str(row.get("conn_type_id", "")).startswith("covale")):
                covalent.append(row)
                break
    result["reference"] = {
        "site": site, "heavy_atom_names": atom_names,
        "expected_heavy_atom_count": expected_heavy,
        "observed_unique_heavy_atom_count": len(atom_names),
        "heavy_atom_count_matches": len(atom_names) == expected_heavy,
        "covalent_connections": covalent,
        "noncovalent_use_prechecked": not covalent and len(atom_names) == expected_heavy,
    }
    return result
