"""按稳定成分身份读取同源中英文名称；名称只用于显示，不改变归属或身份。"""

from copy import deepcopy

from contracts import require
from storage import read_json, verified_file


def compound_names(workflow, manifest, a03_run=None, packet=None):
    """英语取绑定A03，中文取明确绑定同一A03的已归档核查，缺译不猜译。"""
    a03 = a03_run
    if not a03 and packet:
        for rid in reversed(list(manifest.get("runs", {}))):
            run = workflow.run(manifest, rid)
            if run.get("module_id") == "A06" and run.get("inputs", {}).get(
                "trial_id"
            ) == packet.get("trial_id"):
                a03 = run.get("parent_runs", {}).get("A03")
                break
    a03 = a03 or manifest["current"].get("A03")
    if not a03:
        return {}
    result = workflow.result(manifest, a03)
    root = workflow.location(manifest["study_id"])
    source = manifest["runs"][a03]["result_file"]
    names = {
        r["compound_id"]: {
            "name_en": r.get("name", r["compound_id"]),
            "name_zh": r.get("name_zh", ""),
            "evidence": [deepcopy(source)],
        }
        for r in result.get("tables", {}).get("ranking", [])
    }
    for record in manifest.get("docking_review_records", []):
        review = read_json(verified_file(root, record))
        require(review.get("study_id") == manifest["study_id"], "成分名称来源研究不一致")
        if review.get("binding", {}).get("source_runs", {}).get("A03") != a03:
            continue
        for row in review.get("compounds", []) + review.get("excluded", []):
            if row.get("compound_id") in names and row.get("name_zh"):
                value = names[row["compound_id"]]
                value["name_zh"] = row["name_zh"]
                value["evidence"].append(deepcopy(record))
    if packet:
        for row in packet["compounds"]:
            value = names.setdefault(
                row["compound_id"],
                {"name_en": row.get("name_en", row.get("name", "")), "evidence": []},
            )
            value["name_zh"] = row.get("name_zh", value.get("name_zh", ""))
    return names


def bilingual_label(value):
    """已有中文与英语一起显示；无中文时明确保留原名。"""
    zh, en = value.get("name_zh", ""), value.get("name_en", "")
    return f"{zh}（{en}）" if zh and en and zh != en else zh or en
