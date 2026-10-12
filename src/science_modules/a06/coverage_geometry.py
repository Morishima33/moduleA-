"""A06第二版空间核查：真实口袋、组装与环境分开记录，未知内容保持阻断。"""

import math
from contracts import require
from science_modules.a06.quality_engine import inside_box

RULE = "A06.pocket_environment.3"


def atoms(residue, altloc):
    """统一只读取已选构象的重原子，避免混用替代构象。"""
    return [
        a
        for a in residue
        if not a.element.is_hydrogen and (not a.has_altloc() or a.altloc == altloc)
    ]


def distance(left, right):
    """距离用于初筛与证据，不单独证明缺失片段无影响。"""
    return min((a.pos.dist(b.pos) for a in left for b in right), default=math.inf)


def assembly_groups(block):
    """把官方标签链映射为作者链，保留组装编号与变换操作原文。"""
    cat = block.get_mmcif_category("_atom_site.")
    mapping = dict(zip(cat.get("label_asym_id", []), cat.get("auth_asym_id", [])))
    gen = block.get_mmcif_category("_pdbx_struct_assembly_gen.")
    return [
        {
            "assembly_id": gen["assembly_id"][i],
            "chains": sorted({mapping.get(x, x) for x in values.split(",")}),
            "operators": gen.get("oper_expression", [""] * len(gen["assembly_id"]))[i],
        }
        for i, values in enumerate(gen.get("asym_id_list", []))
    ]


def audit(cif_text, spec, box, pocket_keys=None):
    """按实际参考5Å或预测残基初筛；编号相邻只登记，不能自动通过缺失。"""
    import gemmi

    block = gemmi.cif.read_string(cif_text).sole_block()
    structure = gemmi.make_structure_from_block(block)
    alt = spec.get("altloc")
    selected = set(spec["chains"])
    ref_id = (
        spec.get("reference_chain"),
        spec.get("reference_code"),
        str(spec.get("reference_sequence")),
    )
    reference = [
        a
        for c in structure[0]
        for r in c
        if (c.name, r.name, str(r.seqid)) == ref_id
        for a in atoms(r, alt)
    ]
    groups = assembly_groups(block)
    relevant_groups = [g for g in groups if selected.issubset(g["chains"])]
    crystal = " ".join(
        str(v or "")
        for v in block.get_mmcif_category("_exptl_crystal_grow.").get(
            "pdbx_details", []
        )
    ).lower()
    additives = {
        "SO4": ("sulfate", "sulphate"),
        "EDO": ("ethylene glycol", "ethanediol"),
        "GOL": ("glycerol",),
        "DMS": ("dimethyl sulfoxide", "dmso"),
        "IPA": ("isopropanol", "2-propanol"),
        "TLA": ("tartrate", "tartaric acid"),
        "ACT": ("acetate",),
    }

    nearby, box_environment, unresolved, retained = set(), [], [], []
    partners = set()
    poly_types = dict(
        zip(
            block.get_mmcif_category("_entity_poly.").get("entity_id", []),
            block.get_mmcif_category("_entity_poly.").get("type", []),
        )
    )
    site = block.get_mmcif_category("_atom_site.")
    protein_chains = {
        auth
        for auth, eid in zip(
            site.get("auth_asym_id", []), site.get("label_entity_id", [])
        )
        if poly_types.get(eid) == "polypeptide(L)"
    }

    for chain in structure[0]:
        for residue in chain:
            heavy = atoms(residue, alt)
            key = (chain.name, str(residue.seqid))
            if (
                residue.entity_type == gemmi.EntityType.Polymer
                and chain.name in selected
            ):
                if (
                    key in (pocket_keys or [])
                    if pocket_keys is not None
                    else distance(heavy, reference) <= 5
                ):
                    nearby.add(key)
                continue
            if (
                residue.is_water()
                or (chain.name, residue.name, str(residue.seqid)) == ref_id
            ):
                continue
            hit = any(inside_box([a.pos.x, a.pos.y, a.pos.z], box) for a in heavy)
            if not hit and not (
                chain.name in selected
                and residue.name in {"ZN", "MG", "CA", "MN", "FE", "CU"}
            ):
                continue
            item = {
                "chain": chain.name,
                "residue": residue.name,
                "sequence": str(residue.seqid),
                "polymer": residue.entity_type == gemmi.EntityType.Polymer,
                "reference_distance_A": distance(heavy, reference)
                if reference
                else None,
                "action": "pending",
                "reason_zh": "伴随组分必要性尚未确定",
            }
            # 只移除明确属于另一官方组装的聚合物，不凭距离删除必要伙伴。
            if (
                item["polymer"]
                and relevant_groups
                and all(chain.name not in g["chains"] for g in relevant_groups)
            ):
                item.update(
                    action="omit_crystal_chain",
                    reason_zh="不属于包含目标链的官方生物组装；留存原始坐标与组装证据",
                )
            elif (
                item["polymer"]
                and chain.name in protein_chains
                and relevant_groups
                and any(
                    chain.name in g["chains"] and g["operators"] == "1"
                    for g in relevant_groups
                )
            ):
                item.update(
                    action="retain_partner",
                    reason_zh="保留同一官方生物组装的蛋白伙伴；复合物用途及身份记录待集中核对",
                )
                partners.add(chain.name)
            elif (
                not item["polymer"]
                and residue.name in additives
                and any(phrase in crystal for phrase in additives[residue.name])
            ):
                item.update(
                    action="omit_crystallization_additive",
                    reason_zh="原始结晶条件明确包含该添加剂；保留原件及条件，不作为原生辅因子",
                    evidence_zh=crystal,
                )
            elif not item["polymer"] and residue.name in {
                "ZN",
                "MG",
                "CA",
                "MN",
                "FE",
                "CU",
            }:
                item.update(
                    action="retain_cofactor",
                    reason_zh="金属保留并接受参数化核查，不删除以绕过环境要求",
                )
                retained.append((chain.name, residue.name, str(residue.seqid)))
            box_environment.append(item)
            if item["action"] == "pending":
                unresolved.append(item)
    missing = []
    cat = block.get_mmcif_category("_pdbx_unobs_or_zero_occ_atoms.")
    for i, chain in enumerate(cat.get("auth_asym_id", [])):
        key = (chain, str(cat["auth_seq_id"][i]))
        if chain in selected:
            missing.append(
                {
                    "chain": chain,
                    "sequence": key[1],
                    "residue": cat["auth_comp_id"][i],
                    "atom": cat["auth_atom_id"][i],
                }
            )
    gaps = block.get_mmcif_category("_pdbx_unobs_or_zero_occ_residues.")
    missing_residues = [
        {
            "chain": c,
            "sequence": str(gaps["auth_seq_id"][i]),
            "residue": gaps["auth_comp_id"][i],
            "reason_zh": "无坐标片段：需完整独立结构对照或更换结构",
        }
        for i, c in enumerate(gaps.get("auth_asym_id", []))
        if c in selected
    ]
    # 官方明确的非原生表达标签不属于目标位点；不推断未注明的末端为标签。
    dif = block.get_mmcif_category("_struct_ref_seq_dif.")
    labels = {
        (chain, str(dif.get("pdbx_auth_seq_num", dif.get("seq_num", []))[i])): {
            "chain": chain,
            "sequence": str(dif.get("pdbx_auth_seq_num", dif.get("seq_num", []))[i]),
            "residue": dif["mon_id"][i],
            "details": dif["details"][i],
            "reason_zh": "原件明确为无原生UniProt位置的表达标签；不补建、不改变蛋白身份",
        }
        for i, chain in enumerate(dif.get("pdbx_pdb_strand_id", []))
        if chain in selected
        and str(dif.get("details", [])[i]).lower()
        in ("expression tag", "cloning artifact", "initiating methionine")
        and not dif.get("pdbx_seq_db_seq_num", [None] * len(dif.get("details", [])))[i]
        and dif.get("pdbx_seq_db_accession_code", [""] * len(dif.get("details", [])))[i]
        == spec.get("uniprot")
    }
    expression_tags = [
        labels[(r["chain"], r["sequence"])]
        for r in missing_residues
        if (r["chain"], r["sequence"]) in labels
    ]
    missing_residues = [
        r for r in missing_residues if (r["chain"], r["sequence"]) not in labels
    ]
    # 相邻编号不构成口袋损坏，但没有完整对照也不据此放行。
    adjacent = (
        [
            g
            for g in missing_residues
            if any(
                (g["chain"], str(int(g["sequence"]) + delta)) in nearby
                for delta in (-1, 1)
            )
        ]
        if all(g["sequence"].lstrip("-").isdigit() for g in missing_residues)
        else missing_residues
    )
    return {
        "rule_version": RULE,
        "expression_tag_evidence": expression_tags,
        "pocket_residues": sorted(nearby),
        "pocket_complete": not missing and not missing_residues,
        "environment_resolved": not unresolved,
        "missing_pocket_atoms": missing,
        "unobserved_residues": missing_residues,
        "adjacent_unobserved_residues": adjacent,
        "box_environment": box_environment,
        "unresolved_environment": unresolved,
        "retained_cofactors": retained,
        "retained_partner_chains": sorted(partners),
        "assemblies": groups,
        "note_zh": "5Å仅用于初筛；无坐标片段继续核查，不补建",
    }


def extract_receptor(converted, spec, retained, partners=None):
    """准备同身份目标链及明确保留的金属，拒绝丢失辅因子后仍称完成。"""
    from docking_top10_execute import _protein_pdb

    protein = _protein_pdb(
        converted, set(spec["chains"]) | set(partners or []), spec.get("altloc")
    )
    lines = protein.splitlines()[:-2]
    for line in converted.read_text("ascii").splitlines():
        if line.startswith("HETATM") and (
            line[21:22],
            line[17:20].strip(),
            line[22:26].strip(),
        ) in {tuple(x) for x in retained}:
            require(line[16:17] in (" ", spec.get("altloc")), "保留金属存在未核定构象")
            lines.append(line[:16] + " " + line[17:])
    require(
        all(
            any(
                line.startswith("HETATM")
                and (line[21:22], line[17:20].strip(), line[22:26].strip()) == tuple(r)
                for line in lines
            )
            for r in retained
        ),
        "必要金属未完整保留",
    )
    return "\n".join(lines + ["TER", "END"]) + "\n"


def canonical_map(block, spec):
    """按来源明确的UniProt线性映射定位作者编号；非线性或插入编号保持未知。"""
    refs = block.get_mmcif_category("_struct_ref_seq.")
    mapping = {}
    for i, chains in enumerate(refs.get("pdbx_strand_id", [])):
        if (
            refs.get("pdbx_db_accession", [""] * len(refs["pdbx_strand_id"]))[i]
            != spec["uniprot"]
        ):
            continue
        try:
            start = int(refs["pdbx_auth_seq_align_beg"][i])
            end = int(refs["pdbx_auth_seq_align_end"][i])
            db_start = int(refs["db_align_beg"][i])
            db_end = int(refs["db_align_end"][i])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start != db_end - db_start:
            continue
        for chain in chains.split(","):
            if chain in spec["chains"]:
                mapping.update(
                    {
                        (chain, str(n)): db_start + n - start
                        for n in range(start, end + 1)
                    }
                )
    return mapping


def compare_missing(cif_text, spec, env, control, control_text):
    """完整同身份实验对照加功能域映射评估缺失；未映射、未建模或可能触及口袋均不放行。"""
    import gemmi, numpy as np

    block = gemmi.cif.read_string(cif_text).sole_block()
    ctrl = gemmi.cif.read_string(control_text).sole_block()
    current = gemmi.make_structure_from_block(block)
    other = gemmi.make_structure_from_block(ctrl)
    smap = canonical_map(block, spec)
    cmap = canonical_map(ctrl, control["spec"])
    source = {
        smap[(c.name, str(r.seqid))]: r
        for c in current[0]
        for r in c
        if (c.name, str(r.seqid)) in smap and r.entity_type == gemmi.EntityType.Polymer
    }
    target = {
        cmap[(c.name, str(r.seqid))]: r
        for c in other[0]
        for r in c
        if (c.name, str(r.seqid)) in cmap and r.entity_type == gemmi.EntityType.Polymer
    }
    positions = {smap.get(tuple(k)) for k in env["pocket_residues"]}
    require(
        None not in positions and positions and positions <= set(target),
        "完整对照不能覆盖当前口袋的UniProt映射",
    )
    pairs = []
    for pos in sorted(positions):
        require(source[pos].name == target[pos].name, "对照口袋残基身份不一致")
        left = next((a for a in source[pos] if a.name == "CA"), None)
        right = next((a for a in target[pos] if a.name == "CA"), None)
        require(left and right, "对照口袋Cα映射不完整")
        pairs.append(
            (
                [right.pos.x, right.pos.y, right.pos.z],
                [left.pos.x, left.pos.y, left.pos.z],
            )
        )
    require(len(pairs) >= 3, "口袋对照不足三个点，无法确定空间变换")
    x = np.array([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    require(
        np.linalg.matrix_rank(x - x.mean(0)) >= 2
        and np.linalg.matrix_rank(y - y.mean(0)) >= 2,
        "口袋对照点共线，不能唯一定位空间变换",
    )
    u, _, vt = np.linalg.svd((x - x.mean(0)).T @ (y - y.mean(0)))
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    shift = y.mean(0) - x.mean(0) @ rotation
    residual = np.linalg.norm(x @ rotation + shift - y, axis=1)
    # 最大对齐残差作为保守几何余量，不能凭一条远距离忽略坐标不确定性。
    uncertainty = float(max(residual))
    ref = [
        a
        for c in current[0]
        for r in c
        if (c.name, r.name, str(r.seqid))
        == (
            spec.get("reference_chain"),
            spec.get("reference_code"),
            str(spec.get("reference_sequence")),
        )
        for a in atoms(r, spec.get("altloc"))
    ]
    if not ref:
        ref = [a for pos in positions for a in atoms(source[pos], spec.get("altloc"))]
    resolved = []
    for missing in env["unobserved_residues"] + env["missing_pocket_atoms"]:
        key = (missing["chain"], missing["sequence"])
        pos = smap.get(key)
        if pos is None or pos not in target:
            continue
        residue = target[pos]
        if missing.get("residue") and missing["residue"] != residue.name:
            continue
        values = atoms(residue, control["spec"].get("altloc"))
        if missing.get("atom") and not any(a.name == missing["atom"] for a in values):
            continue
        coords = [
            np.array([a.pos.x, a.pos.y, a.pos.z]) @ rotation + shift for a in values
        ]
        gap_distance = min(
            (
                float(np.linalg.norm(v - np.array([a.pos.x, a.pos.y, a.pos.z])))
                for v in coords
                for a in ref
            ),
            default=0,
        )
        if gap_distance - uncertainty <= 5:
            continue
        resolved.append(
            {
                **missing,
                "canonical_position": pos,
                "control_pdb": control["spec"]["pdb_id"],
                "control_file": control["file"],
                "minimum_distance_A": gap_distance,
                "alignment_rmsd_A": float(np.sqrt(np.mean(residual**2))),
                "alignment_max_residual_A": uncertainty,
                "pocket_mapping_count": len(pairs),
                "reason_zh": "同UniProt实验完整残基对照、口袋映射与空间余量共同支持本位点不受缺失直接影响；未补建原结构",
            }
        )
    return resolved
