"""隔离执行新方案A06实际准备；工具只从本机配置传入。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--tools-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--study", required=True)
    args = parser.parse_args()
    from docking_runtime import activate
    runtime = activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / "Lib/site-packages"))
    from modulea.core.kernel import full_workflow
    from science_modules.a06.plan_preparation import run
    result = run(full_workflow(args.data_root), args.study,
                 json.loads(args.request_file.read_text(encoding="utf-8")),
                 args.tools_root, lambda message: print("PROGRESS " + message, flush=True))
    args.result_file.write_text(json.dumps({"run_id": result["run_id"],
        "summary": result["summary"], "runtime": runtime}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
