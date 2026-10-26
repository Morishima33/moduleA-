"""A01新方案三库发布：参数、原件、HGNC和校验器绑定同一运行；旧协议保持。"""

from copy import deepcopy
from pathlib import Path
from types import FunctionType

from contracts import fingerprint, require, safe_id
from storage import new_id, read_json, verified_file, write_json, write_lock
from science_modules.analysis_protocol import VERSION as PLAN_VERSION, checked_plan
from . import collection_flow, multisource, uploads
from .plan_screening import analyze_rows, screening_parameters

VERSION = "A01.plan_publication.1"


def configuration(plan):
    """只把本模块实际消费的门槛和固定规则写入科学配置。"""
    parameters = screening_parameters(plan)
    return dict(collection_flow.CONFIG, version=VERSION,
                tcmsp_ob_min=parameters["ob_min"], tcmsp_dl_min=parameters["dl_min"],
                screening_version="A01.plan_screening.1", plan_version=PLAN_VERSION)


def plan_record(home, inputs):
    """复算读取运行绑定的不可变方案，不寻找后来追加的最新草稿。"""
    record = read_json(verified_file(home, inputs["analysis_plan_file"]))
    require(record.get("schema_version") == PLAN_VERSION
            and record.get("study_id") == inputs["study_id"]
            and record.get("expected_a00") == inputs["bound_a00"]
            and record.get("plan_id") == inputs["analysis_plan_id"], "A01方案不属于本研究或本次登记")
    plan = checked_plan(record["plan"])
    require(plan["parameter_hash"] == inputs["analysis_parameter_hash"], "A01方案参数指纹不一致")
    return record, plan


def _source_folders(home, inputs, plan):
    """核验三库原件和来源清单，拒绝以高门槛采集的不完整映射冒充低门槛来源。"""
    source = read_json(verified_file(home, inputs["staging_file"]))
    require(source.get("study_id") == inputs["study_id"]
            and source.get("a00_run_id") == inputs["bound_a00"]
            and source.get("herbs") == inputs["herbs"], "三库来源不属于本研究登记")
    slots = {row["database"]: row for row in source["datasets"]}
    require(len(slots) == len(source["datasets"]) and set(slots) == set(uploads.DATABASES),
            "三库缺失或重复，不回退单库发布")
    folders = {}
    for db, slot in slots.items():
        verified_file(home, slot["source_record"])
        for item in slot["files"]:
            verified_file(home, item)
        folder = (home / slot["folder"]).resolve()
        require(folder.is_relative_to(home.resolve()), "来源目录超出本研究")
        meta = read_json(folder / "modulea_source.json")
        require(meta.get("database") == db and meta.get("herbs") == inputs["herbs"], "原件数据库或药味绑定改变")
        binding = slot.get("analysis_plan_source")
        if binding is not None:
            require(binding.get("binding", {}).get("study_id") == inputs["study_id"]
                    and binding["binding"].get("a00_run") == inputs["bound_a00"]
                    and binding.get("database") == db and binding.get("herbs") == inputs["herbs"],
                    "采集原件的研究或登记绑定不一致")
            context = {key: binding[key] for key in ("schema_version", "binding", "database", "herbs", "screening_parameters")}
            require(binding.get("binding_hash") == fingerprint(context), "采集绑定指纹不一致")
        if db == "TCMSP":
            requested = screening_parameters(plan)
            collected = meta.get("screening_parameters")
            if collected is not None:
                require(collected == requested, "TCMSP采集门槛与本次筛选不同，请按本方案补齐来源")
            elif str(slot.get("version", "")).startswith("A01.acquisition."):
                require(requested == {"ob_min": 30, "dl_min": .18},
                        "旧自动来源仅按默认门槛补查靶点，请按新方案重新获取TCMSP")
            if binding is not None:
                require(binding.get("screening_parameters") == requested and collected == requested,
                        "TCMSP获取与筛选参数不一致")
        folders[db] = folder
    return source, folders


def facts(home, inputs):
    """按真实OB/DL筛选后复用旧三库、HGNC、完整性和身份异常规则。"""
    from components import select_rows
    from hgnc import HgncMap
    from identity_sources import IdentityEvidence
    from normalization import compute
    from .preview import build_candidate

    home = Path(home)
    _, plan = plan_record(home, inputs)
    source, folders = _source_folders(home, inputs, plan)
    binding = inputs["mapping"]
    evidence = [verified_file(home, row).read_bytes() for row in binding["identity_evidence_files"]]
    require(not evidence or len(evidence) == 3, "身份补充证据不完整")
    supplement = IdentityEvidence(*evidence) if evidence else None
    mapper = HgncMap(verified_file(home, binding["mapping_file"]).read_bytes(),
                     rule=binding["mapping_rule"], supplement=supplement)
    require(mapper.digest == binding["mapping_snapshot"]
            and (supplement.digest if supplement else "") == binding["identity_evidence_snapshot"],
            "HGNC与补充证据指纹不一致")

    identities = multisource.catalog(folders["HERB"] / "HERB_ingredient_info_v2.txt")
    rows, _ = select_rows(folders["TCMSP"], inputs["herbs"])
    screened = analyze_rows(rows, inputs["herbs"], plan)

    # 仅绑定本次TCMSP记录适配，不修改旧模块全局函数或共享CONFIG。
    def analyze(current_rows, herbs):
        current = analyze_rows(current_rows, herbs, plan)
        return current["summary"], current["tables"], current["anomalies"]

    original = multisource.tcmsp_records
    tcmsp_records = FunctionType(original.__code__, dict(vars(multisource), analyze=analyze),
                                original.__name__, original.__defaults__, original.__closure__)
    tc, _, _ = tcmsp_records(folders["TCMSP"], identities, inputs["herbs"])
    herb_meta = read_json(folders["HERB"] / "modulea_source.json")
    batman_meta = read_json(folders["BATMAN"] / "modulea_source.json")
    hr = multisource.herb_records(folders["HERB"], identities, herb_meta["herb_files"])
    pubchem = folders["BATMAN"] / "PubChem既有官方快照复用_v1.json"
    br, _, pending = multisource.batman_records(folders["BATMAN"], identities, batman_meta["herb_names"],
                                               pubchem if pubchem.exists() else None)
    tc_slot = next(row for row in source["datasets"] if row["database"] == "TCMSP")
    base = {"run_id": "uploaded_TCMSP_" + tc_slot["source_record"]["sha256"][:24],
            "summary": screened["summary"], "tables": screened["tables"]}
    identity_summary, identity_tables, _ = compute(
        base, mapper, "A01", {}, False, analysis_purpose=inputs["analysis_purpose"],
        disease_identity=inputs.get("disease_identity"))
    candidate = build_candidate(folders["HERB"], tc, hr, br, mapper,
                                identity_tables["normalized_compound_targets"], identity_summary,
                                inputs["herbs"], {db: inputs["herbs"] for db in uploads.DATABASES},
                                batman_raw=folders["BATMAN"])
    summary, tables = candidate["result"]["summary"], candidate["result"]["tables"]
    checks = collection_flow.coverage(home, inputs)
    unresolved = [row for row in screened["tables"]["exclusions"] if "待" in row["reason"]]
    issues = candidate["identity_issues"] + identity_tables["identity_issues"] + unresolved
    blocked = any(not row["complete"] for row in checks) or bool(issues)
    tables.update(component_sources=candidate["source_records"], source_coverage=checks,
                  identity_issues=candidate["identity_issues"],
                  tcmsp_identity_issues=identity_tables["identity_issues"], tcmsp_source_issues=unresolved,
                  tcmsp_identity_mapping=identity_tables["identity_mapping"],
                  tcmsp_exclusions=screened["tables"]["exclusions"],
                  tcmsp_screened_components=screened["tables"]["components"],
                  new_relation_evidence=candidate["new_relation_evidence"], pending_structures=pending)
    tables["identity_decisions"] = [dict(row, issue_key=collection_flow.issue_key(row), decision="待核验")
                                    for row in issues]
    parameters = screening_parameters(plan)
    summary.update(component_source_profile=VERSION, candidate_only=blocked, handoff_blocked=blocked,
                   analysis_plan_id=inputs["analysis_plan_id"],
                   analysis_parameter_hash=plan["parameter_hash"], effective_tcmsp_parameters=parameters,
                   **{"完整性待核项数": sum(not row["complete"] for row in checks),
                      "未决身份组数": len({collection_flow.issue_key(row) for row in issues}),
                      "明确暂不采用身份组数": 0, "身份问题组数": len(issues),
                      "资料阶段": "新方案三库标准化结果；未自动批准或启动下游"})
    anomalies = ["新方案只影响本批A01；疾病侧、历史资料及人工复核保持。",
                 "HERB不附加OB/DL；BATMAN仅采用known，已有关系不等于实验验证。",
                 "三库完整性和关键身份问题仍阻断；结构待核单独保留，不伪造结构。"]
    return summary, tables, anomalies


def validator(root, fallback):
    """新协议逐表复算；旧协议继续委托原校验器，不升级历史授权。"""
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("version") != VERSION:
            return fallback(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        require(run["inputs"]["study_id"] == run["study_id"]
                and run["inputs"]["bound_a00"] == run["parent_runs"].get("A00"), "A01输入与实际父运行不一致")
        _, plan = plan_record(home, run["inputs"])
        require(run["config"] == configuration(plan), "A01新方案科学配置被改变")
        require((summary, tables, anomalies) == facts(home, run["inputs"]) and outcome == "success",
                "A01结果与绑定方案、来源或HGNC复算不一致")
    return check


def context(workflow, manifest, payload, *, pinned_plan=None):
    """发布前核对显式草稿、登记及来源版本；普通GET和旧研究不会启用新流程。"""
    require(not manifest.get("trashed"), "回收站研究只读")
    require(manifest["current"].get("A00") == payload["expected_a00"]
            and manifest["current"].get("A01", "") == payload["expected_a01"], "A00或A01已改变，请刷新")
    require(workflow.approved(manifest, payload["expected_a00"]), "请先通过A00")
    intake = workflow.result(manifest, payload["expected_a00"])["summary"]
    require(intake.get("analysis_plan_profile") == PLAN_VERSION, "旧固定研究不能隐式启用新方案")
    records = workflow._analysis_plan_records(manifest)
    if pinned_plan is None:
        require(records and records[-1]["plan_id"] == payload["expected_plan_id"],
                "方案草稿已改变，请刷新后明确选择")
        index = len(records) - 1
    else:
        # 已开始的获取绑定原草稿；追加草稿不能换掉或中止它所采用的门槛。
        indexes = [i for i, row in enumerate(records) if row["plan_id"] == payload["expected_plan_id"]]
        require(len(indexes) == 1 and records[indexes[0]] == pinned_plan, "本次获取绑定的原方案改变")
        index = indexes[0]
    require(records[index]["expected_a00"] == payload["expected_a00"], "方案登记版本已改变")
    require((manifest.get("current_component_uploads") or {}).get("sha256", "") == payload["expected_staging"],
            "三库来源清单已改变，请刷新")
    return intake, records[index], manifest["analysis_plan_records"][index]


def acquire_sources(workflow, sid, payload, *, progress=None, opener=None, sleeper=None):
    """按本研究方案获取并调用原stage；只留来源，不发布A01或自动批准。"""
    from components import parse_herbs
    from .plan_acquisition import VERSION as ACQUISITION_VERSION, acquire_for_plan

    fields = {"expected_a00", "expected_a01", "expected_plan_id", "expected_staging", "databases", "reason"}
    require(isinstance(payload, dict) and set(payload) == fields, "新方案采集字段不完整或含未支持选项")
    databases = payload["databases"]
    require(isinstance(databases, list) and databases and all(isinstance(db, str) for db in databases)
            and len(databases) == len(set(databases)) and set(databases) <= set(uploads.DATABASES), "采集数据库范围无效")
    require(isinstance(payload["reason"], str) and 0 < len(payload["reason"].strip()) <= 2000, "请填写采集依据")
    manifest = workflow.load(sid)
    intake, draft, _ = context(workflow, manifest, payload)
    home = workflow.location(sid)
    folder = home / "raw/A01_plan_acquisition"
    herbs = parse_herbs(intake["herbs"])
    binding = {"study_id": sid, "a00_run": payload["expected_a00"], "a01_run": payload["expected_a01"]}
    current_payload = dict(payload)
    results = []
    for db in databases:
        try:
            # 网络期间不持研究写锁；归档时原stage重新核对A00、A01及来源版本。
            context(workflow, workflow.load(sid), current_payload, pinned_plan=draft)
            if progress:
                progress("按本方案获取 " + db + " 原始资料")
            source = acquire_for_plan(db, herbs, folder, binding, draft["plan"],
                                      progress=progress, opener=opener, sleeper=sleeper)
            context(workflow, workflow.load(sid), current_payload, pinned_plan=draft)
            if db == "HERB":
                # 原件由原采集器包装；同时保留适配版本，复用其后台64MiB校验。
                source = dict(source, acquisition_adapter_version=ACQUISITION_VERSION,
                              version="A01.acquisition.1；以原响应固定")
            uploads.stage(workflow, sid, payload["expected_a00"], payload["expected_a01"],
                          current_payload["expected_staging"], source, folder / "validation", automatic_herb=db == "HERB")
            current_payload["expected_staging"] = workflow.load(sid)["current_component_uploads"]["sha256"]
            results.append({"database": db, "status": "success", "message_zh": "本方案来源已验证归档，尚未发布A01"})
        except Exception as error:
            results.append({"database": db, "status": "failed", "message_zh": str(error)})
    write_json(folder / (new_id("attempt") + ".json"), {
        "study_id": sid, "bound_a00": payload["expected_a00"], "bound_a01": payload["expected_a01"],
        "analysis_plan_id": draft["plan_id"], "analysis_parameter_hash": draft["plan"]["parameter_hash"],
        "reason": payload["reason"], "databases": results, "a01_published": False})
    return results


def publish(workflow, sid, payload):
    """后台公开方法调用的发布实现；锁内追加A01，绝不写入A02或人工批准。"""
    fields = {"expected_a00", "expected_a01", "expected_plan_id", "expected_staging", "reason"}
    require(isinstance(payload, dict) and set(payload) == fields, "A01发布字段不完整或含未支持选项")
    for key, prefix in (("expected_a00", "run"), ("expected_plan_id", "plan")):
        safe_id(payload[key], prefix)
    require(isinstance(payload["expected_a01"], str), "A01版本格式无效")
    if payload["expected_a01"]:
        safe_id(payload["expected_a01"], "run")
    require(isinstance(payload["reason"], str) and 0 < len(payload["reason"].strip()) <= 2000, "请填写A01发布依据")
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        intake, draft, reference = context(workflow, manifest, payload)
        from components import parse_herbs
        from mesh_identity import validate_mesh_identity
        purpose = intake.get("analysis_purpose")
        require(purpose in ("formal_research", "workflow_test"), "请明确研究用途")
        inputs = {"study_id": sid, "bound_a00": payload["expected_a00"],
                  "staging_file": deepcopy(manifest.get("current_component_uploads")),
                  "herbs": parse_herbs(intake["herbs"]), "analysis_purpose": purpose,
                  "disease_identity": validate_mesh_identity(intake) if purpose == "formal_research" else None,
                  "analysis_plan_id": draft["plan_id"], "analysis_plan_file": deepcopy(reference),
                  "analysis_parameter_hash": draft["plan"]["parameter_hash"],
                  "mapping": uploads.mapping_binding(workflow, manifest)}
        home = workflow.location(sid)
        summary, tables, anomalies = facts(home, inputs)
        run = workflow._begin(manifest, "A01", inputs, configuration(draft["plan"]), payload["reason"])
        source = read_json(verified_file(home, inputs["staging_file"]))
        sources = [reference, inputs["staging_file"], inputs["mapping"]["mapping_file"],
                   *inputs["mapping"]["identity_evidence_files"]]
        for slot in source["datasets"]:
            sources.extend([slot["source_record"], *slot["files"]])
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success", sources=sources)
        workflow.save(manifest)
        return result
