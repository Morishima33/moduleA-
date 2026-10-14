"""已确认全覆盖试算接入A06；新结果明确限定扩展用途，不改旧严格契约。"""

from pathlib import Path

from contracts import require
from storage import read_json, verified_file

from .trial_evidence import audit_outputs

VERSION = "A06.trial.handoff.1"
NOTE = "本批为已确认的扩展试算；允许用于扩展筛查与报告，不表示全部受体严格质控通过。"


def matrix_rows(packet):
    """使用同批原值，保留完整225格，不按评分改变范围。"""
    pairmap = {(p["compound_id"], p["target_id"]): p for p in packet["pairs"]}
    return [
        {
            "compound_id": c["compound_id"],
            "compound_name": c["name_zh"],
            **{
                r["symbol"]: pairmap[(c["compound_id"], r["target_id"])]["score"]
                for r in packet["receptors"]
            },
        }
        for c in packet["compounds"]
    ]


def setup_rows(packet):
    """旧报告可读的真实结构清单，预测/多区域保持明确说明。"""
    rows = []
    for r in packet["receptors"]:
        spec = r.get("spec", {})
        reference = (
            f"{spec['reference_code']} {spec.get('reference_chain', '')}:{spec.get('reference_sequence', '')}"
            if spec.get("reference_code")
            else "未采用共晶参考配体定位"
        )
        fixed = r["regions"][0] if r["mode"] == "fixed_site" and r["regions"] else None
        rows.append(
            {
                "靶点基因": r["symbol"],
                "PDB ID": r.get("structure_id", "NA"),
                "蛋白链": ",".join(spec.get("chains", [])) or "见归档",
                "共晶参考配体": reference,
                "搜索盒中心坐标": str(fixed.get("center"))
                if fixed
                else "多区域，见区域明细",
                "搜索盒尺寸": str(fixed.get("size")) if fixed else "见固定区域集合",
                "重对接RMSD（Å）": r.get("history_rmsd_A"),
                "质控状态": "扩展试算；历史输入："
                + r.get("history_quality_zh", "未通过"),
            }
        )
    return rows


def validator(root, previous):
    """新协议逐格及真实姿势核验；历史正式结果仍走原校验器。"""

    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("schema_version") != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        require(
            run["config"]
            == {"schema_version": VERSION, "interpretation_scope": "extended_trial"},
            "扩展交接配置非法",
        )
        packet = read_json(verified_file(home, run["inputs"]["trial_packet"]))
        review = read_json(verified_file(home, run["inputs"]["trial_review"]))
        require(
            packet["study_id"]
            == review.get("study_id", packet["study_id"])
            == run["study_id"],
            "试算研究不一致",
        )
        require(
            review["trial_id"] == packet["trial_id"] == run["inputs"]["trial_id"]
            and review["confirmed"],
            "试算未确认或版本不一致",
        )
        audit_outputs(home, packet)
        require(
            tables["score_matrix"] == matrix_rows(packet), "A06矩阵与实际试算不一致"
        )
        require(
            tables["receptor_setup"] == setup_rows(packet), "结构说明与本批试算不一致"
        )
        require(
            summary["interpretation_scope"] == "extended_trial"
            and summary["all_receptors_strict_passed"] is False,
            "不能将扩展试算改写为严格通过",
        )
        require(
            summary["成功组合数"] == packet["summary"]["completed"]
            and summary["失败组合数"] == packet["summary"]["NA"],
            "试算数量不一致",
        )
        require(
            outcome == "success" and summary["handoff_blocked"] is False,
            "试算交接状态不一致",
        )

    return check
