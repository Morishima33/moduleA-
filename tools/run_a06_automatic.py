"""隔离自动连接和一次授权计算；固定依赖，来源目录只能由服务器配置。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def main():
    """读取私有请求，执行单一阶段；不提交任何科研批准。"""
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    for name in ("request-file", "result-file", "tools-root", "data-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--repair-packages", type=Path)
    parser.add_argument("--mode", choices=("connect", "run", "connect-run", "resume"), required=True)
    args = parser.parse_args()
    from docking_runtime import activate
    runtime = activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / "Lib/site-packages"))
    from modulea.core.kernel import full_workflow
    workflow = full_workflow(args.data_root)
    payload = json.loads(args.request_file.read_text("utf-8"))
    progress = lambda value: print("PROGRESS " + value, flush=True)
    if args.mode == 'resume':
        from science_modules.a06.interrupted_recovery import run
        data = run(workflow,args.study,payload,args.tools_root,CODE,progress,args.repair_packages)
        result = {'run_id':data['run_id'],'message_zh':'已核验原件并续算中断批次；原评分保留，新完整结果仍待独立复核。'}
    elif args.mode == "connect":
        if payload.get("policy_version") in (None, "A06.automatic.2"):
            from modulea.core.automatic_coverage import AutomaticCoverageWorkflow
            from science_modules.a06.automatic_coverage_sources import connect
            workflow = AutomaticCoverageWorkflow(args.data_root, workflow.validators)
        else:
            from science_modules.a06.reference_sources import connect
        record = connect(workflow, args.study, payload, progress)
        result = {"id": record["id"], "message_zh": "资料连接已完成，请核对范围后一次确认开始；尚未计算对接。"}
    elif args.mode == "connect-run":
        from modulea.core.automatic_start import run as connect_run
        from science_modules.a06.reference_sources import connect
        from science_modules.a06.reference_engine import run
        data = connect_run(workflow, args.study, payload, connect,
            lambda request: run(workflow, args.study, request, args.tools_root, CODE, runtime, progress, args.repair_packages), progress)
        result = {"run_id": data["run_id"], "message_zh": "连续执行及图表已归档，异常原因保留；请独立复核A06结果。"}
    else:
        if payload.get("policy_version") == "A06.automatic.1":
            from modulea.core.automatic_docking import AutomaticDockingWorkflow
            from science_modules.a06.automatic_engine import run
            workflow = AutomaticDockingWorkflow(args.data_root, workflow.validators)
            data = run(workflow, args.study, payload, args.tools_root, CODE, runtime, progress)
        elif payload.get("policy_version") == "A06.automatic.2":
            from modulea.core.automatic_coverage import AutomaticCoverageWorkflow
            from science_modules.a06.automatic_coverage_engine import run
            workflow = AutomaticCoverageWorkflow(args.data_root, workflow.validators)
            data = run(workflow, args.study, payload, args.tools_root, CODE, runtime, progress, args.repair_packages)
        else:
            from science_modules.a06.reference_engine import run
            data = run(workflow, args.study, payload, args.tools_root, CODE, runtime, progress, args.repair_packages)
        result = {"run_id": data["run_id"], "message_zh": "自动对接及图表已归档，异常原因保留；请独立复核A06结果。"}
    args.result_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
