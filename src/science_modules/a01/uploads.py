"""A01分库上传与三库整理生产入口；沿用既有解析、身份和归档规则。"""
from __future__ import annotations

import hashlib
import io
import json
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from contracts import require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from .multisource import catalog, herb_records, batman_records, batman_known, tcmsp_records
from .preview import build_candidate

VERSION = "A01.multisource.upload.1"
CONFIG = {"version": VERSION, "sources": ["TCMSP", "HERB", "BATMAN"], "tcmsp_ob_min": 30,
          "tcmsp_dl_min": 0.18, "new_sources_adme_filter": False,
          "new_relations": "database_existing_only", "dedup": "full_inchikey_no_formula_conflict"}
DATABASES = tuple(CONFIG["sources"])

# 只读当前研究的上传清单，所有引用都必须通过内容指纹核验。
def current(workflow, manifest):
    record = manifest.get("current_component_uploads")
    return read_json(verified_file(workflow.location(manifest["study_id"]), record)) if record else None

# 解压前检查全部成员；不接受路径穿越、盘符、链接、重复名称或超大展开内容。
def unpack(data, folder):
    require(len(data) <= 16 * 1024 * 1024, "资料包超过16MiB，请按库分包")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            require(len(members) <= 5000 and sum(m.file_size for m in members) <= 256 * 1024 * 1024, "ZIP展开文件数量或体积过大")
            names = set()
            for item in members:
                name = item.filename
                path = PurePosixPath(name)
                require(name and "\\" not in name and ":" not in name and not path.is_absolute()
                        and all(p not in (".", "..") for p in path.parts)
                        and not stat.S_ISLNK(item.external_attr >> 16), "ZIP含不安全路径或链接")
                require(name.casefold() not in names and not item.flag_bits & 1, "ZIP含重复名称或加密文件")
                names.add(name.casefold())
                target = (folder / name).resolve()
                require(target.is_relative_to(folder.resolve()), "ZIP路径超出资料目录")
            for item in members:
                target = folder / item.filename
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(archive.read(item))
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise ValueError("ZIP资料包无法完整读取，请重新检查文件") from error

# 固定HERB官方关系表结构；本函数不预测靶点，也不对空表伪造记录。
def validate_herb(folder, records):
    target = read_json(folder / "HERB_target_browse_page001.json")
    require(isinstance(target.get("browse_data"), list) and len(target["browse_data"]) - 1 == target.get("total_num"), "HERB靶点命名表不完整")
    targets = {row[0]["title"] for row in target["browse_data"][1:]}
    for cid in {r["source_id"] for r in records}:
        require(cid.startswith("HBIN") and cid[4:].isdigit(), "HERB成分编号不合法")
        detail = read_json(folder / "HERB_existing_details" / (cid + ".json"))
        require(len(detail.get("summary", [])) == 2 and detail["summary"][1][0] == cid, "HERB详情成分身份不一致")
        rows = detail.get("ingredient_target")
        require(rows and rows[0] == ["Target id", "Target name", "Database sources"], "HERB已有关系表缺失或格式错误")
        require(all(r[0]["title"] in targets for r in rows[1:]), "HERB已有关系未对应官方靶点命名表")

# 包装规范只明确文件与药味绑定；具体科学解析复用已迁入模块。
def validate_package(folder, database, herbs):
    meta = read_json(folder / "modulea_source.json")
    require(meta.get("database") == database and meta.get("version") == "A01.source_package.1", "资料包的数据库或包装版本不匹配")
    require(meta.get("herbs") == herbs, "资料包药味及顺序与当前研究不一致")
    if database == "TCMSP":
        from components import select_rows, analyze
        path = folder / "references/tcmsp_snapshot.tsv"
        raw = path.read_bytes()
        encoding = meta.get("encoding", "utf-8-sig")
        require(encoding in ("utf-8-sig", "gbk"), "TCMSP编码只支持UTF-8或GBK")
        # 生成本上传自己的文件指纹，不改变项目共享TCMSP快照。
        write_json(folder / "references/tcmsp_snapshot.json", {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "encoding": encoding})
        rows, _ = select_rows(folder, herbs)
        analyze(rows, herbs)
    elif database == "HERB":
        bindings = meta.get("herb_files")
        require(isinstance(bindings, dict) and set(bindings) == set(herbs), "HERB工作簿绑定未覆盖完整处方")
        records = herb_records(folder, catalog(folder / "HERB_ingredient_info_v2.txt"), bindings)
        validate_herb(folder, records)
    else:
        bindings = meta.get("herb_names")
        require(isinstance(bindings, dict) and len(bindings) == len(herbs) and set(bindings.values()) == set(herbs), "BATMAN官方拼音条目未明确绑定完整处方")
        evidence = folder / "PubChem既有官方快照复用_v1.json"
        batman_records(folder, {}, bindings, evidence if evidence.exists() else None)
        batman_known(folder / "BATMAN_known_browse_by_ingredients.txt.gz")
    return meta

# 校验后才归档一个库；上传版本和原始ZIP全部留存，当前计算结果不在这里改变。
def stage(workflow, study_id, expected_a00, expected_a01, expected_staging, source, runtime_dir):
    require(source.get("database") in DATABASES, "A01不支持此来源库")
    require(source.get("format") == "source_zip", "A01请上传按模板包装的官方资料ZIP")
    with write_lock(workflow.root):
        manifest = workflow.load(study_id)
        require(not manifest.get("trashed"), "研究在回收站中，请先恢复")
        require(manifest["current"].get("A00") == expected_a00 and manifest["current"].get("A01", "") == expected_a01, "页面版本已改变，请刷新后上传")
        require((manifest.get("current_component_uploads") or {}).get("sha256", "") == expected_staging, "上传清单已改变，请刷新")
        require(workflow.approved(manifest, expected_a00), "请先复核通过A00研究登记")
        intake = workflow.result(manifest, expected_a00)["summary"]
        from components import parse_herbs
        herbs = parse_herbs(intake["herbs"])
        Path(runtime_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="a01_parse_", dir=runtime_dir) as temporary:
            folder = Path(temporary)
            unpack(source["data"], folder)
            validate_package(folder, source["database"], herbs)
            old = current(workflow, manifest)
            slots = {s["database"]: s for s in old.get("datasets", [])} if old and old["a00_run_id"] == expected_a00 else {}
            token = new_id("source")
            home = workflow.location(study_id)
            destination = home / "raw/A01_uploads" / token
            destination.mkdir(parents=True, exist_ok=False)
            archive_path = destination / "original.zip"
            archive_path.write_bytes(source["data"])
            files = []
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    target = destination / "package" / path.relative_to(folder)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
                    files.append(file_record(home, target, "component_source"))
            item = {k: v for k, v in source.items() if k != "data"}
            item.update(folder=(destination / "package").relative_to(home).as_posix(), source_record=file_record(home, archive_path, "source"), files=files, uploaded_at=now())
            slots[source["database"]] = item
            value = {"version": "A01.source_staging.1", "study_id": study_id, "a00_run_id": expected_a00, "herbs": herbs,
                     "datasets": [slots[db] for db in DATABASES if db in slots], "created_at": now()}
            path = destination / "source_staging.json"
            write_json(path, value)
            record = file_record(home, path, "component_source_manifest")
            manifest.setdefault("component_upload_versions", []).append(record)
            manifest["current_component_uploads"] = record
            workflow.save(manifest)
            return value

# 优先绑定当前疾病侧已经归档的同一HGNC依据；缺失时只用明确配置的共享快照。
def mapping_binding(workflow, manifest):
    a02 = manifest["current"].get("A02")
    if a02:
        run = workflow.run(manifest, a02)
        inputs = run.get("inputs", {})
        if inputs.get("mapping_file"):
            summary = workflow.result(manifest, a02)["summary"]
            return {"mapping_file": inputs["mapping_file"], "identity_evidence_files": inputs.get("identity_evidence_files", []),
                    "mapping_rule": summary["mapping_rule"], "mapping_snapshot": summary["mapping_snapshot"], "identity_evidence_snapshot": summary.get("identity_evidence_snapshot", "")}
    from hgnc import load_snapshot
    mapper, meta = load_snapshot(workflow.root)
    home = workflow.location(manifest["study_id"])
    records = []
    for item in [{"filename": "hgnc_complete_set_20260913.tsv", "sha256": mapper.digest}] + meta.get("identity_evidence", []):
        source = workflow.root / "references" / item["filename"]
        require(hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"], "身份依据文件指纹不一致")
        target = home / "raw" / ("mapping_" + item["sha256"] + source.suffix)
        if not target.exists():
            target.write_bytes(source.read_bytes())
        records.append(file_record(home, target, "mapping_source" if not records else "identity_source"))
    return {"mapping_file": records[0], "identity_evidence_files": records[1:], "mapping_rule": mapper.rule,
            "mapping_snapshot": mapper.digest, "identity_evidence_snapshot": mapper.supplement.digest if mapper.supplement else ""}

# 每次复算只读取运行绑定文件；不会读取后来改变的当前来源或沿用历史身份例外。
def facts(home, inputs):
    from hgnc import HgncMap
    from identity_sources import IdentityEvidence
    from components import select_rows, analyze
    from normalization import compute
    source = read_json(verified_file(home, inputs["staging_file"]))
    require(source["study_id"] == inputs["study_id"] and source["a00_run_id"] == inputs["bound_a00"] and source["herbs"] == inputs["herbs"], "三库来源不属于当前研究登记")
    slots = {r["database"]: r for r in source["datasets"]}
    require(set(slots) == set(DATABASES), "三库尚未全部上传，不能生成完整结果")
    folders = {}
    for db, slot in slots.items():
        verified_file(home, slot["source_record"])
        for item in slot["files"]:
            verified_file(home, item)
        folders[db] = (home / slot["folder"]).resolve()
        require(folders[db].is_relative_to(home.resolve()), "来源路径超出研究目录")
    binding = inputs["mapping"]
    evidence = [verified_file(home, r).read_bytes() for r in binding["identity_evidence_files"]]
    require(not evidence or len(evidence) == 3, "身份补充证据缺失")
    supplement = IdentityEvidence(*evidence) if evidence else None
    mapper = HgncMap(verified_file(home, binding["mapping_file"]).read_bytes(), rule=binding["mapping_rule"], supplement=supplement)
    require(mapper.digest == binding["mapping_snapshot"] and (supplement.digest if supplement else "") == binding["identity_evidence_snapshot"], "绑定HGNC与身份依据快照不一致")
    identities = catalog(folders["HERB"] / "HERB_ingredient_info_v2.txt")
    tc, _, _ = tcmsp_records(folders["TCMSP"], identities, inputs["herbs"])
    herb_meta = read_json(folders["HERB"] / "modulea_source.json")
    batman_meta = read_json(folders["BATMAN"] / "modulea_source.json")
    hr = herb_records(folders["HERB"], identities, herb_meta["herb_files"])
    # PubChem快照可随BATMAN包提供；既有校验器限制其引用在包内。
    pubchem = folders["BATMAN"] / "PubChem既有官方快照复用_v1.json"
    br, _, pending = batman_records(folders["BATMAN"], identities, batman_meta["herb_names"], pubchem if pubchem.exists() else None)
    rows, _ = select_rows(folders["TCMSP"], inputs["herbs"])
    summary, tables, _ = analyze(rows, inputs["herbs"])
    base = {"run_id": "uploaded_TCMSP_" + slots["TCMSP"]["source_record"]["sha256"][:24], "summary": summary, "tables": tables}
    identity_summary, identity_tables, _ = compute(base, mapper, "A01", {}, False, analysis_purpose=inputs["analysis_purpose"], disease_identity=inputs.get("disease_identity"))
    candidate = build_candidate(folders["HERB"], tc, hr, br, mapper, identity_tables["normalized_compound_targets"], identity_summary, inputs["herbs"], {db: inputs["herbs"] for db in DATABASES}, batman_raw=folders["BATMAN"])
    result = candidate["result"]
    s, t = result["summary"], result["tables"]
    issues = identity_tables["identity_issues"]
    s.update(candidate_only=False, component_source_profile=VERSION, handoff_blocked=bool(issues or candidate["identity_issues"]), **{"资料阶段": "三库上传整理结果，待独立复核", "身份问题组数": len(issues) + len(candidate["identity_issues"]), "结构待核处理": "独立编号保留，进入对接前须核实"})
    t.update(component_sources=candidate["source_records"], identity_issues=candidate["identity_issues"], tcmsp_identity_issues=issues, pending_structures=pending)
    anomalies = ["上传整理不等于复核通过；未知基因身份不继承其他研究的省略决定。", "数据库已有关系不等于人体直接结合实验证据，未增加靶点预测。", "结构待核分组独立保留，进入对接前须核实。"]
    return s, t, anomalies

# 新上传契约单独登记，不改变既有A01.multisource.1和旧TCMSP版本行为。
def validator(root, fallback):
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("version") != VERSION:
            return fallback(run, summary, tables, anomalies, outcome)
        require(run["config"] == CONFIG, "三库上传科学配置被改变")
        expected = facts(Path(root) / "studies" / run["study_id"], run["inputs"])
        require((summary, tables, anomalies) == expected and outcome == "success", "三库上传结果与绑定来源复算不一致")
    return check

# 用户另行触发完整三库整理，生成新运行并停在复核；不自动运行A03或批准结果。
def process(workflow, study_id, expected_a00, expected_a01, expected_staging, reason):
    with write_lock(workflow.root):
        manifest = workflow.load(study_id)
        require(not manifest.get("trashed"), "研究在回收站中，请先恢复")
        require(manifest["current"].get("A00") == expected_a00 and manifest["current"].get("A01", "") == expected_a01, "页面版本已改变，请刷新")
        require(workflow.approved(manifest, expected_a00), "请先复核通过A00研究登记")
        record = manifest.get("current_component_uploads")
        require(record and record["sha256"] == expected_staging, "上传清单已改变或尚未上传，请刷新")
        source = current(workflow, manifest)
        require({r["database"] for r in source["datasets"]} == set(DATABASES), "三库尚未全部上传")
        intake = workflow.result(manifest, expected_a00)["summary"]
        from components import parse_herbs
        from mesh_identity import validate_mesh_identity
        purpose = intake.get("analysis_purpose") or ("formal_research" if (intake.get("mesh_verification") or {}).get("status") == "verified" else "workflow_test")
        require(purpose in ("formal_research", "workflow_test"), "研究用途未明确，不能整理三库")
        disease_identity = validate_mesh_identity(intake) if purpose == "formal_research" else None
        inputs = {"study_id": study_id, "bound_a00": expected_a00, "staging_file": record,
                  "herbs": parse_herbs(intake["herbs"]), "analysis_purpose": purpose, "disease_identity": disease_identity,
                  "mapping": mapping_binding(workflow, manifest)}
        summary, tables, anomalies = facts(workflow.location(study_id), inputs)
        run = workflow._begin(manifest, "A01", inputs, dict(CONFIG), reason)
        sources = [record, inputs["mapping"]["mapping_file"], *inputs["mapping"]["identity_evidence_files"]]
        for item in source["datasets"]:
            sources.extend([item["source_record"], *item["files"]])
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success", sources=sources)
        workflow.save(manifest)
        return result

# 自动接续识别新上传契约；A00改变时要求重新绑定，不静默退回共享单库。
def run_components(workflow, study_id, expected_a00, expected_a01, reason):
    manifest = workflow.load(study_id)
    if expected_a01:
        previous = workflow.run(manifest, expected_a01)
        if previous["config"].get("version") == VERSION:
            require(previous["inputs"]["bound_a00"] == expected_a00, "三库资料绑定的A00已改变，请按新登记重新上传")
            record = manifest.get("current_component_uploads")
            require(bool(record), "三库上传清单缺失，请核查来源")
            return process(workflow, study_id, expected_a00, expected_a01, record["sha256"], reason)
    from components_multisource_flow import run_components as frozen_run_components
    return frozen_run_components(workflow, study_id, expected_a00, expected_a01, reason)
