"""接口错误：统一为 {"error": {"code", "message_zh", "details", "retryable"}}。"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message_zh: str, details: dict | None = None, retryable: bool = False):
        super().__init__(message_zh)
        self.status = status
        self.code = code
        self.message_zh = message_zh
        self.details = details or {}
        self.retryable = retryable

    def body(self) -> dict:
        return {"error": {"code": self.code, "message_zh": self.message_zh, "details": self.details, "retryable": self.retryable}}


def from_contract(message: str) -> ApiError:
    """把科学内核的 ContractError 按中文含义归类为接口错误码。"""
    if "刷新" in message or "已更新" in message or "已改变" in message or "已失效" in message:
        return ApiError(409, "STALE_VERSION", message)
    if "回收站" in message:
        return ApiError(423, "TRASHED_READONLY", message)
    if "上游" in message or "不能批准" in message or "候选整理阶段" in message or "通路" in message:
        return ApiError(409, "GATE_BLOCKED", message)
    if "校验失败" in message:
        return ApiError(503, "ARCHIVE_UNAVAILABLE", message, retryable=True)
    return ApiError(422, "VALIDATION_FAILED", message)


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", "找不到：" + what)
