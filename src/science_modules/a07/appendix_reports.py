"""A07第24版：保留第23版原事实及发布流程，统一末尾术语附录。"""

from pathlib import Path

from docx import Document
from storage import verified_file
from . import refined_reports as previous
from .appendix_documents import revise_file, validate_document
from .appendix_heatmap import export_heatmap
from .report_heatmap import bind

CONFIG = dict(
    previous.CONFIG,
    schema_version="A07.report.config.24",
    template_version="A07.double_report.24",
    concise_target_pages=3,
)


def assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record=None):
    """首页结论和机器事实包同步去掉重复PPI，其他科学数据沿用第23版。"""
    payload = previous.assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record)
    for section in payload["conclusion_sections"]:
        if section["层次"] == "成分与靶点概览":
            section["结论"] = section["结论"].split("；PPI第二轮Degree前十靶点为", 1)[0] + "。"
    payload["conclusion_draft"] = " ".join(
        section["结论"] for section in payload["conclusion_sections"]
    )
    return payload


def build_detailed(payload, destination, root, revision):
    """在既有专业版骨架上完成局部图表移动和末尾附录。"""
    previous.build_detailed(payload, destination, root, revision)
    revise_file(destination, payload, True)


def build_concise(payload, destination, root, revision):
    """简报保留正文内容，新增独立末尾附录，与专业版释义完全一致。"""
    previous.build_concise(payload, destination, root, revision)
    revise_file(destination, payload, False)


generate_report_figures = bind(previous.generate_report_figures, export_heatmap=export_heatmap)


class ReportView(previous.previous.ReportView):
    def _begin(self, manifest, module, inputs, config, reason):
        """复用同源图件原字节，新的报告专用热图独立生成。"""
        reusable = {}
        prior = manifest["current"].get("A07")
        if prior and self.workflow.active(manifest, prior):
            source = self.workflow.run(manifest, prior)
            parents = {key: manifest["current"].get(key) for key in source.get("parent_runs", {})}
            if source.get("parent_runs") == parents:
                for record in self.workflow.result(manifest, prior)["tables"]["report_figures"]:
                    if record["role"].removesuffix("_png").removesuffix("_svg") in {
                        "venn",
                        "herb_compound_target",
                        "ppi_full",
                        "ppi_round1",
                        "go_faceted",
                        "kegg_bubble",
                    }:
                        path = Path(record["path"])
                        reusable.setdefault(path.stem, {})[path.suffix[1:]] = record
        result = super()._begin(manifest, module, inputs, config, reason)
        self.reusable_figures.update(reusable)
        return result


def run_reports(workflow, study_id, expected_a07, reason, **kwargs):
    """经原写锁追加新修订，不将第23版审批迁给新报告。"""
    kwargs["reuse_current_concise"] = False
    generate = bind(
        previous.previous.previous.base.run_reports,
        CONFIG=CONFIG,
        assemble_payload=assemble_payload,
        build_detailed=build_detailed,
        build_concise=build_concise,
        generate_report_figures=generate_report_figures,
        report_heatmap_record=lambda *_: None,
    )
    with workflow.handoff_read_cache():
        return generate(ReportView(workflow), study_id, expected_a07, reason, **kwargs)


def validator(root, old):
    """继续完整校验原评分、排名表和绑定，再检查新版附录及顺序。"""
    current_check = bind(previous.validator, CONFIG=CONFIG)(root, old)

    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("schema_version") != CONFIG["schema_version"]:
            return old(run, summary, tables, anomalies, outcome)
        current_check(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        for record in tables["report_files"]:
            if record["role"] in ("detailed_report", "concise_report"):
                validate_document(
                    Document(verified_file(home, record)), record["role"] == "detailed_report"
                )

    return check
