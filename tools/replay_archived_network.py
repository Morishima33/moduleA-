"""Offline A03–A05 regression against explicitly selected Module A archives."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
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
from science_modules.a05 import plan_figures, plan_flow, plan_flow_utf8
from storage import read_json, verified_file


def export_a05(folder, run, result, home):
    """Regenerate figures and CSV from output just matched to a complete R rerun."""
    from PIL import Image
    from xml.etree import ElementTree

    folder.mkdir(parents=True, exist_ok=False)
    plan = read_json(verified_file(home, run['inputs']['analysis_plan_file']))['plan']
    figures = plan_figures.draw(result['tables'], plan, folder)
    for path in figures.values():
        if path.suffix == '.png':
            with Image.open(path) as picture:
                picture.verify()
        else:
            require(ElementTree.parse(path).getroot().tag == '{http://www.w3.org/2000/svg}svg', 'SVG 格式错误')

    tables = {}
    for ref in result['files']:
        if ref['role'] != 'table':
            continue
        archived = verified_file(home, ref)
        rows = result['tables'][archived.stem]
        columns = sorted({key for row in rows for key in row})
        path = folder / archived.name
        with path.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        require(path.read_bytes() == archived.read_bytes(), f'{archived.name} 与已核验原表不同')
        tables[path.name] = len(rows)
    require(figures and tables, 'A05 未形成图表')
    return {'figures': sorted(path.name for path in figures.values()), 'csv_rows': tables}


def replay(root, study_id, selected, rscript, *, output_dir=None):
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
    if output_dir is not None:
        output_dir = output_dir.resolve()
        require(not output_dir.is_relative_to(root.resolve()) and not output_dir.exists(),
                '验收图表须写入归档外的全新目录')

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
            def check(module):
                started = perf_counter()
                # Each branch gets its own Workflow so no in-memory state is shared.
                worker = full_workflow(root)
                run = runs[module]
                result = worker.result(manifest, run['run_id'])
                require(result is not None, f'{module}没有完整归档结果')
                if module == 'A05':
                    logs = [ref for ref in result['files']
                            if ref['role'] == 'log' and Path(ref['path']).name == 'R_log.txt']
                    require(len(logs) == 1, 'A05缺少唯一归档R执行日志')
                    with verified_file(home, logs[0]).open(encoding='utf-8') as log:
                        recorded = json.loads(log.readline())
                    require(recorded.get('rscript_sha256') == rscript_hash, 'Rscript与归档执行程序指纹不一致')
                worker.validators[module](run, result['summary'], result['tables'],
                                          result['anomalies'], result['outcome'])
                finished = perf_counter()
                stage = {'run_id': run['run_id'], 'protocol': run['config']['version'],
                                  'input_hash': run['input_hash'], 'config_hash': run['config_hash'],
                                  'result_sha256': manifest['runs'][run['run_id']]['result_file']['sha256'],
                                  'summary_and_tables_sha256': fingerprint((result['summary'], result['tables'])),
                                  'seconds': round(finished - started, 3)}
                return stage, started, finished

            stages['A03'], _, _ = check('A03')
            with ThreadPoolExecutor(max_workers=2) as pool:
                ppi = pool.submit(check, 'A04')
                enrichment = pool.submit(check, 'A05')
                stages['A04'], ppi_start, ppi_end = ppi.result()
                stages['A05'], enrichment_start, enrichment_end = enrichment.result()
            overlap = min(ppi_end, enrichment_end) - max(ppi_start, enrichment_start)
            require(overlap > 0, '未观察到 A04 和 A05 并行复跑')
            if output_dir is not None:
                a05 = workflow.result(manifest, selected['A05'])
                stages['A05']['output'] = export_a05(output_dir, runs['A05'], a05, home)
    require((home / 'manifest.json').read_bytes() == original, '复跑期间研究索引改变，请使用固定归档')
    return {'passed': True, 'study_id': study_id, 'rscript_sha256': rscript_hash,
            'parallel_overlap_seconds': round(overlap, 3), 'stages': stages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--study-id', required=True)
    for module in ('a03', 'a04', 'a05'):
        parser.add_argument('--' + module, required=True, metavar='RUN_ID')
    parser.add_argument('--rscript', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, help='Fresh destination outside the archive for verified A05 charts and CSVs')
    args = parser.parse_args()
    stages = {key.upper(): getattr(args, key) for key in ('a03', 'a04', 'a05')}
    print(json.dumps(replay(args.data_root, args.study_id, stages, args.rscript, output_dir=args.output_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
