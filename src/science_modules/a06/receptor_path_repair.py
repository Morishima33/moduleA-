"""只补执行确由目录启动错误阻断的原受体尝试，重建同一固定矩阵的资格事实。"""
from copy import deepcopy
import math
from pathlib import Path
import re

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, read_json, verified_file, within, write_json
import tool_process_paths
from . import plan_preparation_v2, receptor_cli_paths, system_quality

VERSION = 'A06.receptor_path_repair.1'
IMPLEMENTATIONS = (Path(__file__), Path(receptor_cli_paths.__file__),
                   Path(tool_process_paths.__file__), Path(plan_preparation_v2.__file__),
                   Path(system_quality.__file__))


# 来源必须由调度方先执行原准备规范验证；此处再绑定归档字节、研究、批次及固定顺序。
def source_data(home, reference):
    home = Path(home).resolve()
    fact = read_json(verified_file(home, reference))
    require(fact.get('schema_version') == 'A06.system_preparation.2'
            and fact.get('study_id') == home.name and fact.get('human_review_written') is False,
            '路径补执行只接受同研究完整原系统准备事实')
    batch = read_json(verified_file(home, fact['batch_file']))
    decision = read_json(verified_file(home, fact['system_input_ref']))
    fixed = decision['payload']
    safe_id(batch['batch_id'], 'systembatch')
    require(batch['study_id'] == decision['study_id'] == home.name
            and decision['batch_id'] == batch['batch_id'] and decision['stage'] == 'A06_INPUT'
            and decision['human_review_written'] is False and fixed['input_key'] == fact['input_key']
            and fixed['human_reviews'] == {} and fixed['replacement_after_preparation_failure'] is False,
            '路径补执行的固定输入、研究或原批次不同')
    for key, id_key in (('compounds', 'compound_id'), ('receptors', 'target_id')):
        ids = [row[id_key] for row in fixed[key]]
        require(len(ids) == len(set(ids)) and [row[id_key] for row in fact[key]] == ids
                and [row[id_key] for row in fact['connection'][key]] == ids,
                '原准备对象数量或顺序与本批固定范围不同')
    require(fixed['pair_count'] == len(fixed['compounds']) * len(fixed['receptors']),
            '路径补执行固定组合不完整')
    return fact, fixed, batch['batch_id']


# 只选可从原文件精确定位的启动失败。另有口袋或环境问题的尝试保留原证据，不运行工具。
def candidates(home, fact):
    found = []
    for i, (row, connected) in enumerate(zip(fact['receptors'], fact['connection']['receptors'])):
        for j, trace in enumerate(row['attempts']):
            evidence = trace['evidence']
            if not re.match(r'^\[WinError 267\](?:\s|$)', evidence.get('error_zh') or ''):
                continue
            if evidence.get('pocket_complete') is not True or evidence.get('environment_resolved') is not True:
                continue
            candidate = trace['candidate']
            spec = candidate['spec']
            require(candidate == connected['candidates'][j]
                    and spec['source_type'] == 'experimental' and spec['pocket'] == 'p2rank'
                    and evidence['structure_id'] == spec['pdb_id']
                    and evidence['identity']['target_id'] == row['target_id']
                    and evidence['receptor_ready'] is False and not evidence.get('receptor')
                    and trace['assessment']['state'] == 'failed',
                    '原目录故障与已固定的失败候选不一致')
            expected = [r for r in evidence['files']
                        if r['path'].endswith('/receptors/' + row['symbol'] + '_input.pdb')]
            require(len(expected) == 1, '无法唯一定位原受体工具输入')
            original = expected[0]
            predicted = evidence['predicted_pocket']['input_pdb']
            require(verified_file(home, original).read_bytes() == verified_file(home, predicted).read_bytes(),
                    '原受体工具输入与已归档预测输入不同')
            found.append({'receptor_index': i, 'candidate_index': j, 'target_id': row['target_id'],
                          'symbol': row['symbol'], 'original_input': original, 'original_trace_hash': fingerprint(trace),
                          'box': deepcopy(evidence['box'])})
    return found


# 请求ID绑定原事实与实现版本；中断时只复用完整且重新核验的尝试。
def _session(home, folder, reference, fact, batch_id, items):
    path = folder / 'session.json'
    binding = {'schema_version': VERSION, 'study_id': fact['study_id'], 'batch_id': batch_id,
               'source_preparation_fact': reference, 'candidates': items, 'human_review_written': False}
    if path.exists():
        value = read_json(path)
        require(value.get('binding') == binding, '路径补执行会话的固定来源或候选已改变')
        _implementations(home, folder, value['implementations'], compare_live=True)
        return file_record(home, path, 'receptor_path_repair_session')
    files = []
    for original in IMPLEMENTATIONS:
        target = folder / 'code' / original.name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = original.read_bytes()
        if target.exists():
            require(target.read_bytes() == raw, '未完成路径补执行的实现字节已改变')
        else:
            with target.open('xb') as stream:
                stream.write(raw)
        files.append(file_record(home, target, 'receptor_path_repair_implementation'))
    write_json(path, {'binding': binding, 'implementations': files})
    return file_record(home, path, 'receptor_path_repair_session')


# 实现快照必须精确覆盖本协议；历史读取只验证归档，执行续做还比较当前字节。
def _implementations(home, folder, refs, *, compare_live=False):
    require(len(refs) == len(IMPLEMENTATIONS), '路径补执行实现快照不完整')
    for source, ref in zip(IMPLEMENTATIONS, refs):
        archived = verified_file(home, ref)
        require(archived == folder / 'code' / source.name, '路径补执行实现快照路径不同')
        if compare_live:
            require(archived.read_bytes() == source.read_bytes(), '路径补执行实现已改变，不能静默续做')


# 验证CLI已实际运行及输入/输出身份；旧原件、参数和没有分数的状态均由事实重建。
def _read_attempt(home, folder, expected, ref):
    path = verified_file(home, ref)
    require(path.parent.parent == folder and path.name == 'receipt.json', '路径补执行回执不属于实际候选')
    value = read_json(path)
    require(value.get('schema_version') == VERSION and value.get('candidate') == expected
            and value.get('human_review_written') is False, '路径补执行回执与原候选不同')
    symbol = expected['symbol']
    out = path.parent / 'receptors'
    command_file = verified_file(home, value['execution'])
    require(command_file == out / (symbol + '_path_execution.json'), '路径补执行命令位置不同')
    execution = read_json(command_file)
    require(execution['protocol'] == receptor_cli_paths.VERSION and execution['box'] == expected['box']
            and execution['human_review_written'] is False and execution['scientific_thresholds_changed'] is False
            and execution['same_physical_input_and_directory_verified'] is True,
            '路径补执行实际命令或搜索盒不同')
    command = execution['arguments']
    require(len(command) == 20 and command[1:4] == ['-m', 'meeko.cli.mk_prepare_receptor', '--read_pdb']
            and command[5] == '-o' and command[7:9] == ['-p', '--write_pdb']
            and command[10:] == ['--box_center', *map(str, expected['box']['center']),
                                  '--box_size', *map(str, expected['box']['size']),
                                  '--delete_bad_res_from_box_radius', '0.0'],
            '路径补执行改变了原固定受体工具参数')
    actual_input = verified_file(home, value['input'])
    require(actual_input == out / (symbol + '_input.pdb')
            and execution['input_sha256_before'] == execution['input_sha256_after']
            == value['input']['sha256'] == expected['original_input']['sha256']
            and value['input']['bytes'] == expected['original_input']['bytes'],
            '路径补执行输入不是同一原蛋白字节')
    require(execution['state'] == 'finished' and type(execution['returncode']) is int,
            '路径补执行没有真实工具结束证据，不能作为已完成复用')
    files = {verified_file(home, item): item for item in value['files']}
    require(len(files) == len(value['files']) and all(p.is_relative_to(out) for p in files)
            and {command_file, actual_input, out / (symbol + '_prepare_stdout.txt'),
                 out / (symbol + '_prepare_stderr.txt')} <= files.keys(), '路径补执行文件证据不完整')
    output = value['receptor']
    if output:
        result = verified_file(home, output)
        require(execution['returncode'] == 0 and result == out / (symbol + '.pdbqt') and result in files,
                '路径补执行无有效工具输出')
        atoms = [line for line in result.read_text('ascii').splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
        require(atoms and all(math.isfinite(float(line[i:i + 8])) for line in atoms for i in (30, 38, 46))
                and all(math.isfinite(float(line[70:76])) for line in atoms), '路径补执行受体坐标或电荷无效')
    else:
        require(execution['returncode'] != 0 or not (out / (symbol + '.pdbqt')).is_file(),
                '成功工具输出未完整登记')
    return value


# 工具真正完成后才写入可复用回执，未启动或中断的目录保留且不择优覆盖。
def _execute_attempt(home, folder, candidate, tools):
    attempt = folder / new_id('attempt')
    attempt.mkdir(parents=True, exist_ok=False)
    symbol = candidate['symbol']
    raw = verified_file(home, candidate['original_input']).read_bytes()
    receptor = None
    try:
        output = receptor_cli_paths.prepare(tools, raw.decode('ascii'), candidate['box'], symbol, attempt)
        receptor = file_record(home, output, 'receptor')
    except ValueError:
        # 非零退出保留原stderr；路径映射/未实际结束的错误不能伪装成已完成尝试。
        execution_path = attempt / 'receptors' / (symbol + '_path_execution.json')
        if not execution_path.exists() or read_json(execution_path)['state'] != 'finished':
            raise
    out = attempt / 'receptors'
    value = {'schema_version': VERSION, 'candidate': deepcopy(candidate), 'human_review_written': False,
             'input': file_record(home, out / (symbol + '_input.pdb'), 'receptor_path_repair_input'),
             'execution': file_record(home, out / (symbol + '_path_execution.json'), 'receptor_path_repair_execution'),
             'receptor': receptor, 'files': [file_record(home, p, 'receptor_path_repair_evidence')
                                             for p in sorted(out.iterdir()) if p.is_file()]}
    path = attempt / 'receipt.json'
    write_json(path, value)
    return file_record(home, path, 'receptor_path_repair_attempt')


# 重建只替换已核验的技术尝试；原位置、源文件、预测证据与质控规则均保持。
def rebuild(home, fact, items, patches, folder):
    require(len(items) == len(patches), '路径补执行回执覆盖不完整')
    repaired = deepcopy(fact)
    for candidate, reference in zip(items, patches):
        i, j = candidate['receptor_index'], candidate['candidate_index']
        value = _read_attempt(home, folder / f'candidate_{i:03d}_{j:03d}', candidate, reference)
        row = repaired['receptors'][i]
        trace = row['attempts'][j]
        evidence = trace['evidence']
        evidence['files'] = [*evidence['files'], *value['files'], reference]
        if value['receptor']:
            evidence.update(receptor_ready=True, receptor=value['receptor'])
            evidence.pop('error_zh', None)
        else:
            evidence['error_zh'] = '目录启动已恢复，原条件下受体工具未生成可用文件；见本次原始日志'
        trace['assessment'] = plan_preparation_v2.assess_plan_attempt(trace['candidate']['spec'], evidence,
                                                                       row, 2, fact['config'])
        if row['state'] == 'NA':
            row['reason_zh'] = '; '.join(t['evidence'].get('error_zh') or t['assessment']['reason_zh']
                                         for t in row['attempts'])
    return repaired


# 本入口由新协议后台显式调用，得到只追加的归档和按原规则复算的资格事实。
def compute(home, reference, repair_id, tools, progress):
    home = Path(home).resolve()
    safe_id(repair_id, 'receptorpathrepair')
    fact, fixed, batch_id = source_data(home, reference)
    items = candidates(home, fact)
    require(items, '没有仅受目录启动错误阻断且口袋环境已明确的原候选')
    folder = within(home, f'decisions/analysis_plans/system_batches/{batch_id}/receptor_path_repairs/{repair_id}')
    session = _session(home, folder, reference, fact, batch_id, items)
    complete = folder / 'packet.json'
    if complete.exists():
        ref = file_record(home, complete, 'receptor_path_repair_packet')
        return ref, read_packet(home, ref)[2]
    patches = []
    for item in items:
        sub = folder / f'candidate_{item["receptor_index"]:03d}_{item["candidate_index"]:03d}'
        existing = sorted(sub.glob('*/receipt.json'))
        require(len(existing) <= 1, '同一候选存在多个完整回执，不能静默择优')
        if existing:
            ref = file_record(home, existing[0], 'receptor_path_repair_attempt')
        else:
            progress('补执行原受体工具：' + item['symbol'])
            ref = _execute_attempt(home, sub, item, tools)
        _read_attempt(home, sub, item, ref)
        patches.append(ref)
    repaired = rebuild(home, fact, items, patches, folder)
    receptors, decisions = system_quality.qualify(repaired)
    write_json(complete, {'schema_version': VERSION, 'session': session, 'patches': patches,
                          'qualification_hash': fingerprint([receptors, decisions]), 'human_review_written': False})
    return file_record(home, complete, 'receptor_path_repair_packet'), (repaired, receptors, decisions)


# 规范验证从原准备和本次真实工具回执重新推导，不依赖客户端提交结果。
def read_packet(home, reference):
    home = Path(home).resolve()
    path = verified_file(home, reference)
    packet = read_json(path)
    folder = path.parent
    require(path.name == 'packet.json' and packet['schema_version'] == VERSION
            and packet['human_review_written'] is False
            and verified_file(home, packet['session']) == folder / 'session.json', '路径补执行归档归属不同')
    session = read_json(folder / 'session.json')
    binding = session['binding']
    fact, fixed, batch_id = source_data(home, binding['source_preparation_fact'])
    safe_id(folder.name, 'receptorpathrepair')
    require(folder == within(home, f'decisions/analysis_plans/system_batches/{batch_id}/receptor_path_repairs/{folder.name}')
            and binding['schema_version'] == VERSION and binding['study_id'] == fact['study_id']
            and binding['batch_id'] == batch_id and binding['human_review_written'] is False,
            '路径补执行会话不属于同一研究和批次')
    _implementations(home, folder, session['implementations'])
    items = candidates(home, fact)
    require(items and items == binding['candidates'], '补执行范围改变或包含非技术失败')
    repaired = rebuild(home, fact, items, packet['patches'], folder)
    receptors, decisions = system_quality.qualify(repaired)
    require(packet['qualification_hash'] == fingerprint([receptors, decisions]), '路径补执行资格事实不同')
    return fixed, packet, (repaired, receptors, decisions)
