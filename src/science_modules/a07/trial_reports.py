"""A07第21版：已正式复核的扩展A06引用同批评分，旧报告与结论规则保留。"""

from copy import deepcopy
from pathlib import Path
from types import FunctionType

from contracts import require
from science_modules.a06.trial_exports import insert_professional_trial
from science_modules.a06.trial_handoff import NOTE
from science_modules.a06.trial_handoff import VERSION as A06_VERSION
from science_modules.a06.trial_presentation import score_label
from storage import read_json, verified_file

from . import circular_reports as base
from . import compact_enrichment_reports as previous

CONFIG = dict(
    previous.CONFIG,
    schema_version="A07.report.config.21",
    template_version="A07.double_report.21",
)


def packet_for(workflow, manifest, a06_id):
    run = workflow.run(manifest, a06_id)
    require(run["config"].get("schema_version") == A06_VERSION, "报告未绑定扩展A06")
    workflow.handoff_binding(manifest, run["inputs"])
    return read_json(
        verified_file(
            workflow.location(manifest["study_id"]), run["inputs"]["trial_packet"]
        )
    )


def current_export(workflow, manifest, name):
    records = manifest["docking_trial_records"][-1]["files"]
    proof = next(
        r for r in reversed(records) if r["path"].endswith("/export_validation.json")
    )
    folder = Path(proof["path"]).parent
    return next(
        r
        for r in records
        if Path(r["path"]).parent == folder and Path(r["path"]).name == name
    )


class PayloadView:
    """仅抑制旧模板从扩展分值自动推出严格主要结论；源归档不改。"""

    def __init__(self, workflow):
        self.workflow = workflow

    def __getattr__(self, name):
        return getattr(self.workflow, name)

    def result(self, manifest, rid):
        result = self.workflow.result(manifest, rid)
        if (
            self.workflow.run(manifest, rid).get("config", {}).get("schema_version")
            == A06_VERSION
        ):
            result = deepcopy(result)
            for row in result["tables"]["score_matrix"]:
                for key in row:
                    if key not in {"compound_id", "compound_name"}:
                        row[key] = None
        return result


def assemble_payload(workflow, manifest, parent_runs, heatmap_metadata_record=None):
    payload = previous.assemble_payload(
        PayloadView(workflow), manifest, parent_runs, None
    )
    packet = packet_for(workflow, manifest, parent_runs["A06"])
    result = workflow.result(manifest, parent_runs["A06"])
    payload["docking_matrix"] = deepcopy(result["tables"]["score_matrix"])
    payload["primary_targets"] = []
    payload["trial_packet"] = packet
    payload["heatmap_png"] = current_export(
        workflow, manifest, "A06_01_重点结合能热图.png"
    )
    payload["heatmap_display"] = {
        "compounds": len(packet["display"]["config"]["heatmap_compounds"]),
        "receptors": len(packet["display"]["config"]["heatmap_targets"]),
    }
    payload["heatmap_display_note"] = "同批8×8重点展示；完整15×15矩阵见专业版。" + NOTE
    payload["docking_reuse_text"] = "直接引用已完成试算与实际姿势，报告未重新计算。"
    payload["_a05_home"] = str(workflow.location(manifest["study_id"]))
    payload["limitations"] = [
        NOTE if "主要结论只使用" in line else line for line in payload["limitations"]
    ]
    for count in payload["key_counts"]:
        if count["指标"] == "正式对接成功组合数":
            count["指标"] = "扩展试算成功组合数"
    for section in payload["conclusion_sections"]:
        if section["层次"] == "PPI方向":
            a04 = workflow.result(manifest, parent_runs["A04"])
            names = [r["symbol"] for r in a04["tables"]["degree_round1_top10"]]
            section["结论"] = (
                "Degree第一轮前列节点包括"
                + "、".join(names)
                + "。排序反映本次网络连接，疾病生物学作用仍须核实。"
            )
        elif section["层次"] == "富集方向":
            a05 = workflow.result(manifest, parent_runs["A05"])
            go = [
                a05["tables"][g + "_graph8"][0]
                for g in ("bp", "cc", "mf")
                if a05["tables"][g + "_graph8"]
            ]
            kegg = a05["tables"]["kegg_graph15"][:2]
            names = [r.get("description_zh") or r["Description"] for r in go + kegg]
            section["结论"] = (
                "当前已确认展示范围的前列条目包括"
                + "；".join(names)
                + "。富集不等同通路被调控或临床有效，已排除疾病条目不用于摘要。"
            )
        elif section["层次"] == "结构方向":
            section["结论"] = (
                f"本批完成{packet['summary']['completed']}/225组合的Vina评分，NA={packet['summary']['NA']}。"
                + NOTE
            )
        elif section["层次"] == "后续研究":
            section["结论"] = (
                "逐受体结合所选结构、位点和准备限制核查姿势；试算评分不能单独确定药效或实测结合自由能。"
            )
    payload["conclusion_draft"] = (
        " ".join(s["结论"] for s in payload["conclusion_sections"])
        + " 因此不能据此认定治疗有效或机制已证实。"
    )
    a05 = workflow.result(manifest, parent_runs["A05"])
    for lead in payload["research_leads"]:
        if "功能" in lead["线索"] or "通路" in lead["线索"]:
            rows = a05["tables"]["bp_graph8"][:2] + a05["tables"]["kegg_graph15"][:2]
            lead["支持事实"] = "当前已确认展示范围：" + "；".join(
                r["ID"] + " " + (r.get("description_zh") or r["Description"])
                for r in rows
            )
    return payload


def build_detailed(payload, destination, root, revision):
    from docx import Document

    previous.build_detailed(payload, destination, root, revision)
    doc = Document(destination)
    start = next(p for p in doc.paragraphs if p.text == "6 分子对接结果")
    stop = next(p for p in doc.paragraphs if p.text == "7 待进一步核验的研究线索")
    node = start._p.getnext()
    while node is not stop._p:
        following = node.getnext()
        node.getparent().remove(node)
        node = following
    insert_professional_trial(
        doc, payload["trial_packet"], verified_file(root, payload["heatmap_png"])
    )
    # 第六章标题随内容进入横向节，避免上一页只剩一个空标题。
    trial_heading = next(p for p in doc.paragraphs if p.text == "A06 扩展试算")
    trial_heading._p.addprevious(start._p)
    trial_heading._p.getparent().remove(trial_heading._p)
    for paragraph in doc.paragraphs:
        if paragraph.text.startswith("分子对接："):
            paragraph.text = (
                "分子对接：引用已完成的15×15扩展试算，同一受体采用固定结构及区域集合。"
                + NOTE
            )
    doc.save(destination)


def build_concise(payload, destination, root, revision):
    from docx import Document

    base.build_concise(payload, destination, root, revision)
    doc = Document(destination)
    for p in doc.paragraphs:
        if p.text.startswith("主要受体范围内，") or p.text.startswith(
            "本次未形成有效对接评分。"
        ):
            p.text = (
                f"本批{payload['trial_packet']['summary']['completed']}/225组合形成真实扩展评分。"
                + NOTE
            )
    doc.save(destination)


class ReportView(previous.ReportView):
    def _begin(self, manifest, module, inputs, config, reason):
        # 原生成流程已持有研究写锁；此刻清除操作前缓存，重新核对正式批准。
        self.workflow.reset_handoff_cache()
        a06 = self.workflow.run(manifest, manifest["current"]["A06"])
        inputs = dict(
            inputs,
            a06_trial_packet=deepcopy(a06["inputs"]["trial_packet"]),
            a06_trial_review=deepcopy(a06["inputs"]["trial_review"]),
            a06_trial_export=current_export(
                self.workflow, manifest, "export_validation.json"
            ),
        )
        return super()._begin(manifest, module, inputs, config, reason)


def run_reports(workflow, study_id, expected_a07, reason, **kwargs):
    scope = dict(
        vars(base),
        CONFIG=CONFIG,
        assemble_payload=assemble_payload,
        build_detailed=build_detailed,
        build_concise=build_concise,
        generate_report_figures=previous.generate_report_figures,
        report_heatmap_record=lambda *_: None,
    )
    generate = FunctionType(
        base.run_reports.__code__,
        scope,
        base.run_reports.__name__,
        base.run_reports.__defaults__,
    )
    with workflow.handoff_read_cache():
        return generate(ReportView(workflow), study_id, expected_a07, reason, **kwargs)


def validator(root, old):
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("schema_version") != CONFIG["schema_version"]:
            return old(run, summary, tables, anomalies, outcome)
        from docx import Document

        home = Path(root) / "studies" / run["study_id"]
        packet = read_json(verified_file(home, run["inputs"]["a06_trial_packet"]))
        require(packet["study_id"] == run["study_id"], "报告试算跨研究")
        manifest = read_json(home / "manifest.json")
        parent = read_json(
            verified_file(home, manifest["runs"][run["parent_runs"]["A06"]]["run_file"])
        )
        require(
            parent["inputs"]["trial_packet"] == run["inputs"]["a06_trial_packet"]
            and parent["inputs"]["trial_review"] == run["inputs"]["a06_trial_review"],
            "报告与已批准A06来源不一致",
        )
        reports = tables["report_files"]
        require(
            {r["role"] for r in reports}
            >= {"detailed_report", "concise_report", "report_index"},
            "双报告未齐",
        )
        for r in reports:
            verified_file(home, r)
        detail = Document(
            verified_file(
                home, next(r for r in reports if r["role"] == "detailed_report")
            )
        )
        matches = [t for t in detail.tables if len(t.columns) == 16]
        from science_modules.a06.trial_handoff import matrix_rows

        expected = [
            [r["compound_name"]]
            + [score_label(r[t["symbol"]], mark=True) for t in packet["receptors"]]
            for r in matrix_rows(packet)
        ]
        require(
            len(matches) == 1
            and [[c.text for c in row.cells] for row in matches[0].rows[1:]]
            == expected,
            "报告225格与当前试算不一致",
        )
        require(
            NOTE in "\n".join(p.text for p in detail.paragraphs)
            and summary["handoff_blocked"] is False,
            "报告缺少扩展解释范围",
        )
        concise = Document(
            verified_file(
                home, next(r for r in reports if r["role"] == "concise_report")
            )
        )
        require(
            NOTE in "\n".join(p.text for p in concise.paragraphs),
            "临床版缺少扩展解释范围",
        )

    return check
