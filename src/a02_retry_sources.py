# A02失败来源定向重试；网络读取后由统一入口锁内核对版本并合并其他库。
from contracts import require
from storage import read_json, verified_file
from a02_auto_prepare import _otp_source, _ttd_source, _terms, _failure
from pharmgkb_source import fetch_pharmgkb
from disease import run_disease


def retry_sources(workflow, study_id, payload):
    """只重取当前版本中明确失败的自动来源，始终停在A02复核。"""
    manifest = workflow.load(study_id)
    require(not manifest.get("trashed"), "研究在回收站中，只读")
    a00, a02 = payload["expected_a00"], payload["expected_run"]
    require(manifest["current"].get("A00") == a00 and manifest["current"].get("A02") == a02, "页面版本已改变，请刷新后重试")
    require(workflow.approved(manifest, a00) and workflow.active(manifest, a02), "A00未通过或A02已失效")
    result = workflow.result(manifest, a02)
    record = next(r for r in result["sources"] if r["role"] == "source_manifest")
    sources = read_json(verified_file(workflow.location(study_id), record))["datasets"]
    failed = {s["database"] for s in sources if s.get("source_status") == "query_failed"}
    selected = payload.get("databases")
    require(isinstance(selected, list) and selected and all(isinstance(db, str) for db in selected), "请选择失败来源")
    require(len(selected) == len(set(selected)) and set(selected) <= failed & {"OTP", "TTD", "PharmGKB"}, "只能重试当前获取失败的自动来源")
    a00_summary = workflow.result(manifest, a00)["summary"]
    jobs = {"OTP": lambda: _otp_source(a00_summary)[0], "TTD": lambda: _ttd_source(a00_summary)[0],
            "PharmGKB": lambda: fetch_pharmgkb(_terms(a00_summary))}
    updates = []
    for database in selected:
        try:
            updates.append(jobs[database]())
        except Exception as error:
            updates.append(_failure(database, error))
    return run_disease(workflow, study_id, a00, a02, updates, payload["reason"])
