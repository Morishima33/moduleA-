"""隔离科学环境复验已归档口袋；不联网、不调用预测或评分工具。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    """任务请求仅来自私有暂存，科学依赖和工具根由服务器指定。"""
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
    print("PROGRESS 复核原第二版准备与两次预测证据", flush=True)
    result = full_workflow(args.data_root).publish_analysis_plan_a06_pocket_review(
        args.study, json.loads(args.request_file.read_text(encoding="utf-8")))
    args.result_file.write_text(json.dumps({"run_id": result["run_id"],
        "summary": result["summary"], "runtime": runtime}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
