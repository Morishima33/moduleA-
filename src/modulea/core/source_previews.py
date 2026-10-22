"""只读来源采集记录和疾病候选索引；不在页面请求中联网或改变科研状态。"""
from storage import read_json, verified_file
from contracts import require


def mapping(workflow, manifest, identity, verify_originals=True):
    """仅由本研究登记目录定位，并复核归档索引的内容指纹。"""
    import re
    require(isinstance(identity, str) and re.fullmatch(r"task_[0-9a-f]{32}", identity), "候选预览编号无效")
    home = workflow.location(manifest["study_id"])
    index = read_json(home / "raw/A02_mapping_previews" / identity / "index.json")
    value = read_json(verified_file(home, index["file"]))
    require(value["study_id"] == manifest["study_id"], "候选预览不属于本研究")
    if verify_originals:
        for record in value.get("source_files", []):
            verified_file(home, record)
    return value


def latest(workflow, manifest, kind):
    """摘要限当前绑定，旧版本仍留原目录但不会冒充本次候选。"""
    home = workflow.location(manifest["study_id"])
    base = home / ("raw/A02_mapping_previews" if kind == "mapping" else "raw/A01_acquisition")
    name = "index.json" if kind == "mapping" else "acquisition_result*.json"
    paths = sorted(base.glob("*/" + name), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in paths:
        value = mapping(workflow, manifest, path.parent.name, verify_originals=False) if kind == "mapping" else read_json(path)
        module = "A02" if kind == "mapping" else "A01"
        if value.get("bound_a00") != manifest["current"].get("A00") or value.get("bound_a02" if kind == "mapping" else "bound_a01", "") != manifest["current"].get(module, ""):
            continue
        rows = []
        for row in value.get("databases", []):
            rows.append({k: row[k] for k in ("database", "status", "status_zh", "message_zh", "error_zh") if k in row}
                        | ({"candidates_count": len(row.get("candidates", []))} if kind == "mapping" else {}))
        return {"preview_id": path.parent.name, "databases": rows}
    return None
