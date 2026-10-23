"""三库获取与完整性新协议；复用上传科学解析，旧版本原样保留。"""
from pathlib import Path
from copy import deepcopy

from contracts import require, fingerprint
from storage import read_json, verified_file, write_lock
from . import uploads

VERSION = "A01.multisource.collect.1"
CONFIG = dict(uploads.CONFIG, version=VERSION, completeness="per_database_per_herb")


def coverage(home, inputs):
    """从真实原始表重数，来源声明不能代替实际药味和条目校验。"""
    from components import select_rows
    from .multisource import catalog, herb_records, batman_records
    source = read_json(verified_file(home, inputs["staging_file"]))
    output = []
    for slot in source["datasets"]:
        folder = home / slot["folder"]
        meta = read_json(folder / "modulea_source.json")
        db = slot["database"]
        if db == "TCMSP":
            rows, _ = select_rows(folder, inputs["herbs"])
            counts = {h: sum(r["Chinesename"].strip() == h for r in rows) for h in inputs["herbs"]}
        elif db == "HERB":
            rows = herb_records(folder, catalog(folder / "HERB_ingredient_info_v2.txt"), meta["herb_files"])
            counts = {h: sum(r["herb"] == h for r in rows) for h in inputs["herbs"]}
        else:
            _, counts, _ = batman_records(folder, {}, meta["herb_names"])
        proofs = meta.get("completeness", {})
        for herb in inputs["herbs"]:
            proof = proofs.get(herb, {})
            count = counts.get(herb, 0)
            declared = proof.get("status") == "complete"
            if declared:
                require(type(proof.get("records")) is int and proof["records"] == count,
                        db + "完整性声明数量与原始药味清单不一致")
                require(isinstance(proof.get("basis"), str) and proof["basis"].strip(), db + "完整性依据缺失")
                require(count > 0 or proof.get("official_zero") is True, db + "空清单缺少官方零结果依据")
            confirmed = bool(inputs.get("coverage_decision"))
            complete = declared or (confirmed and count > 0)
            output.append({"database": db, "herb": herb, "records": count,
                           "complete": complete, "availability": "完整性已核对" if complete else "完整性待核对",
                           "basis": proof.get("basis") or (inputs.get("coverage_decision") or {}).get("note", "原始清单无完整性声明")})
    return output


def issue_key(row):
    """决定绑定当前原始问题内容，不以易变的列表序号授权省略。"""
    return fingerprint(row)


def facts(home, inputs):
    """按原上传算法复算，再叠加本版本完整性和明确的身份例外决定。"""
    summary, tables, anomalies = uploads.facts(home, inputs)
    checks = coverage(home, inputs)
    problems = tables.get("identity_issues", []) + tables.get("tcmsp_identity_issues", [])
    # 原TCMSP快照解析中的缺物种、缺靶点不能在新版完整性协议中悄悄丢失。
    from components import select_rows, analyze
    staging = read_json(verified_file(home, inputs["staging_file"]))
    slot = next(r for r in staging["datasets"] if r["database"] == "TCMSP")
    tc_rows, _ = select_rows(home / slot["folder"], inputs["herbs"])
    _, tc_tables, _ = analyze(tc_rows, inputs["herbs"])
    unresolved_source = [r for r in tc_tables["exclusions"] if "待" in r["reason"]]
    tables["tcmsp_source_issues"] = unresolved_source
    problems += unresolved_source
    keys = {issue_key(r) for r in problems}
    omitted = set(inputs.get("omit_identity_keys", []))
    require(omitted <= keys, "身份例外已改变，请重新核查本次问题")
    tables["source_coverage"] = checks
    tables["identity_decisions"] = [dict(r, issue_key=issue_key(r), decision="暂不采用" if issue_key(r) in omitted else "待核验") for r in problems]
    summary.update(component_source_profile=VERSION, handoff_blocked=any(not r["complete"] for r in checks) or bool(keys - omitted),
                   candidate_only=any(not r["complete"] for r in checks) or bool(keys - omitted),
                   **{"完整性待核项数": sum(not r["complete"] for r in checks), "未决身份组数": len(keys - omitted),
                      "明确暂不采用身份组数": len(omitted), "资料阶段": "三库完整性及身份核查结果，仍须独立整体复核"})
    anomalies.append("三库覆盖按每库每味药核对；候选、人工例外处理和整体复核分别留痕。")
    return summary, tables, anomalies


def validator(root, fallback):
    """只验证新版本，历史上传与三库规则继续委托原校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("version") != VERSION:
            return fallback(run, summary, tables, anomalies, outcome)
        require(run["config"] == CONFIG, "三库采集参数被改变")
        expected = facts(Path(root) / "studies" / run["study_id"], run["inputs"])
        require((summary, tables, anomalies) == expected and outcome == "success", "三库完整性结果与绑定来源不一致")
    return check


def process(workflow, sid, expected_a00, expected_a01, expected_staging, reason, decision=None):
    """发布新待复核A01；当前A02不写入、不重新标准化、不继承决定。"""
    with write_lock(workflow.root):
        m = workflow.load(sid)
        require(not m.get("trashed"), "研究在回收站中，只读")
        require(m["current"].get("A00") == expected_a00 and m["current"].get("A01", "") == expected_a01,
                "页面版本已改变，请刷新")
        require(workflow.approved(m, expected_a00), "请先通过A00")
        record = m.get("current_component_uploads")
        require(record and record["sha256"] == expected_staging, "三库来源清单已改变")
        source = uploads.current(workflow, m)
        require({r["database"] for r in source["datasets"]} == set(uploads.DATABASES), "三库缺资料，请先补齐；不回退单库")
        intake = workflow.result(m, expected_a00)["summary"]
        from components import parse_herbs
        from mesh_identity import validate_mesh_identity
        purpose = intake.get("analysis_purpose", "workflow_test")
        inputs = {"study_id": sid, "bound_a00": expected_a00, "staging_file": record,
                  "herbs": parse_herbs(intake["herbs"]), "analysis_purpose": purpose,
                  "disease_identity": validate_mesh_identity(intake) if purpose == "formal_research" else None,
                  "mapping": uploads.mapping_binding(workflow, m)}
        if decision:
            require(decision.get("confirmed") is True and isinstance(decision.get("reviewer"), str) and decision["reviewer"].strip()
                    and isinstance(decision.get("note"), str) and decision["note"].strip(), "请明确核验人、依据和确认")
            require(bool(expected_a01) and workflow.run(m, expected_a01)["config"].get("version") == VERSION,
                    "请先生成本版本三库核查结果")
            old = workflow.result(m, expected_a01)
            prior = workflow.run(m, expected_a01).get("inputs", {})
            require(prior["staging_file"]["sha256"] == expected_staging, "当前核验结果绑定的来源已改变，请重新整理")
            for key in ("coverage_decision", "omit_identity_keys"):
                if key in prior:
                    inputs[key] = deepcopy(prior[key])
            if decision.get("confirm_coverage") is True:
                inputs["coverage_decision"] = {k: decision[k].strip() for k in ("reviewer", "note")}
            if decision.get("omit_unresolved") is True:
                issues = old["tables"].get("identity_issues", []) + old["tables"].get("tcmsp_identity_issues", []) + old["tables"].get("tcmsp_source_issues", [])
                inputs["omit_identity_keys"] = sorted({issue_key(r) for r in issues})
            require(inputs.get("coverage_decision") or inputs.get("omit_identity_keys"), "请选择实际需要处理的项目")
            inputs["review_decision"] = deepcopy(decision)
        summary, tables, anomalies = facts(workflow.location(sid), inputs)
        run = workflow._begin(m, "A01", inputs, dict(CONFIG), reason)
        sources = [record, inputs["mapping"]["mapping_file"], *inputs["mapping"]["identity_evidence_files"]]
        for item in source["datasets"]:
            sources.extend([item["source_record"], *item["files"]])
        result = workflow._finish(m, run["run_id"], summary, tables, anomalies, "success", sources=sources)
        workflow.save(m)
        return result


def herb_resume_folders(home, folder, binding):
    """仅查本研究同A00/A01的先前采集；旧版须有结束记录佐证，不跨研究复用。"""
    root = Path(home).resolve() / "raw/A01_acquisition"
    folder = Path(folder)
    require(folder.resolve().is_relative_to(root.resolve()) and folder.parent.resolve() == root.resolve()
            and not folder.is_symlink(), "采集目录不属于本研究")
    candidates = []
    for prior in sorted(root.iterdir()) if root.exists() else []:
        if not prior.is_dir() or prior.is_symlink() or prior.resolve() == folder.resolve():
            continue
        marker = prior / "acquisition_binding.json"
        records = [marker] if marker.exists() else sorted(prior.glob("acquisition_result_*.json"))
        for record in records:
            require(not record.is_symlink(), "旧采集绑定路径改变")
            data = read_json(record)
            if all(data.get(k) == binding[k] for k in ("study_id", "bound_a00", "bound_a01")):
                if "herbs" in data and data["herbs"] != binding["herbs"]:
                    continue
                requests = prior / "HERB/original_requests"
                require(not (prior / "HERB").is_symlink() and not requests.is_symlink()
                        and requests.resolve().is_relative_to(root.resolve()), "旧采集原件路径改变")
                candidates.append(requests)
                break
    return candidates


def acquire_sources(workflow, sid, expected_a00, expected_a01, expected_staging, folder, databases=None, progress=None):
    """缺库逐个获取并复用统一stage；失败归档，不撤销已成功的库。"""
    from .acquisition import acquire
    from components import parse_herbs
    from storage import write_json
    m = workflow.load(sid)
    require(not m.get("trashed") and workflow.approved(m, expected_a00), "当前研究不可采集")
    require(m["current"].get("A00") == expected_a00 and m["current"].get("A01", "") == expected_a01
            and (m.get("current_component_uploads") or {}).get("sha256", "") == expected_staging, "来源版本已改变")
    herbs = parse_herbs(workflow.result(m, expected_a00)["summary"]["herbs"])
    existing = uploads.current(workflow, m)
    available = {r["database"] for r in existing["datasets"]} if existing and existing["a00_run_id"] == expected_a00 else set()
    wanted = databases if databases is not None else [db for db in uploads.DATABASES if db not in available]
    require(isinstance(wanted, list) and len(wanted) == len(set(wanted)) and set(wanted) <= set(uploads.DATABASES), "三库获取范围无效")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    binding = {"study_id": sid, "bound_a00": expected_a00, "bound_a01": expected_a01, "herbs": herbs}
    resume_folders = herb_resume_folders(workflow.location(sid), folder, binding) if "HERB" in wanted else []
    marker = folder / "acquisition_binding.json"
    require(not marker.is_symlink(), "本次采集绑定路径改变")
    if marker.exists():
        require(read_json(marker) == binding, "本次采集目录绑定已改变")
    else:
        write_json(marker, binding)
    results = []
    for db in wanted:
        try:
            require(not (folder / db).is_symlink() and (folder / db).resolve().is_relative_to(folder.resolve()),
                    "本次采集数据库目录改变")
            if progress:
                progress("获取 " + db + " 原始资料")
            source = acquire(db, herbs, folder / db, progress=progress, resume_folders=resume_folders if db == "HERB" else ())
            uploads.stage(workflow, sid, expected_a00, expected_a01, expected_staging, source, folder / "validation",
                          automatic_herb=db == "HERB")
            m = workflow.load(sid)
            expected_staging = m["current_component_uploads"]["sha256"]
            results.append({"database": db, "status": "success", "message_zh": "原件已通过统一上传校验并归档"})
        except Exception as error:
            results.append({"database": db, "status": "failed", "message_zh": str(error)})
    from storage import new_id
    write_json(folder / ("acquisition_result_" + new_id("attempt") + ".json"), {"study_id": sid, "bound_a00": expected_a00, "bound_a01": expected_a01,
                                                   "databases": results, "current_a02_unchanged": True})
    return results


def run_components(workflow, sid, expected_a00, expected_a01, reason, progress=None):
    """新登记只走完整三库；历史研究保持原版本，显式升级由网页提交。"""
    m = workflow.load(sid)
    intake = workflow.result(m, expected_a00)["summary"]
    new_policy = intake.get("component_source_profile") == VERSION
    if expected_a01:
        new_policy = new_policy or workflow.run(m, expected_a01)["config"].get("version") == VERSION
    if not new_policy:
        return uploads.run_components(workflow, sid, expected_a00, expected_a01, reason)
    from storage import new_id
    source = uploads.current(workflow, m)
    available = {r["database"] for r in source["datasets"]} if source and source["a00_run_id"] == expected_a00 else set()
    if available != set(uploads.DATABASES):
        acquire_sources(workflow, sid, expected_a00, expected_a01, (m.get("current_component_uploads") or {}).get("sha256", ""),
                        workflow.location(sid) / "raw/A01_acquisition" / new_id("fetch"), progress=progress)
    m = workflow.load(sid)
    source = uploads.current(workflow, m)
    require(source and {r["database"] for r in source["datasets"]} == set(uploads.DATABASES),
            "三库自动获取未完整，请在A01查看获取记录并补充失败库原始资料；未回退TCMSP单库")
    return process(workflow, sid, expected_a00, expected_a01, m["current_component_uploads"]["sha256"], reason)
