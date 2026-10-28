"""隔离复验同批A06科学资料并发布可复核准备，不提交人工决定或运行评分。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'src'))


def main():
    """仅服务器配置科学环境和工具目录，浏览器不能选择执行器。"""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    for name in ('request-file', 'result-file', 'tools-root', 'data-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--study', required=True)
    args = parser.parse_args()
    from docking_runtime import activate
    runtime = activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / 'Lib/site-packages'))
    from modulea.core.kernel import full_workflow
    result = full_workflow(args.data_root).publish_analysis_plan_a06_reviewable(
        args.study, json.loads(args.request_file.read_text(encoding='utf-8')))
    args.result_file.write_text(json.dumps({'run_id': result['run_id'],
        'summary': result['summary'], 'runtime': runtime}, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
