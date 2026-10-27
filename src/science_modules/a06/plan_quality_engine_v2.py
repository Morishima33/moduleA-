"""新方案第二版准备：复用冻结内核，单独执行和记录方案参数。"""
from pathlib import Path
import json
import math
import re
import urllib.request
from contracts import require
from storage import write_json, file_record, verified_file
from docking_top10_execute import (
    _write_text, _protein_pdb, _ligand_lines, _run,
    _meeko_settings, _prepare_receptor_cli,
)
from docking_ligand import prepare_ligand
from docking_reference_ligand import prepare_reference_ligand
from docking_p2rank import run_twice, _prediction_rows, _residue_keys, _pdb_atoms
from science_modules.a06.two_pass import assess_attempt


def reference_box(text, padding):
    """参考配体重原子包络及方案外扩；零尺寸盒不能进入工具。"""
    require(type(padding) in (int, float) and math.isfinite(padding) and padding >= 0, "搜索盒外扩值无效")
    coords = [tuple(float(line[i:i+8]) for i in (30, 38, 46)) for line in text.splitlines()
              if line.startswith("HETATM") and line[76:78].strip().upper() not in {"H", "D"}]
    require(coords and all(math.isfinite(v) for row in coords for v in row), "参考配体坐标无效")
    lows = [min(row[i] for row in coords) for i in range(3)]
    highs = [max(row[i] for row in coords) for i in range(3)]
    box = {"center": [round((a+b)/2, 3) for a,b in zip(lows, highs)],
           "size": [round(b-a+2*padding, 3) for a,b in zip(lows, highs)]}
    require(all(v > 0 for v in box["size"]), "搜索盒尺寸无效")
    return box


def prediction_box(text, prediction, padding):
    """由两次一致的预测残基与输入坐标重建本方案搜索盒。"""
    require(type(padding) in (int, float) and math.isfinite(padding) and padding >= 0, "搜索盒外扩值无效")
    keys = _residue_keys(prediction["residue_ids"])
    atoms = [a for a in _pdb_atoms(text) if (a["chain"], a["residue"]) in keys]
    require(atoms, "预测口袋残基没有对应重原子")
    low = [min(a["xyz"][i] for a in atoms) for i in range(3)]
    high = [max(a["xyz"][i] for a in atoms) for i in range(3)]
    box = {"center": [round((a+b)/2, 3) for a,b in zip(low, high)],
           "size": [round(b-a+2*padding, 3) for a,b in zip(low, high)],
           "padding_angstrom": float(padding), "envelope_atom_count": len(atoms),
           "adjacent_residue_count": len(keys),
           "adjacent_residues": [f"{c}:{r}" for c,r in sorted(keys)],
           "p2rank_reported_center": [float(prediction[k]) for k in ("center_x", "center_y", "center_z")],
           "box_rule": "adjacent_residue_heavy_atom_envelope_plus_plan_padding"}
    require(all(v > 0 for v in box["size"]) and all(math.isfinite(v) for v in box["p2rank_reported_center"]), "预测搜索盒无效")
    return box


def redock(executable, receptor, reference_pdbqt, reference_sdf, box, label, folder, params):
    """记录实际参数和命令，并以Top-1输出计算对称RMSD。"""
    from docking_redocking import _poses, symmetry_rmsd
    output = folder / "redocking" / f"{label}_redocked.pdbqt"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(executable), "--receptor", str(receptor), "--ligand", str(reference_pdbqt)]
    for axis, value in zip("xyz", box["center"]): command.extend(["--center_" + axis, str(value)])
    for axis, value in zip("xyz", box["size"]): command.extend(["--size_" + axis, str(value)])
    for key, value in (("scoring", params["scoring"]), ("exhaustiveness", params["exhaustiveness"]),
                       ("num_modes", params["num_modes"]), ("energy_range", params["energy_range_kcal_mol"]),
                       ("seed", params["seed"])): command.extend(["--" + key, str(value)])
    command.extend(["--out", str(output)])
    write_json(folder / "redocking" / "command.json", {"parameters": params, "box": box, "arguments": command})
    result = _run(command, folder, folder / "redocking" / f"{label}_stdout.txt", folder / "redocking" / f"{label}_stderr.txt")
    require(result.returncode == 0 and output.is_file(), "参考配体重对接失败：" + label)
    value = symmetry_rmsd(reference_sdf.read_bytes(), reference_pdbqt.read_text("ascii"), _poses(output.read_text("ascii"))[0])["rmsd_angstrom"]
    return value, output


def target_folder(target):
    """HGNC科学编号保持原样，Windows目录使用不含冒号的映射。"""
    require(isinstance(target, str) and re.fullmatch(r"HGNC:[0-9]+", target),
            "HGNC编号格式不合法，不能建立受体目录")
    return target.replace(":", "_")


def inside_box(xyz, box):
    """仅采用已确认的搜索盒边界，不新增结构质量距离阈值。"""
    return all(abs(xyz[i] - box["center"][i]) <= box["size"][i] / 2 for i in range(3))


def environment_audit(cif_text, spec, box, pocket_keys=None):
    """记录盒内缺原子、伴随组分和其他聚合物；有疑问保留待核定。"""
    import gemmi
    block = gemmi.cif.read_string(cif_text).sole_block()
    structure = gemmi.make_structure_from_block(block)
    modeled, nearby, environment = {}, set(), []
    reference = (spec.get("reference_chain"), spec.get("reference_code"),
                 str(spec.get("reference_sequence")))
    for chain in structure[0]:
        for residue in chain:
            key = (chain.name, str(residue.seqid))
            heavy = [atom for atom in residue if not atom.element.is_hydrogen
                     and (not atom.has_altloc() or atom.altloc == spec.get("altloc"))]
            hit = any(inside_box([atom.pos.x, atom.pos.y, atom.pos.z], box) for atom in heavy)
            if residue.entity_type == gemmi.EntityType.Polymer and chain.name in spec["chains"]:
                modeled[key] = residue
                if hit:
                    nearby.add(key)
            elif hit and not residue.is_water() and (
                chain.name, residue.name, str(residue.seqid)) != reference:
                environment.append({"chain": chain.name, "residue": residue.name,
                                    "sequence": str(residue.seqid),
                                    "polymer": residue.entity_type == gemmi.EntityType.Polymer})
    if pocket_keys is not None:
        nearby = set(pocket_keys)
    missing = []
    category = block.get_mmcif_category("_pdbx_unobs_or_zero_occ_atoms.")
    for i, chain in enumerate(category.get("auth_asym_id", [])):
        key = (chain, str(category["auth_seq_id"][i]) + str(
            category.get("PDB_ins_code", [""] * len(category["auth_asym_id"]))[i] or ""))
        # 来源插入码可能是?/.，必须按真实有坐标的编号核对。
        base = (chain, str(category["auth_seq_id"][i]))
        if key in nearby or base in nearby:
            missing.append({"chain": chain, "residue": category["auth_comp_id"][i],
                            "sequence": base[1], "atom": category["auth_atom_id"][i]})
    gaps = block.get_mmcif_category("_pdbx_unobs_or_zero_occ_residues.")
    adjacent_gaps = []
    for i, chain in enumerate(gaps.get("auth_asym_id", [])):
        if chain not in spec["chains"]:
            continue
        seq = str(gaps["auth_seq_id"][i])
        try:
            adjacent = any((chain, str(int(seq) + delta)) in nearby for delta in (-1, 1))
        except ValueError:
            adjacent = True
        if adjacent:
            adjacent_gaps.append({"chain": chain, "sequence": seq})
    return {"pocket_complete": not missing and not adjacent_gaps,
            "environment_resolved": not environment,
            "missing_pocket_atoms": missing, "adjacent_unobserved_residues": adjacent_gaps,
            "box_environment": environment,
            "water_policy": "沿用冻结的蛋白坐标准备；原始水、组分与复合物全部保留可追溯",
            "note_zh": "盒内其他聚合物或组分需要核定，不自动认定其可删除；无坐标片段不自动补建"}


def source_file(root, source, key):
    """原件只从同研究登记的文件键取出并再次核对哈希。"""
    rows = [r["file"] for r in source["files"] if r["key"] == key]
    require(len(rows) == 1, "原件文件键不能唯一定位")
    return verified_file(root, rows[0])


def prepare_compounds(root, source, plan, folder, progress):
    """十五来源三维逐项准备，失败项保留且不本地生成或改变化学形态。"""
    rows = []
    settings = _meeko_settings()
    for index, row in enumerate(plan["compounds"]):
        progress("准备来源三维：" + row["compound_id"])
        audit = next(r for r in source["compounds"] if r["compound_id"] == row["compound_id"])
        value = {"compound_id": row["compound_id"], "name_zh": audit["name_zh"],
                 "cid": audit["cid"], "state": "NA", "reason_zh": "", "files": []}
        try:
            require(row["status"] == "use" and audit["identity_matched"], "成分不可用或身份未通过")
            path = source_file(root, source, audit["file_key"])
            prepared = prepare_ligand(path.read_text(encoding="utf-8"), audit["cid"],
                                      audit["audit"]["inchi_key"], settings)
            dest = _write_text(folder / "ligands" / (row["compound_id"] + ".pdbqt"),
                               prepared.pop("pdbqt_text"), "ascii")
            value.update(state="ready", reason_zh="来源三维身份复验与Meeko参数化完成，未执行对接",
                         preparation=prepared,
                         files=[file_record(root, path, "source_3d"),
                                file_record(root, dest, "prepared_ligand")])
        except Exception as error:
            value["reason_zh"] = str(error)
        rows.append(value)
        write_json(folder / "ligands" / (row["compound_id"] + "_quality.json"), value)
    return rows


def download_ccd(code, folder):
    """按确认的参考代码获取官方拓扑原文，错误不解释为空数据。"""
    url = "https://files.rcsb.org/ligands/download/" + code + ".cif"
    path = folder / ("ccd_" + code + ".cif")
    if not path.exists():
        with urllib.request.urlopen(url, timeout=90) as response:
            raw = response.read(5_000_001)
        require(0 < len(raw) <= 5_000_000, "CCD原文为空或过大")
        path.write_bytes(raw)
        write_json(folder / ("ccd_" + code + "_source.json"), {"url": url})
    return path


def attempt(root, source, row, spec, round_no, folder, tools, progress, box_padding=5.0, vina_parameters=None):
    """一遍只使用该方案独立结构；预测先出证据，不能代签口袋确认。"""
    import gemmi
    folder.mkdir(parents=True, exist_ok=False)
    evidence = {"structure_id": spec.get("pdb_id", spec.get("model_id")),
                "receptor_ready": False, "pocket_complete": False,
                "environment_resolved": False, "files": []}
    try:
        require(spec["source_type"] == "experimental",
                "预测模型执行尚缺本轮来源原件及置信度资料，保留待补")
        match = [r for r in source["receptors"] if r["target_id"] == row["target_id"]
                 and r["pdb_id"] == spec["pdb_id"] and r["chains"] == spec["chains"]]
        require(len(match) == 1 and match[0]["identity_matched"], "该结构未通过本轮来源身份核查")
        original = source_file(root, source, match[0]["file_key"])
        cif = original.read_text(encoding="utf-8")
        inspection = match[0]["audit"]
        require(all(r["uniprot"] == spec["uniprot"] and r["identity_check"] == "matched"
                    for r in inspection["identity"]), "原件UniProt核查不符")
        evidence["identity"] = {"target_id": row["target_id"], "uniprot": spec["uniprot"],
            "species": 9606, "polymer_type": "Protein", "sequence_matches": True,
            "chains": spec["chains"], "source_review_id": source["review_id"]}
        block = gemmi.cif.read_string(cif).sole_block()
        structure = gemmi.make_structure_from_block(block)
        require(len(structure) == 1, "原件多模型，未授权任意取一个")
        converted = _write_text(folder / "original_conversion.pdb", structure.make_pdb_string(), "ascii")
        protein = _protein_pdb(converted, set(spec["chains"]), spec.get("altloc"))
        pocket_keys = None
        if spec["pocket"] == "reference":
            require(match[0]["reference_count_matches"] and not match[0]["reference_covalent_count"],
                    "共晶参考缺原子或存在共价连接")
            reference = _ligand_lines(converted, spec["reference_code"], spec["reference_chain"],
                                      spec["reference_sequence"], spec.get("altloc"))
            box = reference_box(reference, box_padding)
            ccd = download_ccd(spec["reference_code"], folder)
            prepared = prepare_reference_ligand(ccd.read_text(encoding="utf-8"), reference,
                spec["reference_code"], spec["reference_chain"], spec["reference_sequence"],
                _meeko_settings())
            ref_sdf = _write_text(folder / "reference.sdf", prepared["sdf_text"])
            ref_qt = _write_text(folder / "reference.pdbqt", prepared["pdbqt_text"], "ascii")
            evidence["reference"] = {k: spec[k] for k in (
                "reference_code", "reference_chain", "reference_sequence")}
        else:
            progress("两次预测首位口袋：" + row["symbol"])
            pdb = _write_text(folder / "prediction_input.pdb", protein, "ascii")
            predicted = run_twice(tools / "environments/p2rank_2.5", pdb,
                                  folder / "p2rank", row["symbol"], root)
            raw_rows = [_prediction_rows(verified_file(root, r))[0] for r in
                        predicted["files"] if r["role"] == "p2rank_prediction"]
            from science_modules.a06.two_pass import pocket_key
            shared = {k: raw_rows[0][k] for k in (
                "rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids")}
            require(shared == {k: raw_rows[1][k] for k in shared}, "首位预测证据不一致")
            pocket_keys = _residue_keys(shared["residue_ids"])
            pocket = {"rank": 1, "runs": [shared, shared], "mapped_indices": sorted(
                      shared["residue_ids"].split()), "confirmation": {}}
            pocket["pocket_key"] = pocket_key(spec, pocket)
            evidence["pocket"] = pocket
            box = prediction_box(protein, shared, box_padding)
            write_json(folder / "plan_box.json", box)
            predicted["original_fixed_padding_box"] = predicted["box"]
            predicted["box"] = box
            evidence["predicted_pocket"] = predicted
        evidence["box"] = box
        env = environment_audit(cif, spec, box, pocket_keys)
        evidence.update(pocket_complete=env["pocket_complete"],
                        environment_resolved=env["environment_resolved"], environment_audit=env)
        progress("准备受体：" + row["symbol"] + " / " + spec["pdb_id"])
        receptor = _prepare_receptor_cli(tools, protein, box, row["symbol"], folder)
        evidence.update(receptor_ready=True, receptor=file_record(root, receptor, "receptor"))
        # 未解决环境或不完整口袋不执行无科学保障的重对接。
        if spec["pocket"] == "reference" and env["pocket_complete"] and env["environment_resolved"]:
            progress("参考配体Top-1重对接：" + row["symbol"])
            rmsd, output = redock(
                tools / "environments/vina_1.2.7/vina_1.2.7_win.exe",
                receptor, ref_qt, ref_sdf, box, row["symbol"], folder,
                vina_parameters)
            evidence.update(top1_rmsd=rmsd,
                redocking_output=file_record(root, output, "redocking_output"),
                reference_sdf=file_record(root, ref_sdf, "reference_sdf"),
                reference_pdbqt=file_record(root, ref_qt, "reference_pdbqt"))
        if not env["pocket_complete"]:
            evidence["error_zh"] = "口袋缺原子或邻接未观测片段，保留待补，不自动补建"
        elif not env["environment_resolved"]:
            evidence["error_zh"] = "搜索盒内伴随组分或复合物环境待核定"
        elif spec["pocket"] == "p2rank":
            evidence["error_zh"] = "两次首位口袋一致；具体预测证据仍待用户一次集中确认"
    except Exception as error:
        evidence["error_zh"] = str(error)
    evidence["files"] = [file_record(root, p, "quality_evidence") for p in folder.rglob("*")
                         if p.is_file()]
    write_json(folder / "evidence.json", evidence)
    return evidence


def run_engine(root, context, source, plan, folder, tools, progress):
    """完整遍历名单，第一遍通过就不跑第二遍，补救失败仍保留全部组合。"""
    compounds = prepare_compounds(root, source, plan, folder, progress)
    evidence = {}
    for row in plan["receptors"]:
        target = row["target_id"]
        evidence[target] = {"first": None, "second": None}
        if row.get("unavailable"):
            continue
        if row.get("first"):
            evidence[target]["first"] = attempt(root, source, row, row["first"], 1,
                    folder / "receptors" / target_folder(target) / "first", tools, progress)
            outcome = assess_attempt(row["first"], evidence[target]["first"], row, 1)
            if outcome["state"] == "ready":
                continue
        if row.get("second"):
            evidence[target]["second"] = attempt(root, source, row, row["second"], 2,
                    folder / "receptors" / target_folder(target) / "second", tools, progress)
    return evidence, compounds
