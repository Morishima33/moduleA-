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
    from science_modules.a05.compact_flow import run_enrichment

    manager.update(task["task_id"], progress={"step_zh": "按依赖顺序检查并生成下一批结果", "done": 0, "total": 1})
    workflow = full_workflow(settings.data_root)
    # 新双分支的对接来源未确认时停下，不启动旧候选准备和计算。
    manifest = workflow.load(task["study_id"])
    a04 = manifest.get("current", {}).get("A04")
    if a04 and workflow.active(manifest, a04) and workflow.result(manifest, a04).get("summary", {}).get("docking_candidate_source_pending"):
        # PPI与富集保持独立；可以重试未完成的A05，但始终不进入A06。
        a05 = manifest.get("current", {}).get("A05")
        if not a05 or not workflow.active(manifest, a05):
            run_enrichment(workflow, task["study_id"], manifest["current"]["A03"], a05 or "", "用户明确继续：生成独立A05分支")
            manager.update(task["task_id"], progress={"step_zh": "新A05图表已归档，等待人工复核", "done": 1, "total": 1})
            return "A05已生成待复核；双分支PPI的对接候选来源未确认，未启动A06。"
        return "双分支PPI的对接候选来源尚未确认；已停下，未启动A06。"
    # 复用冻结编排，仅将该科学子进程的PPI入口显式绑定为新版本；不修改旧模块全局。
    from types import FunctionType
    from ppi_dispatch import run_ppi
    continuation = FunctionType(continue_after_review.__code__, dict(continue_after_review.__globals__, run_ppi=run_ppi, run_enrichment=run_enrichment))
    result = continuation(workflow, task["study_id"])
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

# 只生成本次绑定A03的PPI，停止在A04复核，不推进其他科学模块。
def run_a04_ppi(settings: Settings, task: dict, manager: TaskManager) -> str:
    from ppi_dispatch import run_ppi
    payload = json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"], progress={"step_zh": "获取当前交集的STRING网络并进行双分支筛选", "done": 0, "total": 1})
    workflow = full_workflow(settings.data_root)
    if payload.get("reuse_source_run"):
        # 图件修复沿用已核验的同研究、同A03原始来源；不能借用另一研究网络。
        from contracts import require
        from storage import read_json, verified_file
        manifest = workflow.load(task["study_id"])
        require(payload["reuse_source_run"] == payload["expected_a04"], "图件修订来源与当前A04不一致")
        previous = workflow.run(manifest, payload["reuse_source_run"])
        require(previous["module_id"] == "A04" and previous["parent_runs"].get("A03") == payload["expected_a03"], "图件修订来源不属于本次交集")
        source = read_json(verified_file(workflow.location(task["study_id"]), previous["inputs"]["source_file"]))
        result = run_ppi(workflow, task["study_id"], payload["expected_a03"], payload["expected_a04"], payload["reason"], bundle=source)
    else:
        result = run_ppi(workflow, task["study_id"], payload["expected_a03"], payload["expected_a04"], payload["reason"])
    manager.update(task["task_id"], progress={"step_zh": "新A04图表已归档，等待人工复核", "done": 1, "total": 1})
    pending = result["summary"].get("身份待核验数", 0)
    return f"新A04已归档：{result['run_id']}；{pending}个身份待核验。未自动批准，请核对本轮图表及范围。"


# 人工方案留存后补查，失败保留原结果，只生成A04。
def run_a04_identity(settings: Settings, task: dict, manager: TaskManager) -> str:
    from science_modules.a04.identity_flow import run_identity

    payload = json.loads(task.get("payload") or "{}")
    manager.update(
        task["task_id"],
        progress={"step_zh": "留存人工方案并按官方稳定编号补查STRING", "done": 0, "total": 1},
    )
    result = run_identity(full_workflow(settings.data_root), task["study_id"], payload)
    manager.update(
        task["task_id"],
        progress={"step_zh": "身份方案已应用到新的待复核A04", "done": 1, "total": 1},
    )
    count = result["summary"].get("身份待核验数", 0)
    return f"身份补查方案已保存并应用，生成新A04：{result['run_id']}；仍有{count}项待核验。旧版本保留，新结果未自动批准；请核查图表和剩余问题。"

# A05展示确认只重绘归档，不重新计算ORA、不代签或启动后续模块。
def run_a05_display(settings: Settings, task: dict, manager: TaskManager) -> str:
    from science_modules.a05.compact_flow import apply_confirmation
    payload = json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"], progress={"step_zh":"保存人工确认并生成同源图表","done":0,"total":1})
    result = apply_confirmation(full_workflow(settings.data_root),task["study_id"],payload)
    manager.update(task["task_id"], progress={"step_zh":"新展示已归档，仍须独立复核A05","done":1,"total":1})
    return "A05展示确认已保存并应用；生成新版本："+result["run_id"]+"。未重新计算ORA、未批准A05或启动A06。"

HANDLERS = {"a05_display": run_a05_display, "a04_identity": run_a04_identity, "a04_ppi": run_a04_ppi, "continue": run_continue, "source_upload": run_source_upload, "a01_sources": run_a01_sources}


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
