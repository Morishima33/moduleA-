"""固定隔离解释器下执行本机明确受体路径修订或其同批评分。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'src'))


# 隔离环境只由服务器设置，输入不携带工具路径、科学参数或受体替换。
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('repair', 'score'), required=True)
    for field in ('request-file', 'result-file', 'data-root', 'tools-root'):
        parser.add_argument('--' + field, type=Path, required=True)
    parser.add_argument('--study', required=True)
    args = parser.parse_args()
    from docking_runtime import activate
    activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / 'Lib/site-packages'))
    from modulea.core.kernel import full_workflow
    workflow = full_workflow(args.data_root)
    body = json.loads(args.request_file.read_text('utf-8'))

    def progress(message):
        print('PROGRESS ' + message, flush=True)

    if args.mode == 'repair':
        result = workflow.repair_analysis_plan_system_receptor_paths(args.study, body, tools=args.tools_root, progress=progress)
    else:
        m = workflow.load(args.study)
        current = m['current'].get('A06_PREP')
        if not current or current != body.get('expected_preparation_run_id') or \
                workflow.run(m, current)['config'].get('version') != 'A06.system_qualification_paths.1':
            raise ValueError('路径修订评分要求当前实际技术修订资格')
        result = workflow.score_analysis_plan_system_preparation(args.study, body, tools=args.tools_root, progress=progress)
    with args.result_file.open('x', encoding='utf-8') as stream:
        json.dump({'run_id': result['run_id'], 'outcome': result['outcome']}, stream, ensure_ascii=False)
    if result['outcome'] != 'success':
        raise ValueError('路径修订评分未生成可用结果，已保留真实失败与NA')


if __name__ == '__main__':
    main()
