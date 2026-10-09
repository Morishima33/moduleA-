# A06通用受体筛查预览；按PPI顺序整理证据，但不替用户决定最终受体。
from pathlib import Path  # 安全定位研究包与历史结果。

from contracts import require  # 复用项目统一的阻断规则。
from storage import file_record, new_id, read_json, verified_file, write_json, write_lock  # 保存不可覆盖预览和唯一索引。


SCREEN_SCHEMA = "A06.receptor.screen.2"  # 第二版固定筛查PPI前十位，并完整保留第十位并列对象。
AUDIT_SCHEMA = "A06.receptor.audit.2"  # 第二版允许严格质控、扩展探索及无法计算三种真实结论。
LEGACY_SCHEMAS = {"A06.receptor.screen.1", "A06.receptor.audit.1"}  # 第一版历史预览继续保持可读。
SCREEN_TOP_N = 10  # 每项研究先检查PPI前十位，不为凑数量无限向后扩展。
MIN_STRICT_RECEPTORS = 5  # 主要结论至少需要五个通过本项目严格结构质控的受体。


def _approved_diagnostics(workflow):  # 从本项目已批准结果建立可复用的技术质控线索库。
    library = {}  # 同一靶点只保留指向明确批准结果的记录。
    evidence = []  # 历史结果文件作为当前预览的来源证据。
    studies = workflow.root / "studies"  # 所有独立研究均位于统一研究包目录。
    if not studies.is_dir():  # 新建空项目时没有历史质控可复用。
        return library, evidence  # 返回空库而不是伪造无结构结论。
    for folder in sorted(path for path in studies.iterdir() if path.is_dir()):  # 稳定顺序扫描研究包。
        manifest_path = folder / "manifest.json"  # 每个研究只从明确索引读取当前版本。
        if not manifest_path.is_file():  # 非研究辅助目录不参与筛查。
            continue  # 不按目录名称猜测内容。
        try:  # 损坏或历史不兼容研究不能污染新筛查。
            manifest = workflow.load(folder.name)  # 复用工作流完整性检查。
        except Exception:  # 当前任务保留真实研究，但不把不可核验资料当证据。
            continue  # 后续可单独修复该历史研究。
        run_id = manifest.get("current", {}).get("A06_PREP")  # 只复用当前准备版本。
        if not run_id or not workflow.approved(manifest, run_id):  # 未批准或已失效结果不能称作已质控。
            continue  # 保留在历史中但不进入技术线索库。
        result = workflow.result(manifest, run_id)  # 重新校验结果及文件指纹。
        diagnostics = result.get("tables", {}).get("receptor_diagnostics", [])  # 五乘五版本保存了重对接事实。
        if not diagnostics:  # 旧版不含统一诊断表时不自行补字段。
            continue  # 避免凭文件名推断PDB和RMSD。
        result_path = verified_file(workflow.location(folder.name), manifest["runs"][run_id]["result_file"])  # 定位真实结果文件。
        result_record = file_record(workflow.root, result_path, "historical_receptor_qc")  # 转换成项目级证据索引。
        evidence.append(result_record)  # 页面可以下载并复核原始记录。
        for row in diagnostics:  # 每个受体单独判断是否具备历史技术质控。
            symbol = str(row.get("受体", "")).strip()  # 使用标准基因符号作为匹配键。
            passed = row.get("诊断通过") is True  # 只有明确通过才可作为复用线索。
            rmsd = row.get("RMSD_A")  # 保存实际重对接结果，不只写“通过”。
            if not symbol or not passed or not isinstance(rmsd, (int, float)) or rmsd > 2.0:  # 不接受缺失或超阈值记录。
                continue  # 失败结果仍在原文件中可追溯。
            library[symbol] = {"pdb": str(row.get("PDB", "")), "rmsd_angstrom": float(rmsd), "source_study": folder.name, "source_run": run_id, "evidence": result_record}  # 保存最小且明确的复用事实。
    return library, evidence  # 返回技术线索及其不可变来源。


def _screen_rows(round1, library):  # 选取PPI前十位并保留第十位边界并列，不依赖历史合格数量停止。
    ordered = sorted(round1, key=lambda row: -float(row["degree"]))  # Python稳定排序保留A04对并列项的原始顺序。
    rows = []  # 保存进入本轮窗口的全部候选。
    require(ordered, "A04第一轮PPI候选为空，不能建立受体筛查窗口")  # 空PPI不能生成伪候选。
    boundary_index = min(SCREEN_TOP_N, len(ordered)) - 1  # 取得前十位窗口的最后一个实际位置。
    boundary_degree = float(ordered[boundary_index]["degree"])  # 使用Degree值保留边界并列对象。
    for position, source in enumerate(ordered, 1):  # 排名来自本次A04而不是旧研究。
        symbol = str(source["symbol"])  # 基因符号已经过A04身份校验。
        prior = library.get(symbol)  # 查找可复核的历史技术线索。
        status = "已有历史技术质控，仍需本研究确认" if prior else "需要新做结构与口袋筛查"  # 不把历史通过直接等同本研究入选。
        rank = 1 + sum(1 for item in ordered[:position - 1] if float(item["degree"]) > float(source["degree"]))  # 相同Degree使用同一名次。
        row = {"ppi_order": rank, "symbol": symbol, "target_id": source["target_id"], "degree": source["degree"], "degree_tie": sum(1 for item in ordered if item["degree"] == source["degree"]) > 1, "screen_status": status, "historical_pdb": prior["pdb"] if prior else "", "historical_redocking_rmsd_angstrom": prior["rmsd_angstrom"] if prior else None, "decision": "pending_manual_confirmation"}  # 所有对象先保持待确认。
        rows.append(row)  # 未决前列对象也必须出现在复核页。
        if position >= SCREEN_TOP_N and float(source["degree"]) < boundary_degree:  # 第十位后的更低Degree不进入固定窗口。
            rows.pop()  # 当前项已经加入，发现低于边界时立即撤回。
            break  # 后续Degree只会更低，可以稳定停止。
    return rows  # 返回包含所有排序缺口的完整窗口。


def _current_preview(workflow, study_id, parents):  # 判断现有预览是否已准确绑定当前上游。
    index_path = workflow.root / "environments" / "A06_previews.json"  # 预览只通过唯一索引定位。
    if not index_path.is_file():  # 首次运行尚无索引。
        return None  # 继续创建新预览。
    index = read_json(index_path)  # 不扫描文件修改时间猜最新版。
    reference = index.get("studies", {}).get(study_id)  # 每项研究独立保存当前预览。
    if not reference:  # 其他研究已有预览不影响本研究。
        return None  # 继续创建。
    try:  # 被修改或过期的预览不应被静默复用。
        preview = read_json(verified_file(workflow.root, reference))  # 校验实际文件指纹。
        for record in preview.get("evidence", []):  # 规则代码或上游证据变化时旧预览也应失效。
            verified_file(workflow.root, record)  # 嵌套证据必须继续匹配原指纹。
    except Exception:  # 索引损坏应由新版本替换当前指针但保留旧文件。
        return None  # 继续创建可追溯新版本。
    supported = {SCREEN_SCHEMA, AUDIT_SCHEMA} | LEGACY_SCHEMAS  # 新旧预览均保持可读，只有新版可继续写入。
    return preview if preview.get("schema_version") in supported and preview.get("parent_runs") == parents else None  # 不能被过期上游或未知版本覆盖。


def prepare_screen(workflow, study_id):  # 自动生成下一人工关口的受体筛查预览。
    manifest = workflow.load(study_id)  # 读取当前研究的唯一状态。
    parents = {module: manifest.get("current", {}).get(module, "") for module in ("A03", "A03_SELECT", "A04")}  # 明确绑定交集、成分选择和PPI。
    require(all(parents.values()) and all(workflow.approved(manifest, run_id) for run_id in parents.values()), "A03、A03_SELECT和A04须先全部复核通过")  # 自动化不能跨越人工关口。
    current = _current_preview(workflow, study_id, parents)  # 避免重复点击生成竞争版本。
    if current is not None and current.get("schema_version") in (SCREEN_SCHEMA, AUDIT_SCHEMA):  # 同一上游已有有效新版预览。
        return {"created": False, "preview": current}  # 页面直接继续使用原版本。
    selection = workflow.result(manifest, parents["A03_SELECT"])  # 读取用户已确认的主候选成分。
    ppi = workflow.result(manifest, parents["A04"])  # 读取本研究第一轮PPI候选。
    ligands = [{"compound_id": row["compound_id"], "name": row["name"], "herbs": row.get("herbs", ""), "selection_role": row.get("selection_role", "")} for row in selection.get("tables", {}).get("selected", [])]  # 保留七项实际选择及角色。
    require(ligands, "A03_SELECT没有已确认的对接成分")  # 空成分列表不能进入准备阶段。
    round1 = ppi.get("tables", {}).get("round1", [])  # 第一轮是大纲规定的主要候选来源。
    require(round1, "A04没有第一轮PPI候选")  # 不从第二轮或图形反推对象。
    library, historical_evidence = _approved_diagnostics(workflow)  # 获取可复用但不自动批准的历史技术证据。
    rows = _screen_rows(round1, library)  # 按本研究排名生成连续筛查窗口。
    unresolved = [row for row in rows if not row["historical_pdb"]]  # 高位无历史证据者必须先处理。
    reusable = [row for row in rows if row["historical_pdb"]]  # 历史线索仍需本研究人工确认。
    run_folder = workflow.location(study_id) / "runs" / "A06_PREP" / new_id("screen")  # 预览归入既定A06_PREP目录但不冒充正式运行。
    screen_path = run_folder / "receptor_screen.json"  # 文件名直接表达用途。
    source_records = [file_record(workflow.root, verified_file(workflow.location(study_id), manifest["runs"][parents[module]]["result_file"]), module.lower() + "_result") for module in ("A03_SELECT", "A04")]  # 固定本次两项直接来源。
    code_record = file_record(workflow.root, Path(__file__).resolve(), "screening_code")  # 将实际规则代码纳入指纹。
    evidence = source_records + historical_evidence + [code_record]  # 所有结论均可回到具体文件。
    preview = {"schema_version": SCREEN_SCHEMA, "study_id": study_id, "status": "pending_receptor_screen_review", "analysis_purpose": selection.get("summary", {}).get("analysis_purpose", ppi.get("summary", {}).get("analysis_purpose", "")), "parent_runs": parents, "selection_rule": "A04第一轮Degree前10位及第10位边界并列全部核查；主要结论至少保留5个严格质控受体", "screen_top_n": SCREEN_TOP_N, "minimum_strict_receptors": MIN_STRICT_RECEPTORS, "ligands": ligands, "ligand_count": len(ligands), "screening_window": rows, "historically_qc_candidates": reusable, "unresolved_higher_ranked_candidates": unresolved, "final_receptors": [], "planned_pair_count": len(ligands) * len(rows), "handoff_blocked": True, "notice": str(len(ligands)) + "个成分已接入；请核查PPI前十位及边界并列受体。结构限制不直接删除对象，但必须记录口袋依据和解释边界。", "pending": [{"item": "受体筛查集中复核", "impact": "为每个对象确定严格质控、扩展探索或无法计算；不得静默删除。"}, {"item": "本研究受体结构准备与搜索盒核查", "impact": "有参考配体者重对接；预测口袋保留P2Rank完整证据，不伪造RMSD。"}], "evidence": evidence}  # 预览不包含伪搜索盒或对接评分。
    write_json(screen_path, preview)  # 新预览不可覆盖任何历史版本。
    with write_lock(workflow.root):  # 当前指针更新与其他网页写入互斥。
        index_path = workflow.root / "environments" / "A06_previews.json"  # 使用既有唯一索引。
        index = read_json(index_path) if index_path.is_file() else {"schema_version": "A06.preview.index.1", "studies": {}}  # 首次运行建立标准索引。
        require(index.get("schema_version") == "A06.preview.index.1", "A06预览索引版本不支持")  # 不覆盖未知格式。
        index.setdefault("studies", {})[study_id] = file_record(workflow.root, screen_path, "a06_receptor_screen")  # 只切换本研究当前预览。
        write_json(index_path, index, replace=True)  # 索引允许原子替换，预览文件本身不变。
    return {"created": True, "preview": preview, "path": str(screen_path)}  # 供自动接续和验收使用。


def publish_audit(workflow, study_id, assessments, evidence):  # 保存一次完整受体适用性核查并切换网页预览。
    manifest = workflow.load(study_id)  # 研究状态必须来自统一索引。
    parents = {module: manifest.get("current", {}).get(module, "") for module in ("A03", "A03_SELECT", "A04")}  # 审计绑定当前交集、成分和PPI版本。
    base = _current_preview(workflow, study_id, parents)  # 取得当前筛查窗口或已发布核查。
    require(base is not None and base.get("schema_version") == SCREEN_SCHEMA, "当前没有可发布的第二版受体筛查草案，或该版本已经完成核查")  # 防止重复发布竞争结论。
    require(isinstance(assessments, list) and assessments, "受体核查结果不能为空")  # 不允许空表通过。
    expected = [row["symbol"] for row in base["screening_window"]]  # 本轮必须覆盖筛查窗口的全部对象。
    require([row.get("symbol") for row in assessments] == expected, "受体核查必须保持PPI顺序并覆盖全部筛查对象")  # 不允许漏掉高位未决对象。
    allowed = {"strict_candidate", "exploratory_candidate", "not_computable"}  # 三类均为结构事实，不在热图中显示字母等级。
    require(all(row.get("decision") in allowed and str(row.get("reason", "")).strip() for row in assessments), "每个受体都须有明确结论和理由")  # 无理由跳过无效。
    strict = [row for row in assessments if row["decision"] == "strict_candidate"]  # 主要结论候选必须完成本研究重对接。
    require(len(strict) >= MIN_STRICT_RECEPTORS, "前十位严格质控候选不足五个；须暂停并决定是否扩展检查第11至15位")  # 不自动向后补齐。
    candidates = [row for row in assessments if row["decision"] != "not_computable"]  # 可计算对象全部进入动态矩阵。
    for record in evidence:  # 官方结构与历史质控文件必须保持完整。
        verified_file(workflow.root, record)  # 先校验再引用。
    run_folder = workflow.location(study_id) / "runs" / "A06_PREP" / new_id("audit")  # 核查版继续归入A06_PREP阶段目录。
    audit_path = run_folder / "receptor_audit.json"  # 文件名说明它是结构适用性核查。
    audit = dict(base)  # 保留已确认的七个成分和原始筛查窗口。
    audit.update({"schema_version": AUDIT_SCHEMA, "status": "receptor_audit_completed_pending_preparation", "notice": "受体核查完成；全部可计算对象进入结构准备。严格质控受体用于主要结论，其他对象仅作扩展或探索解释。", "assessments": assessments, "recommended_receptors": strict[:MIN_STRICT_RECEPTORS], "strict_candidates": strict, "candidate_receptors": candidates, "final_receptors": [], "planned_pair_count": len(base["ligands"]) * len(candidates), "handoff_blocked": True, "pending": [{"item": "准备全部可计算受体和已确认配体", "impact": "生成受体/配体PDBQT并逐项记录实际处理。"}, {"item": "建立搜索盒并完成相应质控", "impact": "共晶口袋完成重对接；预测口袋保留P2Rank证据且RMSD记为不适用。"}], "evidence": list(base.get("evidence", [])) + [record for record in evidence if record.get("path") not in {item.get("path") for item in base.get("evidence", [])}]})  # 新证据去重并持续阻断正式对接。
    write_json(audit_path, audit)  # 审计记录不可覆盖。
    with write_lock(workflow.root):  # 当前预览指针原子更新。
        index_path = workflow.root / "environments" / "A06_previews.json"  # 继续使用唯一索引。
        index = read_json(index_path)  # 筛查阶段已建立索引。
        index["studies"][study_id] = file_record(workflow.root, audit_path, "a06_receptor_audit")  # 只切换本研究指针。
        write_json(index_path, index, replace=True)  # 旧筛查文件完整保留。
    return {"audit": audit, "path": str(audit_path)}  # 供后续结构准备和验收使用。
