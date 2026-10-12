"""A06最终证据审计：原位点和必要环境再次核对，只读既有计算，不补评分。"""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import shutil
from contracts import require
from storage import read_json, write_json, verified_file, file_record
from science_modules.a06.coverage_engine import CONFIG, VERSION, eligible
from science_modules.a06.coverage_flow import counts, reports


def audit_choice(root, row, original, original_file):
    """同一人类蛋白仍须同域并保留必要环境；完整性补正不能解除未解决辅因子。"""
    import gemmi
    from docking_p2rank import _residue_keys
    from science_modules.a06.coverage_geometry import audit, canonical_map

    chosen = row.get("selected")
    if not chosen:
        return None
    require(eligible(chosen, chosen["spec"]), "引用技术候选未满足基本边界")
    for record in chosen["files"]:
        verified_file(root, record)
    spec = original.get("first") or original.get("second")
    initial = next(
        (
            a
            for a in row["attempts"]
            if spec and a["spec"].get("pdb_id") == spec.get("pdb_id") and a.get("box")
        ),
        None,
    )
    require(initial is not None, "原位点范围资料缺失，继续待补")
    text = verified_file(root, original_file).read_text("utf-8")
    keys = (
        _residue_keys(initial["pocket"]["runs"][0]["residue_ids"])
        if initial.get("pocket")
        else None
    )
    env = audit(text, spec, initial["box"], keys)
    mapping = canonical_map(gemmi.cif.read_string(text).sole_block(), spec)
    positions = sorted(
        {mapping[tuple(k)] for k in env["pocket_residues"] if tuple(k) in mapping}
    )
    require(positions, "原位点残基缺少明确UniProt映射，继续待补")
    new_spec = chosen["spec"]
    if new_spec["source_type"] == "alphafold":
        require(
            not (
                env["retained_cofactors"]
                or env["retained_partner_chains"]
                or any(x["polymer"] for x in env["unresolved_environment"])
            ),
            "预测模型的必要伙伴／辅因子未解决，不能因置信度合格放行",
        )
        model_positions = {
            i + new_spec["sequence_start"] for i in chosen["pocket"]["mapped_indices"]
        }
    elif new_spec["pdb_id"] == spec["pdb_id"] and new_spec["chains"] == spec["chains"]:
        model_positions = set(positions)
    else:
        source = verified_file(root, chosen["source_file"]).read_text("utf-8")
        new_mapping = canonical_map(
            gemmi.cif.read_string(source).sole_block(), new_spec
        )
        require(
            set(positions) <= set(new_mapping.values()),
            "替代实验结构未覆盖原位点相关功能域",
        )
        model_positions = (
            {
                new_mapping.get(tuple(k))
                for k in _residue_keys(chosen["pocket"]["runs"][0]["residue_ids"])
            }
            if chosen.get("pocket")
            else set(positions)
        )
    require(
        None not in model_positions
        and model_positions
        and min(model_positions) <= max(positions)
        and max(model_positions) >= min(positions),
        "首位预测口袋不在原位点相关范围，继续待补",
    )
    return {
        "original_positions": positions,
        "selected_positions": sorted(model_positions),
        "note_zh": "已核对原位点相关UniProt范围；同域与可重复不代表结合位点已获生物学验证",
        "original_source": original_file,
    }


def prepare_final_audit(workflow, sid, payload, tools, progress):
    """新增完成证据审计版本；成功原件仍核验，失败历史以完整归档包索引保留。"""
    context, plan, plan_record, source, auth = workflow.coverage_authorization(
        sid, payload
    )
    manifest = workflow.load(sid)
    home = workflow.location(sid)
    previous_result = workflow.result(manifest, payload["expected_base_run"])
    require(
        previous_result and previous_result["outcome"] == "success",
        "只审计完整归档结果",
    )
    previous_record = previous_result["tables"]["coverage_packet"][0]
    old = read_json(verified_file(home, previous_record))
    require(
        old["source_key"] == context["source_key"]
        and old["plan_id"] == plan["plan_id"]
        and old["source_review_id"] == source["review_id"],
        "审计上游绑定不一致",
    )
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
        "最终核对原位点与必要环境；技术采用待确认，未重算评分",
    )
    folder = home / "runs/A06_PREP" / run["run_id"] / "coverage"
    folder.mkdir(parents=True, exist_ok=False)
    inputs = {r["target_id"]: r for r in plan["plan"]["receptors"]}
    source_rows = {r["target_id"]: r for r in source["receptors"]}
    rows = deepcopy(old["receptors"])
    used = [previous_record, plan_record, auth]
    for row in rows:
        progress("最终证据审计：" + row["symbol"])
        row["adopted"] = False
        origin = source_rows[row["target_id"]]
        record = next(
            f["file"] for f in source["files"] if f["key"] == origin["file_key"]
        )
        used.append(record)
        chosen = row.get("selected")
        if chosen:
            try:
                facts = audit_choice(home, row, inputs[row["target_id"]], record)
                chosen["site_coverage"] = facts
                row["attempts"].append(
                    {
                        **deepcopy(chosen),
                        "reason_zh": "最终环境与同域证据已核对；仍待用户采用",
                    }
                )
                used.extend(chosen["files"])
            except ValueError as error:
                row["attempts"].append(
                    {
                        **deepcopy(chosen),
                        "eligible": False,
                        "reason_zh": str(error),
                        "environment_resolved": False,
                    }
                )
                row.update(
                    selected=None,
                    eligible=False,
                    quality_zh="待补／无法计算",
                    status_zh="待补／无法计算",
                    reason_zh=str(error),
                )
        write_json(
            folder / ("target_" + row["target_id"].replace(":", "_") + ".json"), row
        )
    for name in (
        "coverage_final_audit.py",
        "coverage_engine.py",
        "coverage_flow.py",
        "coverage_geometry.py",
    ):
        dest = folder / "code" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / name, dest)
    packet = deepcopy(old)
    packet.update(
        schema_version=VERSION,
        run_id=run["run_id"],
        campaign_id="campaign_" + uuid4().hex,
        receptors=rows,
        counts=counts(rows),
        confirmation=None,
        previous_evidence_packet=previous_record,
    )
    # 当前准备输入完整校验；失败原件在 previous_evidence_packet 对应历史运行完整留存。
    # 不把数万份历史失败文件再复制为当前准备输入，历史查看仍按自身索引核验。
    used.extend(
        file_record(home, f, "coverage_audit") for f in folder.rglob("*") if f.is_file()
    )
    packet["files"] = list({r["path"]: r for r in used}.values())
    path = folder / "packet.json"
    write_json(path, packet)
    summary, tables = reports(packet)
    record = file_record(home, path, "coverage_packet")
    tables["coverage_packet"] = [record]
    return workflow.finish_coverage(
        sid, run["run_id"], payload, summary, tables, packet["files"] + [record]
    )
