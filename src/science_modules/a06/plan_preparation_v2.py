"""新方案A06的独立准备运行：官方来源、真实质控、完整NA矩阵。"""

from pathlib import Path
import hashlib
import re
import shutil
import subprocess

from contracts import require
from storage import file_record, read_json, verified_file, write_json, write_lock
from science_modules.analysis_protocol import checked_plan
from .automatic_sources import Fetcher, compound_source, receptor_sources
from .automatic_engine import preparation_source
from .plan_input import pair_statuses
from .plan_quality_engine_v2 import attempt, prepare_compounds, target_folder
from .two_pass import assess_attempt

VERSION = "A06.plan_preparation.2"
CONFIG = {"version": VERSION, "batch_docking_allowed": False,
          "automatic_approval": False, "predicted_pocket_approval": False}
DEFAULT_RMSD = 2.0


def assess_plan_attempt(spec, evidence, target, round_no, config):
    """严格RMSD同时满足默认2 Å与方案更严上限，宽松上限不升格严格。"""
    outcome = assess_attempt(spec, evidence, target, round_no)
    if outcome["state"] == "ready" and spec.get("pocket") == "reference":
        limit = min(config["strict_rmsd_A"], config["requested_rmsd_max_A"])
        if outcome["rmsd"] > limit:
            return {**outcome, "state": "failed", "quality": "无法计算",
                    "reason_zh": "Top-1重对接RMSD超过本方案上限"}
    return outcome


def execution_config(plan):
    """把已编译方案转换成实际调用参数；严格RMSD判定仍固定为2 Å。"""
    values = plan["parameters"]
    return {**CONFIG, "vina_parameters": {
        "scoring": "vina", "exhaustiveness": values["a06.exhaustiveness"],
        "num_modes": values["a06.num_modes"],
        "energy_range_kcal_mol": values["a06.energy_range"],
        "seed": values["a06.seed"]},
        "box_padding": values["a06.box_padding"],
        "strict_rmsd_A": DEFAULT_RMSD,
        "requested_rmsd_max_A": values["a06.redocking_rmsd_max"]}


def current_input(workflow, sid, input_id):
    """重新核验当前方案和全部复核，不把历史输入当成当前授权。"""
    info = workflow.analysis_plan_info(sid)
    record = info.get("a06_preparation_input")
    require(record and record["input_id"] == input_id,
            "A06准备输入或上游复核已更新，请重新登记")
    manifest = workflow.load(sid)
    reference = next(ref for ref in manifest["analysis_plan_a06_input_records"]
                     if read_json(verified_file(workflow.location(sid), ref))["input_id"] == input_id)
    packet = record["packet"]
    from .plan_input import build
    expected = build(sid, packet["runs"], packet["reviews"], packet["result_refs"],
                     packet["a04_selection_ref"], packet["a04_selection_review_ref"],
                     packet["plan_ref"], {"network_run_id": packet["runs"]["A04"],
                     "selected": packet["receptors"],
                     "analysis_parameter_hash": packet["analysis_parameter_hash"]},
                     packet["compounds"])
    require(packet == expected, "A06准备输入内容或指纹不一致")
    plan_record = read_json(verified_file(workflow.location(sid), packet["plan_ref"]))
    plan = checked_plan(plan_record["plan"])
    require(plan["parameter_hash"] == packet["analysis_parameter_hash"],
            "A06准备方案指纹不一致")
    # 个性化RMSD上限可以记录在方案，但严格质控仍按项目冻结的2 Å判定。
    return packet, reference, plan


def _version(tools):
    executable = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    require(executable.is_file(), "缺少固定Vina 1.2.7工具")
    result = subprocess.run([str(executable), "--version"], capture_output=True,
                            text=True, timeout=20)
    require(result.returncode == 0 and result.stdout.strip() == "AutoDock Vina v1.2.7",
            "Vina实际版本不符合固定1.2.7要求")
    return executable


def connect(root, packet, folder, progress):
    """逐项请求官方来源，失败留请求记录及原因，不改变固定名单。"""
    fetch = Fetcher(root, folder)
    compounds, receptors = [], []
    for row in packet["compounds"]:
        progress("连接成分来源：" + row["compound_id"])
        try:
            require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", row["compound_id"]),
                    "成分编号不能安全建立目录")
            require(isinstance(row.get("name"), str) and row["name"].strip(),
                    "成分缺少用于官方身份定位的名称")
            compounds.append(compound_source(row, fetch))
        except Exception as error:
            compounds.append({**row, "state": "NA", "reason_zh": str(error)})
    for row in packet["receptors"]:
        progress("连接受体来源：" + row["symbol"])
        try:
            receptors.append(receptor_sources(row, fetch, progress))
        except Exception as error:
            receptors.append({**row, "state": "NA", "reason_zh": str(error), "candidates": []})
    return {"id": folder.parent.parent.name, "compounds": compounds,
            "receptors": receptors, "files": fetch.records}


def prepare(root, connection, folder, tools, progress, config):
    """复用既有来源身份和Meeko/结构质控内核；预测口袋留待人工确认。"""
    source = preparation_source(connection)
    connected = [r for r in connection["compounds"] if r["state"] == "connected"]
    prepared = prepare_compounds(root, source,
                                 {"compounds": [{"compound_id": r["compound_id"], "status": "use"}
                                                for r in connected]}, folder / "quality", progress)
    by_id = {r["compound_id"]: r for r in prepared}
    compounds = []
    for row in connection["compounds"]:
        value = by_id.get(row["compound_id"])
        compounds.append(value or {"compound_id": row["compound_id"], "state": "NA",
                                   "reason_zh": row.get("reason_zh") or "官方来源未连接"})
    receptors = []
    for row in connection["receptors"]:
        traces, selected = [], None
        for index, candidate in enumerate(row.get("candidates", []), 1):
            spec = candidate["spec"]
            evidence = attempt(root, source, row, spec,
                               1 if spec["pocket"] == "reference" else 2,
                               folder / "quality/receptors" / target_folder(row["target_id"])
                               / f"attempt_{index}", tools, progress,
                               box_padding=config["box_padding"], vina_parameters=config["vina_parameters"])
            assessment = assess_plan_attempt(spec, evidence, row,
                                        1 if spec["pocket"] == "reference" else 2, config)
            traces.append({"candidate": candidate, "evidence": evidence,
                           "assessment": assessment})
            if assessment["state"] == "ready":
                selected = traces[-1]
                break
        reason = (row.get("reason_zh") or "官方结构未连接") if not traces else "; ".join(
            t["assessment"]["reason_zh"] for t in traces)
        receptors.append({"target_id": row["target_id"], "symbol": row["symbol"],
                          "state": "ready" if selected else "NA",
                          "reason_zh": selected["assessment"]["reason_zh"] if selected else reason,
                          "quality": selected["assessment"]["quality"] if selected else "待核查",
                          "attempts": traces})
    return compounds, receptors


def reports(packet, compounds, receptors):
    c = {r["compound_id"]: {"state": r["state"], "reason_zh": r["reason_zh"]}
         for r in compounds}
    r = {row["target_id"]: {"state": row["state"], "reason_zh": row["reason_zh"]}
         for row in receptors}
    pairs = pair_statuses(packet, c, r)
    summary = {"input_key": packet["input_key"], "compound_count": len(compounds),
               "receptor_count": len(receptors), "pair_count": len(pairs),
               "ready_pairs": sum(row["state"] == "ready" for row in pairs),
               "na_pairs": sum(row["state"] == "NA" for row in pairs),
               "scored_pairs": 0, "execution_available": False,
               "handoff_blocked": True,
               "message_zh": "结构与配体准备事实待独立复核；预测口袋未经确认保持NA，未计算组合评分"}
    return summary, {"compound_preparation": [
        {"compound_id": row["compound_id"], "state": row["state"],
         "reason_zh": row["reason_zh"]} for row in compounds],
        "receptor_preparation": [
        {"target_id": row["target_id"], "symbol": row["symbol"],
         "state": row["state"], "reason_zh": row["reason_zh"],
         "quality": row["quality"]} for row in receptors],
        "planned_pairs": pairs}


def validator(root, previous):
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("version") != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        plan_record = read_json(verified_file(home, read_json(
            verified_file(home, run["inputs"]["a06_plan_input"]))["packet"]["plan_ref"]))
        expected_config = execution_config(checked_plan(plan_record["plan"]))
        require(run["config"] == expected_config and outcome == "success" and anomalies == [],
                "A06新准备配置或结果状态不一致")
        records = tables.get("preparation_packet", [])
        require(len(records) == 1 and records[0]["path"] ==
                f"runs/A06_PREP/{run['run_id']}/plan_preparation/packet.json",
                "A06准备事实包路径不属于当前运行")
        fact = read_json(verified_file(home, records[0]))
        packet = read_json(verified_file(home, run["inputs"]["a06_plan_input"]))["packet"]
        require(fact.get("schema_version") == VERSION and
                packet.get("schema_version") == "A06.plan_preparation_input.1" and
                fact["study_id"] == run["study_id"] and fact["input_key"] == packet["input_key"],
                "A06准备证据与本次输入不符")
        require(checked_plan(plan_record["plan"])["parameter_hash"] == packet["analysis_parameter_hash"],
                "方案参数与准备输入指纹不一致")
        require(fact.get("config") == expected_config,
                "A06实际准备参数与方案配置不一致")
        require(all(run["parent_runs"].get(k) == packet["runs"].get(k)
                    for k in ("A03", "A03_SELECT", "A04")) and
                all(run["parent_review_ids"].get(k) == packet["reviews"].get(k)
                    for k in ("A03", "A03_SELECT", "A04")),
                "A06准备上游运行或复核不符")
        connection = fact["connection"]
        require([r["compound_id"] for r in connection["compounds"]] ==
                [r["compound_id"] for r in packet["compounds"]] and
                [r["target_id"] for r in connection["receptors"]] ==
                [r["target_id"] for r in packet["receptors"]], "准备对象与固定选择不一致")
        for record in fact["files"] + connection["files"]:
            verified_file(home, record)
        require(fact["vina_binary"]["path"] ==
                f"runs/A06_PREP/{run['run_id']}/plan_preparation/software/vina_1.2.7.exe" and
                hashlib.sha256(verified_file(home, fact["vina_binary"]).read_bytes()).hexdigest()
                == fact["vina_sha256"], "Vina工具快照与记录指纹不符")
        from docking_ligand import prepare_ligand
        from docking_top10_execute import _meeko_settings
        connected = {r["compound_id"]: r for r in connection["compounds"]
                     if r["state"] == "connected"}
        for row in fact["compounds"]:
            source = connected.get(row["compound_id"])
            if row["state"] == "ready":
                require(source and source["identity_matched"], "配体通过项缺少官方身份证据")
                actual = prepare_ligand(verified_file(home, source["sdf"]).read_text("utf-8"),
                                        source["cid"], source["audit"]["inchi_key"],
                                        _meeko_settings())
                prepared = next(r for r in row["files"] if r["role"] == "prepared_ligand")
                require(verified_file(home, prepared).read_text("ascii") ==
                        actual.pop("pdbqt_text") and row["preparation"] == actual,
                        "配体准备文件与来源三维复算不一致")
            else:
                require(row["state"] == "NA" and row["reason_zh"], "失败配体须保留NA和原因")
        from docking_redocking import _poses, symmetry_rmsd
        originals = {r["target_id"]: r for r in connection["receptors"]}
        for row in fact["receptors"]:
            require(row["target_id"] in originals, "受体不属于固定输入")
            assessments = []
            for trace in row["attempts"]:
                spec, evidence = trace["candidate"]["spec"], trace["evidence"]
                require(trace["candidate"] in originals[row["target_id"]].get("candidates", []),
                        "受体尝试不属于官方连接候选")
                if evidence.get("predicted_pocket"):
                    from docking_p2rank import _prediction_rows
                    from .plan_quality_engine_v2 import prediction_box
                    predicted = evidence["predicted_pocket"]
                    predictions = [r for r in predicted["files"] if r["role"] == "p2rank_prediction"]
                    require(len(predictions) == 2, "预测口袋缺少两次原始文件")
                    rows = [_prediction_rows(verified_file(home, ref))[0] for ref in predictions]
                    keys = ("rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids")
                    require(all(rows[0][k] == rows[1][k] for k in keys), "两次预测口袋不一致")
                    expected_box = prediction_box(verified_file(home, predicted["input_pdb"]).read_text("ascii"),
                                                  rows[0], expected_config["box_padding"])
                    require(evidence.get("box") == expected_box, "预测搜索盒与方案参数或原始坐标不符")
                if evidence.get("top1_rmsd") is not None:
                    from docking_top10_execute import _ligand_lines
                    from .plan_quality_engine_v2 import reference_box
                    conversions = [r for r in evidence["files"] if r["path"].endswith("/original_conversion.pdb")]
                    require(len(conversions) == 1, "参考重对接缺少实际结构转换文件")
                    reference = _ligand_lines(verified_file(home, conversions[0]), spec["reference_code"],
                                              spec["reference_chain"], spec["reference_sequence"], spec.get("altloc"))
                    require(evidence["box"] == reference_box(reference, expected_config["box_padding"]),
                            "参考搜索盒与实际坐标或方案外扩不符")
                    commands = [r for r in evidence["files"] if r["path"].endswith("/redocking/command.json")]
                    require(len(commands) == 1, "参考重对接缺少实际命令记录")
                    command = read_json(verified_file(home, commands[0]))
                    require(command["parameters"] == expected_config["vina_parameters"] and
                            command["box"] == evidence["box"], "重对接命令与方案参数不符")
                    args = command["arguments"]
                    for flag, value in (("--scoring", expected_config["vina_parameters"]["scoring"]),
                        ("--exhaustiveness", expected_config["vina_parameters"]["exhaustiveness"]),
                        ("--num_modes", expected_config["vina_parameters"]["num_modes"]),
                        ("--energy_range", expected_config["vina_parameters"]["energy_range_kcal_mol"]),
                        ("--seed", expected_config["vina_parameters"]["seed"])):
                        require(args.count(flag) == 1 and args[args.index(flag)+1] == str(value),
                                "实际命令参数与方案不一致")
                    for axis, center, size in zip("xyz", evidence["box"]["center"], evidence["box"]["size"]):
                        for flag, value in (("--center_" + axis, center), ("--size_" + axis, size)):
                            require(args.count(flag) == 1 and args[args.index(flag)+1] == str(value),
                                    "实际命令搜索盒与归档不一致")
                    pose = _poses(verified_file(home, evidence["redocking_output"]).read_text("ascii"))[0]
                    value = symmetry_rmsd(verified_file(home, evidence["reference_sdf"]).read_bytes(),
                                          verified_file(home, evidence["reference_pdbqt"]).read_text("ascii"),
                                          pose)["rmsd_angstrom"]
                    require(abs(value - evidence["top1_rmsd"]) < 1e-9,
                            "参考重对接RMSD与Top-1原文件不符")
                assessment = assess_plan_attempt(spec, evidence, originals[row["target_id"]],
                                            1 if spec["pocket"] == "reference" else 2, expected_config)
                require(assessment == trace["assessment"], "受体质控结论与证据复算不一致")
                assessments.append(assessment)
            ready = next((a for a in assessments if a["state"] == "ready"), None)
            require(row["state"] == ("ready" if ready else "NA") and
                    row["reason_zh"] == (ready["reason_zh"] if ready else
                    (originals[row["target_id"]].get("reason_zh") or "官方结构未连接") if not assessments
                    else "; ".join(a["reason_zh"] for a in assessments)),
                    "受体准备状态与原始证据不一致")
        expected_summary, expected_tables = reports(packet, fact["compounds"], fact["receptors"])
        expected_tables["preparation_packet"] = records
        require(summary == expected_summary and tables == expected_tables,
                "A06准备摘要或NA组合与固定输入不一致")
    return check


def run(workflow, sid, payload, tools, progress):
    require(isinstance(payload, dict) and set(payload) ==
            {"expected_input_id", "request_id", "author", "note", "confirmed"},
            "A06准备请求字段不完整")
    from contracts import safe_id
    safe_id(payload["expected_input_id"], "input")
    safe_id(payload["request_id"], "planprep")
    require(payload["confirmed"] is True and all(isinstance(payload[k], str) and
            payload[k].strip() for k in ("author", "note")), "请明确确认结构准备范围和执行人")
    packet, input_ref, plan = current_input(workflow, sid, payload["expected_input_id"])
    config = execution_config(plan)
    manifest = workflow.load(sid)
    for run_id, indexed in manifest["runs"].items():
        run_record = workflow.run(manifest, run_id)
        if (run_record["module_id"] != "A06_PREP" or
                run_record.get("config", {}).get("version") != VERSION or
                not indexed.get("result_file")):
            continue
        previous = workflow.result(manifest, run_id)
        evidence_ref = previous["tables"]["preparation_packet"][0]
        old = read_json(verified_file(workflow.location(sid), evidence_ref))
        if old["request_id"] == payload["request_id"]:
            require(old["input_key"] == packet["input_key"] and
                    old["author"] == payload["author"].strip() and
                    old["note"] == payload["note"].strip(),
                    "A06准备请求编号已用于其他输入或说明")
            return previous
    executable = _version(tools)
    # 真实来源请求与准备只属于当前运行；失败保留该次运行和原件供诊断。
    run_info = workflow.begin(sid, "A06_PREP", {"a06_plan_input": input_ref}, config,
                              "新方案固定名单：实际连接官方来源并准备结构与配体；不评分")
    home = workflow.location(sid)
    folder = home / "runs/A06_PREP" / run_info["run_id"] / "plan_preparation"
    folder.mkdir(parents=True, exist_ok=False)
    binary = folder / "software/vina_1.2.7.exe"
    binary.parent.mkdir(parents=True)
    shutil.copyfile(executable, binary)
    code_root = Path(__file__).resolve().parents[2]
    for name in ("science_modules/a06/plan_preparation_v2.py",
                 "science_modules/a06/plan_quality_engine_v2.py",
                 "science_modules/a06/plan_input.py",
                 "science_modules/a06/automatic_sources.py",
                 "science_modules/a06/automatic_engine.py",
                 "science_modules/a06/quality_engine.py",
                 "science_modules/a06/two_pass.py", "docking_ligand.py",
                 "docking_audit.py", "docking_receptor.py", "docking_p2rank.py",
                 "docking_reference_ligand.py", "docking_redocking.py",
                 "docking_top10_execute.py"):
        destination = folder / "code" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(code_root / name, destination)
    connection = connect(home, packet, folder / "sources", progress)
    compounds, receptors = prepare(home, connection, folder, tools, progress, config)
    summary, tables = reports(packet, compounds, receptors)
    fact = {"schema_version": VERSION, "study_id": sid, "input_key": packet["input_key"],
            "request_id": payload["request_id"], "author": payload["author"].strip(),
            "note": payload["note"].strip(), "connection": connection,
            "config": config,
            "compounds": compounds, "receptors": receptors,
            "vina_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "vina_binary": file_record(home, binary, "vina_binary"),
            "files": [file_record(home, p, "preparation_evidence")
                      for p in folder.rglob("*") if p.is_file()]}
    write_json(folder / "packet.json", fact)
    record = file_record(home, folder / "packet.json", "preparation_packet")
    tables["preparation_packet"] = [record]
    with write_lock(workflow.root):
        current_input(workflow, sid, payload["expected_input_id"])
        manifest = workflow.load(sid)
        result = workflow._finish(manifest, run_info["run_id"], summary, tables, [],
                                  "success", attachments=fact["files"] + [record])
        workflow.save(manifest)
    return result
