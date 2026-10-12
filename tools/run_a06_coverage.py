"""隔离第二版A06技术补救执行：只运行已登记授权的准备和质控。"""

import argparse, json, sys
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    """固定依赖、独立过程目录和私有输入；不开放批量结合能参数。"""
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    for flag in ("request-file", "result-file", "tools-root", "data-root"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--study", required=True)
    args = parser.parse_args()
    from docking_runtime import activate

    runtime = activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / "Lib/site-packages"))
    from modulea.core.kernel import full_workflow
    from science_modules.a06.coverage_flow import prepare_coverage

    payload = json.loads(args.request_file.read_text("utf-8"))
    if payload.get("mode") == "final_audit":
        from science_modules.a06.coverage_final_audit import prepare_final_audit

        producer = prepare_final_audit
    elif payload.get("mode") == "refinement":
        from science_modules.a06.coverage_refinement import prepare_refinement

        producer = prepare_refinement
    else:
        producer = prepare_coverage
    result = producer(
        full_workflow(args.data_root),
        args.study,
        payload,
        args.tools_root,
        lambda text: print("PROGRESS " + text, flush=True),
    )
    args.result_file.write_text(
        json.dumps(
            {
                "run_id": result["run_id"],
                "summary": result["summary"],
                "runtime": runtime,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("全部技术证据已归档，等待集中采用确认；未运行批量结合能", flush=True)


if __name__ == "__main__":
    main()
