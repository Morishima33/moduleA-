# 疾病范围核验适配：展示完整当前条目和来源身份，提交沿用原批次入口。
from contracts import require
from disease import SCOPES, run_disease
from storage import read_json, verified_file
from source_identity import identity_warning


def context(workflow, manifest, result, enabled, disabled_reason=""):
    """只读当前结果；原件必须属于本研究并通过指纹核验。"""
    groups = ((result or {}).get("tables") or {}).get("scope_groups")
    if not groups:
        return None
    sid = manifest["study_id"]
    a00 = manifest["current"].get("A00", "")
    summary = workflow.result(manifest, a00)["summary"]
    record = next(r for r in result["sources"] if r["role"] == "source_manifest")
    datasets = read_json(verified_file(workflow.location(sid), record))["datasets"]
    evidence = {}
    for item in datasets:
        db = item["database"]
        warning = ""
        if item["format"] in ("omim_xlsx", "omim_xlsx_v2", "genecards_csv"):
            _, warning = identity_warning(summary, item, verified_file(workflow.location(sid), item["source_record"]).read_bytes())
        evidence[db] = {"source_name": item.get("name", ""), "source_url": f"/api/v1/studies/{sid}/modules/A02/sources/{db}/file", "identity_warning": warning, "direct_allowed": not warning.startswith("来源检索身份不匹配")}
    return {"enabled": enabled, "disabled_reason_zh": disabled_reason, "expected_a00": a00,
            "expected_run": result["run_id"], "expected_staging": "",
            "items": [dict(row, **evidence.get(row["database"], {})) for row in groups],
            "choices": [{"value": key, "label_zh": label} for key, label in SCOPES.items()]}


def review_scope(workflow, sid, payload):
    """锁内写入前再核对版本和完整清单，不代签A02整体复核。"""
    manifest = workflow.load(sid)
    require(not manifest.get("trashed") and manifest["current"].get("A00") == payload["expected_a00"] and manifest["current"].get("A02") == payload["expected_run"], "研究只读或页面版本已改变，请刷新")
    require(workflow.active(manifest, payload["expected_run"]), "A02已失效，请更新资料后核验")
    result = workflow.result(manifest, payload["expected_run"])
    info = context(workflow, manifest, result, True)
    batch = validate_submission(info, payload)
    return run_disease(workflow, sid, payload["expected_a00"], payload["expected_run"], [], "全表疾病范围复核：" + payload["note"].strip(), scope_change=batch)


def validate_submission(info, payload):
    """接口与后台共享纯校验，拒绝遗漏和错来源纳入。"""
    require(info is not None, "当前没有可核验的疾病范围条目")
    decisions = payload.get("decisions")
    require(payload.get("confirmed") is True and isinstance(decisions, list) and decisions, "请核对完整范围表并明确确认提交")
    require(all(isinstance(d, dict) and isinstance(d.get("scope_id"), str) and isinstance(d.get("scope"), str) and d["scope"] in SCOPES for d in decisions), "范围决定不合法")
    ids = [d["scope_id"] for d in decisions]
    require(len(ids) == len(set(ids)) and set(ids) == {r["scope_id"] for r in info["items"]}, "范围条目遗漏或重复，须完整覆盖当前清单")
    for key in ("reviewer", "note"):
        require(isinstance(payload.get(key), str) and 0 < len(payload[key].strip()) <= 4000, "请填写核验人和依据")
    warnings = {r["scope_id"] for r in info["items"] if r.get("identity_warning", "").startswith("来源检索身份不匹配")}
    require(not any(d["scope_id"] in warnings and d["scope"] == "direct" for d in decisions), "来源文件疾病与当前研究不符，请更换文件或保留待核验/排除，不能标为本病")
    return [dict(d, reviewer=payload["reviewer"].strip(), note=payload["note"].strip()) for d in decisions]
