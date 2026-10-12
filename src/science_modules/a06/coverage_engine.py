"""A06第二版实际候选质控：独立补救、真实原件和待采纳状态；批量评分始终关闭。"""

from copy import deepcopy
from contracts import require
from storage import write_json, file_record, verified_file
from docking_top10_execute import (
    _write_text,
    _ligand_lines,
    _box_from_lines,
    _prepare_receptor_cli,
    _current_redock,
    _meeko_settings,
)
from docking_reference_ligand import prepare_reference_ligand
from docking_p2rank import run_twice, _prediction_rows, _residue_keys
from science_modules.a06.quality_engine import download_ccd, target_folder
from science_modules.a06.coverage_geometry import (
    audit,
    extract_receptor,
    compare_missing,
    canonical_map,
)
from science_modules.a06.coverage_sources import (
    experimental,
    alphafold,
    supplemental_candidates,
)
from science_modules.a06.two_pass import confidence, pocket_key

VERSION = "A06.coverage.execution.4"
CONFIG = {
    "version": VERSION,
    "geometry_rule": "A06.pocket_environment.3",
    "batch_docking_allowed": False,
    "automatic_approval": False,
}


def eligible(evidence, spec):
    """技术资格不含人工签名；预测残基、置信度与环境均先核对，最终确认另存。"""
    if not all(
        evidence.get(k) is True
        for k in ("receptor_ready", "pocket_complete", "environment_resolved")
    ):
        return False
    if spec["pocket"] == "reference":
        rmsd = evidence.get("top1_rmsd")
        return (
            isinstance(rmsd, (int, float))
            and not isinstance(rmsd, bool)
            and 0 <= rmsd <= 2
        )
    if spec["source_type"] == "alphafold" and not evidence.get(
        "confidence_facts", {}
    ).get("passed"):
        return False
    pocket = evidence.get("pocket", {})
    return (
        pocket.get("rank") == 1
        and len(pocket.get("runs", [])) == 2
        and pocket["runs"][0] == pocket["runs"][1]
    )


def attempt(root, origin, target, round_no, folder, tools, progress, controls=None):
    """执行单个独立候选；保留原件、口袋、环境和RMSD，不重复调参寻找过线姿势。"""
    import gemmi

    folder.mkdir(parents=True, exist_ok=False)
    spec = origin["spec"]
    result = {
        "spec": spec,
        "round": round_no,
        "structure_id": spec.get("pdb_id", spec.get("model_id")),
        "receptor_ready": False,
        "pocket_complete": False,
        "environment_resolved": False,
        "quality_zh": "待补／无法计算",
        "eligible": False,
        "reason_zh": "",
        "files": [],
        "source_file": origin["file"],
        "source_audit": origin["audit"],
    }
    try:
        require(
            all(x["identity_check"] == "matched" for x in origin["audit"]["identity"]),
            "结构目标身份未通过",
        )
        original = verified_file(root, origin["file"])
        text = original.read_text("utf-8")
        input_block = gemmi.cif.read_string(text).sole_block()
        if (
            target.get("required_site_positions")
            and spec["source_type"] == "experimental"
        ):
            mapping = set(canonical_map(input_block, spec).values())
            require(
                set(target["required_site_positions"]) <= mapping,
                "独立候选未覆盖原位点相关功能域，不移到其他结构域凑数",
            )
        st = gemmi.make_structure_from_block(input_block)
        converted = _write_text(
            folder / "original_conversion.pdb", st.make_pdb_string(), "ascii"
        )
        result["identity"] = {
            "target_id": target["target_id"],
            "uniprot": spec["uniprot"],
            "species": 9606,
            "polymer_type": "Protein",
            "sequence_matches": True,
            "chains": spec["chains"],
        }
        pocket_keys = None
        if spec["pocket"] == "reference":
            reference = _ligand_lines(
                converted,
                spec["reference_code"],
                spec["reference_chain"],
                spec["reference_sequence"],
                spec.get("altloc"),
            )
            box = _box_from_lines(reference)
            ccd = download_ccd(spec["reference_code"], folder)
            prepared = prepare_reference_ligand(
                ccd.read_text("utf-8"),
                reference,
                spec["reference_code"],
                spec["reference_chain"],
                spec["reference_sequence"],
                _meeko_settings(),
            )
            sdf = _write_text(folder / "reference.sdf", prepared["sdf_text"])
            qt = _write_text(
                folder / "reference.pdbqt", prepared["pdbqt_text"], "ascii"
            )
        else:
            prediction_input = _write_text(
                folder / "prediction_input.pdb",
                extract_receptor(converted, spec, []),
                "ascii",
            )
            progress(
                "两次首位口袋预测：" + target["symbol"] + " / " + result["structure_id"]
            )
            predicted = run_twice(
                tools / "environments/p2rank_2.5",
                prediction_input,
                folder / "p2rank",
                target["symbol"],
                root,
            )
            raw = [
                _prediction_rows(verified_file(root, r))[0]
                for r in predicted["files"]
                if r["role"] == "p2rank_prediction"
            ]
            shared = {
                k: raw[0][k]
                for k in (
                    "rank",
                    "score",
                    "probability",
                    "center_x",
                    "center_y",
                    "center_z",
                    "residue_ids",
                )
            }
            require(shared == {k: raw[1][k] for k in shared}, "首位口袋两次输出不一致")
            pocket_keys = _residue_keys(shared["residue_ids"])
            indices = sorted(shared["residue_ids"].split())
            if spec["source_type"] == "alphafold":
                indices = sorted(int(seq) - 1 for chain, seq in pocket_keys)
                require(len(indices) == len(pocket_keys), "预测模型口袋残基映射不完整")
                data = {**origin["confidence"], "pocket_indices": indices}
                result["confidence_facts"] = confidence(data)
                result["confidence"] = data
                result["identity"].update(
                    sequence_start=spec["sequence_start"],
                    sequence_end=spec["sequence_end"],
                )
                require(
                    result["confidence_facts"]["passed"],
                    "口袋置信度未达到80／70／10边界",
                )
            pocket = {
                "rank": 1,
                "runs": [shared, shared],
                "mapped_indices": indices,
                "confirmation": {},
            }
            pocket["pocket_key"] = pocket_key(spec, pocket)
            if target.get("required_site_positions"):
                if spec["source_type"] == "alphafold":
                    positions = {i + spec["sequence_start"] for i in indices}
                else:
                    mapped = canonical_map(input_block, spec)
                    positions = {mapped.get(tuple(k)) for k in pocket_keys}
                expected = target["required_site_positions"]
                require(
                    None not in positions
                    and positions
                    and min(positions) <= max(expected)
                    and max(positions) >= min(expected),
                    "首位预测口袋位于另一结构域，不改取后续口袋",
                )
            result.update(pocket=pocket, predicted_pocket=predicted)
            box = predicted["box"]
        env = audit(text, spec, box, pocket_keys)
        env["missing_reviews"] = []
        if (env["unobserved_residues"] or env["missing_pocket_atoms"]) and spec[
            "source_type"
        ] == "experimental":
            for candidate in (controls or {}).get("candidates", []):
                if candidate["pdb_id"] == spec["pdb_id"]:
                    continue
                if not any(
                    x.get("mutation_count") == 0 for x in candidate["target_chains"]
                ):
                    continue
                try:
                    comparison = experimental(
                        root,
                        controls,
                        candidate["pdb_id"],
                        folder / "controls" / candidate["pdb_id"],
                        "p2rank",
                    )
                    reviews = compare_missing(
                        text,
                        spec,
                        env,
                        comparison,
                        verified_file(root, comparison["file"]).read_text("utf-8"),
                    )
                    env["missing_reviews"].extend(reviews)
                    decided = {
                        (r["chain"], r["sequence"], r.get("atom")) for r in reviews
                    }
                    env["unobserved_residues"] = [
                        r
                        for r in env["unobserved_residues"]
                        if (r["chain"], r["sequence"], r.get("atom")) not in decided
                    ]
                    env["missing_pocket_atoms"] = [
                        r
                        for r in env["missing_pocket_atoms"]
                        if (r["chain"], r["sequence"], r.get("atom")) not in decided
                    ]
                    if (
                        not env["unobserved_residues"]
                        and not env["missing_pocket_atoms"]
                    ):
                        break
                except Exception:
                    continue
            env["pocket_complete"] = (
                not env["unobserved_residues"] and not env["missing_pocket_atoms"]
            )
        result.update(
            box=box,
            environment_audit=env,
            pocket_complete=env["pocket_complete"],
            environment_resolved=env["environment_resolved"],
        )
        protein = extract_receptor(
            converted, spec, env["retained_cofactors"], env["retained_partner_chains"]
        )
        progress("候选受体准备：" + target["symbol"] + " / " + result["structure_id"])
        receptor = _prepare_receptor_cli(tools, protein, box, target["symbol"], folder)
        # 明确保留的金属必须出现在准备输出，不能工具静默丢失后通过。
        qt_text = receptor.read_text("ascii")
        require(
            all(
                any(
                    line.startswith(("ATOM", "HETATM")) and line[17:20].strip() == code
                    for line in qt_text.splitlines()
                )
                for _, code, _ in env["retained_cofactors"]
            ),
            "参数化输出丢失必要金属",
        )
        result.update(
            receptor_ready=True, receptor=file_record(root, receptor, "receptor")
        )
        require(
            env["pocket_complete"],
            "存在未解决缺失；需完整独立结构对照或更换结构，不补建",
        )
        require(env["environment_resolved"], "必要环境待核定；不能删除后放行")
        if spec["pocket"] == "reference":
            progress(
                "候选参考配体Top-1重对接："
                + target["symbol"]
                + " / "
                + result["structure_id"]
            )
            rmsd, output = _current_redock(
                tools / "environments/vina_1.2.7/vina_1.2.7_win.exe",
                receptor,
                qt,
                sdf,
                box,
                target["symbol"],
                folder,
            )
            result.update(
                top1_rmsd=rmsd,
                redocking_output=file_record(root, output, "redocking_output"),
                reference_sdf=file_record(root, sdf, "reference_sdf"),
                reference_pdbqt=file_record(root, qt, "reference_pdbqt"),
            )
            require(rmsd <= 2, "Top-1重对接RMSD超过2Å，保留失败，不调整参数")
            result.update(
                quality_zh="严格", reason_zh="参考配体严格质控通过；待最终采纳"
            )
        else:
            result.update(
                quality_zh="探索",
                reason_zh="首位预测口袋两次一致，位点依据待集中确认；RMSD不适用",
            )
        result["eligible"] = eligible(result, spec)
    except Exception as error:
        result["reason_zh"] = str(error)
    result["files"] = origin["files"] + [
        file_record(root, p, "quality_evidence")
        for p in folder.rglob("*")
        if p.is_file()
    ]
    write_json(folder / "evidence.json", result)
    return result


def candidate_pool(metadata, first_spec, failures):
    """优先目标同域实验结构；剔除已知突变、短肽、失败原结构，排序仅用于核查顺序。"""
    items = []
    origin = next(
        (
            c
            for c in metadata["candidates"]
            if first_spec and c["pdb_id"] == first_spec.get("pdb_id")
        ),
        None,
    )
    original_length = max(
        (x["length"] for x in (origin or {}).get("target_chains", [])), default=0
    )
    for c in metadata["candidates"]:
        if (
            c["pdb_id"] in failures
            or c.get("blocked_previous_failure")
            or c.get("source_rejected")
        ):
            continue
        targets = [x for x in c["target_chains"] if x.get("mutation_count") == 0]
        if not targets:
            continue
        size = max(x["length"] for x in targets)
        if original_length and size < original_length / 2:
            continue
        if (
            not c.get("ligands")
            and first_spec
            and first_spec.get("pocket") == "reference"
        ):
            continue
        # 这只是排除明显不同短片段的候选预筛，不是科学通过阈值。
        items.append(c)
    return items


def run(root, context, source, plan, metadata, previous, folder, tools, progress):
    """完整17项技术核查；成功可引用已校验历史，失败尝试独立来源，仍不批准正式方案。"""
    rows = []
    originals = {r["target_id"]: r for r in source["receptors"]}
    candidates = {r["target_id"]: r for r in metadata["receptors"]}
    for target in plan["receptors"]:
        progress("核查受体：" + target["symbol"])
        tid = target["target_id"]
        meta = candidates[tid]
        home = folder / "receptors" / target_folder(tid)
        home.mkdir(parents=True, exist_ok=True)
        attempts = []
        previous_attempts = previous["evidence"][tid]
        chosen = None
        # 无改动的严格成功证据完整引用，不改写文件或重算评分。
        old_spec = target.get("first")
        old = previous_attempts.get("first")
        if (
            old
            and old_spec
            and old.get("top1_rmsd") is not None
            and old["top1_rmsd"] <= 2
            and all(
                old.get(k) is True
                for k in ("receptor_ready", "pocket_complete", "environment_resolved")
            )
        ):
            for record in old["files"]:
                verified_file(root, record)
            chosen = {
                **deepcopy(old),
                "spec": deepcopy(old_spec),
                "round": 1,
                "quality_zh": "严格",
                "eligible": True,
                "reason_zh": "原成功证据及输入、工具指纹已核对；待最终采纳",
                "reused_from_run": previous["run_id"],
            }
            attempts.append(chosen)
        spec = target.get("first") or target.get("second")
        if spec:
            import gemmi

            origin_row = originals[tid]
            original_file = next(
                f["file"] for f in source["files"] if f["key"] == origin_row["file_key"]
            )
            original_text = verified_file(root, original_file).read_text("utf-8")
            old_evidence = (
                previous_attempts.get("first") or previous_attempts.get("second") or {}
            )
            if old_evidence.get("box"):
                keys = (
                    _residue_keys(old_evidence["pocket"]["runs"][0]["residue_ids"])
                    if old_evidence.get("pocket")
                    else None
                )
                facts = audit(original_text, spec, old_evidence["box"], keys)
                mapped = canonical_map(
                    gemmi.cif.read_string(original_text).sole_block(), spec
                )
                positions = sorted(
                    {
                        mapped[tuple(k)]
                        for k in facts["pocket_residues"]
                        if tuple(k) in mapped
                    }
                )
                target = deepcopy(target)
                target["required_site_positions"] = positions
        failed_ids = {spec["pdb_id"]} if spec else set()
        extended = deepcopy(meta)
        if not chosen:
            try:
                current = next(
                    (
                        c
                        for c in meta["candidates"]
                        if spec and c["pdb_id"] == spec.get("pdb_id")
                    ),
                    {},
                )
                minimum = (
                    max(
                        (x["length"] for x in current.get("target_chains", [])),
                        default=0,
                    )
                    // 2
                )
                extended["candidates"].extend(
                    supplemental_candidates(root, meta, home / "supplemental", minimum)
                )
            except Exception as error:
                attempts.append(
                    {
                        "spec": {"source_type": "experimental", "pdb_id": "待补检索"},
                        "round": 2,
                        "eligible": False,
                        "quality_zh": "待补／无法计算",
                        "reason_zh": "独立候选补充检索失败：" + str(error),
                        "files": [],
                    }
                )
        if not chosen and spec:
            origin = originals[tid]
            old = (
                previous_attempts.get("first") or previous_attempts.get("second") or {}
            )
            if old.get("top1_rmsd") is not None and old["top1_rmsd"] > 2:
                attempts.append(
                    {
                        **deepcopy(old),
                        "spec": spec,
                        "round": 1,
                        "eligible": False,
                        "quality_zh": "待补／无法计算",
                        "reason_zh": "原Top-1 RMSD超过2Å，必须独立结构补救",
                    }
                )
            else:
                origin = {
                    "spec": deepcopy(spec),
                    "audit": origin["audit"],
                    "file": next(
                        f["file"]
                        for f in source["files"]
                        if f["key"] == origin["file_key"]
                    ),
                    "files": [
                        f["file"]
                        for f in source["files"]
                        if f["key"] == origin["file_key"]
                    ],
                }
                chosen = attempt(
                    root,
                    origin,
                    target,
                    1 if target.get("first") else 2,
                    home / "current",
                    tools,
                    progress,
                    extended,
                )
                attempts.append(chosen)
                if not chosen["eligible"]:
                    chosen = None
        pool = candidate_pool(extended, spec, failed_ids)
        for candidate in pool:
            if chosen:
                break
            pdb = candidate["pdb_id"]
            progress("核查独立候选：" + target["symbol"] + " / " + pdb)
            try:
                origin = experimental(
                    root, meta, pdb, home / ("source_" + pdb), "reference"
                )
                evidence = attempt(
                    root,
                    origin,
                    target,
                    2,
                    home / ("quality_" + pdb),
                    tools,
                    progress,
                    extended,
                )
                attempts.append(evidence)
                if evidence["eligible"]:
                    chosen = evidence
            except Exception as error:
                attempts.append(
                    {
                        "spec": {"pdb_id": pdb, "source_type": "experimental"},
                        "round": 2,
                        "eligible": False,
                        "quality_zh": "待补／无法计算",
                        "reason_zh": str(error),
                        "files": [],
                    }
                )
        if not chosen:
            # 无共晶时再核查独立实验探索来源；不换失败原结构的口袋。
            for candidate in pool:
                pdb = candidate["pdb_id"]
                if any(
                    a["spec"].get("pdb_id") == pdb
                    and (
                        a.get("top1_rmsd") is not None
                        or a.get("environment_audit")
                        and (
                            not a.get("pocket_complete")
                            or not a.get("environment_resolved")
                        )
                    )
                    for a in attempts
                ):
                    continue
                try:
                    origin = experimental(
                        root, meta, pdb, home / ("source_" + pdb), "p2rank"
                    )
                    evidence = attempt(
                        root,
                        origin,
                        target,
                        2,
                        home / ("prediction_" + pdb),
                        tools,
                        progress,
                        extended,
                    )
                    attempts.append(evidence)
                    if evidence["eligible"]:
                        chosen = evidence
                        break
                except Exception as error:
                    attempts.append(
                        {
                            "spec": {"pdb_id": pdb, "source_type": "experimental"},
                            "round": 2,
                            "eligible": False,
                            "quality_zh": "待补／无法计算",
                            "reason_zh": str(error),
                            "files": [],
                        }
                    )
        if not chosen:
            try:
                origin = alphafold(root, meta, home / "alphafold_source")
                evidence = attempt(
                    root, origin, target, 2, home / "alphafold_quality", tools, progress
                )
                # 源蛋白需要伙伴或金属时，单体预测模型不能自动解决该环境。
                base_env = next(
                    (
                        a.get("environment_audit", {})
                        for a in attempts
                        if spec and a["spec"].get("pdb_id") == spec.get("pdb_id")
                    ),
                    {},
                )
                if (
                    base_env.get("retained_cofactors")
                    or base_env.get("retained_partner_chains")
                    or any(
                        x.get("polymer")
                        for x in base_env.get("unresolved_environment", [])
                    )
                ):
                    evidence.update(
                        eligible=False,
                        environment_resolved=False,
                        reason_zh="模型口袋即使满足置信度，必要伙伴／辅因子仍待解决",
                    )
                attempts.append(evidence)
                if evidence["eligible"]:
                    chosen = evidence
            except Exception as error:
                attempts.append(
                    {
                        "spec": {"source_type": "alphafold", "model_id": "待补"},
                        "round": 2,
                        "eligible": False,
                        "quality_zh": "待补／无法计算",
                        "reason_zh": str(error),
                        "files": [],
                    }
                )
        final = chosen or attempts[-1]
        value = {k: target[k] for k in ("target_id", "symbol", "candidate_grade")}
        value.update(
            attempts=attempts,
            selected=deepcopy(chosen),
            eligible=bool(chosen),
            quality_zh=chosen["quality_zh"] if chosen else "待补／无法计算",
            status_zh=(
                "严格可用，待最终采纳"
                if chosen and chosen["quality_zh"] == "严格"
                else "探索可用，待位点确认"
                if chosen
                else "待补／无法计算"
            ),
            reason_zh=final["reason_zh"],
            pdb_id=final["spec"].get("pdb_id", final["spec"].get("model_id", "")),
            ppi_order=next(
                r["ppi_order"] for r in context["receptors"] if r["target_id"] == tid
            ),
            adopted=False,
        )
        rows.append(value)
        write_json(home / "summary.json", value)
    return rows
