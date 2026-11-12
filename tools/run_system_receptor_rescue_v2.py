"""固定隔离解释器运行第二轮受体补救；第一轮脚本及归档保持。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'src'))


def main():
    """服务器工具与私有七字段请求分开传入，不增加科学参数覆盖。"""
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
    from modulea.core.system_receptor_rescue_v2 import SystemReceptorRescueV2Workflow
    base = full_workflow(args.data_root)
    workflow = base if isinstance(base, SystemReceptorRescueV2Workflow) else SystemReceptorRescueV2Workflow(args.data_root, base.validators)
    result = workflow.execute_analysis_plan_receptor_rescue_v2(args.study,
        json.loads(args.request_file.read_text('utf-8')), tools=args.tools_root, repair_packages=args.repair_packages,
        progress=lambda message: print('PROGRESS ' + message, flush=True))
    with args.result_file.open('x', encoding='utf-8') as stream:
        json.dump({'run_id': result['run_id'], 'outcome': result['outcome']}, stream, ensure_ascii=False)
    if result['outcome'] != 'success':
        raise ValueError('第二轮没有有效结果，已保留真实失败及NA')


if __name__ == '__main__':
    main()
