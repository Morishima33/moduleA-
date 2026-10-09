"""后台任务子进程的执行入口（python -m modulea task-run <task_id>）。

支持自动接续、分库上传解析和A01三库整理；continue 调用 auto_continue.continue_after_review，
按既定规则把研究推进到下一个人工关口（与原网页“保存并继续”完全相同的逻辑），从不代签任何模块。
新增任务类型时：在 manager.KINDS 登记中文名，在 HANDLERS 登记执行函数。
"""

from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
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


# 上传解析只在科学子进程运行；从已绑定的私有暂存文件读取原始字节。
def run_source_upload(settings: Settings, task: dict, manager: TaskManager) -> str:
    payload = json.loads(task.get("payload") or "{}")
    source = dict(payload["source"])
    path = (settings.runtime_dir / "upload_queue" / payload["blob_name"]).resolve()
    if not path.is_relative_to((settings.runtime_dir / "upload_queue").resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != payload["blob_sha256"]:
        raise ValueError("上传暂存文件校验失败，请重新上传")
    source["data"] = path.read_bytes()
    workflow = full_workflow(settings.data_root)
    manager.update(task["task_id"], progress={"step_zh": "校验并归档所选库资料", "done": 0, "total": 1})
    if payload["module_id"] == "A02":
        from disease import run_disease
        result = run_disease(workflow, task["study_id"], payload["expected_a00"], payload["expected_run"], [source], payload["reason"], profile_version=payload["source_profile"])
        text = "所选库资料已归档，生成新的A02候选：" + result["run_id"] + "；请核查范围与身份，未自动批准。"
    else:
        from science_modules.a01.uploads import stage
        stage(workflow, task["study_id"], payload["expected_a00"], payload["expected_run"], payload["expected_staging"], source, settings.runtime_dir / "source_parse")
        text = "所选库资料已校验并独立留存；当前A01结果未改变，完整三库齐备后可另行整理。"
    manager.update(task["task_id"], progress={"step_zh": "资料已留存，等待人工核查", "done": 1, "total": 1})
    return text

# 完整来源整理也走已有后台任务与Workflow，不自动推进到A03。
def run_a01_sources(settings: Settings, task: dict, manager: TaskManager) -> str:
    from science_modules.a01.uploads import process
    payload = json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"], progress={"step_zh": "按现有规则整理三库与统一身份", "done": 0, "total": 1})
    result = process(full_workflow(settings.data_root), task["study_id"], payload["expected_a00"], payload["expected_run"], payload["expected_staging"], payload["reason"])
    manager.update(task["task_id"], progress={"step_zh": "新A01结果待独立复核", "done": 1, "total": 1})
    return "已生成新的三库A01：" + result["run_id"] + "；身份问题保留，未自动批准或运行下游。"

HANDLERS = {"continue": run_continue, "source_upload": run_source_upload, "a01_sources": run_a01_sources}


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
