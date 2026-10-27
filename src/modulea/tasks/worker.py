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
    a06 = manifest.get("current", {}).get("A06")
    automatic = bool(a06 and workflow.run(manifest, a06).get("config", {}).get("schema_version") in ("A06.automatic.1", "A06.automatic.2", "A06.automatic.3"))
    # 换成完整扩展名单后，旧批次依然归档，接续不能卡在旧批次的不可用复核栏。
    if automatic and not workflow.active(manifest, a06):
        try:
            scope = workflow.validate_extended_scope(task['study_id'], manifest)
        except ValueError as error:
            manager.update(task['task_id'], progress={'step_zh':'等待完整扩展名单及上游复核','done':1,'total':1})
            return '旧对接批次已失效并保留；请先核对扩展名单或上游：' + str(error)
        manager.update(task['task_id'], progress={'step_zh':'扩展名单已接齐，等待A06_PREP连接与一次执行确认','done':1,'total':1})
        return f"已确认{scope['selected_count']}个扩展成分，请在A06_PREP连接本研究全部对象并一次确认执行。旧批次保留，未重新评分或继承旧授权。"
    if a06 and (automatic or workflow.run(manifest, a06).get("config", {}).get("schema_version") == "A06.trial.handoff.1"):
        with workflow.handoff_read_cache():
            approved = workflow.approved(manifest, a06)
        if not approved:
            manager.update(task["task_id"], progress={"step_zh": "等待A06独立复核", "done": 1, "total": 1})
            return "本批自动对接尚待A06独立复核，未生成报告或启动计算。" if automatic else "本批扩展A06尚待正式复核，未生成报告或启动计算。"
        # 接续只补缺失或失效的报告，不替换正在复核或已经发布的同源版本。
        with workflow.handoff_read_cache():
            a05 = manifest["current"].get("A05")
            if not a05 or not workflow.approved(manifest, a05):
                manager.update(task["task_id"], progress={"step_zh": "等待A05独立复核", "done": 1, "total": 1})
                return "本批A06已通过；请完成A05复核后再生成双报告，未启动计算。"
            a07 = manifest["current"].get("A07")
            if a07 and workflow.active(manifest, a07):
                published = workflow.approved(manifest, a07)
                step = "流程完成，保留已发布双报告" if published else "保留已有双报告，等待A07独立复核"
                manager.update(task["task_id"], progress={"step_zh": step, "done": 1, "total": 1})
                return step + "；未重复生成报告，未重新运行对接。"
            if workflow.ranked_maps_for(manifest, a05) is None:
                tables = workflow.result(manifest, a05)["tables"]
                if tables.get("kegg_p_top10") or tables.get("kegg_count_top10"):
                    manager.update(task["task_id"], progress={"step_zh": "等待A05首位命中图", "done": 1, "total": 1})
                    return "双报告尚需当前A05首位命中图；请在A05生成图件后继续，未启动对接或生成部分报告。"
        from report_dispatch import run_reports
        result = run_reports(workflow, task["study_id"], manifest["current"].get("A07", ""), "用户通过自动A06后接续双报告" if automatic else "用户通过扩展A06后接续双报告")
        manager.update(task["task_id"], progress={"step_zh": "双报告已生成，等待A07独立复核", "done": 1, "total": 1})
        return ("本批自动评分已接入新双报告：" if automatic else "本批扩展评分已接入新双报告：") + result["run_id"] + "；未重算Vina，未自动批准A07。"
    prep=manifest.get("current",{}).get("A06_PREP")
    selection = manifest['current'].get('A03_SELECT')
    a04 = manifest['current'].get('A04')
    if not a06 and not prep and selection and a04 and workflow.approved(manifest, selection) and workflow.approved(manifest, a04):
        try:
            scope = workflow.validate_extended_scope(task['study_id'], manifest)
        except ValueError as error:
            return '请先核对完整扩展名单：' + str(error)
        return f"扩展名单{scope['selected_count']}项已复核，请进入A06_PREP连接资料并一次确认计算；尚未自动准备或评分。"
    if prep and workflow.run(manifest,prep).get("config",{}).get("version") in (
            "A06.coverage.execution.4","A06.coverage.confirmed.4"):
        manager.update(task["task_id"],progress={"step_zh":"已停在明确批量计算授权关口","done":1,"total":1})
        return "本轮A06技术／采用资料已留存；真实批量结合能仍待用户明确授权，未启动计算。"
    a04 = manifest.get("current", {}).get("A04")
    if a04 and workflow.active(manifest, a04) and workflow.result(manifest, a04).get("summary", {}).get("docking_candidate_source_pending"):
        # 新名单已归档时准确显示准备关口，仍不调用旧第一轮准备入口。
        from ..core.docking_workflow import candidate_context
        candidates=candidate_context(workflow,manifest)
        source_note="两梯队候选已归档；新版结构方案仍待微调与独立核查，未启动A06。" if candidates and candidates["data"] else "双分支PPI的候选分组尚未生成；请前往A06准备页，未启动A06。"
        # PPI与富集保持独立；可以重试未完成的A05，但始终不进入A06。
        a05 = manifest.get("current", {}).get("A05")
        if not a05 or not workflow.active(manifest, a05):
            run_enrichment(workflow, task["study_id"], manifest["current"]["A03"], a05 or "", "用户明确继续：生成独立A05分支")
            manager.update(task["task_id"], progress={"step_zh": "新A05图表已归档，等待人工复核", "done": 1, "total": 1})
            return "A05已生成待复核；"+source_note
        manager.update(task["task_id"],progress={"step_zh":"已停在A06方案核查关口","done":1,"total":1})
        return source_note
    # 复用冻结编排，仅将该科学子进程的PPI入口显式绑定为新版本；不修改旧模块全局。
    from types import FunctionType
    from ppi_dispatch import run_ppi
    from science_modules.a01.collection_flow import run_components
    def source_progress(text):
        """自动接续也展示真实采集/重试进度，不再长时间只显示第0步。"""
        manager.update(task["task_id"], progress={"step_zh": text, "done": 0, "total": 1})
        print(text, flush=True)
    def collect_components(*args, **kwargs):
        return run_components(*args, **kwargs, progress=source_progress)
    continuation = FunctionType(continue_after_review.__code__, dict(continue_after_review.__globals__, run_ppi=run_ppi, run_enrichment=run_enrichment, run_components=collect_components))
    result = continuation(workflow, task["study_id"])
    print("自动接续结果：", result, flush=True)
    manager.update(task["task_id"], progress={"step_zh": "已停在下一人工关口", "done": 1, "total": 1})
    # 分支错误不隐藏：message() 会把每个分支的失败原因写进说明
    return message(result)


# 上传解析只在科学子进程运行；从已绑定的私有暂存文件读取原始字节。
def run_normalization(settings: Settings, task: dict, manager: TaskManager) -> str:
    """调用既有标准化入口，预览与发布均不替用户整体复核。"""
    from ..core.normalization_bridge import execute
    manager.update(task["task_id"], progress={"step_zh": "核对当前范围、映射证据与输入版本", "done": 0, "total": 1})
    message, _ = execute(settings, full_workflow(settings.data_root), task["study_id"], json.loads(task["payload"]))
    manager.update(task["task_id"], progress={"step_zh": message, "done": 1, "total": 1})
    return message


def run_a02_scope_review(settings: Settings, task: dict, manager: TaskManager) -> str:
    """沿用统一范围批次入口，不代签研究复核。"""
    from ..core.disease_scope import review_scope
    manager.update(task["task_id"], progress={"step_zh": "核对来源身份并保存范围决定", "done": 0, "total": 1})
    result = review_scope(full_workflow(settings.data_root), task["study_id"], json.loads(task["payload"]))
    manager.update(task["task_id"], progress={"step_zh": "范围决定已留存，等待身份核查和整体复核", "done": 1, "total": 1})
    return "已保存范围核验并生成新A02：" + result["run_id"] + "；未批准或启动下游。"


def run_a02_sources_retry(settings: Settings, task: dict, manager: TaskManager) -> str:
    """只重取失败的疾病来源，不推进下游。"""
    from a02_retry_sources import retry_sources
    manager.update(task["task_id"], progress={"step_zh": "重取选定失败来源", "done": 0, "total": 1})
    result = retry_sources(full_workflow(settings.data_root), task["study_id"], json.loads(task["payload"]))
    failures = result["summary"].get("失败来源库数", 0)
    manager.update(task["task_id"], progress={"step_zh": "新A02已归档，等待人工核查", "done": 1, "total": 1})
    return "已生成新A02候选：" + result["run_id"] + "；仍失败来源数：" + str(failures) + "。未自动批准或启动下游。"


def run_source_upload(settings: Settings, task: dict, manager: TaskManager) -> str:
    payload = json.loads(task.get("payload") or "{}")
    source = dict(payload["source"])
    path = (settings.runtime_dir / "upload_queue" / payload["blob_name"]).resolve()
    if not path.is_relative_to((settings.runtime_dir / "upload_queue").resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != payload["blob_sha256"]:
        raise ValueError("上传暂存文件校验失败，请重新上传")
    source["data"] = path.read_bytes()
    if source["format"] == "omim_xlsx":
        source["format"] = "omim_xlsx_v2"  # 新上传升级；既有历史来源仍按原格式读取。
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
    from science_modules.a01.collection_flow import process
    payload = json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"], progress={"step_zh": "按现有规则整理三库与统一身份", "done": 0, "total": 1})
    result = process(full_workflow(settings.data_root), task["study_id"], payload["expected_a00"], payload["expected_run"], payload["expected_staging"], payload["reason"])
    manager.update(task["task_id"], progress={"step_zh": "新A01结果待独立复核", "done": 1, "total": 1})
    return "已生成新的三库A01：" + result["run_id"] + "；身份问题保留，未自动批准或运行下游。"


def run_a01_acquire(settings, task, manager):
    """只获取并暂存原件；完整整理和批准是后续明确动作。"""
    from science_modules.a01.collection_flow import acquire_sources
    payload = json.loads(task["payload"])
    def progress(text):
        manager.update(task["task_id"], progress={"step_zh": text, "done": 0, "total": 1})
        print(text, flush=True)
    results = acquire_sources(full_workflow(settings.data_root), task["study_id"], payload["expected_a00"], payload["expected_run"],
                              payload["expected_staging"], settings.data_root / "studies" / task["study_id"] / "raw/A01_acquisition" / payload.get("acquisition_id", task["task_id"]),
                              payload["databases"], progress)
    failed = [r for r in results if r["status"] != "success"]
    if failed:
        raise ValueError("；".join(r["database"] + "：" + r["message_zh"] for r in failed) + "；成功库原件已保留，请补齐失败库，未回退单库。")
    return "所选库已获取并通过统一来源校验；请整理三库结果，当前A02保持。"


def run_a01_resolve(settings, task, manager):
    """只保存明确处理决定并追加待复核运行，不签署整体批准。"""
    from science_modules.a01.collection_flow import process
    p = json.loads(task["payload"])
    result = process(full_workflow(settings.data_root), task["study_id"], p["expected_a00"], p["expected_run"], p["expected_staging"], p["note"], p)
    return "A01核验处理已另存：" + result["run_id"] + "，请独立整体复核。A02未改变。"


def run_a02_mapping_preview(settings, task, manager):
    """候选与响应仅留独立目录；A02及其人工决定保持。"""
    from science_modules.a02.disease_candidates import preview
    from contracts import require
    p = json.loads(task["payload"])
    w = full_workflow(settings.data_root)
    m = w.load(task["study_id"])
    require(not m.get("trashed") and m["current"].get("A00") == p["expected_a00"] and m["current"].get("A02", "") == p["expected_run"], "研究版本已改变")
    folder = w.location(task["study_id"]) / "raw/A02_mapping_previews" / task["task_id"]
    preview(w, task["study_id"], p["databases"], folder,
            progress=lambda text: manager.update(task["task_id"], progress={"step_zh": text, "done": 0, "total": 1}))
    from storage import file_record, write_json
    write_json(folder / "index.json", {"file": file_record(w.location(task["study_id"]), folder / "preview.json", "disease_mapping_preview")})
    return "疾病映射候选已保存；仅供核验，当前A02原件、集合和批准未改变。"

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

# 只整理归档名单；不下载受体、准备配体或调用Vina。
def run_a06_candidates(settings: Settings,task: dict,manager: TaskManager) -> str:
    payload=json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"],progress={"step_zh":"核验已批准A04并归档两梯队","done":0,"total":1})
    data=full_workflow(settings.data_root).generate_candidates(task["study_id"],payload)
    manager.update(task["task_id"],progress={"step_zh":"候选已留存，真实对接未启动","done":1,"total":1})
    return f"候选分组已生成：A组{data['counts']['a']}个、B组{data['counts']['b']}个；结构质控仍需独立核查。"

# 两个新任务只留存人工决定，不调用prepare/execute或自动接续。
def run_a03_selection(settings,task,manager):
    payload=json.loads(task.get("payload") or "{}")
    result=full_workflow(settings.data_root).save_selection(task["study_id"],payload)
    return "对接成分选择已保存；请在复核栏独立确认，不会自动运行对接。"

def run_a04_plan_selection(settings, task, manager):
    """从已批准A04归档复算受体名单，停在独立核查关口。"""
    payload = json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"], progress={"step_zh": "核验A04方案与完整指标表", "done": 0, "total": 1})
    result = full_workflow(settings.data_root).save_analysis_plan_a04_selection(task["study_id"], payload)
    manager.update(task["task_id"], progress={"step_zh": "受体选择已归档，等待独立核查", "done": 1, "total": 1})
    return "A04方案受体选择已归档：" + result["record"]["selection_id"] + "；未批准或启动A06。"

def run_a06_plan_input(settings, task, manager):
    """锁内核对两份独立选择并归档准备输入，不启动结构工具。"""
    payload = json.loads(task.get("payload") or "{}")
    manager.update(task["task_id"], progress={"step_zh": "核验成分、受体和复核版本", "done": 0, "total": 1})
    result = full_workflow(settings.data_root).save_analysis_plan_a06_preparation_input(
        task["study_id"], payload)
    manager.update(task["task_id"], progress={"step_zh": "新版准备输入已归档，结构准备仍未开始", "done": 1, "total": 1})
    return "A06准备输入已归档：" + result["record"]["input_id"] + "；未准备结构或启动Vina。"

def run_a06_plan(settings,task,manager):
    payload=json.loads(task.get("payload") or "{}")
    data=full_workflow(settings.data_root).save_two_pass(task["study_id"],payload)
    return "两遍方案已确认并留存；真实准备、重对接与Vina未启动。"

# 获明确授权的质控走隔离科学子进程；暂停在实际证据核查，不计算研究成分组合。
def run_a06_quality(settings, task, manager):
    """父任务记录进度、支持整树取消；实际科学依赖由-I -S子进程加载。"""
    import subprocess
    import sys
    payload = json.loads(task.get("payload") or "{}")
    folder = settings.runtime_dir / "a06_quality_requests" / task["task_id"]
    folder.mkdir(parents=True, exist_ok=False)
    request, output = folder / "request.json", folder / "result.json"
    request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable, "-I", "-S", "-B",
               str(settings.project_root / ("tools/run_a06_coverage.py" if task["kind"]=="a06_coverage" else "tools/run_a06_quality.py")),
               "--request-file", str(request), "--result-file", str(output),
               "--tools-root", payload["tools_root"], "--data-root", str(settings.data_root),
               "--study", task["study_id"]]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               env=dict(os.environ,TEMP=str(folder),TMP=str(folder),
                                        PYTHONDONTWRITEBYTECODE="1",PYTHONUTF8="1"))
    for line in process.stdout:
        print(line, end="", flush=True)
        if line.startswith("PROGRESS "):
            manager.update(task["task_id"], progress={"step_zh":line[9:].strip(), "done":0, "total":1})
    code = process.wait()
    if code != 0 or not output.is_file():
        raise ValueError("隔离质控执行未完整结束；请查看任务日志，已有原件和运行均保留")
    result = json.loads(output.read_text(encoding="utf-8"))
    summary = result["summary"]
    manager.update(task["task_id"], progress={"step_zh":"本轮质控证据已归档，等待集中核查", "done":1, "total":1})
    return ("新版A06准备已归档："+result["run_id"]+"；严格通过"
            +str(summary["严格质控通过受体数"])+"个，待集中核查"
            +str(summary["等待集中核查受体数"])+"个；未自动批准、未计算批量结合能。")

def run_a06_coverage_confirm(settings,task,manager):
    """后台追加采用确认准备版本，独立结果审批和批量执行仍关闭。"""
    data=full_workflow(settings.data_root).save_coverage_selection(
        task["study_id"],json.loads(task.get("payload") or "{}"))
    return data["message_zh"]

def run_a06_trial(settings, task, manager):
    """真实试算的后台包装；区域进度由科学子进程回报，支持日志与整树取消。"""
    import subprocess
    import sys
    payload = json.loads(task.get("payload") or "{}")
    payload["task_id"] = task["task_id"]
    folder = settings.runtime_dir / "a06_trial_requests" / task["task_id"]
    folder.mkdir(parents=True, exist_ok=False)
    request, output = folder / "request.json", folder / "result.json"
    request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable, "-I", "-S", "-B", str(settings.project_root / "tools/run_a06_trial.py"),
               "--request-file", str(request), "--result-file", str(output),
               "--tools-root", payload["tools_root"], "--data-root", str(settings.data_root),
               "--study", task["study_id"]]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               env=dict(os.environ, TEMP=str(folder), TMP=str(folder),
                                        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
    for line in process.stdout:
        print(line, end="", flush=True)
        if line.startswith("PROGRESS "):
            state = json.loads(line[9:])
            manager.update(task["task_id"], progress={"step_zh": state["step_zh"],
                "done": state["pairs_done"], "total": state["pairs_total"],
                "regions_done": state["regions_done"], "regions_total": state["regions_total"]})
    if process.wait() != 0 or not output.is_file():
        workflow = full_workflow(settings.data_root)
        for record in workflow.load(task["study_id"]).get("docking_trial_records", []):
            if record.get("payload", {}).get("task_id") == task["task_id"]:
                workflow.stop_trial(task["study_id"], record["trial_id"], "后台试算失败，原始输出保留")
        raise ValueError("试算未完整结束，原始资料及失败输出保留，请查看日志")
    result = json.loads(output.read_text(encoding="utf-8"))
    return "试算已归档：" + result["trial_id"] + "；真实评分" + str(result["summary"]["completed"]) + "/225，未批准正式科研结果"


HANDLERS = {"a02_scope_review": run_a02_scope_review, "a02_sources_retry": run_a02_sources_retry, "a06_trial":run_a06_trial,"a06_coverage_confirm":run_a06_coverage_confirm,"a06_coverage":run_a06_quality,"a06_quality":run_a06_quality,"a03_selection":run_a03_selection,"a06_plan":run_a06_plan,"a06_candidates": run_a06_candidates, "a05_display": run_a05_display, "a04_identity": run_a04_identity, "a04_ppi": run_a04_ppi, "continue": run_continue, "source_upload": run_source_upload, "a01_sources": run_a01_sources}
HANDLERS["a04_plan_selection"] = run_a04_plan_selection
HANDLERS["a06_plan_input"] = run_a06_plan_input


from .drawing import run_figure, run_packages, run_bundle
from .automatic_docking import execute as run_automatic
from .automatic_display import run as run_automatic_display
HANDLERS["a06_display"] = run_automatic_display
HANDLERS.update({"a06_auto_connect": run_automatic, "a06_auto_run": run_automatic, "a06_auto_start": run_automatic, "a06_resume": run_automatic})
from .ranked_pathway_maps import run_ranked_maps
HANDLERS["a05_pathway_maps"] = run_ranked_maps
HANDLERS.update({"normalization_preview": run_normalization, "normalization_publish": run_normalization})
HANDLERS.update(a01_acquire=run_a01_acquire, a01_resolve=run_a01_resolve, a02_mapping_preview=run_a02_mapping_preview)
HANDLERS.update({"a06_figure": run_figure, "a06_pair_packages": run_packages, "a06_pair_bundle": run_bundle})


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
