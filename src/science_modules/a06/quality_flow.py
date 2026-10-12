"""两遍真实准备的Workflow发布与历史兼容校验；不批准结果、不计算255组评分。"""
from pathlib import Path
from copy import deepcopy
import hashlib
import subprocess
from contracts import require
from storage import read_json, write_json, verified_file, file_record
from science_modules.a06.two_pass import preparation, POLICY
from science_modules.a06.quality_engine import run_engine

VERSION = "A06.two_pass.execution.1"
CONFIG = {"version": VERSION, "policy_version": POLICY,
          "batch_docking_allowed": False, "automatic_approval": False}


def reports(context, plan, evidence, compounds):
    """摘要与诊断只来自实际证据；口袋未确认及环境待核定单独显示。"""
    prep = preparation(context, plan, evidence, compounds)
    diagnostics, pending = [], 0
    source = {r["target_id"]: r for r in context["receptors"]}
    for row, planned in zip(prep["receptors"], plan["receptors"]):
        first, second = evidence[row["target_id"]]["first"], evidence[row["target_id"]]["second"]
        selected = first if row["selected_round"] == 1 else second if row["selected_round"] == 2 else second or first or {}
        spec = planned["first"] if selected is first else planned["second"] or planned["first"] or {}
        predicted = bool(selected.get("pocket")) and not selected["pocket"].get("confirmation")
        environment = bool(selected.get("environment_audit", {}).get("box_environment"))
        missing = selected.get("environment_audit", {}).get("missing_pocket_atoms", [])
        state = row["quality"] if row["state"] == "ready" else (
            "待核定必要环境" if environment else "口袋缺失待补" if missing else
            "预测口袋待确认" if predicted and selected.get("receptor_ready") else "准备失败 / NA")
        if state.startswith("待核定") or state.startswith("预测口袋"):
            pending += 1
        diagnostics.append({"PPI顺序": source[row["target_id"]]["ppi_order"],
            "受体": row["symbol"], "HGNC": row["target_id"], "候选级别": row["candidate_grade"],
            "第一遍": row["first"]["reason_zh"], "第二遍": row["second"]["reason_zh"],
            "PDB": spec.get("pdb_id", ""), "RMSD_A": selected.get("top1_rmsd"),
            "质控状态": state, "诊断通过": row["state"] == "ready",
            "主要结果": row["target_id"] in prep["primary_targets"],
            "结构限制": selected.get("error_zh") or selected.get("environment_audit", {}).get("note_zh", ""),
            "失败原因": "；".join(x.get("error_zh", "") for x in (first, second) if x and x.get("error_zh")),
            "预测口袋证据键": selected.get("pocket", {}).get("pocket_key", "")})
    ready = sum(r["state"] == "ready" for r in prep["planned_pairs"])
    summary = {"analysis_purpose": context["analysis_purpose"],
        "计划组合数": len(prep["planned_pairs"]), "成分数": len(compounds),
        "来源三维准备成功数": sum(c["state"] == "ready" for c in compounds),
        "受体核查数": len(diagnostics), "严格质控通过受体数": prep["strict_count"],
        "主要受体数": len(prep["primary_targets"]),
        "探索通过受体数": sum(r["state"] == "ready" and r["quality"] == "探索" for r in prep["receptors"]),
        "等待集中核查受体数": pending, "具备准备输入组合数": ready,
        "暂停组合数": len(prep["planned_pairs"]) - ready, "实际批量评分数": 0,
        "handoff_blocked": not prep["primary_conditions_met"] or pending > 0 or ready == 0,
        "说明": "本轮仅结构准备、口袋预测与参考配体重对接；未运行成分×受体结合能计算。预测口袋未人工确认、必要环境未解决时保持待核查。"}
    tables = {"receptor_diagnostics": diagnostics,
        "compound_preparation": [{"成分": c["name_zh"], "成分编号": c["compound_id"],
                "CID": c["cid"], "准备状态": c["state"], "说明": c["reason_zh"]} for c in compounds],
        "planned_pairs": prep["planned_pairs"]}
    return prep, summary, tables


def validator(root, previous):
    """新版复核重算纯契约与RMSD文件；旧科研结果完整委托原校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("version") != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        require(run["config"] == CONFIG, "真实准备配置与授权边界不符")
        record = tables.get("quality_packet", [])
        require(len(record) == 1 and record[0]["path"] == "runs/A06_PREP/" + run["run_id"] + "/quality/packet.json",
                "准备事实包未登记或不属于本次运行")
        packet = read_json(verified_file(home, record[0]))
        plan = read_json(verified_file(home, run["inputs"]["two_pass_plan"]))
        source = read_json(verified_file(home, run["inputs"]["source_review"]))
        authorization = read_json(verified_file(home, run["inputs"]["quality_authorization"]))
        require(packet["study_id"] == plan["study_id"] == source["study_id"] == authorization["study_id"]
                == run["study_id"], "准备资料跨研究")
        require(packet["source_key"] == source["source_key"] == plan["source_key"]
                == authorization["expected_source"]
                and plan["plan_id"] == authorization["expected_plan_id"]
                and source["review_id"] == authorization["expected_source_review_id"],
                "准备来源、方案或授权不一致")
        require(all(packet["context"]["parent_runs"].get(name) == value
                    for name, value in run["parent_runs"].items()), "准备上游来源不符")
        require(all(packet["context"]["parent_review_ids"].get(name) == value
                    for name, value in run["parent_review_ids"].items()), "准备上游复核来源不符")
        for record in packet["context"]["source_results"].values():
            verified_file(home, record)
        for record in source["files"]:
            verified_file(home, record["file"])
        for record in packet["files"]:
            verified_file(home, record)
        # 实际Top-1坐标与参考身份重新计算，不信任手工填入的RMSD。
        from docking_redocking import _poses, symmetry_rmsd
        for attempts in packet["evidence"].values():
            for evidence in attempts.values():
                if evidence and evidence.get("top1_rmsd") is not None:
                    pose = _poses(verified_file(home, evidence["redocking_output"]).read_text("ascii"))[0]
                    value = symmetry_rmsd(
                        verified_file(home, evidence["reference_sdf"]).read_bytes(),
                        verified_file(home, evidence["reference_pdbqt"]).read_text("ascii"), pose)["rmsd_angstrom"]
                    require(abs(value - evidence["top1_rmsd"]) < 1e-9, "重对接RMSD与真实Top-1文件不一致")
        expected = reports(packet["context"], plan["plan"], packet["evidence"], packet["compounds"])
        expected[2]["quality_packet"] = tables["quality_packet"]
        require(packet["preparation"] == expected[0] and summary == expected[1]
                and tables == expected[2] and outcome == "success", "质控摘要或名单与归档证据不一致")
    return check


def prepare_quality(workflow, sid, payload, tools, progress):
    """获准后台生产入口，计算后再次核对版本才发布，全部历史与审核保持。"""
    context, plan, plan_record, source, auth_record = workflow.quality_authorization(sid, payload)
    manifest = workflow.load(sid)
    source_record = next(r for r in manifest["source_review_records"]
                        if read_json(verified_file(workflow.location(sid), r))["review_id"] == source["review_id"])
    # 工具缺失在建立运行前明确失败，不发布假NA结果。
    executable = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    check = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=20)
    require(check.returncode == 0 and check.stdout.strip() == "AutoDock Vina v1.2.7",
            "Vina实际版本不符合固定1.2.7要求")
    run = workflow.begin(sid, "A06_PREP",
        {"two_pass_plan": plan_record, "source_review": source_record,
         "quality_authorization": auth_record},
        CONFIG, "用户明确继续：执行两遍结构准备及质控，批量对接仍关闭")
    home = workflow.location(sid)
    folder = home / "runs/A06_PREP" / run["run_id"] / "quality"
    folder.mkdir(parents=True, exist_ok=False)
    try:
        # 实际调用代码独立快照，与输入和工具指纹一同留存。
        import shutil
        src = Path(__file__).resolve().parents[2]
        names = ("docking_top10_execute.py","docking_ligand.py","docking_reference_ligand.py",
                 "docking_redocking.py","docking_p2rank.py","docking_receptor.py",
                 "docking_audit.py","docking_ligand_flow.py","docking_runtime.py",
                 "science_modules/a06/quality_engine.py","science_modules/a06/quality_flow.py",
                 "science_modules/a06/two_pass.py")
        for name in names:
            destination = folder / "code" / name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src / name,destination)
        evidence, compounds = run_engine(home, context, source, plan["plan"], folder, tools, progress)
        prep, summary, tables = reports(context, plan["plan"], evidence, compounds)
        packet = {"schema_version": VERSION, "study_id": sid, "source_key": context["source_key"],
                  "context": context, "plan_id": plan["plan_id"],
                  "evidence": evidence, "compounds": compounds, "preparation": prep,
                  "batch_docking_allowed": False,
                  "vina_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "files": [file_record(home, p, "quality_evidence") for p in folder.rglob("*") if p.is_file()]}
        path = folder / "packet.json"
        write_json(path, packet)
        record = file_record(home, path, "quality_packet")
        tables["quality_packet"] = [record]
        result = workflow.finish_quality(sid, run["run_id"], payload, summary, tables,
                                        packet["files"] + [record])
        return result
    except Exception:
        # 未完整发布的运行保留；不覆盖旧结果、不自动批准、不改参数重试。
        raise
