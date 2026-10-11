"""A05隔离自测夹具：虚构研究、HGNC字段和注释，不读取真实研究结果。"""

import gzip
import hashlib
import json
from pathlib import Path

from science_modules.a05 import flow
from storage import file_record, write_json
from workflow import Workflow


# 40基因背景、5个命中、1个无注释；期望概率可用组合数独立核验。
def annotations():
    terms = [
        {"id": "TEST:1", "description": "Synthetic first term", "genes": [str(i) for i in range(1, 11)]},
        {"id": "TEST:2", "description": "Synthetic other term", "genes": [str(i) for i in range(11, 41)]},
    ]
    names = "hsa00001\tSynthetic first pathway\nhsa00002\tSynthetic other pathway\n"
    links = "".join(f"hsa:{i}\tpath:hsa{1 if i <= 10 else 2:05d}\n" for i in range(1, 41))
    sources = {"names": {"response_text": names}, "links": {"response_text": links}}
    groups = {key: terms for key in ("BP", "CC", "MF")}
    groups["KEGG"] = flow.legacy.kegg_terms(sources)
    return groups, sources


# 注释快照为明确合成来源，仅用于运行链自测；不会进入真实资料根目录。
def seed(root):
    root = Path(root)
    workflow = Workflow(root, {"A05": flow.validator(root)})
    sid = workflow.create({"formula": "A05虚构自测方", "herbs": "虚构药味", "disease": "虚构自测病", "disease_scope": "仅测试", "operator": "隔离自测", "species": 9606, "analysis_purpose": "workflow_test"}, kind="contract_test")
    workflow.review(sid, workflow.load(sid)["current"]["A00"], "approved", "虚构核验人", "仅测试上游")
    home = workflow.location(sid)
    targets = [{"target_id": f"HGNC:{i}", "symbol": f"TEST{i}"} for i in range(1, 7)]
    mapping_path = home / "raw/hgnc_synthetic.tsv"
    raw = "hgnc_id\tsymbol\tentrez_id\n" + "".join(f"HGNC:{i}\tTEST{i}\t{i if i < 6 else 999}\n" for i in range(1, 7))
    mapping_path.write_text(raw, encoding="utf-8")
    for mid in ("A01", "A02", "A03", "A04"):
        inputs = {"mapping_file": file_record(home, mapping_path, "mapping_source")} if mid == "A01" else {}
        run = workflow.begin(sid, mid, inputs, {}, "仅测试A05链路的合成上游")
        summary = {"analysis_purpose": "workflow_test"}
        if mid == "A04": summary["docking_candidate_source_pending"] = True
        tables = {"intersection_targets": targets} if mid == "A03" else {}
        workflow.finish(sid, run["run_id"], summary, tables)
        workflow.review(sid, run["run_id"], "approved", "虚构核验人", "合成上游，不是科研结果")
    groups, sources = annotations()
    bundle = {"schema_version": "A05.source.1", "config": flow.CONFIG, "annotations": groups, "metadata": {"fixture": "synthetic"}, "kegg_sources": sources}
    raw = gzip.compress(json.dumps(bundle, ensure_ascii=False).encode("utf-8"), mtime=0)
    source_path = root / "references" / ("enrichment_" + hashlib.sha256(raw).hexdigest() + ".json.gz")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(raw)
    write_json(root / "environments/A05_sources.json", file_record(root, source_path, "annotation_source"))
    return workflow, sid
