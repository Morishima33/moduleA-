"""试算独立证据审计：结构范围、伴随组分及真实输出，保留全部原始文件。"""

from storage import read_json, verified_file

from .trial_rules import validate_matrix


def audit_outputs(root, packet):
    """重新解析每份实际姿势；核对Top-1、成分和受体输入及区域参数。"""
    from docking_redocking import _poses

    validate_matrix(packet)
    compounds = {c["compound_id"]: c for c in packet["compounds"]}
    receptors = {r["target_id"]: r for r in packet["receptors"]}
    completed = 0
    for pair in packet["pairs"]:
        receptor = receptors[pair["target_id"]]
        ligand = next(
            f
            for f in compounds[pair["compound_id"]]["files"]
            if f["role"] == "prepared_ligand"
        )
        boxes = {r["region_id"]: r for r in receptor["regions"]}
        for region in pair["regions"]:
            config = region["config"]
            if (
                config["receptor"] != receptor["receptor"]
                or config["compound"] != ligand
                or config["region"] != boxes[region["region_id"]]
            ):
                raise ValueError("区域输出的准备输入或搜索盒与同批固定集合不一致")
            verified_file(root, config["receptor"])
            verified_file(root, config["compound"])
            if region["state"] == "completed":
                poses = _poses(verified_file(root, region["pose"]).read_text("ascii"))
                if poses[0]["score_kcal_mol"] != region["score"]:
                    raise ValueError("实际Top-1姿势评分与区域归档不一致")
                completed += 1
    return {
        "pairs": len(packet["pairs"]),
        "actual_pose_outputs_checked": completed,
        "same_receptor_and_regions_for_all_compounds": True,
        "prepared_inputs_sha256_verified": True,
    }


def processing_scope(root, packet):
    """从官方原件列出所选范围和移除组分；单体试算不冒充原复合物。"""
    import gemmi

    from .coverage_geometry import canonical_map

    result = []
    baseline = (
        read_json(verified_file(root, packet["base_packet"]))
        if packet.get("base_packet")
        else {}
    )
    baseline_rows = {r["target_id"]: r for r in baseline.get("receptors", [])}
    for row in packet["receptors"]:
        source_record = row.get("source")
        source_kind = "official_original"
        if source_record is None and row.get("reused"):
            selected = baseline_rows.get(row["target_id"], {}).get("selected") or {}
            source_record = next(
                (
                    f
                    for f in selected.get("files", [])
                    if f["path"].endswith("/original_conversion.pdb")
                ),
                None,
            )
            source_kind = "verified_original_conversion"
        if row["state"] != "ready" or source_record is None:
            result.append(
                {
                    "target_id": row["target_id"],
                    "symbol": row["symbol"],
                    "reason_zh": row.get("reason_zh", "来源未登记"),
                }
            )
            continue
        source = verified_file(root, source_record)
        block = (
            gemmi.cif.read_file(str(source)).sole_block()
            if source.suffix.lower() == ".cif"
            else gemmi.read_structure(str(source)).make_mmcif_document().sole_block()
        )
        st = gemmi.make_structure_from_block(block)
        spec = row["spec"]
        mapping = (
            canonical_map(block, spec) if spec["source_type"] == "experimental" else {}
        )
        positions = sorted(
            {
                mapping[(chain.name, str(residue.seqid))]
                for chain in st[0]
                if chain.name in spec["chains"]
                for residue in chain
                if residue.het_flag == "A"
                and (chain.name, str(residue.seqid)) in mapping
            }
        )
        partners = [
            {"chain": chain.name, "observed_residues": len(chain)}
            for chain in st[0]
            if chain.name not in spec["chains"] and len(chain)
        ]
        components = [
            {"chain": chain.name, "name": residue.name, "sequence": str(residue.seqid)}
            for chain in st[0]
            for residue in chain
            if residue.het_flag == "H" and residue.name not in {"HOH", "WAT", "DOD"}
        ]
        scope = {
            "target_id": row["target_id"],
            "symbol": row["symbol"],
            "structure_id": row["structure_id"],
            "source": source_record,
            "source_kind": source_kind,
            "target_chains": spec["chains"],
            "canonical_observed_positions": positions,
            "other_source_chains": partners,
            "source_nonwater_components": components,
            "reused_preparation": bool(row.get("reused")),
            "note_zh": "复用输入沿用其原环境核查证据。"
            if row.get("reused")
            else "本次仅采用所选目标链／可解析功能域，列出的其他链及非水组分未进入简化受体。"
            "参考配体仅定位后移除，缺失主链不补建；试算不证明完整蛋白或原复合物的结合能力。",
        }
        result.append(scope)
    return result
