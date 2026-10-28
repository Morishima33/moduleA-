"""新版正式评分生产器：同批已批准准备、固定Vina参数、完整组合及独立复核。"""
import hashlib
from pathlib import Path
import shutil

from contracts import require
from storage import file_record, read_json, verified_file, write_json
from modulea.core.plan_scoring import VERSION
from .plan_preparation_v2 import _version
from .plan_scoring_inputs import derive, ligand_record, receptor_evidence
from .plan_score_pair import execute
from .plan_scoring_results import summary, matrix_csv, table_rows


def run(workflow, sid, payload, tools, progress):
    """明确确认后执行；每对一CPU顺序计算，不联网、不重新准备或更换对象。"""
    # 工具先核验，缺少固定工具时不创建伪运行。
    executable = _version(Path(tools))
    run_info, repeated = workflow.begin_analysis_plan_a06_scoring(sid, payload)
    if repeated:
        return workflow.result(workflow.load(sid), run_info['run_id'])
    home = workflow.location(sid)
    folder = home / 'runs/A06' / run_info['run_id'] / 'plan_scoring'
    folder.mkdir(parents=True, exist_ok=False)
    try:
        progress('复验已批准准备及固定输入')
        data = derive(workflow.root, sid, run_info['inputs'])
        binary = folder / 'software/vina.exe'
        binary.parent.mkdir(parents=True)
        shutil.copyfile(executable, binary)
        software = {'name': 'AutoDock Vina', 'version': '1.2.7', 'version_stdout': 'AutoDock Vina v1.2.7',
                    'source_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                    'binary': file_record(home, binary, 'scoring_vina')}
        write_json(folder / 'software/version.json', software)
        software_ref = file_record(home, folder / 'software/version.json', 'scoring_software')
        for name in ('plan_scoring.py', 'plan_scoring_inputs.py', 'plan_score_pair.py', 'plan_scoring_results.py'):
            destination = folder / 'code' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(__file__).with_name(name), destination)
        src = Path(__file__).resolve().parents[2]
        for relative in ('docking_redocking.py', 'science_modules/a06/plan_quality_engine_v2.py', 'modulea/core/plan_scoring.py'):
            destination = folder / 'code' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / relative, destination)
        compounds = {row['compound_id']: row for row in data['compounds']}
        receptors = {row['target_id']: row for row in data['receptors']}
        pairs = []
        for index, planned in enumerate(data['planned_pairs'], 1):
            # 每个组合前重新检查当前批准，撤回后停止后续计算并保留已产生的诊断。
            manifest = workflow.load(sid)
            require(workflow.active(manifest, run_info['run_id']), '评分或上游复核已更新，请刷新；已运行文件保留')
            compound, receptor = compounds[planned['compound_id']], receptors[planned['target_id']]
            row = dict(planned, quality=receptor['quality'], execution=None)
            progress(f"评分组合 {index}/{len(data['planned_pairs'])}：{planned['compound_id']} / {planned['target_id']}")
            if planned['state'] == 'ready':
                evidence = receptor_evidence(receptor)
                ref = execute(home, folder / 'scores' / f'pair_{index:06d}', binary,
                              ligand_record(compound), evidence['receptor'], evidence['box'], run_info['config'])
                result = read_json(verified_file(home, ref))
                row.update(state=result['state'], score=result['score'], reason_zh=result['reason_zh'], execution=ref)
            pairs.append(row)
            write_json(folder / 'progress' / f'pair_{index:06d}.json',
                       {'completed_pairs': index, 'pair_count': len(data['planned_pairs']), 'state': row['state']})
        stats = summary(data, pairs)
        (folder / 'matrix.csv').write_text(matrix_csv(pairs), encoding='utf-8-sig', newline='')
        csv_ref = file_record(home, folder / 'matrix.csv', 'scoring_matrix_csv')
        files = list(run_info['inputs'].values()) + data['preparation_result']['files'] + [
            file_record(home, path, 'scoring_evidence') for path in folder.rglob('*') if path.is_file()]
        # 使用有含义的角色代替同路径的通用扫描角色，索引保持同一字节指纹。
        files += [software_ref, software['binary'], csv_ref]
        for row in pairs:
            if row['execution']:
                files += [row['execution']] + read_json(verified_file(home, row['execution']))['files']
        files = list({ref['path']: ref for ref in files}.values())
        packet = {'schema_version': VERSION, 'study_id': sid, 'run_id': run_info['run_id'],
                  'inputs': run_info['inputs'], 'configuration': run_info['config'], 'software': software_ref,
                  'pairs': pairs, 'summary': stats, 'matrix_csv': csv_ref, 'files': files}
        write_json(folder / 'packet.json', packet)
        packet_ref = file_record(home, folder / 'packet.json', 'scoring_packet')
        progress('重新核对当前批准并独立复算全部输出')
        return workflow.finish_analysis_plan_a06_scoring(sid, run_info['run_id'], stats,
                    {'scoring_packet': [packet_ref], 'plan_scoring_pairs': table_rows(pairs)}, files + [packet_ref])
    except Exception as error:
        write_json(folder / 'failure.json', {'run_id': run_info['run_id'], 'reason_zh': str(error),
                                            'result_published': False})
        raise
