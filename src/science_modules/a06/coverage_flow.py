"""A06扩大覆盖结果契约与生产入口：技术证据待采纳，集中采用另建版本。"""

from copy import deepcopy
from pathlib import Path
import hashlib, subprocess
from uuid import uuid4
from contracts import require, fingerprint
from storage import read_json, write_json, verified_file, file_record
from science_modules.a06.coverage_engine import run, VERSION, CONFIG, eligible
from science_modules.a06.two_pass import VINA, VINA_VERSION


def counts(rows):
    """只计入具备完整证据的技术候选，明确区分未通过者。"""
    return {
        "strict": sum(r["eligible"] and r["quality_zh"] == "严格" for r in rows),
        "exploration": sum(r["eligible"] and r["quality_zh"] == "探索" for r in rows),
        "unavailable": sum(not r["eligible"] for r in rows),
        "receptors": len(rows),
    }


def confirm_packet(packet, decision):
    """只给用户主动采用的完整候选写入确认，未采用和未解决项不产生准备资格。"""
    out = deepcopy(packet)
    selected = set(decision["selected_target_ids"])
    require(
        selected <= set(r["target_id"] for r in packet["receptors"] if r["eligible"]),
        "不能确认未具备证据的受体",
    )
    out["confirmation"] = deepcopy(decision)
    for row in out["receptors"]:
        row["adopted"] = row["target_id"] in selected
        if row["adopted"] and row["selected"].get("pocket"):
            p = row["selected"]["pocket"]
            p["confirmation"] = {
                "confirmed": True,
                "reviewer": decision["reviewer"],
                "note": decision["note"],
                "pocket_key": p["pocket_key"],
            }
    out["schema_version"] = "A06.coverage.confirmed.4"
    return out


def reports(packet):
    """完整15×17计划只来自同批准备事实，探索不能充当主要五，未知结果均无评分。"""
    rows = packet["receptors"]
    strict = [
        r for r in rows if r["adopted"] and r["eligible"] and r["quality_zh"] == "严格"
    ]
    strict.sort(key=lambda r: (r["ppi_order"], r["target_id"]))
    primary = [r["target_id"] for r in strict[:5]] if len(strict) >= 5 else []
    ready = {r["target_id"] for r in rows if r["adopted"] and r["eligible"]}
    key = fingerprint(
        {
            "source_key": packet["source_key"],
            "receptors": rows,
            "compounds": packet["compounds"],
            "vina": VINA,
            "version": VERSION,
        }
    )
    pairs = [
        {
            "input_key": key,
            "compound_id": c["compound_id"],
            "target_id": r["target_id"],
            "state": "ready"
            if c["state"] == "ready" and r["target_id"] in ready
            else "NA",
            "reason_zh": ""
            if c["state"] == "ready" and r["target_id"] in ready
            else (
                c["reason_zh"]
                if c["state"] != "ready"
                else "技术候选尚未确认采用"
                if r["eligible"] and not r["adopted"]
                else r["reason_zh"]
            ),
        }
        for c in packet["compounds"]
        for r in rows
    ]
    done = sum(p["state"] == "ready" for p in pairs)
    pending = not packet.get("confirmation")
    c = counts(rows)
    summary = {
        "analysis_purpose": packet["context"]["analysis_purpose"],
        "计划组合数": len(pairs),
        "成分数": len(packet["compounds"]),
        "受体核查数": len(rows),
        "严格质控通过受体数": c["strict"],
        "探索候选受体数": c["exploration"],
        "待补受体数": c["unavailable"],
        "已确认采用受体数": len(ready),
        "主要受体数": len(primary),
        "主要结果条件满足": len(strict) >= 5,
        "探索可用条件满足": bool(ready),
        "等待集中核查受体数": sum(r["eligible"] for r in rows) if pending else 0,
        "具备准备输入组合数": done,
        "暂停组合数": len(pairs) - done,
        "实际批量评分数": 0,
        "handoff_blocked": pending or not ready,
        "说明": "技术质控与采用确认分开；主要五要求至少五个已采用严格受体。未解决项只影响自身组合，未运行批量结合能。",
    }
    diagnostics = [
        {
            "PPI顺序": r["ppi_order"],
            "受体": r["symbol"],
            "HGNC": r["target_id"],
            "候选级别": r["candidate_grade"],
            "PDB": r["pdb_id"],
            "RMSD_A": (r.get("selected") or {}).get("top1_rmsd"),
            "质控状态": r["quality_zh"]
            + ("，已采用" if r["adopted"] else "，待采纳" if r["eligible"] else ""),
            "诊断通过": r["eligible"],
            "主要结果": r["target_id"] in primary,
            "第一遍": "；".join(
                a.get("reason_zh", "") for a in r["attempts"] if a.get("round") == 1
            ),
            "第二遍": "；".join(
                a.get("reason_zh", "") for a in r["attempts"] if a.get("round") == 2
            ),
            "结构限制": r["reason_zh"],
            "已确认采用": r["adopted"],
        }
        for r in rows
    ]
    return summary, {
        "receptor_diagnostics": diagnostics,
        "planned_pairs": pairs,
        "compound_preparation": [
            {
                "成分编号": c["compound_id"],
                "成分": c["name_zh"],
                "准备状态": c["state"],
                "说明": c["reason_zh"],
            }
            for c in packet["compounds"]
        ],
    }


def validate_packet(root, packet):
    """实际文件、指标、完整范围与版本独立核对，杜绝手填RMSD或突破失败界限。"""
    from docking_redocking import _poses, symmetry_rmsd

    require(packet["batch_docking_allowed"] is False, "本轮禁止批量评分")
    require(
        packet["vina_parameters"] == VINA and packet["vina_version"] == VINA_VERSION,
        "Vina参数变化",
    )
    require(
        [r["target_id"] for r in packet["receptors"]]
        == [r["target_id"] for r in packet["context"]["receptors"]],
        "受体范围或顺序改变",
    )
    require(
        [r["compound_id"] for r in packet["compounds"]]
        == [r["compound_id"] for r in packet["context"]["compounds"]],
        "成分范围改变",
    )
    for rec in packet["files"]:
        verified_file(root, rec)
    indexed = {r["path"]: r for r in packet["files"]}
    manifest = read_json(Path(root) / "manifest.json")
    plans = [
        read_json(verified_file(root, r))
        for r in manifest.get("two_pass_plan_records", [])
    ]
    sources = [
        read_json(verified_file(root, r))
        for r in manifest.get("source_review_records", [])
    ]
    plan = next((p for p in plans if p["plan_id"] == packet["plan_id"]), None)
    source = next(
        (p for p in sources if p["review_id"] == packet["source_review_id"]), None
    )
    require(plan and source, "本研究缺少登记的原结构方案或来源核查")
    original_targets = {r["target_id"]: r for r in plan["plan"]["receptors"]}
    original_sources = {r["target_id"]: r for r in source["receptors"]}
    for row, origin in zip(packet["receptors"], packet["context"]["receptors"]):
        require(
            row["candidate_grade"] == origin["candidate_grade"]
            and row["symbol"] == origin["symbol"],
            "受体身份或A/B被改写",
        )
        chosen = row.get("selected")
        require(row["eligible"] == bool(chosen), "技术资格与所选证据不符")
        require(not row["adopted"] or row["eligible"], "不能采用失败对象")
        if chosen:
            require(
                all(indexed.get(r["path"]) == r for r in chosen["files"]),
                "采用候选原件未完整纳入当前准备输入",
            )
            from science_modules.a06.coverage_final_audit import audit_choice

            original = original_sources[row["target_id"]]
            original_file = next(
                f["file"] for f in source["files"] if f["key"] == original["file_key"]
            )
            facts = audit_choice(
                root, row, original_targets[row["target_id"]], original_file
            )
            if chosen.get("site_coverage"):
                require(
                    chosen["site_coverage"] == facts, "原位点审计事实与实际来源不符"
                )
            require(
                chosen["identity"]["target_id"] == row["target_id"]
                and chosen["identity"]["species"] == 9606
                and chosen["identity"]["uniprot"] == chosen["spec"]["uniprot"],
                "准备身份不符",
            )
            require(eligible(chosen, chosen["spec"]), "技术候选违反严格或探索边界")
            failed_ids = {
                a["spec"].get("pdb_id", a["spec"].get("model_id"))
                for a in row["attempts"]
                if a.get("top1_rmsd") is not None and a["top1_rmsd"] > 2
            }
            require(
                chosen["spec"].get("pdb_id", chosen["spec"].get("model_id"))
                not in failed_ids,
                "不能切换已失败原结构的口袋绕过重对接",
            )
            if chosen["spec"]["source_type"] == "alphafold":
                from science_modules.a06.two_pass import confidence

                require(
                    confidence(chosen["confidence"]) == chosen["confidence_facts"]
                    and chosen["confidence_facts"]["passed"],
                    "模型置信度与完整原文不符",
                )
            if chosen["spec"]["pocket"] == "p2rank":
                from science_modules.a06.two_pass import pocket_key

                require(
                    chosen["pocket"]["pocket_key"]
                    == pocket_key(chosen["spec"], chosen["pocket"]),
                    "预测口袋指纹与本结构、两次原始输出不符",
                )
            if chosen["spec"]["pocket"] == "reference":
                pose = _poses(
                    verified_file(root, chosen["redocking_output"]).read_text("ascii")
                )[0]
                rmsd = symmetry_rmsd(
                    verified_file(root, chosen["reference_sdf"]).read_bytes(),
                    verified_file(root, chosen["reference_pdbqt"]).read_text("ascii"),
                    pose,
                )["rmsd_angstrom"]
                require(
                    abs(rmsd - chosen["top1_rmsd"]) < 1e-9 and rmsd <= 2,
                    "真实Top-1 RMSD核对失败",
                )
    require(packet["counts"] == counts(packet["receptors"]), "覆盖摘要与证据不符")


def validator(root, previous):
    """旧版本完整委托原校验器；新版本核对真实包及人工决定。"""

    def check(run, summary, tables, anomalies, outcome):
        version = run.get("config", {}).get("version")
        if version not in (VERSION, "A06.coverage.confirmed.4"):
            return previous(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        records = tables.get("coverage_packet", [])
        require(
            len(records) == 1
            and records[0]["path"]
            == "runs/A06_PREP/" + run["run_id"] + "/coverage/packet.json",
            "补救事实包不是本次归档",
        )
        packet = read_json(verified_file(home, records[0]))
        require(
            packet["study_id"] == run["study_id"] and packet["run_id"] == run["run_id"],
            "质控包跨研究或运行",
        )
        require(
            all(
                packet["context"]["parent_runs"].get(k) == v
                for k, v in run["parent_runs"].items()
            )
            and all(
                packet["context"]["parent_review_ids"].get(k) == v
                for k, v in run["parent_review_ids"].items()
            ),
            "上游版本不符",
        )
        for source_record in packet["context"]["source_results"].values():
            verified_file(home, source_record)
        validate_packet(home, packet)
        if version == VERSION:
            require(run["config"] == CONFIG, "补救执行配置与授权边界不符")
            original_plan = read_json(
                verified_file(home, run["inputs"]["original_plan"])
            )
            authorization = read_json(
                verified_file(home, run["inputs"]["coverage_authorization"])
            )
            require(
                original_plan["study_id"]
                == authorization["study_id"]
                == run["study_id"]
                and original_plan["plan_id"]
                == packet["plan_id"]
                == authorization["expected_plan_id"]
                and packet["source_key"] == authorization["expected_source"]
                and packet["source_review_id"]
                == authorization["expected_source_review_id"]
                and authorization["batch_docking_allowed"] is False,
                "补救方案、来源或授权绑定不符",
            )
        if version == "A06.coverage.confirmed.4":
            decision = read_json(
                verified_file(home, run["inputs"]["coverage_selection"])
            )
            require(
                packet["confirmation"] == decision
                and decision["confirmed"] is True
                and decision["study_id"] == run["study_id"],
                "采用确认记录不匹配",
            )
            require(
                {r["target_id"] for r in packet["receptors"] if r["adopted"]}
                == set(decision["selected_target_ids"]),
                "采用范围与人工决定不符",
            )
        else:
            require(
                not packet.get("confirmation")
                and not any(r["adopted"] for r in packet["receptors"]),
                "技术核查不得代签采用",
            )
        expected = reports(packet)
        expected[1]["coverage_packet"] = records
        require(
            summary == expected[0] and tables == expected[1] and outcome == "success",
            "补救摘要或组合被改写",
        )

    return check


def prepare_coverage(workflow, sid, payload, tools, progress):
    """追加技术补救运行并保留原历史，不代签方案，不运行成分组合。"""
    context, plan, plan_record, source, auth = workflow.coverage_authorization(
        sid, payload
    )
    manifest = workflow.load(sid)
    old_result = workflow.result(manifest, payload["expected_base_run"])
    seen = set()
    while not (old_result and old_result["tables"].get("quality_packet")):
        current_id = (old_result or {}).get("run_id", payload["expected_base_run"])
        require(current_id not in seen, "质控基线引用循环")
        seen.add(current_id)
        old_run = workflow.run(manifest, current_id)
        baseline = old_run.get("inputs", {}).get("previous_quality")
        require(baseline, "缺少前轮实际质控基线")
        old_result = read_json(verified_file(workflow.location(sid), baseline))
        require(old_result["study_id"] == sid, "质控基线跨研究")
    baseline_id = old_result["run_id"]
    home = workflow.location(sid)
    previous = read_json(verified_file(home, old_result["tables"]["quality_packet"][0]))
    previous["run_id"] = baseline_id
    require(
        previous["source_key"] == context["source_key"]
        and previous["plan_id"] == plan["plan_id"],
        "成功证据属于另一来源或方案，不能复用",
    )
    metadata = workflow.current_receptor_review(manifest, context)
    exe = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    probe = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, timeout=20
    )
    require(
        probe.returncode == 0 and probe.stdout.strip() == "AutoDock Vina v1.2.7",
        "固定Vina版本不符",
    )
    require(
        previous["vina_sha256"] == hashlib.sha256(exe.read_bytes()).hexdigest(),
        "固定工具文件已改变，旧成功证据不能复用",
    )
    for c in previous["compounds"]:
        for rec in c["files"]:
            verified_file(home, rec)
    run_record = workflow.begin(
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
        "用户授权扩大覆盖技术核查；待集中采纳，不运行批量评分",
    )
    folder = home / "runs/A06_PREP" / run_record["run_id"] / "coverage"
    folder.mkdir(parents=True, exist_ok=False)
    # 代码原文随本轮来源留存；不把Git提交号当作科学缓存键。
    import shutil

    code = Path(__file__).resolve().parents[2]
    for name in (
        "coverage_engine.py",
        "coverage_geometry.py",
        "coverage_sources.py",
        "coverage_flow.py",
    ):
        dest = folder / "code" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(code / "science_modules/a06" / name, dest)
    from science_modules.a06.coverage_sources import source_cache

    cache_records = []
    for candidate_id, index in manifest["runs"].items():
        if candidate_id == run_record["run_id"] or not index.get("result_file"):
            continue
        if (
            not index["run_file"]["path"]
            .replace("\\", "/")
            .startswith("runs/A06_PREP/")
        ):
            continue
        result = workflow.result(manifest, candidate_id)
        if result and result.get("outcome") == "failed":
            failed_run = workflow.run(manifest, candidate_id)
            origin = failed_run.get("inputs", {}).get("original_plan")
            if (
                origin
                and read_json(verified_file(home, origin))["source_key"]
                == context["source_key"]
            ):
                # 中断运行本身及科学准备输出不可复用，仅采用已索引的官方原始响应字节。
                cache_records.extend(result["files"])
            continue
        if not result or not result.get("tables", {}).get("coverage_packet"):
            continue
        old_packet = read_json(
            verified_file(home, result["tables"]["coverage_packet"][0])
        )
        if (
            old_packet["source_key"] == context["source_key"]
            and old_packet["plan_id"] == plan["plan_id"]
        ):
            cache_records.extend(old_packet["files"])
    source_cache(home, cache_records)
    rows = run(
        home, context, source, plan["plan"], metadata, previous, folder, tools, progress
    )
    packet = {
        "schema_version": VERSION,
        "study_id": sid,
        "run_id": run_record["run_id"],
        "campaign_id": "campaign_" + uuid4().hex,
        "source_key": context["source_key"],
        "plan_id": plan["plan_id"],
        "source_review_id": source["review_id"],
        "context": context,
        "receptors": rows,
        "compounds": deepcopy(previous["compounds"]),
        "counts": counts(rows),
        "confirmation": None,
        "batch_docking_allowed": False,
        "vina_parameters": VINA,
        "vina_version": VINA_VERSION,
        "vina_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "files": [
            file_record(home, p, "coverage_evidence")
            for p in folder.rglob("*")
            if p.is_file()
        ]
        + [r for row in rows for a in row["attempts"] for r in a.get("files", [])],
    }
    # 复用配体仍逐字节验证，且纳入本轮完整溯源。
    packet["files"] += [r for c in packet["compounds"] for r in c["files"]]
    packet["files"] = list({r["path"]: r for r in packet["files"]}.values())
    path = folder / "packet.json"
    write_json(path, packet)
    summary, tables = reports(packet)
    record = file_record(home, path, "coverage_packet")
    tables["coverage_packet"] = [record]
    return workflow.finish_coverage(
        sid, run_record["run_id"], payload, summary, tables, packet["files"] + [record]
    )
