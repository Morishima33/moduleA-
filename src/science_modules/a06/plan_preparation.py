"""新方案A06的独立准备运行：官方来源、真实质控、完整NA矩阵。"""

from pathlib import Path
import hashlib
import re
import shutil
import subprocess

from contracts import require
from storage import file_record, read_json, verified_file, write_json, write_lock
from science_modules.analysis_protocol import checked_plan, FIELDS
from .automatic_sources import Fetcher, compound_source, receptor_sources
from .automatic_engine import preparation_source
from .plan_input import pair_statuses
from .quality_engine import attempt, prepare_compounds, target_folder
from .two_pass import assess_attempt

VERSION = "A06.plan_preparation.1"
CONFIG = {"version": VERSION, "batch_docking_allowed": False,
          "automatic_approval": False, "predicted_pocket_approval": False}
REDOCK_KEYS = ("a06.exhaustiveness", "a06.num_modes", "a06.energy_range",
               "a06.seed", "a06.box_padding", "a06.redocking_rmsd_max")


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
    # 冻结旧准备工具的重对接参数。可调项未接入前明确阻止，不能用默认值冒充个性化执行。
    require(all(plan["parameters"][key] == FIELDS[key]["default"] for key in REDOCK_KEYS),
            "当前结构准备内核尚未接入个性化重对接参数，请保留此方案待后续版本")
    return packet, reference


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


def prepare(root, connection, folder, tools, progress):
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
                               / f"attempt_{index}", tools, progress)
            assessment = assess_attempt(spec, evidence, row,
                                        1 if spec["pocket"] == "reference" else 2)
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
        require(run["config"] == CONFIG and outcome == "success" and anomalies == [],
                "A06新准备配置或结果状态不一致")
        records = tables.get("preparation_packet", [])
        require(len(records) == 1 and records[0]["path"] ==
                f"runs/A06_PREP/{run['run_id']}/plan_preparation/packet.json",
                "A06准备事实包路径不属于当前运行")
        fact = read_json(verified_file(home, records[0]))
        packet = read_json(verified_file(home, run["inputs"]["a06_plan_input"]))["packet"]
        require(fact["study_id"] == run["study_id"] and fact["input_key"] == packet["input_key"],
                "A06准备证据与本次输入不符")
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
                if evidence.get("top1_rmsd") is not None:
                    pose = _poses(verified_file(home, evidence["redocking_output"]).read_text("ascii"))[0]
                    value = symmetry_rmsd(verified_file(home, evidence["reference_sdf"]).read_bytes(),
                                          verified_file(home, evidence["reference_pdbqt"]).read_text("ascii"),
                                          pose)["rmsd_angstrom"]
                    require(abs(value - evidence["top1_rmsd"]) < 1e-9,
                            "参考重对接RMSD与Top-1原文件不符")
                assessment = assess_attempt(spec, evidence, originals[row["target_id"]],
                                            1 if spec["pocket"] == "reference" else 2)
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
    packet, input_ref = current_input(workflow, sid, payload["expected_input_id"])
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
    run_info = workflow.begin(sid, "A06_PREP", {"a06_plan_input": input_ref}, CONFIG,
                              "新方案固定名单：实际连接官方来源并准备结构与配体；不评分")
    home = workflow.location(sid)
    folder = home / "runs/A06_PREP" / run_info["run_id"] / "plan_preparation"
    folder.mkdir(parents=True, exist_ok=False)
    binary = folder / "software/vina_1.2.7.exe"
    binary.parent.mkdir(parents=True)
    shutil.copyfile(executable, binary)
    code_root = Path(__file__).resolve().parents[2]
    for name in ("science_modules/a06/plan_preparation.py",
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
    compounds, receptors = prepare(home, connection, folder, tools, progress)
    summary, tables = reports(packet, compounds, receptors)
    fact = {"schema_version": VERSION, "study_id": sid, "input_key": packet["input_key"],
            "request_id": payload["request_id"], "author": payload["author"].strip(),
            "note": payload["note"].strip(), "connection": connection,
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
