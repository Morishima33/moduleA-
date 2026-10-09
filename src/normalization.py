# 标准化交接只发布用户明确确认的本次测试范围与例外，不改写原始来源。
from pathlib import Path  # 定位本研究文件。
from collections import defaultdict  # 合并同一基因的来源。
from contracts import require, fingerprint  # 统一校验及预览版本指纹。
from storage import read_json, verified_file, file_record, write_lock, within, write_json, now  # 沿用归档和锁。
from identity_sources import IdentityEvidence  # 发布和复算使用同一证据解释器。
from hgnc import HgncMap, load_snapshot  # 两侧使用相同已核验映射。
from mesh_identity import validate_mesh_identity  # 正式路径使用A00已归档的NLM官方疾病身份。

TABLE_NAMES = {"identity_mapping":"基因身份映射与依据", "identity_issues":"身份例外及本次处理", "normalized_targets":"标准化疾病靶点", "normalized_compound_targets":"标准化成分与靶点", "normalized_reference":"标准化旧方法参考子集", "scope_decisions_final":"本次确认的范围决定", "source_exceptions":"流程测试来源例外"}  # 来源例外独立呈现，不混入基因身份例外。
FIELD_NAMES = {"ncbi_gene_id":"NCBI基因编号", "ncbi_symbol":"NCBI现行符号", "gene_type":"原库对象类型", "verification_url":"官方核对地址", "ncbi_candidate_ids":"NCBI候选编号", "target_name":"原库靶点描述", "query_status":"查询状态", "query_note":"核对说明", "target_id":"HGNC编号", "symbol":"标准基因名", "raw_symbol":"原始名称", "raw_id":"原始编号", "raw_uniprot":"原始UniProt编号", "candidate_ids":"可能对应的HGNC编号", "records":"涉及记录数", "decision":"本次处理", "issue_id":"问题组编号", "source_ref":"来源定位", "mapping_line":"映射表行号", "mapping_rule":"映射规则版本", "mapping_method":"匹配依据", "mapping_snapshot":"映射快照指纹", "status":"身份状态", "analysis_purpose":"结果用途"}  # 网页不强迫用户理解内部字段。
VERSION = "normalized.test.2"  # 仅用于用户批准的旧资料流程测试。
FORMAL_VERSION = "normalized.formal.1"  # 任意新疾病使用已核对MeSH身份的正式标准化版本。
WORKFLOW_EXCEPTION_VERSION = "normalized.test.3"  # 缺GeneCards流程测试使用独立不可混淆的配置。
COPD_TERMS = {"copd", "慢阻肺", "慢性阻塞性肺疾病", "chronic obstructive pulmonary disease", "pulmonary disease, chronic obstructive"}  # 本次明确的本病名称。

def group_id(row):  # 相同原始身份只复核一次。
    return fingerprint([row.get("raw_symbol", ""), row.get("raw_id", ""), row.get("raw_uniprot", "")])[:24]  # 不按基因名称猜测合并。

def compute(base, mapper, module, scopes, omit, review_context=None, analysis_purpose="workflow_test", disease_identity=None, source_exception=None):  # 预览和发布共用计算，并明确区分测试与正式研究。
    original = base["tables"]  # 原表完整留存。
    mappings, normalized, issues = [], [], {}  # 结果与异常独立保存。
    rows = original["compound_targets"] if module == "A01" else original["candidate_records"]  # 不从汇总名单反推证据。
    if module == "A02":  # 只允许逐个明确决定当前范围。
        require(set(scopes) == {r["scope_id"] for r in original["scope_groups"]}, "范围确认缺条目或已改变")  # 不漏掉隐藏条目。
        require(all(v in ("direct", "outside", "subtype", "pending") for v in scopes.values()), "范围决定无效")  # 待核验不能伪装通过。
    for row in rows:  # 原始记录逐条核对。
        if module == "A02" and scopes[row["scope_id"]] != "direct":  # 亚型首版不纳入；待定在汇总中阻断。
            continue  # 排除范围的原表仍保留。
        mapped = mapper.resolve(row["gene"], uniprot=row["uniprot"]) if module == "A01" else mapper.resolve(row["raw_symbol"], row["raw_id"])  # 不猜TTD蛋白名称为accession。
        gid = group_id(mapped)  # 同一异常身份集中归组。
        location = str(row["source_lines"]) if module == "A01" else row["record_id"]  # 来源行或记录编号。
        mapped.update(issue_id=gid, source_ref=base["run_id"] + ":" + location)  # 保留原运行定位。
        mappings.append(mapped)  # 已匹配和未匹配均留存。
        if mapped["status"] != "matched":  # 不把问题记录冒充标准基因。
            issue = issues.setdefault(gid, {"issue_id": gid, "raw_symbol": mapped["raw_symbol"], "raw_id": mapped["raw_id"], "raw_uniprot": mapped["raw_uniprot"], "candidate_ids": mapped["candidate_ids"], "records": 0, "decision": ("本次测试明确不采用" if analysis_purpose == "workflow_test" else "本次研究明确不采用") if omit else "待处理"})  # 只有明确同意才不采用。
            if mapper.rule != "HGNC.resolve.2":  # 新版异常细分，旧结果字段不改。
                issue.update({key: mapped.get(key, "") for key in ("status", "mapping_method", "ncbi_gene_id", "ncbi_symbol", "gene_type", "verification_url", "ncbi_candidate_ids", "query_status", "query_note")})  # 给出查实类别及来源。
                issue["target_name"] = row.get("target_name", "")  # 缺基因名称时显示原库靶点描述。
            issue["records"] += 1  # 不要求按重复关系审核。
            continue  # 未批准例外时后续发布会阻断。
        item = {k: mapped[k] for k in ("target_id", "symbol", "source_ref")} | {"species": 9606}  # 下游标准接口。
        item.update({"compound_id": row["compound_id"]} if module == "A01" else {"database": row["database"]})  # 保留成分或来源库。
        normalized.append(item)  # 多条证据不因基因去重丢失。
    summary = dict(base["summary"])  # 保留原始计数，明确另报标准化计数。
    pending = sum(v == "pending" for v in scopes.values()) if module == "A02" else 0  # 未决范围独立阻断。
    stage = "标准化流程测试，非正式研究结果" if analysis_purpose == "workflow_test" else "正式研究标准化结果，待专业复核"  # 正式只表示资料链合规，不替代总体复核。
    summary.update(namespace="HGNC", mapping_snapshot=mapper.digest, mapping_rule=mapper.rule, handoff_blocked=bool(pending or (issues and not omit)), analysis_purpose=analysis_purpose, **{"资料阶段": stage, "标准化基因数": len({x["target_id"] for x in normalized}), "待定范围组数": pending, "身份问题组数": len(issues), "身份问题处理": "明确不采用并保留明细" if omit else "须处理后才能交接"})  # 保存当前用途及真实阻断项。
    if analysis_purpose == "formal_research":  # 正式结果必须携带唯一疾病身份。
        require(isinstance(disease_identity, dict), "正式标准化缺少MeSH疾病身份")  # 不允许仅靠自由文本进入正式路径。
        summary.update(mesh_id=disease_identity["mesh_id"], mesh_term=disease_identity["preferred_term"], mesh_year=disease_identity["mesh_year"], mesh_checked_at=disease_identity["checked_at"])  # 下游和报告可直接回指A00证据。
    if mapper.rule != "HGNC.resolve.2":  # 新证据组合单独进入版本和分类统计。
        summary["identity_evidence_snapshot"] = mapper.supplement.digest if mapper.supplement else ""  # A01/A02须一致。
        summary["身份分类"] = {status: sum(x.get("status") == status for x in issues.values()) for status in sorted({x.get("status") for x in issues.values()})}  # 数量为问题组，不是原始行。
    tables = dict(original)  # 不删除原始表与历史意见。
    tables.update(identity_mapping=mappings, identity_issues=list(issues.values()))  # 明确保留例外。
    tables["normalized_compound_targets" if module == "A01" else "normalized_targets"] = normalized  # 与A03接口一致。
    if module == "A02":  # 主集合与参考集合分开。
        tables["candidate_records"] = [dict(row, scope=scopes[row["scope_id"]]) for row in original["candidate_records"]]  # 当前表显示已确认决定，旧产物不变。
        tables["scope_groups"] = [dict(row, scope=scopes[row["scope_id"]]) for row in original["scope_groups"]]  # 避免归档后仍显示待核验。
        summary["待范围复核条目数"] = pending  # 当前范围统计同步。
        tables["scope_decisions_final"] = [{"scope_id": k, "scope": v, **(review_context or {})} for k, v in sorted(scopes.items())]  # 本次新决定单独保存。
        tables["scope_history"] = list(original["scope_history"]) + (tables["scope_decisions_final"] if review_context else [])  # 当前历史包含本次明确签署。
        genes = defaultdict(set)  # 按HGNC编号去重统计来源。
        for row in normalized:  # 每条证据保留其来源库。
            genes[row["target_id"]].add(row["database"])  # 五库并集。
        tables["normalized_reference"] = [{"target_id": gid, "sources": "|".join(sorted(dbs))} for gid, dbs in sorted(genes.items()) if "OTP" in dbs and len(dbs) > 1]  # 原四库并集交OTP仅作参考。
        summary["正式疾病主集合"] = "本次仅生成流程测试用标准化集合" if analysis_purpose == "workflow_test" else "已生成正式研究标准化集合，仍须A02总体复核"  # 区分用途与批准状态。
        if source_exception:  # 缺库事实与人工接受决定单独保存。
            require(analysis_purpose == "workflow_test" and source_exception.get("database") == "GeneCards", "来源例外只允许缺GeneCards的流程测试")  # 不扩展为任意缺库放行。
            exception = dict(source_exception)  # 不修改调用者的预览对象。
            if review_context:  # 发布时补充签署人、理由和时间。
                exception.update(review_context)  # 例外决定可追溯。
            tables["source_exceptions"] = [exception]  # 单行表供网页和报告读取。
            summary.update(**{"来源例外": "缺GeneCards的流程测试", "OTP贡献基因数": exception["otp_unique_genes"], "OTP在疾病集合中的占比（%）": exception["otp_contribution_percent"]})  # 摘要直接提示主要来源。
    anomalies = ["仅用于流程测试；旧资料不能代替按MeSH重新检索的正式研究。", "例外处理、范围决定及原始证据全部保留；未匹配不补造身份。"] if analysis_purpose == "workflow_test" else ["疾病身份已绑定NLM官方MeSH记录；各库仍保留实际检索词和原生编号。", "正式标准化不设新增数值评分阈值；范围决定、身份例外和原始证据全部保留。"]  # 不混淆两条资料路径。
    return summary, tables, anomalies  # 返回同一标准结果结构。

def validator(root, fallback):  # 同一模块兼容旧候选和新标准化产物。
    def check(run, summary, tables, anomalies, outcome):  # 根据明确配置分派，不放宽旧候选门控。
        if run["config"].get("version") not in ("normalized.test.1", VERSION, FORMAL_VERSION, WORKFLOW_EXCEPTION_VERSION):  # 保留历史并接入缺库流程测试版本。
            return fallback(run, summary, tables, anomalies, outcome)  # 原计算结果按原规则核对。
        home = within(Path(root) / "studies", run["study_id"])  # 路径限定本研究。
        inputs = run["inputs"]  # 固定本次来源与决定。
        require(run["config"]["mapping_rule"] == ("HGNC.resolve.2" if run["config"]["version"] == "normalized.test.1" else "HGNC.resolve.3"), "标准化版本与映射规则不一致")  # 不能偷换历史算法。
        require(run["config"]["version"] == "normalized.test.1" or len(inputs.get("identity_evidence_files", [])) == 3, "新版标准化缺少完整身份依据")  # 不允许遗漏补充证据。
        base = read_json(verified_file(home, inputs["base_result"]))  # 不复制完整旧结果到run。
        evidence = [verified_file(home, record).read_bytes() for record in inputs.get("identity_evidence_files", [])]  # 从本研究归档读取补充证据。
        mapper = HgncMap(verified_file(home, inputs["mapping_file"]).read_bytes(), rule=run["config"]["mapping_rule"], supplement=IdentityEvidence(*evidence) if evidence else None)  # 复算使用归档快照。
        purpose = inputs.get("analysis_purpose", "workflow_test")  # 历史运行缺字段时保持原用途。
        require((run["config"]["version"] == FORMAL_VERSION) == (purpose == "formal_research"), "标准化版本与研究用途不一致")  # 测试和正式结果不能互相冒充。
        expected = compute(base, mapper, run["module_id"], inputs["scopes"], inputs["omit_unresolved"], inputs["review_context"], purpose, inputs.get("disease_identity"), inputs.get("source_exception"))  # 从真实来源独立复算。
        require((summary, tables, anomalies) == expected, "标准化结果与来源及决定不一致")  # 不允许改数或漏例外。
        require(not summary["handoff_blocked"], "仍有未决范围或身份问题，不能发布交接结果")  # 不绕过专业决定。
        require(outcome == ("success" if summary["标准化基因数"] else "empty"), "标准化空集状态错误")  # 空集如实留存。
    return check  # 注册到同一Workflow。

def preview(workflow, sid):  # 只读预览，不改当前研究。
    manifest = workflow.load(sid)  # 锁定展示所用版本。
    require(not manifest.get("trashed"), "回收站研究只读")  # 不提供确认入口。
    require(all(manifest["current"].get(k) for k in ("A00", "A01", "A02")), "请先生成A01和A02候选")  # 缺上游不伪造空表。
    bases = {k: workflow.result(manifest, manifest["current"][k]) for k in ("A01", "A02")}  # 来源完整性由内核验证。
    require(all(workflow.active(manifest, base["run_id"]) for base in bases.values()), "上游已失效，请重新整理")  # 不能套用过期候选。
    intake = workflow.result(manifest, manifest["current"]["A00"])["summary"]  # 研究疾病身份只读取当前A00版本。
    disease = intake["disease"].strip().casefold()  # 旧测试路径仍使用原登记名称。
    verified_mesh = isinstance(intake.get("mesh_verification"), dict) and intake["mesh_verification"].get("status") == "verified"  # 疾病身份与研究用途分别判断。
    purpose = intake.get("analysis_purpose") or ("formal_research" if verified_mesh else "workflow_test")  # 历史结果兼容，新增研究严格读取A00用途。
    require(purpose in ("formal_research", "workflow_test"), "A00研究用途无效")  # 不接受页面之外的用途值。
    formal = purpose == "formal_research"  # 正式性不再由MeSH存在自动决定。
    disease_identity = validate_mesh_identity(intake) if verified_mesh else None  # 两种用途都可保留正式疾病身份。
    require(verified_mesh or disease in COPD_TERMS, "当前研究没有已核对的MeSH标准词和编号；请先修订A00登记")  # 任意新疾病仍须正式身份。
    source_rows = bases["A02"]["tables"]["source_summary"]  # 当前运行保存实际研究级数据库方案。
    required_databases = bases["A02"]["summary"].get("databases", [row["database"] for row in source_rows])  # 历史结果没有新字段时沿用原表。
    available = {row["database"] for row in source_rows if row["availability"] in ("已有候选资料，待核验", "已查询但0条精确记录")}  # 查询成功的真实零结果属于已提供来源。
    missing = set(required_databases) - available  # 缺库与查询失败分别核验。
    failures = {row["database"] for row in source_rows if row["availability"] == "查询失败，等待重试或上传"}  # 查询失败不能冒充缺库例外。
    require(not failures, "存在自动来源查询失败；请重试或上传后再进入标准化")  # 任何用途均不发布部分自动结果。
    allow_missing_gene_cards = purpose == "workflow_test" and missing == {"GeneCards"} and bases["A02"]["summary"].get("source_profile") == "A02.source_profile.3"  # 例外严格限定新版研究。
    require(not missing or allow_missing_gene_cards, "五库来源未齐备；正式研究或其他缺库不能进入下游")  # 不把OTP视为GeneCards替代。
    if formal:  # 正式研究拒绝明确标记为历史恢复的测试格式。
        source_manifest = next(record for record in bases["A02"]["sources"] if record["role"] == "source_manifest")  # 当前五库来源由唯一清单固定。
        source_data = read_json(verified_file(workflow.location(sid), source_manifest))  # 校验来源文件后读取实际元数据。
        require(all(item.get("format") not in ("otp_legacy", "disgenet_legacy") for item in source_data.get("datasets", [])), "正式研究不能使用旧OTP或旧DisGeNET恢复资料，请重新获取")  # 流程测试授权不能扩展到正式病例。
    mapper, meta = load_snapshot(workflow.root)  # 固定已核验的版本。
    official_terms = {str(value).strip().casefold() for value in ([disease_identity["preferred_term"]] + disease_identity.get("entry_terms", []))} if disease_identity else COPD_TERMS  # 流程测试也使用已核对MeSH身份判定范围。
    official_id = disease_identity["mesh_id"].casefold() if disease_identity else ""  # MeSH编号完全一致时可建议直接条目。
    scopes = {}  # 每个来源疾病条目分别生成草案。
    for row in bases["A02"]["tables"]["scope_groups"]:  # 已保存决定始终优先。
        if row["scope"] != "pending":  # 人工决定不能被自动规则覆盖。
            scopes[row["scope_id"]] = row["scope"]  # 沿用当前版本明确决定。
        elif disease_identity:  # 具有MeSH身份的正式研究和流程测试都不因文字不同自动排除。
            matched = row["disease_id"].strip().casefold() == official_id or row["disease_term"].strip().casefold() in official_terms  # 只接受官方编号或官方词精确匹配。
            scopes[row["scope_id"]] = "direct" if matched else "pending"  # 其他条目仍需全表范围复核。
        else:  # 已批准的COPD旧资料流程测试保持原草案逻辑。
            scopes[row["scope_id"]] = "direct" if row["disease_term"].strip().casefold() in COPD_TERMS else "outside"  # 不改变历史测试结果。
    source_exception = None  # 资料齐备时不产生空例外记录。
    if allow_missing_gene_cards:  # 计算OTP对实际疾病集合的唯一基因贡献。
        probe = compute(bases["A02"], mapper, "A02", scopes, False, analysis_purpose=purpose, disease_identity=disease_identity)  # 使用同一HGNC规则取得可核实基因集合。
        normalized_rows = probe[1]["normalized_targets"]  # 身份未核实记录不进入贡献比例分母。
        all_genes = {row["target_id"] for row in normalized_rows}  # 当前实际可用来源的并集。
        otp_genes = {row["target_id"] for row in normalized_rows if row["database"] == "OTP"}  # OTP支持的标准化基因。
        ratio = round(100 * len(otp_genes) / len(all_genes), 2) if all_genes else 0.0  # 空集合不除零。
        source_exception = {"version": "A02.source_exception.1", "database": "GeneCards", "availability": "因注册或获取障碍未提供", "reason": "GeneCards因注册或获取障碍未提供；Open Targets仅作为本次流程测试主要来源，不视为等价替代", "actual_sources": "|".join(sorted(available)), "source_counts": "|".join(row["database"] + ":" + str(row["records"]) for row in source_rows), "otp_unique_genes": len(otp_genes), "all_unique_genes": len(all_genes), "otp_contribution_percent": ratio}  # 保存真实来源、记录数和标准化贡献比例。
    results = {k: compute(base, mapper, k, scopes if k == "A02" else {}, False, analysis_purpose=purpose, disease_identity=disease_identity, source_exception=source_exception if k == "A02" else None) for k, base in bases.items()}  # 未签署时仅生成预览。
    stamp = fingerprint({"runs": manifest["current"], "mapping": mapper.digest, "rule": mapper.rule, "evidence": mapper.supplement.digest if mapper.supplement else "", "scopes": scopes, "purpose": purpose, "mesh": disease_identity, "source_exception": source_exception})  # 旧预览不能确认新数据。
    return manifest, bases, mapper, meta, scopes, results, stamp  # 网页和提交使用同一准备逻辑。

def publish(workflow, sid, stamp, reviewer, reason, accept_scope, accept_omit, accept_source_exception=False):  # 明确确认后生成两侧标准化版本。
    require(accept_scope and reviewer.strip() and reason.strip(), "请确认范围草案并填写复核人和依据")  # 不代签范围意见。
    with write_lock(workflow.root):  # 整批生成后才更新当前指针。
        manifest, bases, mapper, meta, scopes, drafts, current_stamp = preview(workflow, sid)  # 锁内重新核验预览。
        require(stamp == current_stamp, "预览版本已改变，请刷新后重新确认")  # 防止旧页面覆盖新资料。
        require(workflow.approved(manifest, manifest["current"]["A00"]), "研究登记尚未通过")  # 沿用原登记门控。
        review_context = {"reviewer": reviewer.strip(), "note": reason.strip(), "created_at": now()}  # 本批范围签署与运行共同留存。
        purpose = drafts["A02"][0]["analysis_purpose"]  # 预览已固定本次是测试或正式路径。
        intake = workflow.result(manifest, manifest["current"]["A00"])["summary"]  # 两种用途都可能具有正式MeSH身份。
        disease_identity = validate_mesh_identity(intake) if isinstance(intake.get("mesh_verification"), dict) else None  # 发布再次核对疾病身份。
        source_exception_rows = drafts["A02"][1].get("source_exceptions", [])  # 只接受预览计算出的例外事实。
        require(not source_exception_rows or accept_source_exception, "请明确接受本次流程测试暂不采用GeneCards")  # 缺库例外必须单独签署。
        source_exception = source_exception_rows[0] if source_exception_rows else None  # 资料齐备时自动撤销例外。
        outputs = {k: compute(base, mapper, k, scopes if k == "A02" else {}, accept_omit, review_context, purpose, disease_identity, source_exception if k == "A02" else None) for k, base in bases.items()}  # 不采信浏览器传回的结果数量。
        require(all(not v[0]["handoff_blocked"] for v in outputs.values()), "仍有未决范围或身份问题；请先完成全表范围复核，并核实是否接受未查实身份暂不采用")  # 缺确认时不能排除问题。
        home = workflow.location(sid)  # 原始文件留在本研究。
        shared = home / "raw" / ("hgnc_" + mapper.digest + ".tsv")  # 按内容指纹复用同一映射文件。
        if not shared.exists():  # 不重复保存两份同一数据。
            shared.parent.mkdir(parents=True, exist_ok=True)  # 复用既定raw目录。
            with shared.open("xb") as stream:  # 不覆盖已有来源。
                stream.write((workflow.root / "references/hgnc_complete_set_20260913.tsv").read_bytes())  # 原样保存官方字节。
        mapping_file = file_record(home, shared, "mapping_source")  # 归档指纹。
        require(mapping_file["sha256"] == mapper.digest, "归档映射快照不一致")  # 不用同名坏文件。
        evidence_files = []  # 同一官方补充证据包供两侧复用。
        for record in meta.get("identity_evidence", []):  # 复制精确固定版本而非联网重查。
            source = workflow.root / "references" / record["filename"]  # 来源限定既定参考目录。
            destination = home / "raw" / ("identity_" + record["sha256"] + source.suffix)  # 内容相同只存一份。
            if not destination.exists():  # 不覆盖旧证据。
                with destination.open("xb") as stream:  # 避免同名覆盖。
                    stream.write(source.read_bytes())  # 原字节归档。
            archived = file_record(home, destination, "identity_source")  # 计算实际归档指纹。
            require(archived["sha256"] == record["sha256"], "补充身份归档指纹不一致")  # 坏文件不能交接。
            evidence_files.append(archived)  # 顺序与解析器约定一致。
        made = {}  # 两个结果成功后才统一发布索引。
        for module, base in bases.items():  # A01/A02始终使用同一映射规则和快照。
            if module == "A01" and workflow.approved(manifest, base['run_id']):  # 仅疾病补库时不重复签署未变的方剂侧。
                scientific_keys = ("mapping_snapshot", "mapping_rule", "identity_evidence_snapshot", "namespace", "analysis_purpose")  # 身份规则及用途必须完全一致。
                same_identity = all(base['summary'].get(key) == outputs[module][0].get(key) for key in scientific_keys)  # 不凭靶点数相同判断。
                same_raw = all(base['tables'].get(key) == outputs[module][1].get(key) for key in ("components", "herb_components", "compound_targets", "herb_summary"))  # 原始关系及药味组成须逐项一致。
                scientific_rows = lambda rows: [{key: value for key, value in row.items() if key != "source_ref"} for row in rows]  # 重预览定位会指向当前运行，不能误判科学连边改变。
                same_data = same_raw and scientific_rows(base['tables'].get("normalized_compound_targets", [])) == scientific_rows(outputs[module][1].get("normalized_compound_targets", []))  # 仅忽略新预览的定位，不改旧结果来源字段。
                if same_identity and same_data:  # 科学数据未变才沿用有效批准。
                    made[module] = base  # 不创建新运行或冒充新的人工复核。
                    continue  # A02仍须生成独立待复核版本。
            inputs = {"base_result": manifest["runs"][base["run_id"]]["result_file"], "mapping_file": mapping_file, "mapping_source": meta, "identity_evidence_files": evidence_files, "scopes": scopes if module == "A02" else {}, "omit_unresolved": accept_omit, "review_context": review_context, "reviewer": reviewer.strip(), "reason": reason.strip(), "analysis_purpose": purpose, "disease_identity": disease_identity, "source_exception": source_exception if module == "A02" else None}  # 保存明确决定，不复制整份旧结果。
            version = FORMAL_VERSION if purpose == "formal_research" else (WORKFLOW_EXCEPTION_VERSION if source_exception else VERSION)  # 缺库流程测试使用独立版本。
            run = workflow._begin(manifest, module, inputs, {"version": version, "scope_policy": "direct_only", "score_filter": "none", "mapping_rule": mapper.rule}, ("正式MeSH标准化：" if purpose == "formal_research" else "标准化流程测试：") + reason)  # 不改旧候选和复核。
            summary, tables, anomalies = outputs[module]  # 结果来自锁内预览。
            sources = list(base["sources"]) + [inputs["base_result"], mapping_file] + evidence_files  # 保留完整原始来源链及映射。
            if module == "A02":  # 后续单库更新继承这次明确确认的范围意见。
                original_manifest = next(record for record in base["sources"] if record["role"] == "source_manifest")  # 定位完整来源清单。
                source_data = read_json(verified_file(home, original_manifest))  # 旧清单只读。
                source_data["scope_decisions"] = source_data.get("scope_decisions", []) + [{"scope_id": gid, "scope": decision, "reviewer": reviewer.strip(), "note": reason.strip(), "created_at": review_context["created_at"]} for gid, decision in scopes.items()]  # 每个条目仍可溯源。
                source_data["source_exception"] = source_exception  # 补入GeneCards时可识别需重算和比较的旧基线。
                source_data["comparison_baseline"] = source_data.get("comparison_baseline") or ({"a02_run_id": base["run_id"], "disease_gene_count": summary["标准化基因数"], "source_exception": source_exception, "current_runs": dict(manifest["current"])} if source_exception else None)  # 先保存可计算的补库前基线。
                path = home / "raw" / run["run_id"] / "disease_sources.json"  # 与既有来源命名一致。
                write_json(path, source_data)  # 新文件不覆盖旧来源清单。
                sources = [record for record in sources if record["role"] != "source_manifest"] + [file_record(home, path, "source_manifest")]  # 当前来源清单唯一。
            made[module] = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success" if summary["标准化基因数"] else "empty", sources=sources)  # 专用校验独立复算。
        workflow.save(manifest)  # 不会只发布一侧标准化指针。
    return made  # 先保存待复核结果，不在内核里冒充人工批准。

def impact_preview(results, mapper):  # 仅评估已知候选的影响，不发布科研结果。
    targets = {key: {x["target_id"] for x in value[1]["normalized_compound_targets" if key == "A01" else "normalized_targets"]} for key, value in results.items()}  # 同一版本的已确认身份集合。
    priority = []  # 已知会触及对侧集合的问题优先展示。
    for key, value in results.items():  # 检查两侧未进入主集合的记录。
        other = targets["A02" if key == "A01" else "A01"]  # 方剂侧对疾病侧，反之亦然。
        for issue in value[1]["identity_issues"]:  # 同一问题只显示一次。
            overlap = set(filter(None, issue["candidate_ids"].split("|"))) & other  # 已知候选不能作为真实纳入集合。
            if overlap:  # 只有明确触及对侧集合才标为已知影响。
                names = [mapper.records[x]["symbol"] for x in sorted(overlap)]  # 面向用户显示标准名称。
                priority.append({"模块":key, "原名称":issue["raw_symbol"], "原蛋白编号":issue["raw_uniprot"], "可能涉及的交集基因":"、".join(names), "涉及记录数":issue["records"], "必须处理的原因":"该问题可能改变交集或成分计数；须核对或明确接受本次测试暂不采用", "依据":issue.get("query_note", "")})  # 不冒充已确认影响大小。
    return {"known_intersection":len(targets["A01"] & targets["A02"]), "priority":priority}  # 其余未知记录仍不能宣称无影响。

def review_page(workflow, sid, token):  # 一个页面集中展示可确认内容。
    from web import text, hidden, table, page  # 复用安全显示工具。
    manifest, bases, mapper, meta, scopes, results, stamp = preview(workflow, sid)  # 只读，不建立运行。
    groups = bases["A02"]["tables"]["scope_groups"]  # 全范围来源可展开核对。
    included = [{"来源": r["database"], "疾病条目": r["disease_term"], "编号": r["disease_id"], "原始记录数": r["records"]} for r in groups if scopes[r["scope_id"]] == "direct"]  # 明确建议采用的条目。
    purpose = results["A02"][0]["analysis_purpose"]  # 页面文字必须与实际计算路径一致。
    formal = purpose == "formal_research"  # 正式路径有NLM官方身份并使用新获取资料。
    omitted = [{"来源": r["database"], "疾病条目": r["disease_term"] or "原始表型为空", "编号": r["disease_id"], "原始记录数": r["records"], "草案处理": "本次研究不采用" if formal else "本次测试不采用"} for r in groups if scopes[r["scope_id"]] in ("outside", "subtype")]  # 只有明确决定的范围才列为不采用。
    pending = [{"来源": r["database"], "疾病条目": r["disease_term"] or "原始表型为空", "编号": r["disease_id"], "原始记录数": r["records"], "当前状态": "必须人工确认"} for r in groups if scopes[r["scope_id"]] == "pending"]  # 名称不匹配不能自动排除。
    if formal:  # 正式路径突出唯一MeSH身份和真实人工任务。
        identity = workflow.result(manifest, manifest["current"]["A00"])["summary"]["mesh_verification"]  # 使用已归档官方证据。
        notice = '<p class="notice"><strong>正式MeSH疾病身份已核对</strong><br>' + text(identity["preferred_term"]) + ' [' + text(identity["mesh_id"]) + ']；MeSH ' + text(identity["mesh_year"]) + '。官方编号、首选词或Entry Term精确一致的条目只形成“本病建议”；已保存的人工范围决定优先。文字不同的条目不会自动排除。</p>'  # 不把自动建议冒充最终判断。
    else:  # 历史COPD流程测试保持原说明。
        notice = '<p class="notice"><strong>仅用于流程测试，非正式研究结果</strong><br>以下是待你确认的草案：本病名称明确匹配的条目拟采用；其余条目按本次已批准测试规则拟不采用。不能把名称不匹配理解为无疾病关联。</p>'  # 不改变旧测试授权边界。
    source_exception = results["A02"][1].get("source_exceptions", [])  # 新版流程测试可能存在缺GeneCards例外。
    if source_exception:  # 必须处理项放在范围表前，避免被大量结果淹没。
        item = source_exception[0]  # 现行规则只允许一个明确缺库。
        notice += '<p class="notice"><strong>必须确认：缺GeneCards的流程测试</strong><br>GeneCards因注册或获取障碍未提供；不是0条。实际可用来源：' + text(item["actual_sources"]) + '。Open Targets贡献原始名称 ' + text(item["otp_unique_genes"]) + '/' + text(item["all_unique_genes"]) + '（' + text(item["otp_contribution_percent"]) + '%）；它是本次主要来源，但不等同GeneCards。</p>'  # 直接显示真实来源和比例。
    body = '<p><a href="/study?study=' + text(sid) + '">返回研究</a></p>' + notice + '<h2>1. 本次拟采用的本病条目</h2>' + table(included)  # 不隐藏主集合来源。
    if pending:  # 未决范围必须在身份例外前处理。
        body += '<h2>必须先处理：待核验疾病条目（' + str(len(pending)) + '组）</h2>' + table(pending) + '<p><a href="/disease?study=' + text(sid) + '&amp;table=scope_groups">返回A02全表范围复核</a>，一次确认全部条目后再回到本页。</p>'  # 提供直接操作入口。
    body += '<details><summary>查看已明确不采用范围（' + str(len(omitted)) + '组）</summary>' + table(omitted) + '</details>'  # 例外全量可查。
    body += '<h2>2. 基因身份核对汇总</h2>' + table([{"模块": k, "可明确匹配的基因数": v[0]["标准化基因数"], "身份问题组数": v[0]["身份问题组数"], "说明": "数量尚未人工确认"} for k, v in results.items()])  # 不把重复记录当基因数。
    status_names = {"unmapped":"仍未查实", "ambiguous_or_conflicting":"身份歧义或冲突", "identity_verified_no_hgnc":"身份已查实，未接入HGNC", "non_gene_object":"已确认是生物区域，非单个基因"}  # 不把全部例外称为无效基因。
    body += '<p class="notice">优先处理身份冲突及可能影响交集的记录。已查实但未接入HGNC的条目、调控区域单列保留；不是错误基因。以下草案不会自动批准或删除记录。</p>' + table([{"模块": k, "类别":status_names.get(status,status), "问题组数":number} for k,v in results.items() for status,number in v[0].get("身份分类",{}).items()])  # 汇总优先于明细。
    impact = impact_preview(results, mapper)  # 用当前实际身份候选评估影响。
    body += '<h3>必须优先处理：可能改变交集的已知问题</h3>' + (table(impact["priority"]) if impact["priority"] else '<p>当前没有发现候选身份直接触及对侧集合的问题；这不代表未查实记录均无影响。</p>')  # 主审查内容置顶。
    body += '<p>以下明细用于集中复核和追溯。没有明确候选身份的记录，影响尚不能确定；不能据此判断没有影响。当前已明确身份的交集预检数为 ' + str(impact["known_intersection"]) + '，仅为未签署的流程预检。</p>'  # 不绕过A03签署。
    for key, value in results.items():  # 两侧问题都在当前页可查。
        body += '<details><summary>' + key + '：身份例外及原始标识</summary>' + table([{FIELD_NAMES.get(k,k):(status_names.get(v,v) if k == "status" else v) for k,v in row.items()} for row in value[1]["identity_issues"]]) + '</details>'  # 不匹配者不默默消失。
    context = "本次正式研究" if formal else "本次流程测试"  # 表单措辞不混淆用途。
    body += '<p>本病范围之外的记录不进入本次疾病集合；未进入HGNC主集合的记录，须明确接受' + context + '暂不采用后才能继续；查实状态和原始资料仍保留。原始评分不筛除，缺失不补零。确认后生成A01/A02标准化新版本（已有下游随之失效），返回研究页分别复核；两侧通过后A03才可运行。</p>'  # 不虚称生成即批准。
    if not pending:  # 范围尚未处理时不显示一个注定失败的发布按钮。
        scope_label = "我确认上述采用及不采用范围，作为本次正式研究范围" if formal else "我确认上述采用及不采用范围，仅用于本次流程测试"  # 保留旧浏览器测试文字。
        omit_label = "我已核查未进入主集合的条目，接受" + context + "暂不采用（保留原始资料和查实依据）"  # 正式和测试都明确留存依据。
        body += '<form method="post" action="/normalize">' + hidden("token", token) + hidden("study", sid) + hidden("preview_stamp", stamp) + '<label>本次核验人<input name="reviewer" required maxlength="200"></label><label>范围及身份例外处理依据<textarea name="reason" required maxlength="4000"></textarea></label><label><input type="checkbox" style="width:auto" name="accept_scope" value="yes" required>' + scope_label + '</label><label><input type="checkbox" style="width:auto" name="accept_omit" value="yes">' + omit_label + '</label>'  # 没有预勾选科学决定。
        if source_exception:  # 只有实际缺GeneCards时显示并要求单独确认。
            body += '<label><input type="checkbox" style="width:auto" name="accept_source_exception" value="yes" required>我接受本次流程测试暂不采用GeneCards；Open Targets不是等价替代，结果不作为完整五库正式研究</label>'  # 签署内容与报告边界一致。
        body += '<button>生成标准化结果，返回研究页复核</button></form>'  # 确认后仍须复核A01/A02。
    return page("A02结果汇总与交接准备", body)  # 专业复核集中入口。
