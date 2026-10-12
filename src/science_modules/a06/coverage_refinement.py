"""A06核查补正：只处理新增证据可解除的阻断，不重跑已失败RMSD寻找有利结果。"""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import hashlib, shutil
from contracts import require
from storage import read_json, write_json, verified_file, file_record
from science_modules.a06.coverage_engine import attempt, eligible, CONFIG, VERSION
from science_modules.a06.coverage_sources import (
    experimental,
    alphafold,
    source_cache,
    supplemental_candidates,
)
from science_modules.a06.coverage_flow import counts, reports
from science_modules.a06.quality_engine import target_folder


def prepare_refinement(workflow, sid, payload, tools, progress):
    """完整名单和成功原件指纹固定，仅给新的核查证据建立独立补正版本。"""
    context, plan, plan_record, source, auth = workflow.coverage_authorization(
        sid, payload
    )
    manifest = workflow.load(sid)
    home = workflow.location(sid)
    prior_result = workflow.result(manifest, payload["expected_base_run"])
    require(
        prior_result and prior_result.get("tables", {}).get("coverage_packet"),
        "本轮补正需完整已归档技术事实，不能复用中断科学结果",
    )
    old = read_json(verified_file(home, prior_result["tables"]["coverage_packet"][0]))
    require(
        old["source_key"] == context["source_key"]
        and old["plan_id"] == plan["plan_id"],
        "补正事实属于另一来源或方案",
    )
    for record in old["files"]:
        verified_file(home, record)
    exe = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    require(
        hashlib.sha256(exe.read_bytes()).hexdigest() == old["vina_sha256"],
        "Vina工具字节变化，不可复用",
    )
    source_cache(home, old["files"])
    metadata = workflow.current_receptor_review(manifest, context)
    by_meta = {r["target_id"]: r for r in metadata["receptors"]}
    by_source = {r["target_id"]: r for r in source["receptors"]}
    run = workflow.begin(
        sid,
        "A06_PREP",
        {
            "original_plan": plan_record,
            "coverage_authorization": auth,
            "previous_quality": manifest["runs"][payload["expected_base_run"]][
                "result_file"
            ],
        },
        CONFIG,
        "新增表达标签及来源核查证据补正；独立留存，集中采用仍待确认",
    )
    folder = home / "runs/A06_PREP" / run["run_id"] / "coverage"
    folder.mkdir(parents=True, exist_ok=False)
    src = Path(__file__).resolve().parent
    for name in (
        "coverage_refinement.py",
        "coverage_engine.py",
        "coverage_geometry.py",
        "coverage_sources.py",
        "coverage_flow.py",
    ):
        dest = folder / "code" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / name, dest)
    rows = []
    originals = {r["target_id"]: r for r in plan["plan"]["receptors"]}
    for old_row in old["receptors"]:
        row = deepcopy(old_row)
        tid = row["target_id"]
        target = deepcopy(originals[tid])
        # 补正只处理已通过同域核查、但因完整性或环境失败的候选；原位点范围仍保持。
        original_spec = target.get("first") or target.get("second")
        initial = next(
            (
                a
                for a in row["attempts"]
                if original_spec
                and a["spec"].get("pdb_id") == original_spec.get("pdb_id")
                and a.get("box")
            ),
            None,
        )
        if initial:
            import gemmi
            from docking_p2rank import _residue_keys
            from science_modules.a06.coverage_geometry import audit, canonical_map

            origin_row = by_source[tid]
            original_file = next(
                f["file"] for f in source["files"] if f["key"] == origin_row["file_key"]
            )
            original_text = verified_file(home, original_file).read_text("utf-8")
            keys = (
                _residue_keys(initial["pocket"]["runs"][0]["residue_ids"])
                if initial.get("pocket")
                else None
            )
            facts = audit(original_text, original_spec, initial["box"], keys)
            mapping = canonical_map(
                gemmi.cif.read_string(original_text).sole_block(), original_spec
            )
            target["required_site_positions"] = sorted(
                {
                    mapping[tuple(k)]
                    for k in facts["pocket_residues"]
                    if tuple(k) in mapping
                }
            )
        meta = deepcopy(by_meta[tid])
        progress("补正核查：" + row["symbol"])
        location = folder / "receptors" / target_folder(tid)
        location.mkdir(parents=True, exist_ok=True)
        chosen = row.get("selected")
        if chosen:
            # 只引用已成功、同字节的准备输入；未改变物理输入，不重复采样RMSD。
            for record in chosen["files"]:
                verified_file(home, record)
            require(eligible(chosen, chosen["spec"]), "既有成功证据未通过现行基本边界")
            chosen["reused_from_run"] = old["run_id"]
        else:
            current_spec = target.get("first") or target.get("second")
            original_length = max(
                (
                    x["length"]
                    for c in meta["candidates"]
                    if current_spec and c["pdb_id"] == current_spec.get("pdb_id")
                    for x in c["target_chains"]
                ),
                default=0,
            )
            try:
                meta["candidates"].extend(
                    supplemental_candidates(
                        home, meta, location / "supplemental", original_length // 2
                    )
                )
            except Exception:
                pass
            failed_ids = {
                a["spec"].get("pdb_id", a["spec"].get("model_id"))
                for a in row["attempts"]
                if a.get("top1_rmsd") is not None and a["top1_rmsd"] > 2
            }
            candidates = []
            for index, e in enumerate(row["attempts"]):
                spec = e["spec"]
                sid_value = spec.get("pdb_id", spec.get("model_id"))
                if (
                    sid_value in failed_ids
                    or not spec.get("uniprot")
                    or (not e.get("receptor_ready") and not e.get("confidence"))
                ):
                    continue
                # 无首位口袋、置信度未通过、身份冲突均不是靠补正文本可以解决的问题。
                if e.get("confidence_facts") and not e["confidence_facts"]["passed"]:
                    continue
                if e.get("predicted_pocket") is None and spec.get("pocket") == "p2rank":
                    continue
                if sid_value not in {c[0] for c in candidates}:
                    candidates.append((sid_value, index, spec))
            for sid_value, index, spec in candidates:
                try:
                    progress("核查新增证据：" + row["symbol"] + " / " + sid_value)
                    origin_row = by_source[tid]
                    if spec["source_type"] == "alphafold":
                        origin = alphafold(
                            home, meta, location / ("source_" + str(index))
                        )
                    elif (
                        sid_value == origin_row["pdb_id"]
                        and spec["chains"] == origin_row["chains"]
                    ):
                        origin = {
                            "spec": deepcopy(spec),
                            "audit": origin_row["audit"],
                            "file": next(
                                f["file"]
                                for f in source["files"]
                                if f["key"] == origin_row["file_key"]
                            ),
                            "files": [
                                f["file"]
                                for f in source["files"]
                                if f["key"] == origin_row["file_key"]
                            ],
                        }
                    else:
                        origin = experimental(
                            home,
                            meta,
                            sid_value,
                            location / ("source_" + str(index)),
                            spec["pocket"],
                        )
                    evidence = attempt(
                        home,
                        origin,
                        target,
                        1
                        if target.get("first")
                        and sid_value == target["first"].get("pdb_id")
                        else 2,
                        location / ("quality_" + str(index)),
                        tools,
                        progress,
                        meta,
                    )
                    if spec["source_type"] == "alphafold":
                        base_env = next(
                            (
                                a.get("environment_audit", {})
                                for a in row["attempts"]
                                if current_spec
                                and a["spec"].get("pdb_id")
                                == current_spec.get("pdb_id")
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
                                reason_zh="必要伙伴／辅因子仍待解决；不能通过模型置信度绕过",
                            )
                    row["attempts"].append(evidence)
                    if evidence["eligible"]:
                        chosen = evidence
                        break
                except Exception as error:
                    row["attempts"].append(
                        {
                            "spec": spec,
                            "round": 2,
                            "eligible": False,
                            "quality_zh": "待补／无法计算",
                            "reason_zh": str(error),
                            "files": [],
                        }
                    )
        row["selected"] = deepcopy(chosen)
        row["eligible"] = bool(chosen)
        row["adopted"] = False
        if chosen:
            row.update(
                quality_zh=chosen["quality_zh"],
                pdb_id=chosen["spec"].get("pdb_id", chosen["spec"].get("model_id", "")),
                reason_zh=chosen["reason_zh"],
                status_zh="严格可用，待最终采纳"
                if chosen["quality_zh"] == "严格"
                else "探索可用，待位点确认",
            )
        rows.append(row)
        write_json(location / "summary.json", row)
    packet = deepcopy(old)
    packet.update(
        schema_version=VERSION,
        run_id=run["run_id"],
        campaign_id="campaign_" + uuid4().hex,
        receptors=rows,
        counts=counts(rows),
        confirmation=None,
    )
    new_files = [
        file_record(home, f, "coverage_evidence")
        for f in folder.rglob("*")
        if f.is_file()
    ]
    packet["files"] = list(
        {
            r["path"]: r
            for r in old["files"]
            + new_files
            + [r for row in rows for a in row["attempts"] for r in a.get("files", [])]
        }.values()
    )
    path = folder / "packet.json"
    write_json(path, packet)
    summary, tables = reports(packet)
    record = file_record(home, path, "coverage_packet")
    tables["coverage_packet"] = [record]
    return workflow.finish_coverage(
        sid, run["run_id"], payload, summary, tables, packet["files"] + [record]
    )
