"""一次执行授权后的动态全矩阵：逐项质控、仅计算合格对象、原始构型位点可回溯。"""
from copy import deepcopy
from pathlib import Path
import csv
import hashlib
import json
import math
import shutil
import subprocess
from contracts import require
from storage import file_record, read_json, verified_file, write_json
from .automatic_rules import VERSION, POLICY, assess


# 将本协议的连接资料适配到冻结准备函数，不写入旧人工确认记录。
def preparation_source(connection):
    records = []
    for row in connection["compounds"]:
        if row["state"] == "connected":
            records.append(row["sdf"])
    for row in connection["receptors"]:
        records.extend(c["cif"] for c in row.get("candidates", []))
    unique = list({r["path"]: r for r in records}.values())
    source = {"review_id": connection["id"], "files": [{"key": f"f{i:04d}", "file": r} for i, r in enumerate(unique)], "compounds": [], "receptors": []}
    def key(record):
        return next(r["key"] for r in source["files"] if r["file"] == record)
    for row in connection["compounds"]:
        if row["state"] == "connected":
            source["compounds"].append(dict(row, file_key=key(row["sdf"])))
    for row in connection["receptors"]:
        for candidate in row.get("candidates", []):
            spec = candidate["spec"]
            original = candidate.get("reference_audit", {})
            source["receptors"].append({"target_id": row["target_id"], "pdb_id": spec["pdb_id"], "chains": spec["chains"], "identity_matched": True, "file_key": key(candidate["cif"]), "audit": {"identity": candidate["identity"]}, "reference_count_matches": original.get("reference_count_matches", False), "reference_covalent_count": original.get("reference_covalent_count", 0)})
    return source


# 完整二维表和图使用同一原始评分；NA白底，不用零填补。
def draw_matrix(packet, folder):
    from PIL import Image, ImageDraw, ImageFont
    compounds, receptors = packet["compounds"], packet["receptors"]
    pairs = {(r["compound_id"], r["target_id"]): r for r in packet["pairs"]}
    scores = [r["score"] for r in packet["pairs"] if r["state"] == "completed"]
    low, high = (min(scores), max(scores)) if scores else (None, None)
    width, height = max(900, 330 + 90 * len(receptors)), 170 + 36 * len(compounds)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 13) if font_path.is_file() else ImageFont.load_default()
    draw.text((18, 12), "自动对接原始Top-1评分（kcal/mol）；越负越红，越不负越蓝；NA不填零", font=font, fill="#17212B")
    draw.text((18, 36), f"有效范围：{low} 至 {high}；严格与探索范围请查同批明细", font=font, fill="#52616B")
    for j, receptor in enumerate(receptors):
        draw.text((305 + j * 90, 72), receptor["symbol"], font=font, fill="#17212B")
        draw.text((305 + j * 90, 92), receptor["quality"], font=font, fill="#52616B")
    for i, compound in enumerate(compounds):
        draw.text((12, 128 + i * 36), (compound.get("name") or compound["compound_id"])[:35], font=font, fill="#17212B")
        for j, receptor in enumerate(receptors):
            row = pairs[(compound["compound_id"], receptor["target_id"])]
            color, text = (255, 255, 255), "NA"
            if row["state"] == "completed":
                fraction = (row["score"] - low) / (high - low) if high != low else .5
                a, b, amount = ((178, 24, 43), (247, 247, 247), fraction * 2) if fraction <= .5 else ((247, 247, 247), (33, 102, 172), (fraction - .5) * 2)
                color = tuple(round(x + (y - x) * amount) for x, y in zip(a, b))
                text = str(row["score"])
            x, y = 300 + j * 90, 122 + i * 36
            draw.rectangle((x, y, x + 86, y + 32), fill=color, outline="#DCE1E5" if row["state"] == "completed" else None)
            if row["state"] != "completed":
                for offset in range(0, 86, 8):
                    for edge in (y, y+32):
                        draw.line((x+offset, edge, min(x+offset+4, x+86), edge), fill="#AAB4BE")
                for offset in range(0, 32, 8):
                    for edge in (x, x+86):
                        draw.line((edge, y+offset, edge, min(y+offset+4, y+32)), fill="#AAB4BE")
            draw.text((x + 8, y + 7), text, font=font, fill="#17212B")
    folder.mkdir(parents=True, exist_ok=True)
    image.save(folder / "A06_automatic_heatmap.png")
    with (folder / "A06_automatic_scores.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["compound_id", "target_id", "state", "score", "quality", "reason_zh"])
        writer.writeheader()
        writer.writerows({k: row.get(k) for k in writer.fieldnames} for row in packet["pairs"])


# 参数、软件和执行源码固定到本次尝试，失败原件与输出同样保留。
def run(workflow, sid, payload, tools, code, runtime, progress):
    from .quality_engine import prepare_compounds, attempt, target_folder
    from .trial_compute import score_region
    executable = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    check = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=20)
    require(check.returncode == 0 and check.stdout.strip() == "AutoDock Vina v1.2.7", "固定Vina 1.2.7工具未就绪")
    batch, run_info, completed = workflow.begin_automatic(sid, payload)
    if completed:
        return workflow.result(workflow.load(sid), batch["run_id"])
    root = workflow.location(sid)
    folder = root / "runs/A06" / run_info["run_id"] / "automatic"
    folder.mkdir(parents=True, exist_ok=False)
    connection = read_json(verified_file(root, run_info["inputs"]["automatic_connection"]))
    source = preparation_source(connection)
    try:
        binary = folder / "software/vina_1.2.7.exe"
        binary.parent.mkdir(parents=True)
        shutil.copyfile(executable, binary)
        write_json(folder / "software/runtime.json", {"runtime": runtime, "policy": POLICY, "source_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest()})
        for name in ("science_modules/a06/automatic_engine.py", "science_modules/a06/automatic_rules.py", "science_modules/a06/automatic_sources.py", "science_modules/a06/quality_engine.py", "science_modules/a06/trial_compute.py", "science_modules/a06/trial_rules.py", "docking_ligand.py", "docking_receptor.py", "docking_audit.py", "docking_reference_ligand.py", "docking_redocking.py", "docking_top10_execute.py", "docking_p2rank.py"):
            destination = folder / "code" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(code / "src" / name, destination)
        ligand_plan = {"compounds": [{"compound_id": r["compound_id"], "status": "use"} for r in source["compounds"]]}
        prepared = prepare_compounds(root, source, ligand_plan, folder / "quality", progress)
        compounds = []
        for original in connection["compounds"]:
            actual = next((r for r in prepared if r["compound_id"] == original["compound_id"]), None)
            compounds.append({**original, **(actual or {}), "state": actual["state"] if actual else original["state"]})
        receptors = []
        for original in connection["receptors"]:
            value = {**original, "state": "failed" if original["state"] == "failed" else "NA", "quality": "未通过", "reason_zh": original.get("reason_zh", ""), "attempts": []}
            for index, candidate in enumerate(original.get("candidates", [])):
                progress("准备与质控：" + original["symbol"] + " / " + candidate["spec"]["pdb_id"])
                spec = candidate["spec"]
                evidence = attempt(root, source, original, spec, 1 if spec["pocket"] == "reference" else 2, folder / "quality/receptors" / target_folder(original["target_id"]) / f"attempt_{index+1}", tools, progress)
                trace = {"candidate": candidate, "evidence": evidence}
                try:
                    assessment = assess(spec, evidence, payload["request_id"], original)
                    require(assessment["state"] == "ready", assessment["reason_zh"])
                    trace["assessment"] = assessment
                    value.update(state="ready", quality=assessment["quality"], reason_zh=assessment["reason_zh"], selected_candidate=candidate, evidence=evidence)
                except Exception as error:
                    trace["reason_zh"] = str(error)
                    value["reason_zh"] = str(error)
                value["attempts"].append(trace)
                if value["state"] == "ready":
                    break
            receptors.append(value)
        pairs = []
        total = len(compounds) * len(receptors)
        for compound in compounds:
            for receptor in receptors:
                row = {"compound_id": compound["compound_id"], "target_id": receptor["target_id"], "state": "NA", "score": None, "quality": receptor["quality"], "reason_zh": ""}
                if compound["state"] != "ready" or receptor["state"] != "ready":
                    row["state"] = "failed" if compound["state"] == "failed" or receptor.get("state") == "failed" else "NA"
                    row["reason_zh"] = "；".join(r.get("reason_zh", "") for r in (compound, receptor) if r["state"] != "ready") or "对象未通过本轮准备或质控"
                else:
                    progress(f"自动对接 {len(pairs)+1}/{total}：{compound['compound_id']} / {receptor['symbol']}")
                    ev = receptor["evidence"]
                    region = dict(ev["box"], region_id="site_1")
                    fact = score_region(root, folder, binary, compound, {"target_id": receptor["target_id"], "receptor": ev["receptor"]}, region)
                    row.update(state="completed" if fact["state"] == "completed" else "failed", score=fact["score"], reason_zh=fact["reason_zh"], execution=fact)
                    if row["state"] == "completed":
                        from docking_redocking import _poses, _inside_box
                        pose = _poses(verified_file(root, fact["pose"]).read_text("ascii"))[0]
                        if not math.isfinite(row["score"]) or not _inside_box(pose, {"center_angstrom": region["center"], "size_angstrom": region["size"]})["passed"]:
                            row.update(state="failed", score=None, reason_zh="姿势坐标越出搜索盒或评分无效；保留原始输出")
                pairs.append(row)
                write_json(folder / "progress" / f"pair_{len(pairs):06d}.json", {"completed_pairs": len(pairs), "total": total})
        strict = [r["target_id"] for r in receptors if r["state"] == "ready" and r["quality"] == "严格"]
        primary = strict[:5] if len(strict) >= 5 else []
        summary = {"science_version": VERSION, "成分数": len(compounds), "受体数": len(receptors), "计划组合数": total, "成功组合数": sum(p["state"] == "completed" for p in pairs), "失败组合数": sum(p["state"] == "failed" for p in pairs), "NA组合数": sum(p["state"] == "NA" for p in pairs), "严格受体数": len(strict), "探索受体数": sum(r["state"] == "ready" and r["quality"] == "探索" for r in receptors), "主要受体数": len(primary), "handoff_blocked": not any(p["state"] == "completed" for p in pairs), "interpretation_scope": "strict_and_exploratory_separate", "automatic_scientific_approval": False}
        packet = {"schema_version": VERSION, "study_id": sid, "id": payload["request_id"], "run_id": run_info["run_id"], "connection": run_info["inputs"]["automatic_connection"], "authorization": run_info["inputs"]["automatic_authorization"], "policy": POLICY, "runtime": runtime, "compounds": compounds, "receptors": receptors, "pairs": pairs, "summary": summary, "primary_targets": primary, "executable": file_record(root, binary, "automatic_vina")}
        draw_matrix(packet, folder / "display")
        packet_path = folder / "packet.json"
        write_json(packet_path, packet)
        record = file_record(root, packet_path, "automatic_packet")
        files = list({r["path"]: r for r in connection["files"] + list(run_info["inputs"].values()) + [file_record(root, path, "automatic_evidence") for path in folder.rglob("*") if path.is_file()]}.values())
        tables = {"automatic_packet": [record], "pairs": [{k: r[k] for k in ("compound_id", "target_id", "state", "score", "quality", "reason_zh")} for r in pairs], "receptor_setup": [{"基因": r["symbol"], "HGNC": r["target_id"], "质控": r["quality"], "状态": r["state"], "PDB": r.get("selected_candidate", {}).get("spec", {}).get("pdb_id", ""), "原因": r["reason_zh"]} for r in receptors]}
        return workflow.finish_automatic(sid, payload, run_info["run_id"], record, summary, tables, files)
    except Exception as error:
        workflow.fail_automatic(sid, payload["request_id"], str(error))
        raise


# 科学发布重核输入、完整组合及真实姿势；旧协议继续交给原校验器。
def validator(root, previous):
    def check(run_info, summary, tables, anomalies, outcome):
        if run_info.get("config", {}).get("schema_version") != VERSION:
            return previous(run_info, summary, tables, anomalies, outcome)
        from docking_redocking import _poses, symmetry_rmsd, _inside_box
        from docking_top10_execute import _vina_arguments
        from docking_p2rank import _prediction_rows, _residue_keys, box_from_prediction
        from .quality_engine import environment_audit
        from .trial_rules import VINA as EXECUTION_VINA, fingerprint
        home = Path(root) / "studies" / run_info["study_id"]
        authorization = read_json(verified_file(home, run_info["inputs"]["automatic_authorization"]))
        connection = read_json(verified_file(home, run_info["inputs"]["automatic_connection"]))
        packet = read_json(verified_file(home, tables["automatic_packet"][0]))
        require(run_info["config"] == {"schema_version": VERSION, "policy": POLICY} and packet["policy"] == authorization["policy"] == connection["policy"] == POLICY, "自动策略或参数被修改")
        require(authorization["study_id"] == connection["study_id"] == packet["study_id"] == run_info["study_id"], "自动对接资料跨研究")
        require(authorization["request"]["confirmed"] is True and authorization["approval"] is None and authorization["connection"] == run_info["inputs"]["automatic_connection"], "缺少对应本批连接的一次执行授权")
        require(run_info["parent_runs"] == authorization["binding"]["runs"] and run_info["parent_review_ids"] == authorization["binding"]["reviews"], "自动结果上游与执行授权不一致")
        require(packet["authorization"] == run_info["inputs"]["automatic_authorization"] and packet["connection"] == run_info["inputs"]["automatic_connection"], "自动评分来源不一致")
        require(packet["run_id"] == run_info["run_id"] and packet["id"] == authorization["id"], "自动结果版本不一致")
        expected = {(c["compound_id"], r["target_id"]) for c in connection["context"]["compounds"] for r in connection["context"]["receptors"]}
        actual = [(r["compound_id"], r["target_id"]) for r in packet["pairs"]]
        require(len(actual) == len(set(actual)) and set(actual) == expected, "自动矩阵重复或漏项")
        require(summary == packet["summary"] and not summary["automatic_scientific_approval"], "自动计算不得改写科研批准")
        compounds = {r["compound_id"]: r for r in packet["compounds"]}
        receptors = {r["target_id"]: r for r in packet["receptors"]}
        require([c["compound_id"] for c in packet["compounds"]] == [c["compound_id"] for c in connection["context"]["compounds"]] and [r["target_id"] for r in packet["receptors"]] == [r["target_id"] for r in connection["context"]["receptors"]], "自动准备对象或顺序与连接名单不一致")
        for receptor in packet["receptors"]:
            if receptor["state"] != "ready":
                continue
            original = next(r for r in connection["receptors"] if r["target_id"] == receptor["target_id"])
            candidate, evidence = receptor["selected_candidate"], receptor["evidence"]
            require(candidate in original["candidates"], "采用结构并非本轮连接对象")
            spec = candidate["spec"]
            result = assess(spec, evidence, authorization["id"], receptor)
            require(result["state"] == "ready" and result["quality"] == receptor["quality"], "受体质控与采用范围不一致")
            require(evidence["identity"]["source_review_id"] == connection["id"], "准备证据连接来源不一致")
            for record in evidence.get("files", []):
                verified_file(home, record)
            pocket_keys = None
            if spec["pocket"] == "p2rank":
                predicted = evidence["predicted_pocket"]
                rows = [_prediction_rows(verified_file(home, f))[0] for f in predicted["files"] if f["role"] == "p2rank_prediction"]
                keys = ("rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids")
                require(len(rows) == 2 and [{k: r[k] for k in keys} for r in rows] == evidence["pocket"]["runs"], "预测口袋与两次原始CSV不一致")
                box = box_from_prediction(verified_file(home, predicted["input_pdb"]).read_text("ascii"), rows[0], 5.0)
                require(box == evidence["box"], "搜索盒与真实首位预测残基不一致")
                pocket_keys = _residue_keys(rows[0]["residue_ids"])
            else:
                pose = _poses(verified_file(home, evidence["redocking_output"]).read_text("ascii"))[0]
                value = symmetry_rmsd(verified_file(home, evidence["reference_sdf"]).read_bytes(), verified_file(home, evidence["reference_pdbqt"]).read_text("ascii"), pose)["rmsd_angstrom"]
                require(abs(value - evidence["top1_rmsd"]) < 1e-9, "严格重对接RMSD与实际文件不一致")
            actual_environment = environment_audit(verified_file(home, candidate["cif"]).read_text("utf-8"), spec, evidence["box"], pocket_keys)
            require(actual_environment == evidence["environment_audit"] and actual_environment["pocket_complete"] and actual_environment["environment_resolved"], "口袋或必要环境与原坐标不一致")
        strict = [r["target_id"] for r in packet["receptors"] if r["state"] == "ready" and r["quality"] == "严格"]
        primary = strict[:5] if len(strict) >= 5 else []
        require(packet["primary_targets"] == primary and summary["主要受体数"] == len(primary) and summary["严格受体数"] == len(strict) and summary["探索受体数"] == sum(r["state"] == "ready" and r["quality"] == "探索" for r in packet["receptors"]), "严格与探索范围或主要受体被改变")
        binary = verified_file(home, packet["executable"])
        for row in packet["pairs"]:
            if row["state"] == "completed":
                require(isinstance(row["score"], (int, float)) and not isinstance(row["score"], bool) and math.isfinite(row["score"]), "自动得分无效")
                receptor = receptors[row["target_id"]]
                assessment = assess(receptor["selected_candidate"]["spec"], receptor["evidence"], authorization["id"], receptor)
                require(assessment["state"] == "ready" and row["quality"] == assessment["quality"], "未通过质控对象被计算或探索冒充严格")
                fact = row["execution"]
                poses = _poses(verified_file(home, fact["pose"]).read_text("ascii"))
                require(poses[0]["score_kcal_mol"] == row["score"], "评分与真实Top-1姿势不一致")
                ligand = next(r for r in compounds[row["compound_id"]]["files"] if r["role"] == "prepared_ligand")
                expected_atoms = {int(l[6:11]): l[77:].strip().split()[0] for l in verified_file(home, ligand).read_text("ascii").splitlines() if l.startswith(("ATOM  ", "HETATM"))}
                require(expected_atoms == {k: atom["atom_type"] for k, atom in poses[0]["atoms"].items()}, "Top-1原子身份与同一配体不一致")
                require(fact["config"]["compound"] == ligand and fact["config"]["receptor"] == receptor["evidence"]["receptor"] and all(fact["config"]["region"][k] == receptor["evidence"]["box"][k] for k in ("center", "size")), "得分并非使用所归档构型和位点")
                config = fact["config"]
                expected_command = _vina_arguments(binary, verified_file(home, config["receptor"]), verified_file(home, ligand), config["region"], verified_file(home, fact["pose"])) + ["--cpu", "2"]
                require(fact["command"] == expected_command and config["vina"] == EXECUTION_VINA and config["executable_sha256"] == packet["executable"]["sha256"] and fact["input_key"] == fingerprint(config) and fact["returncode"] == 0 and fact["state"] == "completed" and fact["score"] == row["score"], "实际执行参数、软件或状态与归档不一致")
                require(_inside_box(poses[0], {"center_angstrom": config["region"]["center"], "size_angstrom": config["region"]["size"]})["passed"], "姿势原子越出搜索盒，不能作为通过结果")
            else:
                require(row["state"] in ("NA", "failed") and row["score"] is None and row["reason_zh"], "异常组合须保留状态和原因，不填零")
        for label, state in (("成功组合数", "completed"), ("失败组合数", "failed"), ("NA组合数", "NA")):
            require(summary[label] == sum(p["state"] == state for p in packet["pairs"]), "自动结果数量不一致")
        require(summary["计划组合数"] == len(expected) and summary["handoff_blocked"] == (summary["成功组合数"] == 0), "自动结果交接条件不一致")
        require(summary["成分数"] == len(compounds) and summary["受体数"] == len(receptors), "自动对象数量不一致")
        require(tables["pairs"] == [{k: row[k] for k in ("compound_id", "target_id", "state", "score", "quality", "reason_zh")} for row in packet["pairs"]], "网页明细与自动结果不一致")
        require(outcome == "success", "自动结果状态不一致")
    return check
