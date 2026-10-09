"""开发工具：生成一个供前端开发和演示使用的“演示数据目录”。

用法：PYTHONPATH=src python -m modulea.devtools.demo_data <输出目录> [--source <真实数据根> --study <研究编号>]

- 不给 --source：用内置的小型虚构数据生成一项演示研究（测试使用）。
- 给 --source 与 --study：把该研究各模块“当前运行”的摘要和表格，复制进一个新的 contract_test 研究，
  并按真实复核状态登记复核。只读取源研究，不修改任何源文件；归档附件（图、Word）不复制。
生成的研究类型是 contract_test（契约测试），网页会显示其用途，不能当作科研结果。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.kernel import MODULES, Workflow, read_json

ORDER = list(MODULES.keys())

SYNTHETIC = {
    "A00": {"summary": {"formula": "示例方", "herbs": "甲药、乙药", "disease": "示例病", "mesh_term": "Example Disease", "mesh_id": "D000000",
                        "disease_scope": "仅本病，不纳入亚型", "analysis_purpose": "workflow_test", "species": 9606}},
    "A01": {"summary": {"筛选后不同成分数": 4, "标准化基因数": 12, "原始关系记录数": 40, "通过OB/DL的关系记录数": 20, "人类关系证据行数": 19,
                        "去重成分—人类靶点关系数": 18, "不同人类基因数": 13, "身份问题组数": 1, "mapping_rule": "HGNC.resolve.3"},
            "tables": {"herb_summary": [{"herb": "甲药", "components": 3, "human_genes": 10, "raw_rows": 25}, {"herb": "乙药", "components": 1, "human_genes": 4, "raw_rows": 15}]}},
    "A02": {"summary": {"标准化基因数": 300, "候选记录数": 420, "已有来源库数": 5, "失败来源库数": 0, "databases": ["GeneCards", "OMIM", "TTD", "PharmGKB", "Open Targets"]},
            "tables": {"source_summary": [{"database": "Open Targets", "records": 380, "query": "Example Disease", "retrieved_at": "2026-10-08", "availability": "自动获取"},
                                          {"database": "TTD", "records": 0, "query": "Example Disease", "retrieved_at": "2026-10-08", "availability": "已查询，0 条精确记录"}]}},
    "A03": {"summary": {"方剂靶点数": 12, "疾病靶点数": 300, "交集靶点数": 8, "仅方剂靶点数": 4, "仅疾病靶点数": 292},
            "tables": {"ranking": [{"main_rank": 1, "name": "成分一", "herbs": "甲药", "intersection_count": 6, "mixed_degree": 7, "degree_rank": 1, "compound_id": "MOL1"}]}},
    "A03_SELECT": {"summary": {"主候选数": 1, "人工补充纳入数": 0, "药味代表性纳入数": 0},
                   "tables": {"selected": [{"name": "成分一", "herbs": "甲药", "intersection_count": 6, "main_rank": 1, "selection_role": "边界以上主候选"}],
                              "coverage": [{"herb": "甲药", "covered": True}, {"herb": "乙药", "covered": False}]}},
    "A04": {"summary": {"交集输入数": 8, "已识别数": 8, "参与节点数": 6, "合格边数": 7, "孤立节点数": 2, "第一轮主候选数": 2, "第二轮参考数": 1, "STRING版本": "12.0"},
            "tables": {"round1": [{"symbol": "GENE1", "degree": 4, "bc": 5.0, "cc": 0.8, "round2": True}, {"symbol": "GENE2", "degree": 3, "bc": 2.0, "cc": 0.6, "round2": False}]}},
    "A05": {"summary": {"BP显著条目数": 12, "CC显著条目数": 0, "MF显著条目数": 3, "KEGG显著条目数": 2, "交集输入数": 8, "主显著性": "BH p.adjust < 0.05"},
            "tables": {"group_summary": [{"group": "BP", "effective_count": 8, "tested_count": 100, "significant_count": 12}, {"group": "CC", "effective_count": 8, "tested_count": 20, "significant_count": 0}]}},
    "A06_PREP": {"summary": {"计划组合数": 2, "严格质控通过受体数": 1, "主要受体数": 1, "受体核查数": 2, "成分数": 1},
                 "tables": {"receptor_diagnostics": [{"受体": "GENE1", "PPI顺序": 1, "PDB": "1ABC", "RMSD_A": 0.8, "质控状态": "严格通过", "主要结果": True},
                                                     {"受体": "GENE2", "PPI顺序": 2, "PDB": "2DEF", "RMSD_A": None, "质控状态": "失败，组合为NA", "主要结果": False}]}},
    "A06": {"summary": {"计划组合数": 2, "成功组合数": 1, "失败组合数": 1},
            "tables": {"score_matrix": [{"compound_id": "MOL1", "compound_name": "成分一", "GENE1": -7.5, "GENE2": None}]}},
    "A07": {"summary": {"共同结论草稿": "示例结论。", "研究线索数": 1},
            "tables": {"key_counts": [{"指标": "交集靶点数", "数值": 8}], "research_leads": [{"线索": "示例线索", "支持事实": "示例事实", "下一步核验": "示例核验"}],
                       "limitations": [{"限制": "演示数据，不是研究结果。"}]}},
}


def _source_results(source: Path, study_id: str) -> tuple[dict, dict]:
    """读取源研究各模块当前运行的结果与最近复核决定（只读，不核验附件）。"""
    root = source / "studies" / study_id
    manifest = read_json(root / "manifest.json")
    results, decisions = {}, {}
    reviews = []
    for record in manifest.get("reviews", []):
        try:
            reviews.append(read_json(root / record["path"]))
        except Exception:
            pass
    for module, run_id in manifest["current"].items():
        record = manifest["runs"][run_id].get("result_file")
        if not record:
            continue
        result = read_json(root / record["path"])
        results[module] = {"summary": result["summary"], "tables": result.get("tables") or {}, "outcome": result["outcome"]}
        latest = [r for r in reviews if r.get("artifact_id") == result["artifact_id"]]
        decisions[module] = latest[-1]["decision"] if latest else None
    return results, {"profile": manifest.get("workflow_profile"), "decisions": decisions}


def build(output: Path, source: Path | None = None, study_id: str | None = None) -> str:
    output.mkdir(parents=True, exist_ok=True)
    if source and study_id:
        results, meta = _source_results(source, study_id)
    else:
        results = {m: {"summary": v["summary"], "tables": v.get("tables", {}), "outcome": "success"} for m, v in SYNTHETIC.items()}
        meta = {"profile": None, "decisions": {m: "approved" for m in results}}
        meta["decisions"]["A07"] = None
    # A00 的摘要就是登记原文；源研究带完整 MeSH 核对证据时原样保留，否则去掉 MeSH 字段
    intake = dict(results["A00"]["summary"])
    if not isinstance(intake.get("mesh_verification"), dict):
        for key in ("mesh_term", "mesh_id", "mesh_verification"):
            intake.pop(key, None)
    intake.setdefault("operator", "演示数据生成器")
    workflow = Workflow(output, {})
    study_id_new = workflow.create(intake, kind="contract_test")
    if isinstance(study_id_new, dict):
        study_id_new = study_id_new.get("study_id")
    for module in ORDER:
        if module not in results:
            continue
        manifest = workflow.load(study_id_new)
        if module != "A00":
            data = results[module]
            run = workflow.begin(study_id_new, module, {"demo_source": study_id or "synthetic"}, {"demo": True}, "演示数据：复制源研究当前结果")
            tables = {k: v for k, v in data["tables"].items() if isinstance(v, (list, dict))}
            outcome = data["outcome"]
            workflow.finish(study_id_new, run["run_id"], data["summary"], tables, [], outcome)
            manifest = workflow.load(study_id_new)
        decision = meta["decisions"].get(module)
        if decision:
            workflow.review(study_id_new, manifest["current"][module], decision, "演示数据生成器", "按源研究复核状态登记（演示）", None)
        else:
            break
    return study_id_new


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成演示数据目录")
    parser.add_argument("output")
    parser.add_argument("--source")
    parser.add_argument("--study")
    args = parser.parse_args(argv)
    study = build(Path(args.output), Path(args.source) if args.source else None, args.study)
    print(json.dumps({"data_root": str(Path(args.output).resolve()), "study_id": study}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
