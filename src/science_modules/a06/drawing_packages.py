"""复用现有PyMOL出图脚本，将已归档同源姿势整理为逐组合任务包；不调用Vina。"""

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from contracts import require
from docking_task_package import _pml, _selected_pose
from storage import file_record, read_json, verified_file


def _write(path, text):
    """新任务目录内写入可追溯说明，已有文件禁止覆盖。"""
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(text)


def _source_files(study, pair, destination):
    """复制实际选中区域的输入和全部姿势，固定该区域Top-1。"""
    if pair.get("region"):
        region = pair["region"]
        require(region["score"] == pair["score"], "选定区域评分与矩阵不一致")
        if pair.get("automatic"):
            # 自动协议的实际区域已有同格式配置；再次核对采用文件归属，不从图表重建姿势。
            require(region.get("state") == "completed", "自动出图必须采用通过的区域")
            require(region["config"]["compound"] in pair["compound"].get("files", []),
                    "自动出图配体不属于本组合准备文件")
            receptor = pair["receptor"]
            actual_receptor = receptor.get("receptor") or receptor.get("evidence", {}).get("receptor")
            require(actual_receptor == region["config"]["receptor"], "自动出图受体与采用构型不一致")
        records = {
            "receptor.pdbqt": region["config"]["receptor"],
            "ligand.pdbqt": region["config"]["compound"],
            "output.pdbqt": region["pose"],
        }
        for name, record in records.items():
            shutil.copy2(verified_file(study, record), destination / name)
        pose = _selected_pose((destination / "output.pdbqt").read_text("ascii"), 1)
        raw_score = float(
            next(
                line.split()[3]
                for line in pose.splitlines()
                if line.startswith("REMARK VINA RESULT:")
            )
        )
        require(raw_score == pair["score"], "Top-1原始评分与矩阵不一致")
        _write(destination / "selected_pose.pdbqt", pose)
        vina, box = region["config"]["vina"], region["config"]["region"]
        _write(
            destination / "execution_record.json", json.dumps(region, ensure_ascii=False, indent=2)
        )
        # 归档中没有独立日志时如实标明，不编造原Vina输出。
        _write(
            destination / "log.txt",
            "本组合来源为execution_record.json中的实际区域执行记录；原归档未单独登记Vina标准输出日志。\n",
        )
        source = {
            "selected_region_id": region["region_id"],
            "mode": pair["mode"],
            "original_files": records,
            "original_command": region["command"],
        }
    else:
        row = pair["generic_row"]
        for key, name in (
            ("receptor_record", "receptor.pdbqt"),
            ("ligand_record", "ligand.pdbqt"),
            ("pose_record", "selected_pose.pdbqt"),
            ("log_record", "log.txt"),
        ):
            require(row.get(key), "原任务包缺少来源：" + key)
            shutil.copy2(verified_file(study, row[key]), destination / name)
        command = read_json(verified_file(study, row["command_record"]))
        all_poses = row.get("all_poses_record")
        require(all_poses, "原任务包未明确登记全部姿势")
        shutil.copy2(verified_file(study, all_poses), destination / "output.pdbqt")
        values = command["parameters"]
        vina = {k: values[k] for k in ("scoring", "exhaustiveness", "num_modes", "seed")}
        vina["energy_range"] = values["energy_range_kcal_mol"]
        box = command["search_box"]
        source = {"original_row": row, "original_command": command}
    lines = ["receptor = receptor.pdbqt", "ligand = ligand.pdbqt"]
    lines += [
        f"{kind}_{axis} = {value}"
        for kind in ("center", "size")
        for axis, value in zip("xyz", box[kind])
    ]
    lines += [
        f"{key} = {vina[key]}"
        for key in ("scoring", "exhaustiveness", "num_modes", "energy_range", "seed")
    ]
    _write(destination / "config.txt", "\n".join(lines) + "\n")
    return source


def build_pair_package(workflow, study_id, a06, binding, pair, pymol_exe):
    """生成PDB、PSE和距离接触记录，输出逐组合ZIP及全部文件指纹。"""
    require(pair["eligible"], "本轮仅整理原始评分≤−8的组合")
    require(Path(pymol_exe).is_file(), "未找到PyMOL，请核对本机出图环境")
    folder = workflow.artifact_workspace(study_id, a06)
    package = folder / pair["pair_key"]
    package.mkdir()
    study = workflow.location(study_id)
    source = _source_files(study, pair, package)
    pair_id = pair["pair_key"]
    _write(package / "01_open_in_pymol.pml", _pml(pair_id))
    # 包内入口提供环境变量/本机已配置程序/PATH三种已有安装定位方式。
    launcher = (
        '@echo off\ncd /d "%~dp0"\n'
        'if defined MODULEA_PYMOL_EXE ("%MODULEA_PYMOL_EXE%" -r "01_open_in_pymol.pml" & exit /b)\n'
        f'if exist "{pymol_exe}" ("{pymol_exe}" -r "01_open_in_pymol.pml" & exit /b)\n'
        'pymol -r "01_open_in_pymol.pml"\nif errorlevel 1 pause\n'
    )
    _write(package / "START_PYMOL.cmd", launcher)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    process = subprocess.run(
        [str(pymol_exe), "-cq", "01_open_in_pymol.pml"],
        cwd=package,
        env=environment,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    _write(package / "pymol_build_log.txt", process.stdout + "\n" + process.stderr)
    expected = [f"result_{pair_id}.pdb", f"session_{pair_id}.pse", "hbond_info.txt"]
    require(
        process.returncode == 0
        and all((package / p).is_file() and (package / p).stat().st_size for p in expected),
        "PyMOL出图包制作失败，请查看任务日志和保留草案",
    )
    metadata = {
        "schema_version": "A06.drawing.pair.package.1",
        "binding": binding,
        "compound_id": pair["compound_id"],
        "compound_name_zh": pair["compound_name_zh"],
        "target_id": pair["target_id"],
        "target_zh": pair["target_zh"],
        "score_kcal_mol": pair["score"],
        "pose_rule": "selected_region_top_1",
        "scope_zh": pair["scope_zh"],
        "source": source,
    }
    _write(package / "pair.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    _write(
        package / "使用说明.txt",
        f"{pair['compound_name_zh']} × {pair['target_zh']}；原始评分 {pair['score']} kcal/mol。\n"
        "先解压到独立目录，再双击START_PYMOL.cmd或用PyMOL打开session文件。PDB是同源受体和固定姿势合并结构。\n"
        "selected_pose.pdbqt与矩阵同源；output.pdbqt保留全部原姿势；config.txt供追溯，不要求重新对接。\n"
        "可以调整视角、标签和出图样式，图片随后在A06页面上传并填写说明。\n"
        "hbond_info.txt及红色虚线是N/O距离接触，不能直接视为已确认氢键。\n"
        + pair["scope_zh"]
        + "\n",
    )
    contents = [
        {"path": p.name, "bytes": p.stat().st_size, "sha256": sha256(p.read_bytes()).hexdigest()}
        for p in sorted(package.iterdir())
        if p.is_file()
    ]
    _write(
        package / "package_index.json",
        json.dumps({"pair_key": pair_id, "files": contents}, indent=2),
    )
    archive = folder / (pair_id + ".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(package.iterdir()):
            if path.is_file():
                output.write(path, pair_id + "/" + path.name)
    files = [file_record(study, archive, "docking_pair_archive")]
    files += [
        file_record(study, p, "drawing_package_file")
        for p in sorted(package.iterdir())
        if p.is_file()
    ]
    item = {
        "kind": "package",
        "pair_key": pair_id,
        "name_zh": pair["compound_name_zh"] + " × " + pair["target_zh"],
        "files": files,
    }
    return workflow.publish_artifact(study_id, a06, binding, item)


def prepare_packages(workflow, study_id, payload, pymol_exe, progress=lambda done, total: None):
    """逐项制作并及时归档；中断后只复用同版本已完成包。"""
    manifest, binding, selected = workflow.validate_artifact_request(study_id, payload)
    records = workflow.artifact_records(manifest)
    available = {
        r["pair_key"]: r for r in records if r["kind"] == "package" and r["binding"] == binding
    }
    rows = []
    for number, pair in enumerate(selected, 1):
        old = available.get(pair["pair_key"])
        if old:
            for record in old["files"]:
                verified_file(workflow.location(study_id), record)
            rows.append(old)
        else:
            rows.append(
                build_pair_package(
                    workflow, study_id, payload["expected_a06"], binding, pair, pymol_exe
                )
            )
        progress(number, len(selected))
    return rows


def build_selected_bundle(workflow, study_id, payload):
    """仅将已准备且被选中的逐组合ZIP打包，不制作额外组合或计算评分。"""
    manifest, binding, pairs = workflow.validate_artifact_request(study_id, payload, ready=True)
    records = {
        r["pair_key"]: r
        for r in workflow.artifact_records(manifest)
        if r["kind"] == "package" and r["binding"] == binding
    }
    folder = workflow.artifact_workspace(study_id, payload["expected_a06"])
    path = folder / "selected_docking_packages.zip"
    with zipfile.ZipFile(path, "x", zipfile.ZIP_STORED) as output:
        for pair in pairs:
            source = verified_file(
                workflow.location(study_id), records[pair["pair_key"]]["files"][0]
            )
            output.write(source, pair["pair_key"] + ".zip")
        output.writestr(
            "组合索引.json",
            json.dumps(
                [
                    {k: p[k] for k in ("pair_key", "compound_name_zh", "target_zh", "score")}
                    for p in pairs
                ],
                ensure_ascii=False,
                indent=2,
            ),
        )
    return workflow.publish_artifact(
        study_id,
        payload["expected_a06"],
        binding,
        {
            "kind": "bundle",
            "pair_keys": [p["pair_key"] for p in pairs],
            "name_zh": f"所选{len(pairs)}组对接出图包",
            "files": [file_record(workflow.location(study_id), path, "selected_pair_archives")],
        },
    )
