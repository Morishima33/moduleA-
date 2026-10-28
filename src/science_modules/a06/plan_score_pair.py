"""按同批参数执行一个Vina组合并核验Top-1；失败保留诊断及空评分。"""
import math
from pathlib import Path
import subprocess

from contracts import require
from storage import file_record, now, verified_file, write_json
from docking_redocking import _poses, _inside_box
from .plan_quality_engine_v2 import tool_path


def arguments(executable, receptor, ligand, box, output, config):
    """命令由绑定配置生成，单CPU顺序执行，不接受客户端命令或额外参数。"""
    params = config['vina_parameters']
    args = [tool_path(executable), '--receptor', tool_path(receptor), '--ligand', tool_path(ligand)]
    require(len(box['center']) == len(box['size']) == 3 and
            all(type(x) in (int, float) and math.isfinite(x) for x in box['center'] + box['size']) and
            all(x > 0 for x in box['size']), '评分搜索盒无效')
    for name in ('center', 'size'):
        for axis, value in zip('xyz', box[name]):
            args += ['--' + name + '_' + axis, str(value)]
    for flag, key in (('scoring', 'scoring'), ('exhaustiveness', 'exhaustiveness'),
                      ('num_modes', 'num_modes'), ('energy_range', 'energy_range_kcal_mol'), ('seed', 'seed')):
        args += ['--' + flag, str(params[key])]
    return args + ['--cpu', str(config['cpu_per_pair']), '--out', tool_path(output)]


def top_pose(ligand_text, output_text, box, config):
    """复核所有模式的原子身份及有限数值；只取原文第一模式，不另选最低值。"""
    expected = {int(line[6:11]): line[77:].strip().split()[0] for line in ligand_text.splitlines()
                if line.startswith(('ATOM  ', 'HETATM'))}
    require(expected, '准备配体不含可对接原子')
    poses = _poses(output_text)
    require(len(poses) <= config['vina_parameters']['num_modes'], 'Vina输出模式数超过固定参数')
    counts = []
    for line in output_text.splitlines():
        if line.startswith('MODEL '): counts.append(0)
        elif line.startswith(('ATOM  ', 'HETATM')) and counts: counts[-1] += 1
    require(all(count == len(expected) for count in counts) and len(counts) == len(poses), '姿势含重复或缺失原子')
    require(all({key: atom['atom_type'] for key, atom in pose['atoms'].items()} == expected for pose in poses),
            'Vina输出原子身份与准备配体不一致')
    require(_inside_box(poses[0], {'center_angstrom': box['center'], 'size_angstrom': box['size']})['passed'],
            'Top-1姿势超出已复核搜索盒')
    return {'score': poses[0]['score_kcal_mol'], 'mode_count': len(poses), 'top_mode': 1}


def execute(home, folder, executable, ligand_ref, receptor_ref, box, config):
    """实际Vina、输出与返回码完整落盘；不使用stdout或历史分数补位。"""
    folder.mkdir(parents=True, exist_ok=False)
    ligand, receptor = verified_file(home, ligand_ref), verified_file(home, receptor_ref)
    output = folder / 'poses.pdbqt'
    command = arguments(executable, receptor, ligand, box, output, config)
    command_record = {'configuration': config, 'ligand': ligand_ref, 'receptor': receptor_ref,
                      'box': box, 'executable': file_record(home, executable, 'scoring_vina'), 'arguments': command}
    write_json(folder / 'command.json', command_record)
    value = {'started_at': now(), 'state': 'failed', 'score': None, 'returncode': None,
             'mode_count': 0, 'top_mode': None, 'failure_kind': None, 'reason_zh': ''}
    stdout, stderr = '', ''
    try:
        done = subprocess.run(command, cwd=tool_path(home), capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=config['timeout_seconds'])
        stdout, stderr = done.stdout, done.stderr
        value['returncode'] = done.returncode
        value['failure_kind'] = 'tool_error'
        require(done.returncode == 0, 'Vina执行失败；详见本组合stderr日志')
        value['failure_kind'] = 'invalid_output'
        require(output.is_file(), 'Vina没有生成完整姿势文件')
        computed = top_pose(ligand.read_text('ascii'), output.read_text('ascii'), box, config)
        value.update(computed, state='completed', failure_kind=None)
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or '', error.stderr or ''
        value.update(failure_kind='timeout', reason_zh='Vina单组合运行超时；未生成有效评分')
    except (ValueError, OSError, UnicodeError) as error:
        value['reason_zh'] = str(error)
        value['failure_kind'] = value['failure_kind'] or 'launch_error'
    for name, content in (('stdout.txt', stdout), ('stderr.txt', stderr)):
        (folder / name).write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
    value['finished_at'] = now()
    value['files'] = [file_record(home, path, 'scoring_' + path.stem) for path in
                      (folder / 'command.json', folder / 'stdout.txt', folder / 'stderr.txt')]
    if output.is_file():
        value['pose'] = file_record(home, output, 'scoring_pose')
        value['files'].append(value['pose'])
    write_json(folder / 'execution.json', value)
    return file_record(home, folder / 'execution.json', 'scoring_execution')


def validate(home, execution_ref, executable, ligand_ref, receptor_ref, box, config):
    """独立从命令、实际输出和绑定原件回算成功或失败，不信任归档分值。"""
    from storage import read_json
    value = read_json(verified_file(home, execution_ref))
    folder = Path(home) / execution_ref['path']
    folder = folder.parent
    command = read_json(verified_file(home, next(ref for ref in value['files'] if ref['path'] ==
                                               (folder / 'command.json').relative_to(home).as_posix())))
    expected_files = {(folder / name).relative_to(home).as_posix() for name in ('command.json', 'stdout.txt', 'stderr.txt')}
    if (folder / 'poses.pdbqt').is_file():
        expected_files.add((folder / 'poses.pdbqt').relative_to(home).as_posix())
        require(value.get('pose') in value['files'], '实际姿势必须登记在组合文件索引')
    require(len(value['files']) == len(expected_files) and {ref['path'] for ref in value['files']} == expected_files,
            '组合命令、标准输出或错误日志缺失，或包含其他组合文件')
    expected_arguments = arguments(executable, verified_file(home, receptor_ref), verified_file(home, ligand_ref),
                                   box, folder / 'poses.pdbqt', config)
    actual_arguments = command.get('arguments', [])
    path_indices = {0} | {expected_arguments.index(flag) + 1 for flag in ('--receptor', '--ligand', '--out')}
    # Windows输出创建后可能产生新的8.3短文件名；核对同一实际路径，参数仍逐字一致。
    same_arguments = len(actual_arguments) == len(expected_arguments) and all(
        isinstance(actual, str) and (Path(actual).resolve() == Path(expected).resolve() if index in path_indices else actual == expected)
        for index, (actual, expected) in enumerate(zip(actual_arguments, expected_arguments)))
    require(same_arguments and {k: v for k, v in command.items() if k != 'arguments'} ==
            {'configuration': config, 'ligand': ligand_ref, 'receptor': receptor_ref,
             'box': box, 'executable': file_record(home, executable, 'scoring_vina')}, '组合命令、参数或原件与固定输入不一致')
    for ref in value['files']:
        verified_file(home, ref)
    if value['state'] == 'completed':
        require(value['returncode'] == 0 and value['failure_kind'] is None and value['reason_zh'] == '' and
                value['pose'] in value['files'] and
                value['pose']['path'] == (folder / 'poses.pdbqt').relative_to(home).as_posix(), '成功组合执行状态不一致')
        pose = verified_file(home, value['pose'])
        computed = top_pose(verified_file(home, ligand_ref).read_text('ascii'), pose.read_text('ascii'), box, config)
        require(all(value[key] == expected for key, expected in computed.items()), '组合分值或模式与实际Top-1构型不一致')
    else:
        require(value['state'] == 'failed' and value['score'] is None and value['top_mode'] is None and
                value['mode_count'] == 0 and isinstance(value['reason_zh'], str) and value['reason_zh'].strip(),
                '失败组合必须保留空评分及具体原因')
        kind = value['failure_kind']
        if kind == 'tool_error':
            require(type(value['returncode']) is int and value['returncode'] != 0, '工具失败返回码不一致')
        elif kind == 'invalid_output':
            require(value['returncode'] == 0, '输出失败返回码不一致')
            invalid = not (folder / 'poses.pdbqt').is_file()
            if not invalid:
                try:
                    top_pose(verified_file(home, ligand_ref).read_text('ascii'),
                             (folder / 'poses.pdbqt').read_text('ascii'), box, config)
                except (ValueError, UnicodeError):
                    invalid = True
            require(invalid, '有效姿势不能伪装为失败而隐藏真实评分')
        else:
            require(kind in ('timeout', 'launch_error') and value['returncode'] is None, '失败诊断类型不一致')
    return value
