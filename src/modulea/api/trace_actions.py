"""研究追溯摘要和数据导出接口；所有内容只来自当前研究归档。"""

import json

from contracts import ContractError
from ..core.trace_export import build_trace, trace_csv, trace_file_json
from .errors import from_contract


def _trace(app, study_id, include_data):
    try:
        workflow = app.kernel.read_workflow()
        payload = build_trace(workflow, study_id, include_data=include_data)
        try:
            payload["a06_review_packet"] = workflow.analysis_plan_a06_review_packet(study_id)
        except ContractError:
            payload["a06_review_packet"] = None
        return payload
    except ContractError as error:
        raise from_contract(str(error)) from error


def trace_summary(app, req, study_id):
    """摘要不携带全部结果表，防止普通页面加载大体积数据。"""
    payload = _trace(app, study_id, include_data=False)
    return {"trace_version": payload["trace_version"], "study_id": study_id,
            "workflow_profile": payload["workflow_profile"], "current": payload["current"],
            "modules": [{"module_id": row["module_id"], "label_zh": row["label_zh"],
                         "run_id": row["run_id"], "state": row["state"],
                         "result": row["result"], "table_names": (row["result"] or {}).get("table_names", [])}
                        for row in payload["modules"]],
            "plans": [{"plan_id": row["plan_id"], "state": row["state"], "created_at": row["created_at"]}
                      for row in payload["plans"]],
            "file_count": payload["file_count"], "read_only": True,
            "a06_review_packet_available": bool(payload.get("a06_review_packet", {}).get("supported")),
            "export_json_url": f"/api/v1/studies/{study_id}/trace/export.json",
            "export_csv_url": f"/api/v1/studies/{study_id}/trace/export.csv",
            "message_zh": "摘要、JSON和CSV均绑定当前研究版本；下载前会逐件核验归档指纹。"}


def export_trace_json(app, req, study_id):
    """JSON导出包含结果表，供完整复核和机器读取。"""
    payload = _trace(app, study_id, include_data=True)
    return ("download", trace_file_json(payload), f"{study_id}_trace.json", "application/json; charset=utf-8")


def export_trace_csv(app, req, study_id):
    """CSV导出将每张结果表逐行展开，原始嵌套记录放在record_json列。"""
    payload = _trace(app, study_id, include_data=True)
    return ("download", trace_csv(payload), f"{study_id}_results.csv", "text/csv; charset=utf-8")
