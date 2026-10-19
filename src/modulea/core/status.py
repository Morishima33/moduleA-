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
    "scope_confirmed": "准备范围已核查（扩展试算）",
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
    if state == "scope_confirmed":
        return ModuleState(state, LABELS[state], None, state, False, False, False)
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
    if state == "stale" and raw.get("preparation_scope"):
        reason = raw["preparation_scope"]["reason_zh"]
        blocked = False
    label=LABELS[code]
    if module_id == "A02" and code == "waiting" and summary.get("资料阶段", "").startswith("候选整理"):
        reason = "范围尚有待核验项，请先保存范围决定，再生成标准化结果。" if summary.get("待范围复核条目数") else "范围决定已保存；尚未生成标准化结果，请在范围表下方完成基因身份核查与标准化，再进行整体复核。"
    if module_id=="A05" and code=="waiting" and summary.get("display_version") in ("A05.display.2","A05.display.3"):
        pending=[]
        if not summary.get("display_exclusions_confirmed"):pending.append("KEGG展示范围确认")
        if not summary.get("display_layout_confirmed"):pending.append("GO/KEGG图表版式确认")
        missing=int(summary.get("display_missing_translation_count") or 0)
        identities=int(summary.get("身份待核验数") or 0)
        if missing:pending.append(f"{missing}个条目中文核译")
        if identities:pending.append(f"{identities}项身份核验")
        label="等待身份核验" if identities else ("等待中文核译" if missing else "等待确认")
        reason="需完成："+ "、".join(pending)+"；请在标题下方处理，随后独立复核A05结果"
    return ModuleState(code, label, reason, state, empty, blocked, can_review)


def unavailable(reason: str) -> ModuleState:
    """研究归档无法通过指纹核验时（例如 LFS 文件尚未下载完），整项研究显示为归档未就绪。"""
    return ModuleState("unavailable", LABELS["unavailable"], reason, "unavailable", False, False, False)
