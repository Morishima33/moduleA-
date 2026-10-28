"""独立从同批准备、命令和Top-1构型复算完整评分表及CSV，旧版本保持。"""
import csv
from io import StringIO
from pathlib import Path

from contracts import fingerprint, require
from storage import read_json, verified_file
from modulea.core.plan_scoring import VERSION
from .plan_scoring_inputs import derive, ligand_record, receptor_evidence
from .plan_score_pair import validate as validate_pair


def rows_from_evidence(home, run, data, rows, executable):
    """固定笛卡尔顺序逐格回算；准备NA不执行，失败不能填零或借分。"""
    require(len(rows) == len(data['planned_pairs']), '评分组合数与固定准备不一致')
    compounds = {row['compound_id']: row for row in data['compounds']}
    receptors = {row['target_id']: row for row in data['receptors']}
    expected_rows = []
    for index, (planned, supplied) in enumerate(zip(data['planned_pairs'], rows), 1):
        compound, receptor = compounds[planned['compound_id']], receptors[planned['target_id']]
        row = dict(planned, quality=receptor['quality'], execution=None)
        if planned['state'] == 'ready':
            ref = supplied.get('execution')
            require(isinstance(ref, dict) and ref['path'] ==
                    f"runs/A06/{run['run_id']}/plan_scoring/scores/pair_{index:06d}/execution.json",
                    '评分组合执行文件不属于当前运行或固定位置')
            evidence = receptor_evidence(receptor)
            value = validate_pair(home, ref, executable, ligand_record(compound), evidence['receptor'],
                                  evidence['box'], run['config'])
            row.update(state=value['state'], score=value['score'], reason_zh=value['reason_zh'], execution=ref)
        else:
            require(planned['state'] == 'NA' and planned['score'] is None and planned['reason_zh'], '准备NA缺少明确原因')
        expected_rows.append(row)
    require(expected_rows == rows, '评分表与固定准备和实际构型回算不一致')
    return expected_rows


def summary(data, rows):
    """数量来源为同一固定组合；严格与探索分列，不附通用结合能阈值。"""
    completed = [row for row in rows if row['state'] == 'completed']
    return {'science_version': VERSION, 'compound_count': len(data['compounds']), 'receptor_count': len(data['receptors']),
            'pair_count': len(rows), 'ready_input_pairs': sum(row['state'] == 'ready' for row in data['planned_pairs']),
            'scored_pairs': len(completed), 'failed_pairs': sum(row['state'] == 'failed' for row in rows),
            'na_pairs': sum(row['state'] == 'NA' for row in rows),
            'strict_scored_pairs': sum(row['quality'] == '严格' for row in completed),
            'exploratory_scored_pairs': sum(row['quality'] == '探索' for row in completed),
            'handoff_blocked': not completed, 'automatic_approval': False, 'score_unit': 'kcal/mol',
            'input_key': data['input_record']['packet']['input_key'],
            'analysis_parameter_hash': data['configuration']['analysis_parameter_hash'],
            'source_preparation_run_id': data['preparation']['run_id'],
            'message_zh': '同批Vina评分已归档；NA和失败保留，严格与探索分列，结果待独立人工复核' if completed
                          else '所有可用组合评分失败；诊断已保留，没有可批准的评分结果'}


def matrix_csv(rows):
    """导出本批完整长表，保持原始评分精度，空评分明确写NA。"""
    stream = StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(['compound_id', 'target_id', 'state', 'vina_score_kcal_mol', 'quality', 'reason_zh'])
    for row in rows:
        writer.writerow([row['compound_id'], row['target_id'], row['state'],
                         row['score'] if row['score'] is not None else 'NA', row['quality'], row['reason_zh']])
    return stream.getvalue()


def table_rows(rows):
    """标准结果表只放简单单元格；完整文件索引留在事实包和附件。"""
    return [{key: row[key] for key in ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh', 'input_key')}
            | {'execution_path': row['execution']['path'] if row['execution'] else None,
               'state_zh': {'completed': '已评分', 'failed': '评分失败', 'NA': '准备NA'}[row['state']]} for row in rows]


def validator(root, previous):
    """新版本独立复算输入、全部组合、软件和CSV；旧协议只委托原校验器。"""
    def check(run, supplied_summary, tables, anomalies, outcome):
        if run.get('config', {}).get('version') != VERSION:
            return previous(run, supplied_summary, tables, anomalies, outcome)
        sid = run['study_id']
        home = Path(root) / 'studies' / sid
        data = derive(root, sid, run['inputs'])
        require(run['config'] == data['configuration'] and run['parent_runs'] == {'A06_PREP': data['preparation']['run_id']} and
                run['parent_review_ids'] == {'A06_PREP': data['review']['review_id']} and
                run['parent_artifact_ids'] == [data['preparation']['artifact_id']] and
                run['config_hash'] == fingerprint(run['config']) and
                run['input_hash'] == fingerprint({'inputs': run['inputs'], 'parents': run['parent_artifact_ids']}),
                '评分参数、指纹或上游批准与绑定准备不一致')
        refs = tables.get('scoring_packet', [])
        require(len(refs) == 1 and refs[0]['path'] == f"runs/A06/{run['run_id']}/plan_scoring/packet.json", '评分事实包不属于当前运行')
        packet = read_json(verified_file(home, refs[0]))
        require(packet['schema_version'] == VERSION and packet['study_id'] == sid and packet['run_id'] == run['run_id'] and
                packet['inputs'] == run['inputs'] and packet['configuration'] == run['config'], '评分事实包归属或参数不一致')
        software = read_json(verified_file(home, packet['software']))
        binary = verified_file(home, software['binary'])
        require(software['name'] == 'AutoDock Vina' and software['version'] == '1.2.7' and
                software['version_stdout'] == 'AutoDock Vina v1.2.7' and
                software['source_sha256'] == software['binary']['sha256'] and
                software['binary']['path'] == f"runs/A06/{run['run_id']}/plan_scoring/software/vina.exe", '评分工具快照或版本不一致')
        rows = rows_from_evidence(home, run, data, packet['pairs'], binary)
        expected = summary(data, rows)
        require(supplied_summary == expected == packet['summary'] and tables == {
            'scoring_packet': refs, 'plan_scoring_pairs': table_rows(rows)} and anomalies == [] and
            outcome == ('success' if expected['scored_pairs'] > 0 else 'failed'), '评分摘要、表格或归档状态不一致')
        require(packet['matrix_csv']['path'] == f"runs/A06/{run['run_id']}/plan_scoring/matrix.csv" and
                verified_file(home, packet['matrix_csv']).read_text('utf-8-sig') == matrix_csv(rows), '完整评分CSV与本批结果不一致')
        for ref in packet['files']:
            verified_file(home, ref)
        required = list(run['inputs'].values()) + data['preparation_result']['files'] + [packet['software'], software['binary'], packet['matrix_csv']]
        for row in rows:
            if row['execution']:
                required += [row['execution']] + read_json(verified_file(home, row['execution']))['files']
        require(all(ref in packet['files'] for ref in required), '评分事实包未包含全部输入或输出指纹')
    return check
