"""一次授权后台任务包装；计算只在固定依赖隔离子进程执行。"""
import json
import os
import subprocess
import sys


def execute(settings, task, manager):
    """任务队列防止同研究并发，取消沿用管理器的整树终止。"""
    if not settings.science_tools_root:
        raise ValueError("未配置固定对接工具目录 science_tools_root")
    folder = settings.runtime_dir / "a06_automatic_requests" / task["task_id"]
    folder.mkdir(parents=True, exist_ok=False)
    request, output = folder / "request.json", folder / "result.json"
    request.write_text(task["payload"], encoding="utf-8")
    command = [sys.executable, "-I", "-S", "-B", str(settings.project_root / "tools/run_a06_automatic.py"),
               "--mode", {"a06_auto_connect": "connect", "a06_auto_start": "connect-run"}.get(task["kind"], "run"),
               "--request-file", str(request), "--result-file", str(output),
               "--tools-root", str(settings.science_tools_root), "--data-root", str(settings.data_root), "--study", task["study_id"]]
    if settings.science_repair_packages:
        command += ["--repair-packages", str(settings.science_repair_packages)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=dict(os.environ,
        TEMP=str(folder), TMP=str(folder), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
    for line in process.stdout:
        print(line, end="", flush=True)
        if line.startswith("PROGRESS "):
            manager.update(task["task_id"], progress={"step_zh": line[9:].strip(), "done": 0, "total": 1})
    if process.wait() != 0 or not output.is_file():
        raise ValueError("自动对接阶段未完整结束；原件和已产生证据保留，请查看任务日志")
    message = json.loads(output.read_text("utf-8"))["message_zh"]
    manager.update(task["task_id"], progress={"step_zh": message, "done": 1, "total": 1})
    return message
