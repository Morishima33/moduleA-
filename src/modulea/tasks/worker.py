"""后台任务子进程的执行入口（python -m modulea task-run <task_id>）。

目前只有一种任务：continue —— 调用科学内核 auto_continue.continue_after_review，
按既定规则把研究推进到下一个人工关口（与原网页“保存并继续”完全相同的逻辑），从不代签任何模块。
新增任务类型时：在 manager.KINDS 登记中文名，在 HANDLERS 登记执行函数。
"""

from __future__ import annotations

import os
import traceback

from ..config import Settings
from ..core.kernel import full_workflow
from .manager import TaskManager



def run_continue(settings: Settings, task: dict, manager: TaskManager) -> str:
    """自动接续：导入完整科学依赖，生成下一批待复核结果。返回给用户看的中文说明。"""
    from auto_continue import continue_after_review, message

    manager.update(task["task_id"], progress={"step_zh": "按依赖顺序检查并生成下一批结果", "done": 0, "total": 1})
    workflow = full_workflow(settings.data_root)
    result = continue_after_review(workflow, task["study_id"])
    print("自动接续结果：", result, flush=True)
    manager.update(task["task_id"], progress={"step_zh": "已停在下一人工关口", "done": 1, "total": 1})
    # 分支错误不隐藏：message() 会把每个分支的失败原因写进说明
    return message(result)


HANDLERS = {"continue": run_continue}


def run_task(settings: Settings, task_id: str) -> int:
    manager = TaskManager(settings)
    task = manager._raw(task_id)
    if not task:
        print("找不到任务：" + task_id, flush=True)
        return 2
    if not manager.claim(task_id, os.getpid()):
        print("任务已取消、中断或已被认领，不重复执行：" + task_id, flush=True)
        return 1
    try:
        text = HANDLERS[task["kind"]](settings, task, manager)
        manager.finish(task_id, "succeeded", message_zh=text)
        return 0
    except ModuleNotFoundError as error:  # 科学依赖缺失：说明缺什么、怎么处理
        traceback.print_exc()
        manager.finish(task_id, "failed",
                       error_zh=f"后台计算所用的 Python 缺少科学依赖 {error.name}；请在 config/local.toml 的 science_python 指定已安装科学依赖的解释器后重试。已有结果未受影响。")
        return 1
    except Exception as error:  # 任务失败要如实记录，不伪装成空结果
        traceback.print_exc()
        manager.finish(task_id, "failed", error_zh=f"{type(error).__name__}: {error}")
        return 1
