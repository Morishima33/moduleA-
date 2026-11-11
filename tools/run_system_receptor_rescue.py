"""固定隔离解释器执行明确受体补救；正常A06发布仍等待独立人工复核。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'src'))


def main():
    """工具位置只来自服务器配置，私有请求不携带路径、参数或批准标记。"""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    for field in ('request-file', 'result-file', 'data-root', 'tools-root', 'repair-packages'):
        parser.add_argument('--' + field, type=Path, required=True)
    parser.add_argument('--study', required=True)
    args = parser.parse_args()
    from docking_runtime import activate
    activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / 'Lib/site-packages'))
    from modulea.core.kernel import full_workflow
    workflow = full_workflow(args.data_root)
    body = json.loads(args.request_file.read_text('utf-8'))
    result = workflow.execute_analysis_plan_receptor_rescue(args.study, body, tools=args.tools_root,
        repair_packages=args.repair_packages, progress=lambda text: print('PROGRESS ' + text, flush=True))
    with args.result_file.open('x', encoding='utf-8') as stream:
        json.dump({'run_id': result['run_id'], 'outcome': result['outcome']}, stream, ensure_ascii=False)
    if result['outcome'] != 'success':
        raise ValueError('本批补救未形成有效评分；实际失败、NA与原评分保持，请查看归档')


if __name__ == '__main__':
    main()
