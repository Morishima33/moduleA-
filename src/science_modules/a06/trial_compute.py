"""独立试算生产器；保存225组合及所有实际区域命令、姿势和最低值来源。"""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from docking_redocking import _poses
from docking_top10_execute import _vina_arguments
from storage import file_record, now, read_json, verified_file, write_json

from .trial_prepare import prepare
from .trial_rules import VERSION, VINA, choose_score, fingerprint, validate_matrix


def score_region(root, folder, executable, compound, receptor, region):
    """输入指纹绑定实际结构、成分和搜索配置；不引用历史对接分数。"""
    work = (
        folder
        / "scores"
        / compound["compound_id"]
        / receptor["target_id"].replace(":", "_")
        / region["region_id"]
    )
    work.mkdir(parents=True, exist_ok=False)
    ligand_rec = next(f for f in compound["files"] if f["role"] == "prepared_ligand")
    ligand, protein = (
        verified_file(root, ligand_rec),
        verified_file(root, receptor["receptor"]),
    )
    output = work / "poses.pdbqt"
    command = _vina_arguments(executable, protein, ligand, region, output) + [
        "--cpu",
        "2",
    ]
    config = {
        "compound": ligand_rec,
        "receptor": receptor["receptor"],
        "region": region,
        "version": VERSION,
        "vina": VINA,
        "executable_sha256": file_record(
            root.parent.parent.parent, executable, "vina_executable"
        )["sha256"]
        if executable.is_relative_to(root.parent.parent.parent)
        else __import__("hashlib").sha256(executable.read_bytes()).hexdigest(),
    }
    fact = {
        "region_id": region["region_id"],
        "input_key": fingerprint(config),
        "config": config,
        "command": command,
        "started_at": now(),
        "state": "NA",
        "score": None,
    }
    try:
        done = subprocess.run(
            command,
            cwd=work,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
        (work / "stdout.txt").write_text(done.stdout, encoding="utf-8")
        (work / "stderr.txt").write_text(done.stderr, encoding="utf-8")
        fact["returncode"] = done.returncode
        if done.returncode or not output.is_file():
            raise ValueError("Vina失败：" + done.stderr[-600:])
        poses = _poses(output.read_text("ascii"))
        # 原子编号和类型必须与同一配体输入一致；禁止损坏输出冒充得分。
        expected = {
            int(l[6:11]): l[77:].strip().split()[0]
            for l in ligand.read_text("ascii").splitlines()
            if l.startswith(("ATOM  ", "HETATM"))
        }
        if expected != {k: a["atom_type"] for k, a in poses[0]["atoms"].items()}:
            raise ValueError("Top-1姿势原子身份与配体输入不一致")
        fact.update(
            state="completed",
            score=poses[0]["score_kcal_mol"],
            pose=file_record(root, output, "trial_pose"),
            mode_count=len(poses),
            reason_zh="",
        )
    except Exception as error:  # noqa: BLE001 -- 单对象失败必须保留原始诊断。
        fact["reason_zh"] = str(error)
    fact["finished_at"] = now()
    write_json(work / "execution.json", fact)
    return fact


def run(workflow, sid, payload, tools, repair_packages, code, progress):
    """固定15×15名单，所有受体采用同一批成分与同一冻结区域集合。"""
    trial_id, folder, context, display = workflow.begin_trial(sid, payload)
    root = workflow.location(sid)
    manifest = workflow.load(sid)
    base_result = workflow.result(manifest, payload["expected_base_run"])
    old_record = base_result["tables"]["coverage_packet"][0]
    old = read_json(verified_file(root, old_record))
    if old["source_key"] != context["source_key"]:
        raise ValueError("准备资料与已批准来源不一致")
    config = display["config"]
    compound_map = {c["compound_id"]: c for c in old["compounds"]}
    receptor_map = {r["target_id"]: r for r in old["receptors"]}
    compounds = [compound_map[c] for c in config["table_compounds"]]
    for compound in compounds:
        if (
            compound["state"] != "ready"
            or compound["preparation"]["identity"]["identity_check"] != "matched"
        ):
            raise ValueError("已确认成分身份或来源三维准备发生变化")
        for rec in compound["files"]:
            verified_file(root, rec)
    packet = {
        "schema_version": VERSION,
        "trial_id": trial_id,
        "study_id": sid,
        "source_key": context["source_key"],
        "created_at": now(),
        "display": display,
        "compounds": compounds,
        "receptors": [],
        "pairs": [],
        "vina": VINA,
        "formal_approval": None,
        "unit": "kcal/mol",
        "base_packet": old_record,
        "execution_resources": {"parallel_regions": 4, "cpu_per_region": 2},
        "execution_code": {
            p.name: __import__("hashlib").sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                Path(__file__).with_name("trial_prepare.py"),
                Path(__file__).with_name("trial_rules.py"),
                code / "tools/repair_a06_trial.py",
            ]
        },
    }
    # 将实际执行源码逐字节留在本研究试算包，后续代码细化不影响旧批次复现。
    executed = folder / "execution_code"
    executed.mkdir()
    for name in packet["execution_code"]:
        source = (
            code / "tools" / name
            if name == "repair_a06_trial.py"
            else Path(__file__).with_name(name)
        )
        (executed / name).write_bytes(source.read_bytes())
    state = {
        "trial_id": trial_id,
        "state": "preparing",
        "pairs_done": 0,
        "pairs_total": 225,
        "regions_done": 0,
        "regions_total": 0,
        "receptors_done": 0,
        "receptors_total": 15,
    }

    def update(text):
        state["step_zh"] = text
        write_json(folder / "progress.json", state, replace=True)
        progress(json.dumps(state, ensure_ascii=False))

    for target in config["table_targets"]:
        row = prepare(
            root,
            receptor_map[target],
            folder / "preparation",
            tools,
            repair_packages,
            code,
            update,
        )
        row["preparation_key"] = fingerprint(row)
        packet["receptors"].append(row)
        state["receptors_done"] += 1
        update("受体准备 " + str(state["receptors_done"]) + "/15")
    write_json(folder / "preparation.json", packet)
    executable = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    state["state"] = "scoring"
    state["regions_total"] = sum(len(r["regions"]) * 15 for r in packet["receptors"])
    update("开始真实区域试算")
    # 四个独立区域各用两核；只控制资源，科学评分参数保持不变。
    for receptor in packet["receptors"]:
        by_compound = {c["compound_id"]: [] for c in compounds}
        if receptor["state"] == "ready":
            with ThreadPoolExecutor(max_workers=4) as pool:
                pending = {
                    pool.submit(
                        score_region, root, folder, executable, c, receptor, region
                    ): c
                    for c in compounds
                    for region in receptor["regions"]
                }
                for future in as_completed(pending):
                    compound = pending[future]
                    by_compound[compound["compound_id"]].append(future.result())
                    state["regions_done"] += 1
                    update(
                        "区域 "
                        + str(state["regions_done"])
                        + "/"
                        + str(state["regions_total"])
                    )
        for compound in compounds:
            regions = sorted(
                by_compound[compound["compound_id"]], key=lambda r: r["region_id"]
            )
            best = choose_score(regions, receptor["mode"])
            pair = {
                "compound_id": compound["compound_id"],
                "target_id": receptor["target_id"],
                "mode": receptor["mode"],
                "regions": regions,
                "state": "completed" if best else "NA",
                "score": best["score"] if best else None,
                "selected_region_id": best["region_id"] if best else None,
                "reason_zh": ""
                if best
                else receptor.get("reason_zh", "全部区域计算失败，详见执行日志"),
                "partial_regions": any(r["state"] != "completed" for r in regions),
            }
            packet["pairs"].append(pair)
            state["pairs_done"] += 1
            update(receptor["symbol"] + " × " + compound["name_zh"] + " 已留存")
    validate_matrix(packet)
    packet["finished_at"] = now()
    packet["summary"] = {
        "pairs": 225,
        "completed": sum(p["state"] == "completed" for p in packet["pairs"]),
        "NA": sum(p["state"] == "NA" for p in packet["pairs"]),
        "regions": state["regions_total"],
        "prepared_receptors": sum(r["state"] == "ready" for r in packet["receptors"]),
    }
    path = folder / "packet.json"
    write_json(path, packet)
    files = [
        file_record(root, p, "trial_evidence")
        for p in folder.rglob("*")
        if p.is_file() and p.name != "progress.json"
    ]
    workflow.finish_trial(sid, trial_id, path, files)
    state["state"] = "completed"
    update("试算已完成；正式科研结果未自动批准")
    return packet
