"""A07第23版：按最终模板反馈精简列表、去重正文并修复图表排版。"""

from pathlib import Path

from contracts import require
from storage import read_json, verified_file
from . import commented_reports as previous
from .refined_documents import top_pairs, revise_file, revise_concise
from .report_heatmap import bind, export_heatmap

CONFIG = dict(
    previous.CONFIG,
    schema_version="A07.report.config.23",
    template_version="A07.double_report.23",
)


def assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record=None):
    """全部225原评分不变，结构结论仅保留前十展示；富集摘要保持原范围。"""
    payload = previous.assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record)
    rows = top_pairs(payload["strong_pairs"])
    text = (
        "按原始Vina评分升序展示前十组："
        + "；".join(
            row["成分"] + "—" + row["受体"] + f"（{row['结合能（kcal/mol）']:.2f} kcal/mol）"
            for row in rows
        )
        + "。完整评分见矩阵；评分排序不表示药效排序。"
    )
    for row in payload["conclusion_sections"]:
        if row["层次"] == "结构方向":
            row["结论"] = text
    payload["conclusion_draft"] = " ".join(row["结论"] for row in payload["conclusion_sections"])
    return payload


def build_detailed(payload, destination, root, revision):
    """沿用第22版事实和骨架，在新修订内按截图局部调整。"""
    previous.build_detailed(payload, destination, root, revision)
    revise_file(destination, payload)


def build_concise(payload, destination, root, revision):
    """与专业版共用事实和换行热图，保留两页简报的短摘要。"""
    previous.build_concise(payload, destination, root, revision)
    revise_concise(destination)


generate_report_figures = bind(previous.generate_report_figures, export_heatmap=export_heatmap)


def run_reports(workflow, study_id, expected_a07, reason, **kwargs):
    """复用既有写锁和追加发布入口，不自动批准结果。"""
    kwargs["reuse_current_concise"] = False
    generate = bind(
        previous.previous.base.run_reports,
        CONFIG=CONFIG,
        assemble_payload=assemble_payload,
        build_detailed=build_detailed,
        build_concise=build_concise,
        generate_report_figures=generate_report_figures,
        report_heatmap_record=lambda *_: None,
    )
    with workflow.handoff_read_cache():
        return generate(previous.ReportView(workflow), study_id, expected_a07, reason, **kwargs)


def validator(root, old):
    """继承全部同源/矩阵/审批核验，再检查本版正文去重和章节删除。"""
    previous_check = bind(previous.validator, CONFIG=CONFIG)(root, old)

    def check(run, summary, tables, anomalies, outcome):
        previous_check(run, summary, tables, anomalies, outcome)
        if run["config"].get("schema_version") != CONFIG["schema_version"]:
            return
        from docx import Document

        home = Path(root) / "studies" / run["study_id"]
        record = next(r for r in tables["report_files"] if r["role"] == "detailed_report")
        doc = Document(verified_file(home, record))
        text = [p.text for p in doc.paragraphs]
        require(
            "8 主要限制" not in text and "8 结果复核说明" in text,
            "第23版未删除限制章节或章节编号不连续",
        )
        section = text[text.index("5 GO与KEGG富集结果") : text.index("6 分子对接结果")]
        require(
            not any(
                p.startswith(
                    (
                        "GO BP 生物过程前三：",
                        "GO CC 细胞组分前三：",
                        "GO MF 分子功能前三：",
                        "KEGG统计显著性前五：",
                        "KEGG命中基因数前五：",
                    )
                )
                for p in section
            ),
            "正文仍重复列举富集摘要",
        )
        targets = [
            t
            for t in doc.tables
            if [c.text for c in t.rows[0].cells] == ["序号", "成分", "受体", "Vina评分（kcal/mol）"]
        ]
        packet = read_json(verified_file(home, run["inputs"]["a06_trial_packet"]))
        selected = sorted(
            [p for p in packet["pairs"] if p["state"] == "completed" and p["score"] <= -8],
            key=lambda p: (p["score"], p["target_id"], p["compound_id"]),
        )[:10]
        require(len(targets) == bool(selected), "结构方向前十表缺失或重复")
        if selected:
            symbols = {r["target_id"]: r["symbol"] for r in packet["receptors"]}
            actual = [
                [r.cells[0].text, r.cells[2].text, r.cells[3].text] for r in targets[0].rows[1:]
            ]
            expected = [
                [str(i), symbols[p["target_id"]], f"{p['score']:.2f}"]
                for i, p in enumerate(selected, 1)
            ]
            require(actual == expected, "结构方向前十顺序或原评分不一致")

    return check
