"""在服务器配置的隔离科学环境执行新版Vina评分；结果不自动批准。"""
import argparse
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'src'))


def main():
    """浏览器不能指定科学解释器、工具、路径或命令参数。"""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    for name in ('request-file', 'result-file', 'tools-root', 'data-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--study', required=True)
    args = parser.parse_args()
    from docking_runtime import activate
    activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / 'Lib/site-packages'))
    from modulea.core.kernel import full_workflow
    from science_modules.a06.plan_scoring import run
    result = run(full_workflow(args.data_root), args.study,
                 json.loads(args.request_file.read_text('utf-8')), args.tools_root,
                 lambda message: print('PROGRESS ' + message, flush=True))
    args.result_file.write_text(json.dumps({'run_id': result['run_id'], 'summary': result['summary'],
                                           'outcome': result['outcome']}, ensure_ascii=False), encoding='utf-8')
    if result['outcome'] != 'success':
        raise SystemExit('全部可用组合失败；诊断已归档，没有有效评分')


if __name__ == '__main__':
    main()
