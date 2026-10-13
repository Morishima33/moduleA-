"""全覆盖试算准备：逐候选补救，有限修补及简化模型均独立留证。"""

import csv
import json
import os
import subprocess
import sys

from docking_p2rank import _pdb_atoms, _residue_keys, box_from_prediction
from docking_top10_execute import _box_from_lines, _ligand_lines, _protein_pdb
from storage import file_record, verified_file, write_json

from .trial_rules import partitions


def coordinates(text):
    """只取实际蛋白重原子；PDBQT的AutoDock氢类型也明确排除。"""
    return [
        [float(line[a : a + 8]) for a in (30, 38, 46)]
        for line in text.splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
        and line[77:].strip().split()[0:1] not in (["H"], ["HD"], ["HS"])
        and line[76:78].strip() not in {"H", "D"}
    ]


def prediction_rows(path):
    """空口袋是有效无命中；不得伪造预测位点。"""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return sorted(
            [
                {k.strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(stream)
            ],
            key=lambda r: int(r["rank"]),
        )


def regions_from_predictions(text, rows):
    """所有可映射预测口袋独立归档；未映射者给出原因。"""
    regions, rejected = [], []
    for row in rows:
        try:
            mapped = {(a["chain"], a["residue"]) for a in _pdb_atoms(text)}
            if not _residue_keys(row["residue_ids"]) <= mapped:
                raise ValueError("预测口袋存在未映射残基，不能用部分包络冒充完整区域")
            box = box_from_prediction(text, row, 5.0)
            regions.append(
                {**box, "region_id": "pocket_" + str(row["rank"]), "prediction": row}
            )
        except Exception as error:  # noqa: BLE001 -- 单对象失败必须保留原始诊断。
            rejected.append({"prediction": row, "reason_zh": str(error)})
    return regions, rejected


def predict(tools, protein, folder):
    """固定P2Rank参数重复运行，读取全部预测；无输出转入分区盲搜。"""
    tool = tools / "environments/p2rank_2.5"
    outputs = []
    for repeat in (1, 2):
        out = folder / ("p2rank_" + str(repeat))
        command = [
            str(tool / "prank.bat"),
            "predict",
            "-f",
            str(protein),
            "-threads",
            "1",
            "-visualizations",
            "0",
            "-o",
            str(out),
        ]
        completed = subprocess.run(
            command,
            cwd=tool,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        write_json(
            folder / ("prediction_execution_" + str(repeat) + ".json"),
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )
        if completed.returncode:
            raise ValueError("P2Rank工具执行失败，不能解释为无口袋")
        paths = list(out.rglob("*_predictions.csv"))
        if len(paths) != 1:
            raise ValueError("预测表不存在或不唯一")
        outputs.append(prediction_rows(paths[0]))
    if outputs[0] != outputs[1]:
        raise ValueError("两次全部预测口袋不一致")
    return outputs[0]


def prepare_meeko(tools, protein, folder, symbol):
    """固定Meeko准备；不删除坏残基，不自动改变原子或工具参数。"""
    output = folder / (symbol + ".pdbqt")
    command = [
        sys.executable,
        "-B",
        "-m",
        "meeko.cli.mk_prepare_receptor",
        "--read_pdb",
        str(protein),
        "-o",
        str(folder / symbol),
        "-p",
        "--write_pdb",
        str(folder / (symbol + "_prepared.pdb")),
    ]
    env = dict(
        os.environ,
        PYTHONPATH=str(tools / "environments/docking_packages"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    done = subprocess.run(
        command,
        cwd=folder,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    write_json(
        folder / "meeko_execution.json",
        {
            "command": command,
            "returncode": done.returncode,
            "stdout": done.stdout,
            "stderr": done.stderr,
            "meeko_version": "0.8.0",
        },
    )
    if done.returncode or not output.is_file() or not output.stat().st_size:
        raise ValueError("Meeko准备失败：" + (done.stderr or done.stdout)[-1200:])
    return output


def reuse(root, row):
    """复用输入而不是旧评分；全部预测区域读取原始双次输出。"""
    selected = row["selected"]
    receptor = verified_file(root, selected["receptor"])
    spec = selected["spec"]
    mode, regions, rejected = (
        "fixed_site",
        [{**selected["box"], "region_id": "fixed_site"}],
        [],
    )
    if spec["pocket"] == "p2rank":
        records = [
            r
            for r in selected["predicted_pocket"]["files"]
            if r["role"] == "p2rank_prediction"
        ]
        rows = [prediction_rows(verified_file(root, rec)) for rec in records]
        if len(rows) != 2 or rows[0] != rows[1]:
            raise ValueError("复用预测区域的两次原始证据不一致")
        regions, rejected = regions_from_predictions(
            receptor.read_text("ascii"), rows[0]
        )
        mode = "predicted_sites"
        if not regions:
            mode, regions = (
                "partitioned_blind",
                partitions(coordinates(receptor.read_text("ascii"))),
            )
    return {
        "state": "ready",
        "spec": spec,
        "structure_id": spec.get("pdb_id", spec.get("model_id")),
        "receptor": selected["receptor"],
        "regions": regions,
        "mode": mode,
        "reused": True,
        "history_quality_zh": row["quality_zh"],
        "history_rmsd_A": selected.get("top1_rmsd"),
        "rejected_predictions": rejected,
        "processing_zh": "当前已核查准备输入指纹一致；仅复用准备，试算另存，未签署正式结果",
        "environment": selected.get("environment_audit", {}),
        "source": selected.get("source_file"),
    }


def candidate(root, row, attempt, folder, tools, repair_packages, code):
    """同一人类蛋白原件单独修补；共晶区域在评分前冻结。"""
    import gemmi

    spec = attempt["spec"]
    identities = attempt.get("source_audit", {}).get("identity", [])
    if not identities or any(i.get("identity_check") != "matched" for i in identities):
        raise ValueError("候选人类蛋白身份未核查匹配")
    source = verified_file(root, attempt["source_file"])
    folder.mkdir(parents=True, exist_ok=False)
    block = gemmi.cif.read_file(str(source)).sole_block()
    st = gemmi.make_structure_from_block(block)
    if len(st) != 1:
        raise ValueError("多模型未明确选定，不合并模型")
    original = folder / "source_conversion.pdb"
    original.write_text(st.make_pdb_string(), encoding="ascii")
    metals = [
        line
        for line in original.read_text("ascii").splitlines()
        if line.startswith("HETATM")
        and line[21] in spec["chains"]
        and line[76:78].strip().upper()
        in {"MG", "ZN", "FE", "MN", "CU", "CO", "NI", "CA"}
    ]
    if metals:
        raise ValueError("所选链含待保留参数化的金属，不能按添加剂删除，需独立替代结构")
    protein = folder / "observed_protein.pdb"
    protein.write_text(
        _protein_pdb(original, spec["chains"], spec.get("altloc")), encoding="ascii"
    )
    repaired = folder / "repaired_protein.pdb"
    evidence = folder / "repair_evidence.json"
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(code / "tools/repair_a06_trial.py"),
        "--packages",
        str(repair_packages),
        "--input",
        str(protein),
        "--output",
        str(repaired),
        "--evidence",
        str(evidence),
    ]
    done = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    write_json(
        folder / "repair_execution.json",
        {
            "command": command,
            "returncode": done.returncode,
            "stdout": done.stdout,
            "stderr": done.stderr,
        },
    )
    if done.returncode or not evidence.is_file():
        raise ValueError("有限修补失败：" + done.stderr[-1000:])
    repair = json.loads(evidence.read_text("utf-8"))
    receptor = prepare_meeko(tools, repaired, folder, row["symbol"])
    if spec["pocket"] == "reference":
        ligand = _ligand_lines(
            original,
            spec["reference_code"],
            spec["reference_chain"],
            spec["reference_sequence"],
            spec.get("altloc"),
        )
        (folder / "reference_coordinates.pdb").write_text(ligand, encoding="ascii")
        regions = [{**_box_from_lines(ligand), "region_id": "fixed_site"}]
        mode, rejected = "fixed_site", []
    else:
        rows = predict(tools, repaired, folder)
        regions, rejected = regions_from_predictions(repaired.read_text("ascii"), rows)
        mode = "predicted_sites"
        if not regions:
            mode, regions = (
                "partitioned_blind",
                partitions(coordinates(receptor.read_text("ascii"))),
            )
    # 原环境逐项留存；此分支不把蛋白单体/功能域的探索值称作原复合物严格结果。
    environment = attempt.get("environment_audit", {})
    return {
        "state": "ready",
        "spec": spec,
        "structure_id": spec.get("pdb_id", spec.get("model_id")),
        "receptor": file_record(root, receptor, "trial_receptor"),
        "regions": regions,
        "mode": mode,
        "reused": False,
        "repair": repair,
        "source": attempt["source_file"],
        "rejected_predictions": rejected,
        "environment": environment,
        "confidence": attempt.get("confidence_facts")
        if spec["source_type"] == "alphafold"
        else None,
        "history_quality_zh": "未通过原严格验证；仅试算",
        "history_rmsd_A": attempt.get("top1_rmsd"),
        "processing_zh": "实验所选链／功能域；仅补已解析残基侧链，原重原子坐标不变；未重建缺失主链。"
        "共晶参考配体用于定位并移除；未通过原质控的输入仅用于明确标注的试算。",
    }


def prepare(root, row, folder, tools, repair_packages, code, progress):
    """先复用七项，再逐项补救；不因失败删除受体列。"""
    base = {k: row[k] for k in ("target_id", "symbol", "candidate_grade", "ppi_order")}
    attempts = []
    if row["eligible"]:
        try:
            return {**base, **reuse(root, row), "attempts": attempts}
        except Exception as error:  # noqa: BLE001 -- 单对象失败必须保留原始诊断。
            attempts.append({"reason_zh": str(error), "reused": True})
    for index, origin in enumerate(row["attempts"]):
        if not origin.get("source_file"):
            continue
        progress(
            "准备 "
            + row["symbol"]
            + " / "
            + str(origin["spec"].get("pdb_id", origin["spec"].get("model_id")))
        )
        work = folder / row["target_id"].replace(":", "_") / f"candidate_{index:03d}"
        try:
            # GDP配位金属/必要伙伴不能被当添加剂删除；另选无该环境依赖的预测apo试算。
            env = origin.get("environment_audit", {})
            if env.get("retained_cofactors") or any(
                x.get("necessary") for x in (env.get("partners") or [])
            ):
                raise ValueError(
                    "候选含必要金属／伙伴，当前蛋白-only参数化不能保留；须独立替代模型"
                )
            prepared = candidate(root, row, origin, work, tools, repair_packages, code)
            return {**base, **prepared, "attempts": attempts}
        except Exception as error:  # noqa: BLE001 -- 单对象失败必须保留原始诊断。
            failure = {"spec": origin["spec"], "reason_zh": str(error)}
            attempts.append(failure)
            if work.is_dir() and not (work / "failure.json").exists():
                write_json(work / "failure.json", failure)
    # 已有候选均失败才扩大官方分页检索，不为了数量改变蛋白身份。
    try:
        from .trial_sources import supplemental

        search = folder / row["target_id"].replace(":", "_") / "supplemental"
        search.mkdir(parents=True, exist_ok=False)
        for index, origin in enumerate(supplemental(root, row, search)):
            work = search / f"prepared_{index:04d}"
            try:
                prepared = candidate(
                    root, row, origin, work, tools, repair_packages, code
                )
                return {**base, **prepared, "attempts": attempts}
            except Exception as error:  # noqa: BLE001 -- 单对象失败必须保留原始诊断。
                attempts.append({"spec": origin["spec"], "reason_zh": str(error)})
    except Exception as error:  # noqa: BLE001 -- 单对象失败必须保留原始诊断。
        attempts.append({"reason_zh": "扩大检索失败：" + str(error)})
    return {
        **base,
        "state": "NA",
        "mode": "partitioned_blind",
        "regions": [],
        "reason_zh": "所有已核对候选准备失败，详见逐项记录",
        "attempts": attempts,
    }
