"""第25版自动对接适配：沿用第24版展示规范，读取真实动态矩阵。"""

from copy import deepcopy
from pathlib import Path

from contracts import require
from storage import file_record, read_json, verified_file, write_json, write_lock
from modulea.core.compound_names import compound_names, bilingual_label
from . import compact_enrichment_reports as base
from .commented_reports import report_maps, methods as previous_methods
from .commented_facts import ppi_intersection, enrichment_sections
from .commented_documents import build_concise as previous_concise, tidy, replace_text
from .refined_documents import top_pairs
from .appendix_documents import APPENDIX, APPENDIX_TITLE

CONFIG = dict(base.CONFIG, schema_version="A07.report.config.25", template_version="A07.double_report.25", concise_target_pages=3)
PROTOCOLS = ("A06.automatic.1", "A06.automatic.2", "A06.automatic.3")
NOTE = "本批自动对接严格与探索范围分别记录；探索评分仅用于后续核验，不表示全部受体严格质控通过，也不能单独证明疗效或实测结合自由能。"


def packet_for(workflow, manifest, a06):
    """只使用当前A06显式登记的同研究包，不扫描其他研究或试算资料。"""
    run = workflow.run(manifest, a06)
    require(run["config"].get("schema_version") in PROTOCOLS, "报告未绑定自动对接协议")
    records = workflow.result(manifest, a06)["tables"].get("automatic_packet", [])
    require(len(records) == 1, "自动对接完整事实包缺失或重复")
    record = records[0]
    packet = read_json(verified_file(workflow.location(manifest["study_id"]), record))
    require(packet["study_id"] == manifest["study_id"] and packet["run_id"] == a06, "自动评分跨研究或运行")
    require(packet["schema_version"] == run["config"]["schema_version"], "自动评分协议不一致")
    expected = {(c["compound_id"], r["target_id"]) for c in packet["compounds"] for r in packet["receptors"]}
    keys = [(p["compound_id"], p["target_id"]) for p in packet["pairs"]]
    require(len(keys) == len(set(keys)) and set(keys) == expected, "自动对接矩阵缺项或重复")
    for pair in packet["pairs"]:
        require((isinstance(pair.get("score"), (int, float)) and pair["state"] == "completed") or (pair.get("score") is None and pair["state"] in ("NA", "failed")), "无效评分被填充")
    return packet, record


def matrix_rows(packet, names):
    """将真实完整组合投影为旧报告展示字段，不修改科学协议或记录。"""
    pairs = {(p["compound_id"], p["target_id"]): p for p in packet["pairs"]}
    return [dict(compound_id=c["compound_id"], compound_name=bilingual_label(names[c["compound_id"]]), **{
        r["symbol"]: pairs[(c["compound_id"], r["target_id"])]["score"] for r in packet["receptors"]
    }) for c in packet["compounds"]]


class FactsView:
    """为旧上游事实提取器提供真实准备表，避免旧病例私有路径回退。"""
    def __init__(self, workflow, packet):
        self.workflow, self.packet = workflow, packet

    def __getattr__(self, key):
        return getattr(self.workflow, key)

    def result(self, manifest, rid):
        result = self.workflow.result(manifest, rid)
        if rid != self.packet["run_id"]:
            return result
        result = deepcopy(result)
        result["tables"]["score_matrix"] = [dict(compound_id=c["compound_id"], compound_name=c.get("name", c["compound_id"]), **{r["symbol"]: None for r in self.packet["receptors"]}) for c in self.packet["compounds"]]
        result["tables"]["receptor_setup"] = [{
            "靶点基因": r["symbol"], "PDB ID": r.get("selected_candidate", {}).get("spec", {}).get("pdb_id", r.get("selected_candidate", {}).get("spec", {}).get("model_id", "未采用")),
            "蛋白链": r.get("selected_candidate", {}).get("spec", {}).get("author_chain", ""),
            "共晶参考配体": str(r.get("selected_candidate", {}).get("spec", {}).get("reference_ligand") or "无核定参考配体"),
            "搜索盒中心坐标": "详见本批逐区域归档", "搜索盒尺寸": "详见本批逐区域归档",
            "重对接RMSD（Å）": r.get("evidence", {}).get("top1_rmsd"), "质控状态": r.get("quality", "未通过"),
        } for r in self.packet["receptors"]]
        # 空矩阵仅抑制旧模板自行推导主要靶点；真实矩阵随后独立读取。
        result["tables"].pop("generic_docking", None)
        return result


def assemble_payload(workflow, manifest, parents, heatmap_metadata_record=None):
    """共享旧A03/A04/A05事实与排序，自动对接全部按本批真实数量解释。"""
    packet, record = packet_for(workflow, manifest, parents["A06"])
    payload = base.assemble_payload(FactsView(workflow, packet), manifest, parents, None)
    from modulea.core.automatic_experience import automatic_names
    names = automatic_names(workflow, manifest, packet, parents["A03"])
    payload.update(automatic_packet=packet, automatic_packet_source=record, compound_names=names,
                   compound_labels={cid: bilingual_label(value) for cid, value in names.items()},
                   docking_matrix=matrix_rows(packet, names), primary_targets=packet["primary_targets"],
                   _a05_home=str(workflow.location(manifest["study_id"])), receptor_setup_sources=[record])
    # 仅供冻结文档排版函数读取的列表键；不生成试算协议、批准或225格假数据。
    payload["trial_packet"] = packet
    a03 = payload["a03_tables"]["ranking"]
    ordered = sorted([r for r in a03 if r.get("main_rank") is not None and r.get("intersection_count", 0) > 0], key=lambda r: (-r["intersection_count"], r["compound_id"]))
    if len(ordered) > 10:
        ordered = [r for r in ordered if r["intersection_count"] >= ordered[9]["intersection_count"]]
    for target, source in zip(payload["a03_top10"], ordered):
        target["成分名称"] = bilingual_label(names[source["compound_id"]])
    a04 = workflow.result(manifest, parents["A04"])["tables"]
    intersection, top = ppi_intersection(a04)
    payload.update(ppi_report_intersection=top, ppi_report_intersection_count=len(intersection))
    receptors = {r["target_id"]: r for r in packet["receptors"]}
    payload["strong_pairs"] = [{"compound_id": p["compound_id"], "target_id": p["target_id"], "成分": payload["compound_labels"][p["compound_id"]], "受体": receptors[p["target_id"]]["symbol"], "结合能（kcal/mol）": p["score"]} for p in packet["pairs"] if p["state"] == "completed" and p["score"] <= -8]
    summary = packet["summary"]
    payload["automatic_summary_text"] = f"本批{len(packet['compounds'])}个成分×{len(receptors)}个受体，共{len(packet['pairs'])}组；有效评分{summary['成功组合数']}组，评分未通过或执行失败{summary['失败组合数']}组，准备未通过而无评分{summary['NA组合数']}组。"
    payload["conclusion_sections"] = [{"层次": "成分与靶点概览", "结论": "交集靶点覆盖排名前十成分为" + "、".join(r["成分名称"] for r in payload["a03_top10"]) + "。排名反映资料覆盖，不代表含量或药效。"}, {"层次": "PPI方向", "结论": f"Degree与BC/CC第二轮完整名单共有{len(intersection)}个交集靶点，按Degree前十及并列为" + "、".join(r["symbol"] for r in top) + "。"}] + enrichment_sections(payload["a05_display"]["tables"]) + [{"层次": "结构方向", "结论": payload["automatic_summary_text"] + NOTE}, {"层次": "后续研究", "结论": "优先核对同源姿势、结构和位点，再通过独立实验检验结合与功能。"}]
    payload["conclusion_draft"] = " ".join(r["结论"] for r in payload["conclusion_sections"])
    # 方法前五段沿用已核定来源，自动对接段独立生成，不沿用旧225组试算叙述。
    method_packet = deepcopy(packet)
    for receptor in method_packet["receptors"]:
        receptor.setdefault("mode", "unavailable")
    method_payload = dict(payload, trial_packet=method_packet)
    payload["report_methods"] = previous_methods(method_payload)[:5] + ["分子对接：" + payload["automatic_summary_text"] + f"采用本研究已确认的{packet['schema_version']}策略，严格共晶位点与探索位点分别留存；使用固定AutoDock Vina参数，直接引用原始计算及质控结果，本报告不重新计算。" + NOTE]
    payload["concise_methods"] = ["按本研究实际来源标准化并取交集", "PPI执行Degree及BC/CC独立两轮筛选", "GO三类与KEGG分别进行BH校正", f"自动对接引用本批{len(packet['pairs'])}组原始结果"]
    for count in payload["key_counts"]:
        if count["指标"] == "正式对接成功组合数":
            count["指标"], count["数值"] = "自动对接有效评分组合数", summary["成功组合数"]
    payload["key_counts"].extend([{"指标": "评分未通过或执行失败组合数", "数值": summary["失败组合数"]}, {"指标": "准备未通过组合数", "数值": summary["NA组合数"]}])
    payload["heatmap_display"] = {"compounds": min(5, len(packet["compounds"])), "receptors": min(8, len(receptors))}
    payload["heatmap_display_note"] = "同批重点图与完整矩阵使用相同原评分范围，缺失保留NA。"
    payload["docking_reuse_text"] = "报告引用本批既有自动对接结果，未重新运行Vina。"
    payload["limitations"][-1] = NOTE
    align_research_leads(payload)
    payload["ranked_pathway_maps"] = report_maps(workflow, manifest, parents["A05"])
    return payload


def align_research_leads(payload):
    """线索与已确认A05展示范围同源，不从完整统计恢复已排除疾病通路。"""
    tables = payload["a05_display"]["tables"]
    rows = tables["bp_graph8"][:2] + tables["kegg_graph15"][:2]
    for lead in payload["research_leads"]:
        if "功能" in lead["线索"] or "通路" in lead["线索"]:
            lead["支持事实"] = "当前已确认展示范围：" + "；".join(
                r["ID"] + " " + (r.get("description_zh") or r["Description"]) for r in rows
            )


def add_appendix(document, payload):
    """统一两份报告的术语解释，完整矩阵规模与异常均取当前批次。"""
    from docx.shared import Pt
    before = len(document.paragraphs)
    heading = document.add_heading(APPENDIX_TITLE, 1)
    heading.paragraph_format.page_break_before = True
    for title, text in APPENDIX:
        if title == "热图与评分标记":
            text = text.replace("225格", f"{len(payload['automatic_packet']['pairs'])}格")
        document.add_heading(title, 2)
        document.add_paragraph(text)
    document.add_heading("本批计算范围与异常", 2)
    document.add_paragraph(payload["automatic_summary_text"] + NOTE)
    receptors = {r["target_id"]: r for r in payload["automatic_packet"]["receptors"]}
    groups = {}
    for p in payload["automatic_packet"]["pairs"]:
        if p["state"] != "completed":
            regional = list(dict.fromkeys(r.get("reason_zh", "") for r in p.get("regions", []) if r.get("reason_zh")))
            reason = "；".join(regional) or p["reason_zh"]
            groups.setdefault((p["target_id"], reason), []).append(p["compound_id"])
    for (target, reason), compounds in groups.items():
        prefix = f"本批全部{len(compounds)}个成分" if len(compounds) == len(payload["automatic_packet"]["compounds"]) else "、".join(payload["compound_labels"][cid] for cid in compounds)
        document.add_paragraph(prefix + "—" + receptors[target]["symbol"] + "：NA；" + reason)
    for p in document.paragraphs[before + 1:]:
        p.paragraph_format.space_before = Pt(3) if p.style.name.startswith("Heading") else Pt(0)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.05
        for run in p.runs:
            run.font.size = Pt(10 if p.style.name.startswith("Heading") else 9)


def build_detailed(payload, destination, root, revision):
    """保留已确认的上游模板，仅将A06章节换成动态同批评分及附录。"""
    from docx import Document
    from docx.shared import Cm
    from report_flow_pathway import _table
    from .commented_documents import clear_between, append_before
    from science_modules.a06.trial_presentation import score_label
    base.build_detailed(payload, destination, root, revision)
    doc = Document(destination)
    start = next(p for p in doc.paragraphs if p.text == "6 分子对接结果")
    stop = next(p for p in doc.paragraphs if p.text == "7 待进一步核验的研究线索")
    clear_between(start, stop)
    def docking():
        doc.add_paragraph(payload["automatic_summary_text"] + NOTE)
        p = doc.add_paragraph()
        p.add_run().add_picture(str(verified_file(root, payload["heatmap_png"])), width=Cm(15.8))
        doc.add_paragraph("图 A06 01 重点原始Vina评分热图，单位kcal/mol。")
        doc.add_paragraph("表 A06 01 完整同批评分矩阵")
        # 受体超过8个时按列拆表，避免5×16表挤压标签；仍完整保留全部格。
        receptors = payload["automatic_packet"]["receptors"]
        for offset in range(0, len(receptors), 8):
            part = receptors[offset:offset + 8]
            headers = ["成分"] + [r["symbol"] for r in part]
            rows = [{"成分": row["compound_name"], **{r["symbol"]: score_label(row[r["symbol"]], mark=True) for r in part}} for row in payload["docking_matrix"]]
            _table(doc, rows, headers, [5.0] + [12.0 / len(part)] * len(part), font_size=7)
    append_before(doc, stop._p, docking)
    doc.save(destination)
    # 冻结修改器仅查找一张完整表，故单独应用其上游富集/摘要功能时临时矩阵需避免。
    # 使用局部函数绑定禁用该单表断言并不安全；此处新版本直接整理A05与首页。
    from .commented_documents import add_ranked_maps
    from science_modules.a05.compact_report_section import add_graph, add_table, GO_COLUMNS, KEGG_COLUMNS, GO_CAPTION, KEGG_CAPTION
    from science_modules.a05.compact_display import go_rows, kegg_rows
    h5 = next(p for p in doc.paragraphs if p.text == "5 GO与KEGG富集结果")
    boundary = clear_between(h5, start)
    def enrichment():
        tables = payload["a05_display"]["tables"]
        doc.add_heading("GO富集结果", 2)
        add_graph(doc, tables, root, "go", GO_CAPTION)
        for i, (group, name) in enumerate((("BP", "生物过程"), ("CC", "细胞组分"), ("MF", "分子功能")), 1):
            add_table(doc, f"表 A05 0{i} GO {group} {name}前十五", go_rows(tables, group), GO_COLUMNS, [8.1, 5.5, 3.4])
        doc.add_heading("KEGG富集结果", 2)
        add_graph(doc, tables, root, "kegg", KEGG_CAPTION)
        for i, (key, label) in enumerate((("kegg_p_top10", "统计显著性"), ("kegg_count_top10", "命中基因数")), 4):
            add_table(doc, f"表 A05 0{i} KEGG{label}前十", kegg_rows(tables, key), KEGG_COLUMNS, [7, 4.7, 1.4, 3.9])
        add_ranked_maps(doc, payload, root)
        if payload.get("selected_pathway"):
            from report_pathway import add_selected_pathway
            from report_flow_pathway import _font
            add_selected_pathway(doc, payload, root, _font)
    append_before(doc, boundary if boundary is not None else start._p, enrichment)
    for p in doc.paragraphs:
        for method in payload["report_methods"]:
            if p.text.startswith(method.split("：", 1)[0] + "："):
                replace_text(p, method)
        if p.text == "9 复核与追溯":
            replace_text(p, "9 结果复核说明")
    # 旧第23版精简器的结构块由其前置标记界定；本版自行生成前十表。
    for p in doc.paragraphs:
        if p.text.startswith("结构方向："):
            selected = top_pairs(payload["strong_pairs"])
            replace_text(p, "结构方向：" + payload["automatic_summary_text"] + f"其中原始评分≤−8 kcal/mol的组合{len(payload['strong_pairs'])}组，以下仅列前{len(selected)}组。")
            if selected:
                rows = [{"序号": i, "成分": r["成分"], "受体": r["受体"], "Vina评分（kcal/mol）": f"{r['结合能（kcal/mol）']:.2f}"} for i, r in enumerate(selected, 1)]
                _table(doc, rows, ["序号", "成分", "受体", "Vina评分（kcal/mol）"], [1, 10, 2, 4], font_size=9)
                p._p.addnext(doc.tables[-1]._tbl)
    removing = False
    for p in list(doc.paragraphs):
        if p.text == "8 主要限制":
            removing = True
        elif removing and p.style.name == "Heading 1":
            removing = False
        if removing:
            p._p.getparent().remove(p._p)
        elif p.text == "9 结果复核说明":
            replace_text(p, "8 结果复核说明")
        elif p.text == "10 主要方法参考文献":
            replace_text(p, "9 主要方法参考文献")
    finish_document(doc, payload)
    doc.save(destination)


def finish_document(doc, payload):
    """术语只进附录，展示数量不保留旧8×8、15×15及225组常量。"""
    from .appendix_documents import revise_body
    revise_body(doc, False)
    for p in doc.paragraphs:
        if p.text.startswith(("图 A06 01", "图 重点8×8")):
            replace_text(p, f"图 A06 01 重点{payload['heatmap_display']['compounds']}×{payload['heatmap_display']['receptors']}原始Vina评分热图，单位kcal/mol。")
        if "本批为已确认的扩展试算" in p.text:
            replace_text(p, NOTE)
    add_appendix(doc, payload)
    tidy(doc)


def build_concise(payload, destination, root, revision):
    """简报保持原两页正文与统一末尾附录，解释范围按自动批次重新标明。"""
    from docx import Document
    from science_modules.a06.trial_handoff import NOTE as OLD_NOTE
    concise_payload = dict(payload, key_counts=payload["key_counts"][:3] + [next(r for r in payload["key_counts"] if r["指标"] == "自动对接有效评分组合数")])
    previous_concise(concise_payload, destination, root, revision)
    doc = Document(destination)
    for p in doc.paragraphs:
        if OLD_NOTE in p.text:
            replace_text(p, p.text.replace(OLD_NOTE, NOTE))
        if p.text.startswith("本批") and "受体及中英文成分完整清单见专业版" in p.text:
            replace_text(p, payload["automatic_summary_text"] + "完整评分及前十组见专业版。")
    finish_document(doc, payload)
    doc.save(destination)


def require_alignment(workflow, manifest, run):
    """报告复核前核对当前评分、展示、来源名称和两种排名图，禁止沿用旧决定。"""
    packet, record = packet_for(workflow, manifest, run["parent_runs"]["A06"])
    require(run["inputs"]["a06_automatic_packet"] == record, "自动评分来源改变，请重新生成报告")
    maps = report_maps(workflow, manifest, run["parent_runs"]["A05"])
    require(run["inputs"]["a05_ranked_maps"] == maps["record"], "排名通路图改变，请重新生成报告")
    require(run["inputs"].get("a06_automatic_display") == display_for(manifest, packet["run_id"]), "自动图表展示已改变，请重新生成报告")
    for record in run["inputs"]["compound_name_sources"]:
        verified_file(workflow.location(manifest["study_id"]), record)


def display_for(manifest, a06):
    """展示修订按本研究本运行最新明确账本选择，不按文件时间猜测。"""
    return next((deepcopy(r) for r in reversed(manifest.get("automatic_displays", [])) if r["a06_run"] == a06), None)


def run_reports(workflow, study_id, expected_a07, reason, **kwargs):
    """七个上游独立批准后才追加第25版双报告，停在A07而不代签。"""
    from docx import Document
    from science_modules.a06.automatic_exports import build_view, export
    from report_dispatch import selected_record
    required = ("A00", "A01", "A02", "A03", "A04", "A05", "A06")
    with write_lock(workflow.root):
        manifest = workflow.load(study_id)
        require(not manifest.get("trashed"), "回收站研究只读")
        require(manifest["current"].get("A07", "") == expected_a07, "报告版本已改变，请刷新")
        require(all(manifest["current"].get(m) and workflow.approved(manifest, manifest["current"][m]) for m in required), "请先完成所有上游及A06独立复核")
        require(all(workflow.active(manifest, manifest["current"][m]) for m in required), "上游已有更新，请先更新结果")
        parents = {m: manifest["current"][m] for m in required}
        payload = assemble_payload(workflow, manifest, parents)
        home = workflow.location(study_id)
        names = payload["compound_names"]
        evidence = {r["path"]: r for value in names.values() for r in value["evidence"]}
        inputs = dict(a06_automatic_packet=payload["automatic_packet_source"], a05_display_source=manifest["runs"][parents["A05"]]["result_file"], a05_ranked_maps=payload["ranked_pathway_maps"]["record"], compound_name_sources=list(evidence.values()), selected_pathway_metadata=selected_record(workflow, manifest))
        inputs["a06_automatic_display"] = display_for(manifest, parents["A06"])
        run = workflow._begin(manifest, "A07", inputs, dict(CONFIG), reason)
        revision = "report_rev_" + run["run_id"].removeprefix("run_")
        folder = home / "reports" / revision
        folder.mkdir(parents=True, exist_ok=False)
        display = inputs["a06_automatic_display"]
        if display:
            require(display["packet"] == inputs["a06_automatic_packet"], "图表展示不是本批原评分")
            for record in [display["view"]] + display["files"]:
                verified_file(home, record)
            cs, rs = display["selection"]["compound_ids"], display["selection"]["target_ids"]
        else:
            cs, rs = [c["compound_id"] for c in payload["automatic_packet"]["compounds"][:5]], [r["target_id"] for r in payload["automatic_packet"]["receptors"][:8]]
        view = build_view(payload["automatic_packet"], names=names, selected_compounds=cs, selected_targets=rs)
        payload["heatmap_display"] = {"compounds": len(cs), "receptors": len(rs)}
        paths = base.generate_report_figures(folder / "figures", payload)
        exports = export(view, folder / "figures" / "automatic", include_notes=False)
        png = exports["heatmap_png"]
        payload["heatmap_png"] = file_record(home, png, "a06_automatic_heatmap_png")
        keys = {"venn": "01_方剂疾病靶点韦恩图", "herb_compound_target": "02_药味成分交集靶点网络图", "ppi_full": "03_PPI完整网络图", "ppi_round1": "04_PPI_Degree第二轮候选网络图", "go_faceted": "05_GO富集三分类柱状图", "kegg_bubble": "06_KEGG富集气泡图"}
        payload["report_figures"] = {key: {kind: file_record(home, paths[name][kind], key + "_" + kind) for kind in ("svg", "png")} for key, name in keys.items()}
        payload["comparison_report_included"] = False
        from report_pathway import attach_report_pathway
        pathway_sources = attach_report_pathway(workflow, manifest, payload, folder, inputs["selected_pathway_metadata"])
        ranked_figures = []
        for item in payload["ranked_pathway_maps"]["items"]:
            source = verified_file(home, item["png"])
            path = folder / "figures" / ("KEGG_" + item["ranking"] + "_" + item["id"] + ".png")
            path.write_bytes(source.read_bytes())
            item["png"] = file_record(home, path, "kegg_ranked_" + item["ranking"] + "_png")
            ranked_figures.append(item["png"])
        detail, concise = folder / "ModuleA_专业详细报告.docx", folder / "ModuleA_临床简略报告.docx"
        build_detailed(payload, detail, home, revision)
        build_concise(payload, concise, home, revision)
        figures = [r for formats in payload["report_figures"].values() for r in formats.values()] + [file_record(home, path, "automatic_export_" + key) for key, path in exports.items()] + ranked_figures
        if payload.get("selected_pathway"):
            figures.append(payload["selected_pathway"]["report_figure"])
        index = dict(schema_version="A07.report.index.4", study_id=study_id, run_id=run["run_id"], template_version=CONFIG["template_version"], parent_runs=run["parent_runs"], source_protocol=payload["automatic_packet"]["schema_version"], automatic_packet=inputs["a06_automatic_packet"], figures=figures, ranked_pathway_maps=inputs["a05_ranked_maps"], comparison_report=None, scientific_approval=False)
        write_json(folder / "report_index.json", index)
        files = [file_record(home, detail, "detailed_report"), file_record(home, concise, "concise_report"), file_record(home, folder / "report_index.json", "report_index")]
        summary = dict(analysis_purpose=payload["analysis_purpose"], 报告修订=revision, 详细报告=detail.name, 简略报告=concise.name, 共同结论草稿=payload["conclusion_draft"], 研究线索数=len(payload["research_leads"]), 结论复核状态="待专业复核", handoff_blocked=False)
        tables = dict(key_counts=payload["key_counts"], research_leads=payload["research_leads"], limitations=[{"限制": x} for x in payload["limitations"]], report_files=files, report_figures=figures, version_bindings=[{"模块": m, "运行编号": rid, "复核编号": run["parent_review_ids"][m]} for m, rid in run["parent_runs"].items()])
        sources = [manifest["runs"][rid]["result_file"] for rid in parents.values()] + [inputs["a06_automatic_packet"], inputs["a05_display_source"]] + list(evidence.values()) + ([inputs["a05_ranked_maps"]] if inputs["a05_ranked_maps"] else []) + pathway_sources
        result = workflow._finish(manifest, run["run_id"], summary, tables, payload["limitations"], "success", sources=sources, attachments=files + figures)
        workflow.save(manifest)
        return result


def validate_matrix(document, packet):
    """逐格检查完整矩阵，允许宽表分列但不允许重复、遗漏或用零代NA。"""
    from science_modules.a06.trial_presentation import score_label
    expected = {(p["compound_id"], p["target_id"]): score_label(p["score"], mark=True) for p in packet["pairs"]}
    actual = {}
    symbols = {r["symbol"]: r["target_id"] for r in packet["receptors"]}
    matrices = [t for t in document.tables if t.rows[0].cells[0].text == "成分" and all(c.text in symbols for c in t.rows[0].cells[1:])]
    for table in matrices:
        require(len(table.rows) == len(packet["compounds"]) + 1, "完整评分矩阵行缺失")
        for compound, row in zip(packet["compounds"], table.rows[1:]):
            for head, cell in zip(table.rows[0].cells[1:], row.cells[1:]):
                key = (compound["compound_id"], symbols[head.text])
                require(key not in actual, "完整评分矩阵重复格")
                actual[key] = cell.text
    require(actual == expected, "报告完整矩阵与原始评分不一致")


def validator(root, previous):
    """独立检查动态完整矩阵与同源绑定，旧报告仍交原冻结校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("schema_version") != CONFIG["schema_version"]:
            return previous(run, summary, tables, anomalies, outcome)
        from docx import Document
        from science_modules.a05.compact_report_section import validate_section
        home = Path(root) / "studies" / run["study_id"]
        packet = read_json(verified_file(home, run["inputs"]["a06_automatic_packet"]))
        require(run["config"] == CONFIG and packet["schema_version"] in PROTOCOLS and packet["study_id"] == run["study_id"] and packet["run_id"] == run["parent_runs"]["A06"], "自动报告研究、协议或版本绑定错误")
        manifest = read_json(home / "manifest.json")
        parent_result = read_json(verified_file(home, manifest["runs"][run["parent_runs"]["A06"]]["result_file"]))
        require(parent_result["tables"]["automatic_packet"] == [run["inputs"]["a06_automatic_packet"]], "报告原评分来源被替换")
        for record in tables["report_files"] + tables["report_figures"] + run["inputs"]["compound_name_sources"]:
            verified_file(home, record)
        docs = {r["role"]: Document(verified_file(home, r)) for r in tables["report_files"] if r["role"] in ("detailed_report", "concise_report")}
        require(set(docs) == {"detailed_report", "concise_report"}, "双报告缺失")
        require(run["inputs"]["a05_display_source"] == manifest["runs"][run["parent_runs"]["A05"]]["result_file"], "报告富集来源跨运行")
        a05 = read_json(verified_file(home, run["inputs"]["a05_display_source"]))
        maps = run["inputs"]["a05_ranked_maps"]
        if maps:
            data = read_json(verified_file(home, maps))
            require(data["binding"]["a05_run"] == run["parent_runs"]["A05"] and data["binding"]["result"] == run["inputs"]["a05_display_source"], "报告排名图跨版本")
            for record in data["files"]:
                verified_file(home, record)
        else:
            require(not a05["tables"]["kegg_p_top10"] and not a05["tables"]["kegg_count_top10"], "显著KEGG缺少两张排名图")
        validate_section(docs["detailed_report"], a05["tables"])
        validate_matrix(docs["detailed_report"], packet)
        for document in docs.values():
            text = "\n".join(p.text for p in document.paragraphs)
            require(APPENDIX_TITLE in text and NOTE in text, "报告缺少统一附录或解释范围")
            require("225" not in text and "15×15" not in text and "8×8" not in text, "报告残留旧固定规模")
        require(summary["handoff_blocked"] is False and outcome == "success", "自动报告发布状态错误")
    return check
