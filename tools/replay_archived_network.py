"""Offline A03–A05 regression against explicitly selected Module A archives."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from contracts import fingerprint, require
from modulea.child_environment import child_environment
from modulea.core.kernel import full_workflow
from science_modules.a05 import plan_flow, plan_flow_utf8
from storage import verified_file


def replay(root, study_id, selected, rscript):
    workflow = full_workflow(root)
    home = workflow.location(study_id)
    original = (home / 'manifest.json').read_bytes()
    manifest = workflow.load(study_id)
    runs = {module: workflow.run(manifest, rid) for module, rid in selected.items()}
    require(all(run['module_id'] == module for module, run in runs.items()), '阶段与指定运行不一致')
    require(all(runs[module]['parent_runs'].get('A03') == selected['A03'] for module in ('A04', 'A05')),
            'A04和A05必须绑定指定的同一个A03')
    require(runs['A05']['config']['version'] in (plan_flow.VERSION, plan_flow_utf8.VERSION),
            '当前离线入口仅支持已固定注释及R脚本的A05方案协议')
    require(rscript.is_file(), 'Rscript不存在')
    rscript_hash = sha256(rscript.read_bytes()).hexdigest()

    def refuse_network(*args, **kwargs):
        raise RuntimeError('离线复跑禁止Python发起网络连接')

    stages = {}
    with tempfile.TemporaryDirectory(prefix='modulea_replay_') as output:
        scratch = Path(output)

        def local_r(call):
            def analyze(_archive_root, mode, value):
                require(mode == 'analyze', '离线复跑只分析已归档的注释')
                return call(scratch, mode, value)
            return analyze

        # Redirect only R scratch output. The production validators still read and verify
        # the original plan, inputs and files in their registered archive locations.
        with (patch.object(socket.socket, 'connect', refuse_network),
              patch.object(socket.socket, 'connect_ex', refuse_network),
              patch.dict(os.environ, child_environment(dict(os.environ, MODULEA_RSCRIPT=str(rscript.resolve())))),
              patch.object(plan_flow, 'r_call', local_r(plan_flow.r_call)),
              patch.dict(plan_flow_utf8._namespace, {'r_call': local_r(plan_flow_utf8.r_call)})):
            for module, run in runs.items():
                started = perf_counter()
                result = workflow.result(manifest, run['run_id'])
                require(result is not None, f'{module}没有完整归档结果')
                if module == 'A05':
                    logs = [ref for ref in result['files']
                            if ref['role'] == 'log' and Path(ref['path']).name == 'R_log.txt']
                    require(len(logs) == 1, 'A05缺少唯一归档R执行日志')
                    with verified_file(home, logs[0]).open(encoding='utf-8') as log:
                        recorded = json.loads(log.readline())
                    require(recorded.get('rscript_sha256') == rscript_hash, 'Rscript与归档执行程序指纹不一致')
                workflow.validators[module](run, result['summary'], result['tables'],
                                            result['anomalies'], result['outcome'])
                stages[module] = {'run_id': run['run_id'], 'protocol': run['config']['version'],
                                  'input_hash': run['input_hash'], 'config_hash': run['config_hash'],
                                  'result_sha256': manifest['runs'][run['run_id']]['result_file']['sha256'],
                                  'summary_and_tables_sha256': fingerprint((result['summary'], result['tables'])),
                                  'seconds': round(perf_counter() - started, 3)}
    require((home / 'manifest.json').read_bytes() == original, '复跑期间研究索引改变，请使用固定归档')
    return {'passed': True, 'study_id': study_id, 'rscript_sha256': rscript_hash, 'stages': stages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--study-id', required=True)
    for module in ('a03', 'a04', 'a05'):
        parser.add_argument('--' + module, required=True, metavar='RUN_ID')
    parser.add_argument('--rscript', type=Path, required=True)
    args = parser.parse_args()
    stages = {key.upper(): getattr(args, key) for key in ('a03', 'a04', 'a05')}
    print(json.dumps(replay(args.data_root, args.study_id, stages, args.rscript), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
