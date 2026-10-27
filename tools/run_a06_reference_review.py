"""隔离执行新版A06共晶参考证据复核；不计算成分×受体组合。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    """科学依赖和工具根只由服务器传入，研究请求不能覆盖。"""
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
    from science_modules.a06.reference_review import run
    payload = json.loads(args.request_file.read_text(encoding="utf-8"))
    result = run(full_workflow(args.data_root), args.study, payload, args.tools_root,
                 lambda message: print("PROGRESS " + message, flush=True))
    args.result_file.write_text(json.dumps({"review_id": result["review"]["review_id"],
        "summary": result["summary"], "runtime": runtime}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
