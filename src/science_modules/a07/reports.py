"""A07第14版：专业报告补A03前十表，保持既有双报告结构及结论规则。"""
from pathlib import Path
from docx import Document
from contracts import require, check_result
from storage import file_record, now, read_json, verified_file, write_json, write_lock
from report_figures import generate_report_figures
from report_pathway import report_pathway_record, attach_report_pathway
import report_flow_pathway as legacy
from modulea.core.source_catalog import source_databases, SOURCE_LABELS

CONFIG = dict(legacy.CONFIG, schema_version="A07.report.config.14", template_version="A07.double_report.14")
COLUMNS = ["名次", "成分名称", "来源药味", "不同交集靶点数", "混合Degree"]

# 只读A03归档主排序；第十个处的同分组全部保留，不重新决定对接候选。
def top_rows(ranking):
    rows = sorted([r for r in ranking if r.get("main_rank") is not None and r.get("intersection_count", 0) > 0], key=lambda r: (-r["intersection_count"], str(r.get("compound_id", ""))))
    if len(rows) > 10:
        rows = [r for r in rows if r["intersection_count"] >= rows[9]["intersection_count"]]
    return [{"名次": r["main_rank"], "成分名称": r.get("name", r["compound_id"]), "来源药味": r.get("herbs", ""), "不同交集靶点数": r["intersection_count"], "混合Degree": r.get("mixed_degree")} for r in rows]

# 表名及短说明与网页同口径；明确排名依据、并列和解释边界。
def table_note(rows, a03_run):
    extra = f"第十个处有并列，本表共列{len(rows)}个成分。" if len(rows) > 10 else "同值保留并列名次。"
    return f"按每个成分关联的不同交集靶点数降序排列。{extra}混合Degree为交集靶点数加来源药味数，仅供参考。排名反映当前资料的靶点覆盖，不代表含量、疗效或结合强度；对接候选另行确认。完整排名见A03归档（{a03_run}）。"

# 在韦恩图之后、PPI结果之前插表；其他章节、图片和临床简略版保持原规则。
def add_a03_table(document, ranking, a03_run):
    rows = top_rows(ranking)
    captions = [p for p in document.paragraphs if p.text.startswith("图1 方剂靶点与疾病靶点韦恩图")]
    require(len(captions) == 1, "专业报告韦恩图位置不明确，不能自动插表")
    anchor = captions[0]._p
    title = document.add_paragraph("表 A03 01 成分按不同交集靶点数排名前十")
    title.paragraph_format.keep_with_next = True
    for run in title.runs: legacy._font(run, size=10, bold=True)
    note = document.add_paragraph(table_note(rows, a03_run))
    note.paragraph_format.keep_with_next = True
    if rows:
        legacy._table(document, rows, COLUMNS, [1.5, 6.0, 2.3, 3.2, 3.0], font_size=9)
        element = document.tables[-1]._tbl
        for row in document.tables[-1].rows: legacy._keep_row_together(row)
    else:
        element = document.add_paragraph("当前A03没有关联交集靶点的成分，不生成虚构排名。")._p
    for e in [title._p, note._p, element]: anchor.addnext(e); anchor = e
    return rows

# 原事实包增加实际来源名称供方法段引用，不改变数量、候选或结论。
def assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record=None):
    payload = legacy.assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record)
    a01 = workflow.result(manifest, parent_runs["A01"])
    payload["a01_databases"] = source_databases("A01", manifest, a01)
    payload["a02_databases"] = source_databases("A02", manifest, workflow.result(manifest, parent_runs["A02"]))
    payload["a03_top10"] = top_rows(payload["a03_tables"].get("ranking", []))
    return payload

# 基于冻结模板新增一张表，并修正方法段只写TCMSP而遗漏实际三库的缺陷。
def build_detailed(payload, destination, root, revision):
    legacy.build_detailed(payload, destination, root, revision)
    document = Document(destination)
    databases = payload.get("a01_databases", ["TCMSP"])
    labels = "、".join(SOURCE_LABELS.get(db, db) for db in databases)
    text = f"成分与方剂靶点：来源为{labels}；TCMSP采用OB≥30%、DL≥0.18筛选。"
    if len(databases) > 1: text += "HERB和BATMAN-TCM不按上述ADME阈值淘汰，仅纳入数据库已有关系；完整InChIKey且无分子式冲突才跨库合并。"
    text += "人类基因身份按本研究绑定的HGNC依据统一，原来源证据保留。"
    for paragraph in document.paragraphs:
        if paragraph.text.startswith("成分与方剂靶点："):
            paragraph.text = text
            for run in paragraph.runs: legacy._font(run, size=10.5)
    disease_names = "、".join(SOURCE_LABELS.get(db, db) for db in payload.get("a02_databases", []))
    if disease_names:
        for paragraph in document.paragraphs:
            if paragraph.text.startswith("疾病靶点："):
                paragraph.text = paragraph.text.replace("疾病靶点：", "疾病靶点：来源方案为" + disease_names + "；", 1)
                for run in paragraph.runs: legacy._font(run, size=10.5)
    add_a03_table(document, payload["a03_tables"].get("ranking", []), payload["parent_runs"]["A03"])
    document.save(destination)

# 临床简略版仍调用冻结模板，不加入专业版新表。
build_concise = legacy.build_concise
report_heatmap_record = legacy.report_heatmap_record

# 新版额外核对排名来自同一上游；旧版继续由原校验器负责。
def validator(root):
    original = legacy.validator(root)
    def check(run, summary, tables, anomalies, outcome):
        original(run, summary, tables, anomalies, outcome)
        if run.get("config", {}).get("schema_version") != CONFIG["schema_version"]: return
        require(run["config"] == CONFIG, "新版报告配置不一致")
        home = Path(root) / "studies" / run["study_id"]
        source = run["inputs"].get("a03_ranking_source")
        require(source and source.get("path", "").endswith("/" + run["parent_runs"]["A03"] + "/result.json"), "报告缺少绑定A03来源")
        a03 = read_json(verified_file(home, source))
        require(tables.get("a03_top10") == top_rows(a03["tables"].get("ranking", [])), "报告前十排名与绑定A03不一致")
        detail = next(r for r in tables["report_files"] if r["role"] == "detailed_report")
        document = Document(verified_file(home, detail))
        match = [t for t in document.tables if [c.text for c in t.rows[0].cells] == COLUMNS]
        expected = [["—" if row.get(key) is None or row.get(key) == "" else str(row[key]) for key in COLUMNS] for row in tables["a03_top10"]]
        require((len(match) == 1 and [[c.text for c in row.cells] for row in match[0].rows[1:]] == expected) if expected else not match, "专业报告前十表与归档排名不一致")

    return check

def run_reports(workflow, study_id, expected_a07, reason, reuse_current_concise=False, task_package=None):  # 生成新的A07双报告修订。
    manifest = workflow.load(study_id)  # 读取当前研究状态。
    require(manifest["current"].get("A07", "") == expected_a07, "A07版本已改变，请刷新后重试")  # 防止旧页面覆盖新报告。
    required = ("A00", "A01", "A02", "A03", "A04", "A05", "A06")  # 报告不能混用新交集与旧下游。
    require(all(manifest["current"].get(mid) and workflow.active(manifest, manifest["current"][mid]) and workflow.approved(manifest, manifest["current"][mid]) for mid in required), "报告上游尚未全部有效并复核通过；请按流程更新后再生成完整报告")
    study_home = workflow.location(study_id)  # 后续所有报告附件使用研究包相对路径。
    a06_id = manifest["current"].get("A06")  # 取得当前已批准A06。
    a06_result = workflow.result(manifest, a06_id) if a06_id else None  # 读取当前A06标准结果。
    task_records = []  # 任务包可选，历史报告继续读取原接口。
    if task_package:  # 当前研究可明确绑定同源PyMOL任务包。
        package_index_path = verified_file(study_home, task_package['index'])  # 必须由显式指纹记录指定。
        package_index = read_json(package_index_path)  # 读取已完成包的唯一索引。
        require(package_index['study_id'] == study_id and package_index['source_a06_run'] == a06_id, '任务包不是当前A06来源')  # 拒绝同维度其他运行。
        for item in package_index['files']:  # 原始资料、PDB和PSE都必须完整。
            verified_file(package_index_path.parent, item)  # 不只核对压缩包存在。
        require(package_index['completed_pair_count'] == a06_result['summary']['成功组合数'] and package_index['planned_pair_count'] == a06_result['summary']['计划组合数'], '任务包数量与A06不一致')  # 全计划与有效输出同源。
        verified_file(study_home, task_package['archive'])  # 压缩交付本身也必须通过指纹。
        task_records = [task_package['index'], task_package['archive']]  # 下载记录不挤占固定两份Word。
    heatmap_record = report_heatmap_record(workflow, a06_result)  # 优先使用用户已审核的同源展示修订。
    pathway_record = report_pathway_record(workflow, manifest) # 只选当前富集下已人工确认的通路。
    with write_lock(workflow.root):  # 在一次锁内固定上游、生成文件并发布结果。
        manifest = workflow.load(study_id)  # 锁内重新读取最新状态。
        require(manifest["current"].get("A07", "") == expected_a07, "A07版本已改变，请刷新后重试")  # 再次校验并发版本。
        require(report_heatmap_record(workflow, a06_result) == heatmap_record, "热图展示版本已改变，请刷新后重试")  # 锁内拒绝并发换图。
        require(report_pathway_record(workflow, manifest) == pathway_record, "通路选择版本已改变，请刷新后重试") # 锁内拒绝并发换图。
        inputs = {"heatmap_metadata": heatmap_record} if heatmap_record else {}  # 有效空A06没有图形输入。
        if task_package:  # 将任务包绑定到当前报告运行输入。
            inputs["task_package_index"] = task_package["index"]  # 运行记录回指唯一任务版本。
            inputs["task_package_archive"] = task_package["archive"]  # 下载包独立回指。
        if pathway_record: inputs["selected_pathway_metadata"] = pathway_record # 将人工选定通路作为实际报告输入。
        inputs["a03_ranking_source"] = manifest["runs"][manifest["current"]["A03"]]["result_file"]  # 固定补表的真实A03输入。
        run = workflow._begin(manifest, "A07", inputs, dict(CONFIG), reason)  # 自动固定A00至A06当前批准版本和复核编号。
        payload = assemble_payload(workflow, manifest, run["parent_runs"], heatmap_record)  # 生成唯一事实包。
        revision = "report_rev_" + run["run_id"].removeprefix("run_")  # 从稳定运行编号派生唯一报告修订号。
        report_dir = workflow.location(study_id) / "reports" / revision  # 每次报告修订使用独立目录。
        figure_paths = generate_report_figures(report_dir / "figures", payload)  # 从绑定运行表生成六张同源SVG和PNG。
        figure_keys = {"venn": "01_方剂疾病靶点韦恩图", "herb_compound_target": "02_药味成分交集靶点网络图", "ppi_full": "03_PPI完整网络图", "ppi_round1": "04_PPI第一轮主候选网络图", "go_faceted": "05_GO富集三分类柱状图", "kegg_bubble": "06_KEGG富集气泡图"}  # 建立报告语义键与稳定文件名映射。
        payload["report_figures"] = {key: {kind: file_record(workflow.location(study_id), figure_paths[name][kind], f"{key}_{kind}") for kind in ("svg", "png")} for key, name in figure_keys.items()}  # 记录每张图的两种格式和指纹。
        pathway_sources = attach_report_pathway(workflow, manifest, payload, report_dir, pathway_record) # 固定通路图源、解释与参考文献。
        previous_comparison = None  # 默认不把毕业论文差异说明强加给其他研究。
        if expected_a07:  # 修订已有报告时检查其是否明确绑定过差异说明。
            previous_result = workflow.result(manifest, expected_a07)  # 核验当前A07结果。
            previous_index_record = next((record for record in previous_result.get("tables", {}).get("report_files", []) if record.get("role") == "report_index"), None)  # 定位旧索引。
            if previous_index_record:  # 旧索引存在才读取可选附件。
                previous_index = read_json(verified_file(study_home, previous_index_record))  # 核验旧索引自身。
                old_comparison = previous_index.get("comparison_report")  # 读取旧差异说明记录。
                if old_comparison:  # 只有指纹仍匹配的附件才能复制到新修订。
                    previous_comparison = verified_file(study_home if previous_index.get("schema_version") == "A07.report.index.3" else workflow.root, old_comparison)  # 兼容新旧相对根目录。
        payload["comparison_report_included"] = previous_comparison is not None  # 供专业报告决定是否显示附件提示。
        detailed_path = report_dir / "ModuleA_专业详细报告.docx"  # 使用稳定且可读的详细版名称。
        concise_path = report_dir / "ModuleA_临床简略报告.docx"  # 使用稳定且可读的简略版名称。
        comparison_path = report_dir / "ModuleA_既有研究结果差异说明.docx" if previous_comparison else None  # 可选附件进入本次唯一修订目录。
        build_detailed(payload, detailed_path, workflow.location(study_id), revision)  # 从共同事实包生成详细版。
        if reuse_current_concise and expected_a07:  # 本次仅修订专业版时保持临床简略报告字节不变。
            previous_a07 = workflow.result(manifest, expected_a07)  # 读取当前A07报告记录。
            require(workflow.run(manifest, expected_a07).get("parent_runs") == run.get("parent_runs"), "上游已变化，不能复用旧简略报告")  # 只允许纯报告版式修订复用。
            previous_concise = next(record for record in previous_a07["tables"]["report_files"] if record["role"] == "concise_report")  # 找到旧简略版。
            concise_path.write_bytes(verified_file(workflow.location(study_id), previous_concise).read_bytes())  # 原样复制到新修订目录。
        else:  # 常规A07运行继续生成同源简略报告。
            build_concise(payload, concise_path, workflow.location(study_id), revision)  # 从同一事实包生成简略版。
        if comparison_path:  # 当前研究已有明确差异说明时将其冻结到本次修订。
            comparison_path.write_bytes(previous_comparison.read_bytes())  # 字节级复制，保留已审核内容并禁止共享路径覆盖。
        detailed_record = file_record(workflow.location(study_id), detailed_path, "detailed_report")  # 记录详细版指纹。
        concise_record = file_record(workflow.location(study_id), concise_path, "concise_report")  # 记录简略版指纹。
        index_path = report_dir / "report_index.json"  # 索引与两份报告放在同一修订目录。
        report_index = {  # 建立可机读的报告发布索引。
            "schema_version": "A07.report.index.3",  # 第三版把可选差异说明保存在修订目录内。
            "study_id": study_id,  # 绑定当前研究。
            "run_id": run["run_id"],  # 绑定当前A07运行。
            "report_revision": revision,  # 保存可读修订编号。
            "template_version": CONFIG["template_version"],  # 固定模板版本。
            "analysis_purpose": payload["analysis_purpose"],  # 传播分析用途。
            "parent_runs": run["parent_runs"],  # 固定七个上游运行。
            "parent_review_ids": run["parent_review_ids"],  # 固定当时生效的七个复核决定。
            "selected_pathway": payload.get("selected_pathway"), # 可选通路单独索引，不改变原六张图。
            "selection_run": payload["selection_run"],  # 固定主候选选择版本。
            "heatmap_metadata": heatmap_record,  # 固定图形元数据；有效空结果为None。
            "reports": [detailed_record, concise_record],  # 保存两份Word及指纹。
            "figures": [record for pair in payload["report_figures"].values() for record in pair.values()],  # 保存六张图的SVG和PNG指纹。
            "comparison_report": file_record(study_home, comparison_path, "comparison_report") if comparison_path else None,  # 可选差异说明使用研究包内不可变路径。
            "docking_task_package": task_package,  # 与当前A06相同的固定姿势交付包。
            "conclusion_review_required": True,  # 明确生成后仍须人工复核。
            "created_at": now(),  # 保存报告生成时间。
        }  # 完成报告索引。
        write_json(index_path, report_index)  # 写入不可覆盖的新索引。
        index_record = file_record(workflow.location(study_id), index_path, "report_index")  # 记录索引自身指纹。
        report_files = [detailed_record, concise_record, index_record]  # A07固定三项正式文件。
        summary = {  # 形成网页和后续复核使用的摘要。
            "analysis_purpose": payload["analysis_purpose"],  # 传播流程测试标记。
            "报告修订": revision,  # 显示明确修订编号。
            "详细报告": detailed_path.name,  # 显示可读文件名。
            "简略报告": concise_path.name,  # 显示可读文件名。
            "差异说明": comparison_path.name if comparison_path else "本研究未绑定独立差异说明",  # 不为其他研究生成毕业论文比较。
            "共同结论草稿": payload["conclusion_draft"],  # 网页直接突出待核验结论。
            "研究线索数": len(payload["research_leads"]),  # 告知用户只需审核几条线索。
            "结论复核状态": "待专业复核",  # 不自动代签A07。
            "handoff_blocked": False,  # 文件完整后允许用户提交A07决定。
        }  # 结束A07摘要。
        tables = {  # 保存网页可复核和可追溯的结构化结果。
            "key_counts": payload["key_counts"],  # 两版报告共同数量。
            "a03_top10": payload["a03_top10"],  # 固定专业版前十表与A03来源。
            "research_leads": payload["research_leads"],  # 最多三条线索。
            "limitations": [{"限制": value} for value in payload["limitations"]],  # 共同限制列表。
            "report_files": report_files,  # 两份Word和索引。
            "selected_pathway": [{"通路ID": payload["selected_pathway"]["pathway_id"], "通路名称": payload["selected_pathway"]["display_name"], "命中基因数": payload["selected_pathway"]["count"], "BH调整后P值": payload["selected_pathway"]["adjusted_p"], "确认状态": "用户已确认", "事实包": pathway_record["path"]}] if payload.get("selected_pathway") else [], # 网页明细仅含简单值，完整结构由报告索引关联。
            "report_figures": report_index["figures"],  # 网页和验收可核查全部图源。
            "version_bindings": [{"模块": module, "运行编号": run_id, "复核编号": run["parent_review_ids"].get(module)} for module, run_id in run["parent_runs"].items()],  # 七个上游版本与复核绑定。
        }  # 结束A07结构化表。
        anomalies = list(payload["limitations"])  # 异常与限制区沿用共同边界，不另造成功句式。
        check_result(summary, tables, anomalies, "success")  # 发布前检查统一结果结构。
        optional_sources = [record for record in (heatmap_record, payload["heatmap_png"]) if record]  # 有效空A06没有热图来源。
        sources = [manifest["runs"][run_id]["result_file"] for run_id in run["parent_runs"].values()] + optional_sources + payload["receptor_setup_sources"] + pathway_sources  # 将七个上游结果及实际存在的结构来源纳入索引。
        attachments = task_records + report_files + report_index["figures"] + ([report_index["comparison_report"]] if report_index["comparison_report"] else []) + ([payload["selected_pathway"]["report_figure"]] if payload.get("selected_pathway") else [])  # 报告、索引、图源及可选差异说明均纳入指纹。
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success", sources=sources, attachments=attachments)  # 发布待复核A07标准结果。
        workflow.save(manifest)  # 原子更新研究索引。
    return result  # 返回网页可显示的A07结果。
