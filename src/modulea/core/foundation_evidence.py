"""同批准备与Top-1构象的只读证据视图；只读归档，不联网、不调用工具或修改科研状态。"""
from copy import deepcopy
from pathlib import Path
import math
from urllib.parse import urlencode

from contracts import fingerprint, require
from storage import read_json, verified_file

VERSION = "ModuleA.foundation_evidence.1"
SCORING = ("A06.system_scoring.1", "A06.system_scoring.2", "A06.system_scoring_paths.1", "A06.system_scoring.3")


def _same_file(left, right):
    """文件角色可以有展示别名，但相对路径、实际长度和SHA必须一致。"""
    return isinstance(left, dict) and isinstance(right, dict) and all(left.get(k) == right.get(k) for k in ("path", "bytes", "sha256"))


def _download(home, sid, reference, files, label):
    """只为本模块既有文件索引中的实际原件建立下载链接，不创造路径权限。"""
    verified_file(home, reference)
    found = next((item for item in files if _same_file(item, reference) and item.get("key")), None)
    if found is None:
        return None
    return {"label_zh": label, "name": Path(reference["path"]).name, "sha256": reference["sha256"],
            "url": f"/api/v1/studies/{sid}/files/{found['key']}"}


def _preparation(home, manifest, run, result, fixed):
    """评分页沿真实父运行回读准备，历史页不借用当前新准备。"""
    source_run, source_result = run, result
    if run["module_id"] == "A06":
        rid = run.get("parent_runs", {}).get("A06_PREP")
        registered = manifest.get("runs", {}).get(rid, {})
        require(rid and _same_file(registered.get("run_file"), run["inputs"].get("preparation_run"))
                and _same_file(registered.get("result_file"), run["inputs"].get("preparation_result")),
                "评分证据未绑定本研究实际登记的准备运行")
        source_run = read_json(verified_file(home, registered["run_file"]))
        source_result = read_json(verified_file(home, registered["result_file"]))
        require(source_run["run_id"] == source_result["run_id"] == rid and source_run["module_id"] == "A06_PREP"
                and source_run["batch_file"] == run["batch_file"]
                and source_run["inputs"]["system_input_ref"] == run["inputs"]["system_input_ref"],
                "评分证据准备运行、原批次或固定范围不一致")
    require(source_run["study_id"] == source_result["study_id"] == manifest["study_id"], "准备证据不属于本研究")
    refs = source_result.get("tables", {}).get("preparation_packet", [])
    require(len(refs) == 1, "准备证据缺少唯一实际归档包")
    fact = read_json(verified_file(home, refs[0]))
    require(fact.get("study_id") == manifest["study_id"] and fact.get("input_key") == fixed["input_key"]
            and fact.get("schema_version") == source_run["config"]["version"]
            and fingerprint(fact.get("configuration", fact.get("config"))) == fingerprint(source_run["config"]),
            "准备证据归属、固定范围或实际配置不一致")
    require([r["compound_id"] for r in fact["compounds"]] == [r["compound_id"] for r in fixed["compounds"]]
            and [r["target_id"] for r in fact["receptors"]] == [r["target_id"] for r in fixed["receptors"]],
            "准备证据对象或次序与本批固定名单不同")
    return fact


def _preparation_rows(home, sid, fact, fixed, files):
    """逐尝试展示原核验依据；没有环境审计记录时保留未知，不能把空列表当作通过。"""
    rows = []
    for original, receptor in zip(fixed["receptors"], fact["receptors"]):
        for index, attempt in enumerate(receptor.get("attempts") or [{}], 1):
            spec = (attempt.get("candidate") or {}).get("spec") or {}
            evidence = attempt.get("evidence") or {}
            audit = evidence.get("environment_audit")
            environment_recorded = isinstance(audit, dict)
            audit = audit if environment_recorded else {}
            identities = evidence.get("identity") or {}
            downloads = []
            for key, label in (("receptor", "实际准备受体"), ("reference_sdf", "共晶参考SDF"),
                               ("reference_pdbqt", "共晶参考PDBQT"), ("redocking_output", "参考配体重对接输出")):
                if evidence.get(key):
                    item = _download(home, sid, evidence[key], files, label)
                    if item: downloads.append(item)
            for ref in (evidence.get("predicted_pocket") or {}).get("files", []):
                if ref.get("role") == "p2rank_prediction":
                    item = _download(home, sid, ref, files, "原始口袋预测")
                    if item: downloads.append(item)
            assessment = attempt.get("assessment") or {}
            rows.append({"target_id": receptor["target_id"], "symbol": original.get("symbol") or receptor["target_id"],
                         "attempt": index, "structure_id": evidence.get("structure_id") or spec.get("pdb_id") or spec.get("model_id"),
                         "state": receptor["state"], "quality": receptor.get("quality"),
                         "reason_zh": receptor.get("reason_zh") or "原记录未提供核查原因",
                         "attempt_reason_zh": assessment.get("reason_zh") or evidence.get("error_zh") or "未记录",
                         "chains": deepcopy(identities.get("chains", spec.get("chains"))),
                         "uniprot": identities.get("uniprot", spec.get("uniprot")),
                         "reference": deepcopy(evidence.get("reference")), "pocket_method": spec.get("pocket"),
                         "top1_rmsd": evidence.get("top1_rmsd"), "box": deepcopy(evidence.get("box")),
                         "pocket_complete": evidence.get("pocket_complete") if environment_recorded else None,
                         "environment_resolved": evidence.get("environment_resolved") if environment_recorded else None,
                         "missing_atoms": deepcopy(audit.get("missing_pocket_atoms")) if environment_recorded else None,
                         "unobserved_residues": deepcopy(audit.get("adjacent_unobserved_residues")) if environment_recorded else None,
                         "environment_components": deepcopy(audit.get("box_environment")) if environment_recorded else None,
                         "environment_note_zh": audit.get("note_zh") or "按原准备范围展示；未记录不表示不存在缺失或伴随组分。",
                         "downloads": downloads})
            rows[-1]["state_zh"] = {"ready": "准备可用", "NA": "准备NA", "failed": "准备失败"}.get(receptor["state"], receptor["state"])
            rows[-1]["pocket_complete_zh"] = ("未完成核查" if not environment_recorded else
                "原记录为完整" if evidence.get("pocket_complete") is True else "原记录为不完整" if evidence.get("pocket_complete") is False else "原记录未说明")
            rows[-1]["environment_resolved_zh"] = ("未完成核查" if not environment_recorded else
                "原记录已核定" if evidence.get("environment_resolved") is True else "原记录待核定" if evidence.get("environment_resolved") is False else "原记录未说明")
            for raw_key, text_key in (("missing_atoms", "missing_atoms_zh"), ("unobserved_residues", "unobserved_residues_zh"),
                                      ("environment_components", "environment_components_zh")):
                original_rows = rows[-1][raw_key]
                rows[-1][text_key] = None if original_rows is None else [
                    " / ".join(str(item[key]) for key in ("chain", "residue", "sequence", "atom") if item.get(key) not in (None, ""))
                    + ("（其他聚合物）" if item.get("polymer") is True else "") for item in original_rows]
    return rows


def _ligand(row):
    """沿用准备包的唯一参数化配体，不按名称重新挑选文件。"""
    matches = [ref for ref in row.get("files", []) if ref.get("role") == "prepared_ligand"]
    require(row.get("state") == "ready" and len(matches) == 1, "评分证据配体没有唯一实际准备文件")
    return matches[0]


def _receptor(row):
    """只采用已登记合格尝试；不从多个结构中重新择优。"""
    chosen = row.get("system_qualified_attempt")
    if not chosen:
        matches = [a for a in row.get("attempts", []) if (a.get("assessment") or {}).get("state") == "ready"]
        require(len(matches) == 1, "评分证据受体缺少唯一实际合格尝试")
        chosen = matches[0]
    require(row.get("state") == "ready" and chosen.get("assessment", {}).get("state") == "ready",
            "评分证据受体并未准备可用")
    return chosen["evidence"]


def _arguments(home, command, run, ligand, receptor, box, binary, output):
    """原命令必须逐项对应保存的输入与参数；只核验，不启动Vina。"""
    require(fingerprint(command.get("configuration")) == fingerprint(run["config"])
            and _same_file(command.get("ligand"), ligand) and _same_file(command.get("receptor"), receptor)
            and _same_file(command.get("executable"), binary) and fingerprint(command.get("box")) == fingerprint(box),
            "构象命令的原件、参数或搜索盒与本批准备不同")
    expected = [str(verified_file(home, binary)), "--receptor", str(verified_file(home, receptor)),
                "--ligand", str(verified_file(home, ligand))]
    require(isinstance(box, dict) and all(isinstance(box.get(k), list) and len(box[k]) == 3 for k in ("center", "size")),
            "构象证据搜索盒格式错误")
    require(all(type(n) in (int, float) and math.isfinite(n) for n in box["center"] + box["size"])
            and all(n > 0 for n in box["size"]), "构象证据搜索盒数值无效")
    for name in ("center", "size"):
        for axis, value in zip("xyz", box[name]): expected += ["--" + name + "_" + axis, str(value)]
    for flag, key in (("scoring", "scoring"), ("exhaustiveness", "exhaustiveness"), ("num_modes", "num_modes"),
                      ("energy_range", "energy_range_kcal_mol"), ("seed", "seed")):
        expected += ["--" + flag, str(run["config"]["vina_parameters"][key])]
    expected += ["--cpu", str(run["config"]["cpu_per_pair"]), "--out", str(home / output["path"])]
    actual = command.get("arguments", [])
    path_indices = {0} | {expected.index(flag) + 1 for flag in ("--receptor", "--ligand", "--out")}
    require(len(actual) == len(expected) and all(isinstance(a, str) and
            (Path(a).resolve() == Path(b).resolve() if i in path_indices else a == b)
            for i, (a, b) in enumerate(zip(actual, expected))), "构象原命令与实际参数或搜索盒不一致")


def _execution(home, run, pair, index, ligand, receptor, binary):
    """按冻结原解析器复验原始全部模式、原子和Top-1，不改选分数更低的其他姿势。"""
    from docking_redocking import _poses, _inside_box
    ref = pair.get("execution")
    prefix = f"runs/A06/{run['run_id']}/system_scoring/scores/pair_{index:06d}/"
    require(isinstance(ref, dict) and ref.get("path", "").startswith(prefix)
            and ref["path"].endswith("/execution.json") and "/" not in ref["path"][len(prefix):-len("/execution.json")],
            "构象执行证据不属于本运行实际组合")
    value = read_json(verified_file(home, ref))
    require(value.get("state") == pair["state"] and fingerprint(value.get("score")) == fingerprint(pair.get("score")),
            "构象执行状态或评分与结果表不同")
    references = value.get("files", [])
    for item in references: verified_file(home, item)
    commands = [item for item in references if item["path"] == str(Path(ref["path"]).parent / "command.json").replace("\\", "/")]
    require(len(commands) == 1, "构象执行证据缺少唯一原命令")
    command = read_json(verified_file(home, commands[0]))
    output = value.get("pose") or {"path": str(Path(ref["path"]).parent / "poses.pdbqt").replace("\\", "/")}
    _arguments(home, command, run, _ligand(ligand), receptor["receptor"], receptor["box"], binary, output)
    if pair["state"] == "failed":
        require(value.get("score") is None and value.get("top_mode") is None and value.get("reason_zh"),
                "失败执行必须保留空评分与原原因")
        return value
    require(value.get("state") == "completed" and value.get("returncode") == 0 and value.get("failure_kind") is None
            and value.get("reason_zh") == "" and value.get("pose") in references,
            "成功构象执行状态或原文件索引不一致")
    text = verified_file(home, output).read_text("ascii")
    poses = _poses(text)
    expected = {int(line[6:11]): line[77:].strip().split()[0]
                for line in verified_file(home, _ligand(ligand)).read_text("ascii").splitlines()
                if line.startswith(("ATOM  ", "HETATM"))}
    counts = []
    for line in text.splitlines():
        if line.startswith("MODEL "): counts.append(0)
        elif line.startswith(("ATOM  ", "HETATM")) and counts: counts[-1] += 1
    require(expected and len(poses) <= run["config"]["vina_parameters"]["num_modes"]
            and len(counts) == len(poses) and all(count == len(expected) for count in counts)
            and all({i: a["atom_type"] for i, a in p["atoms"].items()} == expected for p in poses),
            "构象输出原子身份或模式数与实际准备不同")
    require(_inside_box(poses[0], {"center_angstrom": receptor["box"]["center"], "size_angstrom": receptor["box"]["size"]})["passed"],
            "构象Top-1越过已核定搜索盒")
    require(value.get("top_mode") == 1 and type(value.get("top_mode")) is int and value.get("mode_count") == len(poses)
            and type(pair.get("score")) in (int, float) and math.isfinite(pair["score"])
            and pair["score"] == poses[0]["score_kcal_mol"], "结果评分不是原始Top-1构象的评分")
    return value


def _scores(home, sid, run, result, fact, fixed, files):
    """按本批固定笛卡尔顺序核验全部组合，只为通过关联核验的原件提供链接。"""
    refs = result["tables"].get("scoring_packet", [])
    require(len(refs) == 1, "评分证据缺少唯一实际归档包")
    packet = read_json(verified_file(home, refs[0]))
    require(packet.get("study_id") == sid and packet.get("run_id") == run["run_id"]
            and packet.get("schema_version") == run["config"]["version"]
            and fingerprint(packet.get("configuration")) == fingerprint(run["config"])
            and fingerprint(packet.get("inputs")) == fingerprint(run["inputs"]), "构象评分包归属或配置不同")
    binary = packet["binary"]
    verified_file(home, binary)
    compounds = {r["compound_id"]: r for r in fact["compounds"]}
    receptors = {r["target_id"]: r for r in fact["receptors"]}
    pairs, table = packet["pairs"], result["tables"]["plan_scoring_pairs"]
    expected = [(c["compound_id"], r["target_id"]) for c in fixed["compounds"] for r in fixed["receptors"]]
    require([(r["compound_id"], r["target_id"]) for r in pairs] == expected and len(table) == len(pairs),
            "构象证据未覆盖本批原固定组合或次序不同")
    names = {c["compound_id"]: c.get("name") or c["compound_id"] for c in fixed["compounds"]}
    symbols = {r["target_id"]: r.get("symbol") or r["target_id"] for r in fixed["receptors"]}
    rows = []
    for index, (pair, shown) in enumerate(zip(pairs, table), 1):
        require(all(fingerprint(pair.get(k)) == fingerprint(shown.get(k)) for k in
                    ("compound_id", "target_id", "state", "score", "quality", "reason_zh", "input_key"))
                and pair.get("input_key") == fixed["input_key"], "构象评分表与本批真实记录不一致")
        row = {key: deepcopy(pair.get(key)) for key in ("compound_id", "target_id", "state", "score", "quality", "reason_zh")}
        row.update(compound_name=names[pair["compound_id"]], symbol=symbols[pair["target_id"]],
                   top_mode=None, pose_sha256=None, box=None, downloads=[],
                   state_zh={"completed": "已评分", "failed": "评分失败", "NA": "准备NA"}.get(pair["state"], pair["state"]))
        if pair["state"] in ("completed", "failed"):
            evidence = _receptor(receptors[pair["target_id"]])
            value = _execution(home, run, pair, index, compounds[pair["compound_id"]], evidence, binary)
            require(shown.get("execution_path") == pair["execution"]["path"], "构象文件与表格指向了不同执行")
            row.update(box=deepcopy(evidence["box"]), failure_kind=value.get("failure_kind"))
            if pair["state"] == "completed":
                row.update(top_mode=1, pose_sha256=value["pose"]["sha256"])
                base = f"/api/v1/studies/{sid}/runs/{run['run_id']}/foundation/pairs/{index}"
                query = urlencode({"expected_input_key": fixed["input_key"], "expected_pose_sha256": value["pose"]["sha256"]})
                row.update(top1_download_url=base + "/top1.pdbqt?" + query, context_download_url=base + "/context.json?" + query)
                for ref, label in ((value["pose"], "原始对接构象PDBQT（保留全部模式）"),
                                   (evidence["receptor"], "本组合准备受体"),
                                   (_ligand(compounds[pair["compound_id"]]), "本组合准备配体"),
                                   (pair["execution"], "原始执行记录")):
                    download = _download(home, sid, ref, files, label)
                    if download: row["downloads"].append(download)
        else:
            require(pair["state"] == "NA" and pair.get("score") is None and pair.get("execution") is None
                    and pair.get("reason_zh") and shown.get("execution_path") is None, "准备NA不能带入评分或其他构象")
        rows.append(row)
    return rows


def build(workflow, manifest, run, result, fixed, files):
    """增加只读证据，不改变原评分、固定范围、模块状态或人工复核资格。"""
    tables = result.get("tables") or {}
    if not tables.get("preparation_packet") and not tables.get("scoring_packet"):
        return None
    sid = manifest["study_id"]
    require(run.get("study_id") == result.get("study_id") == sid and run.get("run_id") == result.get("run_id")
            and result.get("summary", {}).get("input_key") == fixed.get("input_key"), "基础层证据研究、运行或固定输入不同")
    home = workflow.location(sid)
    fact = _preparation(home, manifest, run, result, fixed)
    scoring = run["module_id"] == "A06"
    require(not scoring or run["config"]["version"] in SCORING, "基础层证据尚不支持该评分版本")
    return {"schema_version": VERSION, "integrity": "verified", "read_only": True,
            "study_id": sid, "run_id": run["run_id"], "input_key": fixed["input_key"],
            "preparation": _preparation_rows(home, sid, fact, fixed, files),
            "scores": _scores(home, sid, run, result, fact, fixed, files) if scoring else [],
            "message_zh": "只读本批原件：准备依据与实际Top-1构象分别核对；未记录不表示检查通过。正常对象无须逐项确认，异常保持原规则。",
            "error_zh": ""}
