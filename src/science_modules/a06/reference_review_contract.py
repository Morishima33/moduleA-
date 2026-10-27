"""新版A06共晶参考请求契约；只依赖标准库和项目通用合同。"""

from contracts import require, safe_id


def validate_request(payload):
    """请求只含同批输入和候选稳定键，不接受路径、坐标或Vina参数。"""
    fields = {"expected_input_id", "expected_preparation_run_id", "request_id", "reviewer",
              "note", "confirmed", "choices"}
    require(isinstance(payload, dict) and set(payload) == fields, "共晶参考请求字段不完整或含不支持选项")
    safe_id(payload["expected_input_id"], "input")
    safe_id(payload["expected_preparation_run_id"], "run")
    safe_id(payload["request_id"], "refreq")
    require(payload["confirmed"] is True and all(isinstance(payload[k], str) and
            0 < len(payload[k].strip()) <= 2000 for k in ("reviewer", "note")),
            "请明确确认共晶参考核查人及依据")
    require(isinstance(payload["choices"], list), "共晶选择必须是列表")
    for choice in payload["choices"]:
        require(isinstance(choice, dict) and set(choice) == {"target_id", "candidate_key", "reference_key"},
                "共晶选择只能提交目标和两个稳定编号")
    return payload
