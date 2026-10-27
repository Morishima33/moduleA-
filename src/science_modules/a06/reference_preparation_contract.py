"""共晶参考证据绑定新版准备的请求契约；只依赖项目通用合同。"""

from contracts import require, safe_id


def validate_request(payload):
    """只接受当前准备、参考核查和明确绑定说明，不接受科学参数。"""
    fields = {"expected_input_id", "expected_preparation_run_id", "expected_review_id",
              "request_id", "reviewer", "note", "confirmed"}
    require(isinstance(payload, dict) and set(payload) == fields,
            "参考证据绑定请求字段不完整或含不支持选项")
    safe_id(payload["expected_input_id"], "input")
    safe_id(payload["expected_preparation_run_id"], "run")
    safe_id(payload["expected_review_id"], "refreview")
    safe_id(payload["request_id"], "refprep")
    require(payload["confirmed"] is True and all(isinstance(payload[k], str) and
            0 < len(payload[k].strip()) <= 2000 for k in ("reviewer", "note")),
            "请明确确认参考证据绑定人及依据")
    return payload
