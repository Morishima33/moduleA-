"""固定科学依赖的15×15试算入口；真实执行与界面进程隔离。"""

import argparse
import json
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    """任务只读取服务端登记的研究与版本绑定，不允许传入任意受体名单。"""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    for name in ("request-file", "result-file", "tools-root", "data-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--study", required=True)
    args = parser.parse_args()
    from docking_runtime import activate

    activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / "Lib/site-packages"))
    from modulea.core.kernel import full_workflow
    from science_modules.a06.trial_compute import run

    payload = json.loads(args.request_file.read_text("utf-8"))
    tools = payload.pop("tools_root")
    repair = payload.pop("repair_packages")
    packet = run(
        full_workflow(args.data_root),
        args.study,
        payload,
        Path(tools),
        Path(repair),
        CODE,
        lambda s: print("PROGRESS " + s, flush=True),
    )
    args.result_file.write_text(
        json.dumps(
            {"trial_id": packet["trial_id"], "summary": packet["summary"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
