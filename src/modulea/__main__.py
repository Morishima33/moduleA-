"""命令行入口：python -m modulea <命令>（需把 src 加入 PYTHONPATH，start 脚本已处理）。

命令：
  serve     启动本机工作台（JSON 接口 + 预构建前端）
  doctor    检查本机环境：数据目录、研究数量、归档核验、科学依赖是否齐备
  task-run  后台任务子进程入口（由任务管理器调用，用户无需手动执行）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from .config import load_settings

DEFAULT_STATIC = Path(__file__).resolve().parent / "static"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modulea", description="Module A 网络药理学与分子对接初筛工作台")
    parser.add_argument("--data-root", help="studies/ 与 references/ 所在目录；默认项目根目录")
    parser.add_argument("--runtime-dir", help="任务索引与日志目录；默认 <项目根>/.runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动本机工作台")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--static-dir", help="预构建前端目录；默认 src/modulea/static")
    serve.add_argument("--allow-origin", help="允许跨源访问的前端开发地址，逗号分隔，例如 http://localhost:5173")
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--check", action="store_true", help="只检查能否启动，随即退出")

    sub.add_parser("doctor", help="检查本机环境")
    task = sub.add_parser("task-run", help="（内部）执行一个后台任务")
    task.add_argument("task_id")

    args = parser.parse_args(argv)
    overrides = {"data_root": args.data_root, "runtime_dir": args.runtime_dir}
    if args.command == "serve":
        overrides["static_dir"] = args.static_dir or (str(DEFAULT_STATIC) if (DEFAULT_STATIC / "index.html").exists() else None)
        overrides["allowed_origins"] = args.allow_origin
    settings = load_settings(**overrides)

    if args.command == "serve":
        from .api.server import create_server
        server, _ = create_server(settings, args.port)
        address = f"http://127.0.0.1:{server.server_port}"
        print("Module A 工作台：" + address, flush=True)
        print("数据目录：" + str(settings.data_root), flush=True)
        if args.check:
            server.server_close()
            print("启动检查通过。", flush=True)
            return 0
        if not args.no_browser:
            webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("工作台已停止；已保存的研究资料仍在 studies 目录。", flush=True)
        finally:
            server.server_close()
        return 0

    if args.command == "doctor":
        return doctor(settings)

    if args.command == "task-run":
        from .tasks.worker import run_task
        return run_task(settings, args.task_id)
    return 1


SCIENCE_DEPS = ("networkx", "docx", "rdkit", "meeko", "gemmi", "numpy")


def probe_science_python(executable: str) -> dict:
    """只读探测配置的科学解释器，不使用服务解释器的依赖结果。"""
    script = """import sys, json, importlib.util
names = %r
found = {}
for name in names:
    try:
        found[name] = importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        found[name] = False
print(json.dumps({"executable": sys.executable, "version": list(sys.version_info[:3]), "dependencies": found}))
""" % (SCIENCE_DEPS,)
    try:
        result = subprocess.run([executable, "-c", script], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, ValueError) as error:
        return {"passed": False, "error_zh": f"科学解释器无法启动（{type(error).__name__}）；请检查 science_python。"}
    except subprocess.TimeoutExpired:
        return {"passed": False, "error_zh": "科学解释器探测超时（15 秒）。"}
    if result.returncode != 0:
        return {"passed": False, "error_zh": f"科学解释器探测失败，退出码 {result.returncode}。"}
    try:
        payload = json.loads(result.stdout)
        version, dependencies = payload["version"], payload["dependencies"]
        if (not isinstance(version, list) or len(version) < 2 or
                any(type(v) is not int for v in version) or
                not isinstance(payload["executable"], str) or
                any(type(dependencies[name]) is not bool for name in SCIENCE_DEPS)):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return {"passed": False, "error_zh": "科学解释器探测返回了无效结果。"}
    payload["passed"] = tuple(version[:2]) >= (3, 11) and all(dependencies.values())
    if tuple(version[:2]) < (3, 11):
        payload["error_zh"] = "后台任务需要 Python 3.11 或更新版本。"
    return payload


def doctor(settings) -> int:
    """环境或归档异常返回非零；缺少科学依赖仍允许只读查看与复核页面。"""
    from .core.kernel import Kernel

    print("项目根目录：", settings.project_root)
    passed = settings.studies_dir.is_dir()
    print("数据目录：  ", settings.data_root, "（存在）" if passed else "（缺少 studies/）")
    print("配置科学解释器：", settings.science_python)
    workflow = Kernel(settings).workflow()
    for trashed in (False, True):
        try:
            studies = workflow.studies(trashed=trashed)
            for manifest in studies:
                try:
                    workflow.view(manifest["study_id"])
                    state = "归档核验通过"
                except Exception as error:
                    passed = False
                    state = "归档未就绪：" + str(error)
                print(f"  研究 {manifest['study_id']}{'（回收站）' if trashed else ''}：{state}")
        except Exception as error:
            passed = False
            print("研究目录读取失败：", str(error))
    probe = probe_science_python(settings.science_python)
    if probe.get("executable"):
        print("实际科学解释器：", probe["executable"], "Python", ".".join(map(str, probe["version"])))
        for name in SCIENCE_DEPS:
            print(f"  科学依赖 {name:<9}：{'已安装' if probe['dependencies'][name] else '缺失（仅影响后台计算）'}")
    if probe.get("error_zh"):
        print(probe["error_zh"])
    return 0 if passed and probe["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
