"""A07第22版：用户批注确认后的同源结论、双语展示与排名通路图。"""

from copy import deepcopy
from pathlib import Path
from types import FunctionType
from contracts import require
from storage import file_record, read_json, verified_file, write_json
from modulea.core.compound_names import compound_names, bilingual_label
from modulea.core.source_catalog import SOURCE_LABELS
from science_modules.a06.bilingual_heatmap import matrix, export_heatmap
from science_modules.a06.trial_handoff import NOTE
from science_modules.a06.trial_presentation import score_label
from . import trial_reports as previous
from .commented_facts import (
    degree_top,
    ppi_intersection,
    enrichment_sections,
    strong_pairs,
    pair_summary,
)
from .commented_documents import revise_detailed, build_concise, INTERNAL_ID

CONFIG = dict(
    previous.CONFIG, schema_version="A07.report.config.22", template_version="A07.double_report.22"
)


def report_maps(workflow, manifest, a05):
    """无显著KEGG时明确不补图；有排名时必须先准备本次同源图。"""
    maps = workflow.ranked_maps_for(manifest, a05)
    if maps is not None:
        return maps
    tables = workflow.result(manifest, a05)["tables"]
    require(
        not tables["kegg_p_top10"] and not tables["kegg_count_top10"],
        "请先生成当前A05两张排名第一通路命中图",
    )
    return {"items": [], "record": None}


def methods(payload):
    """如实叙述已经采用的输入及获准扩展策略，未重新计算不替代方法说明。"""
    labels = "、".join(SOURCE_LABELS.get(x, x) for x in payload["a01_databases"])
    a01 = (
        "成分与方剂靶点：从"
        + labels
        + "读取成分及已有成分—人类靶点关系。TCMSP采用口服生物利用度OB≥30%及类药性DL≥0.18筛选；HERB和BATMAN-TCM不使用上述阈值淘汰。完整InChIKey是化学结构的标准身份标识，跨库合并要求完整标识一致且分子式无冲突，并按HGNC统一基因身份。"
    )
    if len(payload["a01_databases"]) == 1:
        a01 = "成分与方剂靶点：读取TCMSP来源成分及靶点，以OB≥30%和DL≥0.18筛选；按HGNC统一人类基因身份。完整InChIKey是化学结构的标准身份标识，不能当作活性评分。"
    a02 = (
        "疾病靶点：按当前研究配置检索并整合"
        + "、".join(SOURCE_LABELS.get(x, x) for x in payload["a02_databases"])
        + "，保留来源原始评分并统一人类基因身份。实际采集状态为"
        + payload["disease_source_status"]
        + "。"
        + (payload.get("source_exception_text") or "")
    )
    ppi = "PPI：将方剂—疾病交集靶点输入STRING 12.0，使用人类9606的功能关联网络，保留置信度≥0.9的关系，不增加外部节点。全部合格有边分量参与完整网络Degree、Betweenness和Closeness计算；Degree第一轮阈值为全网中位数的2倍，第二轮为本分支第一轮中位数。BC与CC两轮均须同时严格高于对应总体中位数，第二轮不重建网络；结论交集取两分支第二轮完整名单，再按Degree取前十及边界并列。"
    enrichment = "富集：使用固定版本clusterProfiler进行过度代表分析（ORA），比较交集输入基因在条目中的命中比例是否高于本次注释背景。基因集大小为10—500；采用Benjamini–Hochberg（BH）方法校正多重比较产生的P值，GO的BP、CC、MF分别校正，KEGG单独校正，以校正后P值<0.05为主要显著性标准。统计显著性排名按该P值升序，命中规模排名按Count降序。"
    packet = payload["trial_packet"]
    modes = packet["receptors"]
    counts = {
        name: sum(r["mode"] == name for r in modes)
        for name in ("fixed_site", "predicted_sites", "partitioned_blind")
    }
    docking = (
        f"分子对接：从PubChem取得并核对{len(packet['compounds'])}个成分的三维结构，以已核查的RCSB PDB实验结构或可解析功能域作为{len(modes)}个受体输入。经既定补氢、配体准备及有限侧链修补后生成PDBQT；保留原解析重原子坐标，不重建缺失主链。AutoDock Vina 1.2.7以exhaustiveness=8、最多9个姿势、energy_range=3、seed=1运行。{counts['fixed_site']}个受体使用预先固定共晶位点，{counts['predicted_sites']}个使用预先固定预测位点集合，{counts['partitioned_blind']}个使用获准分区盲搜；多区域取各区域Top-1中最低评分，保留所有区域与姿势。报告直接引用该批既有评分，没有重新对接。"
        + NOTE
    )
    return [
        a01,
        a02,
        "交集与候选：计算标准化方剂靶点与疾病靶点交集，按成分关联的不同交集靶点数排序，前十保留边界并列。该展示排名不替代已人工确认的对接成分及A/B受体来源。",
        ppi,
        enrichment,
        docking,
    ]


def assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record=None):
    """两份报告共用一份事实包，排名、评分和译名均从同源归档读取。"""
    payload = previous.assemble_payload(workflow, manifest, parent_runs, None)
    names = compound_names(workflow, manifest, parent_runs["A03"], payload["trial_packet"])
    payload["compound_names"] = names
    payload["compound_labels"] = {cid: bilingual_label(name) for cid, name in names.items()}
    a03 = payload["a03_tables"]["ranking"]
    # 先按原排序列选定稳定ID，再替换展示名称，不以文本名连接科学对象。
    ordered = sorted(
        [r for r in a03 if r.get("main_rank") is not None and r.get("intersection_count", 0) > 0],
        key=lambda r: (-r["intersection_count"], r["compound_id"]),
    )
    if len(ordered) > 10:
        ordered = [
            r for r in ordered if r["intersection_count"] >= ordered[9]["intersection_count"]
        ]
    for target, source in zip(payload["a03_top10"], ordered):
        require(source["compound_id"] in names, "A03前十成分缺少同源名称")
        target["成分名称"] = bilingual_label(names[source["compound_id"]])
    a04 = workflow.result(manifest, parent_runs["A04"])["tables"]
    intersection, top = ppi_intersection(a04)
    payload["ppi_report_intersection"] = top
    payload["ppi_report_intersection_count"] = len(intersection)
    payload["strong_pairs"] = strong_pairs(payload["trial_packet"], names)
    prefix = [
        {
            "层次": "成分与靶点概览",
            "结论": "交集靶点覆盖排名前十成分为"
            + "、".join(r["成分名称"] for r in payload["a03_top10"])
            + "；PPI第二轮Degree前十靶点为"
            + "、".join(r["symbol"] for r in degree_top(a04["degree_round2"]))
            + "。排名反映现有资料覆盖与网络连接，不能直接解释为含量或药效。",
        },
        {
            "层次": "PPI方向",
            "结论": f"Degree与BC/CC第二轮完整名单共有{len(intersection)}个交集靶点，其中按Degree排序前十（含边界并列）为"
            + "、".join(r["symbol"] for r in top)
            + "。该报告展示不改变已确认A/B对接候选。",
        },
    ]
    payload["conclusion_sections"] = (
        prefix
        + enrichment_sections(payload["a05_display"]["tables"])
        + [
            {"层次": "结构方向", "结论": pair_summary(payload["strong_pairs"])},
            {
                "层次": "后续研究",
                "结论": "依据同源姿势和本批结构范围逐项核验候选，并通过独立实验检验结合与功能；富集不表示通路已被激活或抑制。",
            },
        ]
    )
    payload["conclusion_draft"] = " ".join(row["结论"] for row in payload["conclusion_sections"])
    maps = report_maps(workflow, manifest, parent_runs["A05"])
    payload["ranked_pathway_maps"] = maps
    payload["report_methods"] = methods(payload)
    payload["concise_methods"] = [
        "多库整合成分及人类靶点，按标准化基因取方剂—疾病交集",
        "STRING高置信度PPI执行Degree及BC/CC两轮筛选",
        "ORA检验过度代表，BH校正多重比较，GO各类和KEGG分别校正",
        "AutoDock Vina 1.2.7采用已确认结构与位点策略，引用既有225组扩展评分",
    ]
    payload["heatmap_display_note"] = (
        "同批重点成分行、受体列；色标取完整15×15有效范围。完整矩阵见专业版。"
    )
    payload["_reusable_figures"] = getattr(workflow, "reusable_figures", {})
    return payload


def generate_report_figures(directory, payload):
    """原图保留科学表源；新版热图和通路图只写入本次独立报告目录。"""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    reusable = payload.get("_reusable_figures", {})
    if reusable:
        paths = {}
        root = Path(payload["_a05_home"])
        for name, formats in reusable.items():
            paths[name] = {}
            for kind, record in formats.items():
                copy = folder / Path(record["path"]).name
                copy.write_bytes(verified_file(root, record).read_bytes())
                paths[name][kind] = copy
    else:
        paths = previous.previous.generate_report_figures(directory, payload)
    output = export_heatmap(matrix(payload["trial_packet"], payload["compound_names"]), folder)
    root = Path(payload["_a05_home"])
    payload["heatmap_png"] = file_record(root, output["png"], "a06_bilingual_heatmap_png")
    payload["_extra_figures"] = [
        file_record(root, path, "a06_bilingual_heatmap_" + kind) for kind, path in output.items()
    ]
    for item in payload["ranked_pathway_maps"]["items"]:
        source = verified_file(root, item["png"])
        copy = folder / ("KEGG_" + item["ranking"] + "_" + item["id"] + "_命中图.png")
        copy.write_bytes(source.read_bytes())
        payload["_extra_figures"].append(
            file_record(root, copy, "kegg_ranked_" + item["ranking"] + "_png")
        )
        item["png"] = payload["_extra_figures"][-1]
    return paths


def build_detailed(payload, destination, root, revision):
    """继续使用既有文档骨架，批注修改在新协议独立实施。"""
    previous.build_detailed(payload, destination, root, revision)
    revise_detailed(destination, payload, root)


class ReportView(previous.ReportView):
    def _begin(self, manifest, module, inputs, config, reason):
        self.reusable_figures = {}
        prior = manifest["current"].get("A07")
        if prior and self.workflow.active(manifest, prior):
            source = self.workflow.run(manifest, prior)
            parents = {key: manifest["current"].get(key) for key in source.get("parent_runs", {})}
            if source.get("parent_runs") == parents and source.get("config", {}).get(
                "template_version"
            ) in ("A07.double_report.21", "A07.double_report.22"):
                figures = self.workflow.result(manifest, prior)["tables"]["report_figures"]
                for record in figures:
                    if record["role"].removesuffix("_png").removesuffix("_svg") not in {
                        "venn",
                        "herb_compound_target",
                        "ppi_full",
                        "ppi_round1",
                        "go_faceted",
                        "kegg_bubble",
                    }:
                        continue
                    name = Path(record["path"]).stem
                    self.reusable_figures.setdefault(name, {})[Path(record["path"]).suffix[1:]] = (
                        record
                    )
        maps = report_maps(self.workflow, manifest, manifest["current"]["A05"])
        packet = previous.packet_for(self.workflow, manifest, manifest["current"]["A06"])
        names = compound_names(self.workflow, manifest, manifest["current"]["A03"], packet)
        evidence = {r["path"]: r for item in names.values() for r in item["evidence"]}
        inputs = dict(
            inputs, a05_ranked_maps=maps["record"], compound_name_sources=list(evidence.values())
        )
        return super()._begin(manifest, module, inputs, config, reason)

    def _finish(self, manifest, rid, summary, tables, anomalies, outcome, **kwargs):
        """发布前将新增图件写入本次尚未归档的索引并复算其指纹。"""
        root = self.workflow.location(manifest["study_id"])
        old = next(r for r in tables["report_files"] if r["role"] == "report_index")
        index_path = verified_file(root, old)
        index = read_json(index_path)
        figures = list(index["figures"])
        # 新报告目录扫描仅限明确定义的新增文件，禁止扫描任意历史目录。
        folder = index_path.parent / "figures"
        for path in sorted(folder.iterdir()):
            if path.name.startswith(("A06_01_中英重点", "KEGG_")) and path.suffix.lower() in (
                ".png",
                ".svg",
            ):
                role = (
                    "a06_bilingual_heatmap_" + path.suffix[1:]
                    if path.name.startswith("A06")
                    else "kegg_ranked_" + path.stem.removeprefix("KEGG_").split("_hsa")[0] + "_png"
                )
                figures.append(file_record(root, path, role))
        original_figures = index["figures"]
        index["figures"] = figures
        inputs = self.workflow.run(manifest, rid)["inputs"]
        index["ranked_pathway_maps"] = inputs["a05_ranked_maps"]
        index["compound_name_sources"] = inputs["compound_name_sources"]
        write_json(index_path, index, replace=True)
        replacement = file_record(root, index_path, "report_index")
        tables["report_files"] = [
            replacement if r["role"] == "report_index" else r for r in tables["report_files"]
        ]
        tables["report_figures"] = figures
        kwargs["attachments"] = [
            replacement if r["role"] == "report_index" else r for r in kwargs.get("attachments", [])
        ] + [r for r in figures if r not in original_figures]
        kwargs["sources"] = (
            kwargs.get("sources", [])
            + ([inputs["a05_ranked_maps"]] if inputs["a05_ranked_maps"] else [])
            + inputs["compound_name_sources"]
        )
        return self.workflow._finish(manifest, rid, summary, tables, anomalies, outcome, **kwargs)


def run_reports(workflow, study_id, expected_a07, reason, **kwargs):
    """既有锁与发布流程复用，不允许模板变更时复用旧简略报告。"""
    kwargs["reuse_current_concise"] = False
    scope = dict(
        vars(previous.base),
        CONFIG=CONFIG,
        assemble_payload=assemble_payload,
        build_detailed=build_detailed,
        build_concise=build_concise,
        generate_report_figures=generate_report_figures,
        report_heatmap_record=lambda *_: None,
    )
    generate = FunctionType(
        previous.base.run_reports.__code__,
        scope,
        previous.base.run_reports.__name__,
        previous.base.run_reports.__defaults__,
    )
    with workflow.handoff_read_cache():
        return generate(ReportView(workflow), study_id, expected_a07, reason, **kwargs)


def validator(root, old):
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("schema_version") != CONFIG["schema_version"]:
            return old(run, summary, tables, anomalies, outcome)
        from docx import Document
        from science_modules.a05.compact_report_section import validate_section

        home = Path(root) / "studies" / run["study_id"]
        for record in tables["report_files"] + tables["report_figures"]:
            verified_file(home, record)
        packet = read_json(verified_file(home, run["inputs"]["a06_trial_packet"]))
        maps = (
            read_json(verified_file(home, run["inputs"]["a05_ranked_maps"]))
            if run["inputs"]["a05_ranked_maps"]
            else None
        )
        for record in run["inputs"]["compound_name_sources"]:
            verified_file(home, record)
        manifest = read_json(home / "manifest.json")
        parent = read_json(
            verified_file(home, manifest["runs"][run["parent_runs"]["A06"]]["run_file"])
        )
        require(
            parent["inputs"]["trial_packet"] == run["inputs"]["a06_trial_packet"]
            and parent["inputs"]["trial_review"] == run["inputs"]["a06_trial_review"],
            "报告未绑定已批准的A06同批原件",
        )
        require(
            packet["study_id"] == run["study_id"] and run["config"] == CONFIG,
            "报告研究或配置不一致",
        )
        if maps:
            require(
                maps["binding"]["a05_run"] == run["parent_runs"]["A05"]
                and maps["binding"]["result"] == run["inputs"]["a05_display_source"],
                "排名通路图绑定了不同A05",
            )
            for record in maps["files"]:
                verified_file(home, record)
        reports = {
            r["role"]: Document(verified_file(home, r))
            for r in tables["report_files"]
            if r["role"] in ("detailed_report", "concise_report")
        }
        require(set(reports) == {"detailed_report", "concise_report"}, "双报告缺失")
        detail = reports["detailed_report"]
        a05 = read_json(verified_file(home, run["inputs"]["a05_display_source"]))
        if maps is None:
            require(
                not a05["tables"]["kegg_p_top10"] and not a05["tables"]["kegg_count_top10"],
                "显著KEGG结果不能缺少排名通路图",
            )
        validate_section(detail, a05["tables"])
        matrix_tables = [t for t in detail.tables if len(t.columns) == len(packet["receptors"]) + 1]
        require(len(matrix_tables) == 1, "完整同批矩阵缺失")
        scores = {(p["compound_id"], p["target_id"]): p for p in packet["pairs"]}
        expected = [
            [
                score_label(scores[(c["compound_id"], r["target_id"])]["score"], mark=True)
                for r in packet["receptors"]
            ]
            for c in packet["compounds"]
        ]
        require(
            [[cell.text for cell in row.cells[1:]] for row in matrix_tables[0].rows[1:]]
            == expected,
            "报告225格评分不一致",
        )
        for doc in reports.values():
            text = (
                "\n".join(p.text for p in doc.paragraphs)
                + "\n"
                + "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
            )
            require(not INTERNAL_ID.search(text), "报告仍含内部版本编号")
            require(NOTE in text, "报告缺少扩展试算解释范围")
            require("受体结构与处理范围" not in text, "报告未删除长篇处理段落")
        require(summary["handoff_blocked"] is False, "报告不应隐式批准或阻塞")

    return check
