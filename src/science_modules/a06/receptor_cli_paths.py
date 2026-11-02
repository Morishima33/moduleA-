"""显式独立的受体CLI路径适配；旧准备协议不自动调用本实现。"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from contracts import require
from docking_top10_execute import _write_text
from storage import write_json
import tool_process_paths as paths

VERSION = 'A06.receptor_cli_paths.1'


# 保留冻结CLI的全部工具参数，仅将路径映射为已核对的同一物理位置。
def prepare(root, pdb_text, box, label, folder):
    paths.filename(label)
    root, folder = Path(root), Path(folder)
    input_path = folder / 'receptors' / (label + '_input.pdb')
    _write_text(input_path, pdb_text, 'ascii')
    output_base = folder / 'receptors' / label
    packages = root / 'environments' / 'docking_packages'
    environment = dict(os.environ)
    environment['PYTHONPATH'] = paths.existing(packages)
    arguments = [paths.existing(sys.executable), '-m', 'meeko.cli.mk_prepare_receptor',
        '--read_pdb', paths.existing(input_path), '-o', paths.output(output_base), '-p',
        '--write_pdb', paths.output(Path(str(output_base) + '_prepared.pdb')),
        '--box_center', *[str(v) for v in box['center']],
        '--box_size', *[str(v) for v in box['size']], '--delete_bad_res_from_box_radius', '0.0']
    cwd = paths.existing(folder)
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    receipt = {'protocol': VERSION, 'box': box, 'arguments': arguments,
        'original_working_directory': str(folder.resolve()), 'effective_working_directory': cwd,
        'original_input_path': str(input_path.resolve()), 'input_sha256_before': before,
        'same_physical_input_and_directory_verified': True, 'state': 'failed_to_start',
        'scientific_thresholds_changed': False, 'human_review_written': False}
    try:
        completed = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                   text=True, encoding='utf-8', errors='replace', check=False)
        receipt.update(state='finished', returncode=completed.returncode)
        _write_text(folder / 'receptors' / (label + '_prepare_stdout.txt'), completed.stdout)
        _write_text(folder / 'receptors' / (label + '_prepare_stderr.txt'), completed.stderr)
    except OSError as error:
        receipt['error_zh'] = str(error)
        raise
    finally:
        receipt['input_sha256_after'] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        write_json(folder / 'receptors' / (label + '_path_execution.json'), receipt)
    require(receipt['input_sha256_after'] == before, '受体工具执行期间原输入发生改变')
    result = Path(str(output_base) + '.pdbqt')
    require(completed.returncode == 0 and result.is_file() and result.stat().st_size > 0,
            'Meeko受体准备失败：' + label)
    return result
