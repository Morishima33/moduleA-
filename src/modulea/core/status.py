"""把科学内核给出的模块状态，映射为前端统一使用的状态码和中文标签。

科学内核（Workflow.view）的原始状态：
waiting / ready / not_connected / running / stale / failed / awaiting_review / approved / rejected / pending
前端状态码与原型《模块状态样式一览》一一对应：
idle(未开始) running(运行中) failed(执行失败) waiting(等待资料) empty(有效空结果)
review(待你复核) hold(暂存待定) returned(已退回修改) approved(已通过) stale(已失效) published(已发布)
另有 ready(可以开始)、incomplete(未完整提交)、unavailable(归档未就绪) 三个补充状态。

这里只做“翻译”，不改变任何判断：能否复核、能否交给下游，仍以科学内核为准。
"""

from __future__ import annotations

from dataclasses import dataclass

LABELS = {
    "idle": "未开始",
    "ready": "可以开始",
    "running": "运行中",
    "incomplete": "未完整提交",
    "failed": "执行失败",
    "waiting": "等待资料",
    "empty": "有效空结果",
    "review": "待你复核",
    "hold": "暂存待定",
    "returned": "已退回修改",
    "approved": "已通过",
    "stale": "已失效",
    "published": "已发布",
    "unavailable": "归档未就绪",
}


@dataclass
class ModuleState:
    code: str
    label_zh: str
    reason_zh: str | None
    raw_state: str  # 科学内核原始状态，供追溯
    is_empty_result: bool
    handoff_blocked: bool
    can_review: bool  # 是否显示复核栏

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def map_state(module_id: str, raw: dict, task_active: bool = False) -> ModuleState:
    """raw 是 Workflow.view() 返回的单个模块条目。"""
    state = raw["state"]
    result = raw.get("result") or {}
    summary = result.get("summary") or {}
    outcome = result.get("outcome")
    blocked = bool(summary.get("handoff_blocked", False))
    empty = outcome == "empty"
    reason = None

    if state == "waiting":
        code, reason = "idle", "上游尚未全部复核通过"
    elif state in ("ready", "not_connected"):
        code = "ready"
    elif state == "running":
        # 运行没有完整结果：有后台任务在跑就是“运行中”，否则可能是中断留下的未完成运行。
        code = "running" if task_active else "incomplete"
        if code == "incomplete":
            reason = "该运行尚未完整提交结果；若没有后台任务在执行，可能已中断，需要重新运行"
    elif state == "stale":
        code, reason = "stale", "上游已产生新版本或批准已变化，本结果不能再交给下游使用"
    elif state == "failed":
        code = "failed"
    elif state == "awaiting_review":
        code = "waiting" if blocked else ("empty" if empty else "review")
        if blocked:
            reason = "仍有资料、范围或身份问题未处理，暂不能通过"
    elif state == "pending":
        code = "waiting" if blocked else "hold"
    elif state == "rejected":
        code = "returned"
    elif state == "approved":
        # A07 通过即两份正式报告随该修订发布。
        code = "published" if module_id == "A07" else "approved"
    else:
        code, reason = "unavailable", "未知状态：" + str(state)

    can_review = state in ("awaiting_review", "pending", "rejected", "approved")
    return ModuleState(code, LABELS[code], reason, state, empty, blocked, can_review)


def unavailable(reason: str) -> ModuleState:
    """研究归档无法通过指纹核验时（例如 LFS 文件尚未下载完），整项研究显示为归档未就绪。"""
    return ModuleState("unavailable", LABELS["unavailable"], reason, "unavailable", False, False, False)
