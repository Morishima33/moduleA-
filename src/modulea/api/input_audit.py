"""A01—A03输入数量溯源：解释已归档的来源、单位及范围排除，不计算科学集合。"""

from disease import SCOPES
from ..core.source_catalog import source_databases


def context(workflow, manifest, module_id, run, result):
    """A03按实际父运行取证；历史解释不得偷偷连接当前另一版本。"""
    if module_id not in ("A01", "A02", "A03") or not run or not result:
        return None
    parents = run.get("parent_runs") or {}
    formula = result if module_id == "A01" else workflow.result(manifest, parents["A01"]) if module_id == "A03" and parents.get("A01") else None
    disease = result if module_id == "A02" else workflow.result(manifest, parents["A02"]) if module_id == "A03" and parents.get("A02") else None
    info = {"formula": None, "disease": None, "checks": []}
    if formula:
        summary = formula.get("summary") or {}
        sources = source_databases("A01", manifest, formula)
        expected = ["TCMSP", "HERB", "BATMAN"] if manifest.get("workflow_profile") in ("A00.preupload.1", "A00.preupload.2") else sources
        missing = [source for source in expected if source not in sources]
        info["formula"] = {
            "run_id": formula["run_id"], "sources": sources, "missing_sources": missing,
            "component_label_zh": "候选成分分组" if "候选成分分组数" in summary else "筛选后不同成分",
            "component_count": summary.get("候选成分分组数", summary.get("筛选后不同成分数")),
            "target_count": summary.get("标准化基因数"),
            "relationship_count": len(formula["tables"]["normalized_compound_targets"]) if "normalized_compound_targets" in formula.get("tables", {}) else summary.get("去重成分—人类基因关系数"),
        }
        if missing:
            info["checks"].append({"level": "warning", "label_zh": "当前方剂结果尚未覆盖三库",
                "detail_zh": "当前实际来源为" + "、".join(sources) + "；尚未纳入" + "、".join(missing) + "。请在A01补齐本研究来源并整理新版；不能与三库结果直接比较或当作三库已完成。", "module_id": "A01"})
        if module_id == "A03":
            pairs = (("方剂靶点数", "标准化基因数"),)
            for child_key, parent_key in pairs:
                left, right = result["summary"].get(child_key), summary.get(parent_key)
                if left is not None and right is not None:
                    info["checks"].append({"level": "info" if left == right else "warning", "label_zh": "A03方剂输入核对",
                        "detail_zh": f"本交集的方剂靶点为{left}个，绑定A01的标准化靶点为{right}个；" + ("数量一致。成分数与靶点基因数是不同单位。" if left == right else "数量不一致，请核查输入版本。"), "module_id": "A01"})
    if disease:
        summary = disease.get("summary") or {}
        groups = disease.get("tables", {}).get("scope_groups") or []
        counts = [{"value": value, "label_zh": label,
                   "count": sum(row["scope"] == value for row in groups),
                   "records": sum(row["records"] for row in groups if row["scope"] == value)} for value, label in SCOPES.items()]
        reason = ""
        if summary.get("标准化基因数") == 0:
            if groups and all(row["scope"] in ("outside", "subtype") for row in groups):
                reason = f"已取得{summary.get('候选记录数', '—')}条候选记录，但{len(groups)}组疾病范围均被排除或标为不纳入亚型，因此标准化疾病集合为空；这不是数据库没有读取到基因。"
            elif groups and any(row["scope"] == "pending" for row in groups):
                reason = "仍有待核验的疾病范围记录，尚不能据此判断本病没有基因。"
            else:
                reason = "当前归档的标准化疾病集合为空，请核对采用范围和身份处理明细。"
        info["disease"] = {"run_id": disease["run_id"], "candidate_count": summary.get("候选记录数"),
                           "target_count": summary.get("标准化基因数"), "scope_counts": counts, "empty_reason_zh": reason}
        if reason:
            info["checks"].append({"level": "warning", "label_zh": "疾病空集合的来源", "detail_zh": reason, "module_id": "A02"})
        if module_id == "A03":
            left, right = result["summary"].get("疾病靶点数"), summary.get("标准化基因数")
            if left is not None and right is not None:
                info["checks"].append({"level": "info" if left == right else "warning", "label_zh": "A03疾病输入核对",
                    "detail_zh": f"本交集的疾病靶点为{left}个，绑定A02的标准化靶点为{right}个；" + ("数量一致。" if left == right else "数量不一致，请核查输入版本。"), "module_id": "A02"})
    return info
