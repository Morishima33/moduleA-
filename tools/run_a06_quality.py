"""隔离A06质控子进程：固定科学依赖，只执行已登记授权，不开放批量评分。"""
import argparse
import json
from pathlib import Path
import sys

# Python -I -S启动时显式加载正式代码，不使用用户site或其他项目代码。
CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    """仅接受私有任务请求文件，工具目录由明确配置给出。"""
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
    # 辅助外壳依赖只来自当前独立虚拟环境，固定科学包仍优先于此目录。
    sys.path.append(str(Path(sys.executable).parents[1] / "Lib/site-packages"))
    from modulea.core.kernel import full_workflow
    from science_modules.a06.quality_flow import prepare_quality
    workflow = full_workflow(args.data_root)
    payload = json.loads(args.request_file.read_text(encoding="utf-8"))
    result = prepare_quality(workflow, args.study, payload, args.tools_root,
        lambda text: print("PROGRESS " + text, flush=True))
    args.result_file.write_text(json.dumps({
        "run_id": result["run_id"], "summary": result["summary"], "runtime": runtime,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("质控资料已发布，仍待用户独立核查；未运行批量评分", flush=True)


if __name__ == "__main__":
    main()
