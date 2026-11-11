"""受体补救科学适配层的范围、区域续算和Top-1绑定；全部为临时合成原件。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from contracts import ContractError, fingerprint, require
from storage import file_record, new_id, read_json, verified_file, write_json
from science_modules.a06 import plan_score_pair as pair_engine
from science_modules.a06 import system_receptor_rescue as science
from tests.modulea import test_foundation_evidence as geometry


class ArchiveStudy:
    """只保管本测试真实临时文件和已登记引用，不实现科学规则或工作流批准。"""
    def __init__(self, root):
        self.root, self.sid = root, new_id('study')
        self.home = root / 'studies' / self.sid
        self.home.mkdir(parents=True)
        self.manifest = {'study_id': self.sid, 'runs': {}}
        self.checkpoints = {}
        self.validators = {'A06_PREP': lambda *_: None, 'A06': lambda *_: None}

    def location(self, sid):
        require(sid == self.sid, '测试读取不能跨研究')
        return self.home

    def load(self, sid):
        self.location(sid)
        return deepcopy(self.manifest)

    def run(self, manifest, run_id):
        return read_json(verified_file(self.home, manifest['runs'][run_id]['run_file']))

    def result(self, manifest, run_id):
        return read_json(verified_file(self.home, manifest['runs'][run_id]['result_file']))

    def save(self, relative, raw, role='synthetic_evidence'):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if isinstance(raw, bytes) else raw.encode('utf-8'))
        return file_record(self.home, path, role)

    def json(self, relative, value):
        path = self.home / relative
        write_json(path, value, replace=path.exists())
        return file_record(self.home, path, 'synthetic_evidence')

    def append_analysis_plan_receptor_rescue_checkpoint(self, sid, run_id, key, payload, files):
        self.location(sid)
        reference = self.json(f'runs/A06/{run_id}/rescue_checkpoints/{new_id("checkpoint")}.json',
                              {'payload': deepcopy(payload), 'files': deepcopy(files)})
        self.checkpoints[run_id, key] = reference
        return reference

    def read_analysis_plan_receptor_rescue_checkpoint(self, sid, run_id, key):
        self.location(sid)
        reference = self.checkpoints.get((run_id, key))
        if reference is None:
            return None
        value = read_json(verified_file(self.home, reference))
        for item in value['files']:
            verified_file(self.home, item)
        return reference, value


class SystemReceptorRescueScienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rescue_science_')
        self.addCleanup(self.temp.cleanup)
        self.w = ArchiveStudy(Path(self.temp.name) / 'data')
        self.home, self.sid = self.w.home, self.w.sid
        self.run = {'study_id': self.sid, 'run_id': new_id('run'), 'module_id': 'A06',
                    'config': {'version': science.VERSION, 'cpu_per_pair': 1, 'timeout_seconds': 1800,
                               'vina_parameters': {'scoring': 'vina', 'exhaustiveness': 8, 'num_modes': 2,
                                                   'energy_range_kcal_mol': 3, 'seed': 1}}}
        self.folder = self.home / 'runs/A06' / self.run['run_id'] / 'rescue'
        self.binary_ref = self.w.save('tools/vina.exe', 'synthetic bytes, never executed', 'scoring_vina')
        self.binary = verified_file(self.home, self.binary_ref)
        self.ligand = self.w.save('inputs/ligand.pdbqt', geometry.atom(1, 0) + '\n', 'prepared_ligand')
        self.receptor_ref = self.w.save('inputs/receptor.pdbqt', geometry.atom(7, 1) + '\n', 'receptor')
        self.compound = {'compound_id': 'C1', 'state': 'ready', 'files': [self.ligand]}
        self.receptor = {'target_id': 'HGNC:1', 'symbol': '合成受体', 'state': 'ready', 'quality': '探索',
                         'receptor': self.receptor_ref, 'mode': 'predicted_sites',
                         'regions': [{'region_id': 'region_1', 'center': [0, 0, 0], 'size': [10, 10, 10]},
                                     {'region_id': 'region_2', 'center': [1, 0, 0], 'size': [10, 10, 10]}]}
        self.scores = {'region_1': -5.125, 'region_2': -9.25}

    def synthetic_execution(self, home, folder, binary, ligand, receptor, region, config):
        """仅替代外部Vina执行，命令、日志、所有模式和执行记录真实落盘供原校验器回算。"""
        folder.mkdir(parents=True, exist_ok=False)
        output = folder / 'poses.pdbqt'
        arguments = pair_engine.arguments(binary, verified_file(home, receptor), verified_file(home, ligand),
                                          region, output, config)
        command = {'configuration': deepcopy(config), 'ligand': ligand, 'receptor': receptor,
                   'box': deepcopy(region), 'executable': file_record(home, binary, 'scoring_vina'),
                   'arguments': arguments}
        write_json(folder / 'command.json', command)
        (folder / 'stdout.txt').write_text('synthetic execution', 'utf-8')
        (folder / 'stderr.txt').write_text('', 'utf-8')
        score = self.scores[region['region_id']]
        value = {'state': 'completed' if score is not None else 'failed', 'score': score,
                 'returncode': 0 if score is not None else 1, 'mode_count': 2 if score is not None else 0,
                 'top_mode': 1 if score is not None else None, 'failure_kind': None if score is not None else 'tool_error',
                 'reason_zh': '' if score is not None else '明确合成工具失败',
                 'files': [file_record(home, folder / name, 'scoring_' + Path(name).stem)
                           for name in ('command.json', 'stdout.txt', 'stderr.txt')]}
        if score is not None:
            raw = f'MODEL 1\r\nREMARK VINA RESULT: {score} 0 0\r\n' + geometry.atom(1, .1) + '\r\nENDMDL\r\n'
            raw += 'MODEL 2\r\nREMARK VINA RESULT: -50.0 1 1\r\n' + geometry.atom(1, .2) + '\r\nENDMDL\r\n'
            output.write_bytes(raw.encode('ascii'))
            value['pose'] = file_record(home, output, 'scoring_pose')
            value['files'].append(value['pose'])
        write_json(folder / 'execution.json', value)
        return file_record(home, folder / 'execution.json', 'scoring_execution')

    def score_pair(self):
        return science._score_pair(self.w, self.sid, self.run, 1, self.compound, self.receptor,
                                   self.binary, self.folder / 'scores', lambda _: None)

    def test_regional_scoring_selects_lowest_valid_top1_and_resumes_without_execution(self):
        with patch.object(pair_engine, 'execute', side_effect=self.synthetic_execution) as execute:
            row = self.score_pair()
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(row['score'], -9.25)
        self.assertEqual(row['region_id'], 'region_2')
        self.assertFalse(row['partial_regions'])
        raw = verified_file(self.home, row['top1_pose']).read_bytes()
        self.assertTrue(raw.startswith(b'MODEL 1\r\n'))
        self.assertIn(b'-9.25', raw)
        self.assertNotIn(b'MODEL 2', raw)
        before = {path.relative_to(self.home).as_posix(): sha256(path.read_bytes()).hexdigest()
                  for path in self.folder.rglob('*') if path.is_file()}
        with patch.object(pair_engine, 'execute', side_effect=AssertionError('成功区域不得再次执行')):
            self.assertEqual(self.score_pair(), row)
        for name, digest in before.items():
            self.assertEqual(sha256((self.home / name).read_bytes()).hexdigest(), digest)

    def test_failed_region_remains_empty_with_diagnostic_and_is_not_counted_as_zero(self):
        self.scores['region_1'] = None
        with patch.object(pair_engine, 'execute', side_effect=self.synthetic_execution):
            row = self.score_pair()
        self.assertEqual(row['score'], -9.25)
        self.assertTrue(row['partial_regions'])
        failed = row['regions'][0]
        self.assertEqual(failed['state'], 'failed')
        self.assertIsNone(failed['score'])
        self.assertEqual(failed['reason_zh'], '明确合成工具失败')
        self.assertFalse(failed['retryable'])
        with patch.object(pair_engine, 'execute', side_effect=AssertionError('稳定失败也须复验原记录')):
            self.assertEqual(self.score_pair(), row)

    def test_pair_validation_rejects_cross_pair_region_order_and_selected_score_tamper(self):
        with patch.object(pair_engine, 'execute', side_effect=self.synthetic_execution):
            row = self.score_pair()
        packet = {'binary': self.binary_ref}
        science._validate_new_pair(self.home, self.run, packet, 1, row, self.compound, self.receptor)
        cross = deepcopy(row)
        cross['regions'][0]['execution'] = self.w.json(
            f'runs/A06/{self.run["run_id"]}/rescue/scores/pair_000002/region_0001/attempt_cross/execution.json',
            read_json(verified_file(self.home, row['regions'][0]['execution'])))
        reordered = deepcopy(row)
        reordered['regions'].reverse()
        changed = dict(row, score=-100.0)
        for tampered in (cross, reordered, changed):
            with self.subTest(tampered=tampered['score']), self.assertRaises(ContractError):
                science._validate_new_pair(self.home, self.run, packet, 1, tampered, self.compound, self.receptor)

    def test_download_pose_is_bound_to_actual_execution_even_when_other_file_bytes_match(self):
        with patch.object(pair_engine, 'execute', side_effect=self.synthetic_execution):
            row = self.score_pair()
        science._validate_pose(self.home, self.run, row)
        identical = self.w.save('other_pair/poses.pdbqt', verified_file(self.home, row['original_pose']).read_bytes(),
                                row['original_pose']['role'])
        with self.assertRaises(ContractError):
            science._validate_pose(self.home, self.run, dict(row, original_pose=identical))
        raw = verified_file(self.home, row['original_pose']).read_bytes()
        second = raw[raw.index(b'MODEL 2'):]
        selected_second = self.w.save(f'runs/A06/{self.run["run_id"]}/rescue/forged_top1.pdbqt', second, 'rescue_top1_pose')
        with self.assertRaises(ContractError):
            science._validate_pose(self.home, self.run, dict(row, top1_pose=selected_second))

    def source_fixture(self):
        """构造有序2×2原始准备与发布表；语义篡改时刷新SHA以测试领域约束。"""
        prep_id, score_id = new_id('run'), new_id('run')
        fixed = {'input_key': 'original-input', 'analysis_parameter_hash': fingerprint('fixed'),
                 'compounds': [{'compound_id': 'C1', 'name': '合成成分一'}, {'compound_id': 'C2', 'name': '合成成分二'}],
                 'receptors': [{'target_id': 'HGNC:1', 'symbol': '受体一'}, {'target_id': 'HGNC:2', 'symbol': '受体二'}]}
        fixed_ref = self.w.json('source/fixed.json', {'study_id': self.sid, 'stage': 'A06_INPUT', 'payload': fixed})
        compounds = [dict(self.compound), dict(self.compound, compound_id='C2')]
        receptors = [dict(self.receptor), {'target_id': 'HGNC:2', 'symbol': '受体二', 'state': 'NA',
                                         'quality': '待核查', 'reason_zh': '原准备未通过'}]
        fact_ref = self.w.json('source/fact.json', {'connection': {}, 'compounds': compounds})
        qualification = {'source_preparation_fact': fact_ref, 'receptors': receptors}
        qual_ref = self.w.json('source/qualification.json', qualification)
        original_pose = self.w.save('source/original/poses.pdbqt',
            'MODEL 1\nREMARK VINA RESULT: -7.125 0 0\n' + geometry.atom(1, .1) + '\nENDMDL\n', 'scoring_pose')
        original_execution = self.w.json('source/original/execution.json', {'pose': original_pose})
        pairs = [{'compound_id': compound['compound_id'], 'target_id': target['target_id'],
                  'state': 'completed' if target['target_id'] == 'HGNC:1' else 'NA',
                  'score': -7.125 if target['target_id'] == 'HGNC:1' else None,
                  'quality': '探索' if target['target_id'] == 'HGNC:1' else '待核查',
                  'reason_zh': '' if target['target_id'] == 'HGNC:1' else '原准备未通过',
                  'input_key': fixed['input_key'],
                  'execution': original_execution if target['target_id'] == 'HGNC:1' else None}
                 for compound in fixed['compounds'] for target in fixed['receptors']]
        published = [{key: row[key] for key in ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh', 'input_key')}
                     | {'execution_path': row['execution']['path'] if row['execution'] else None,
                        'state_zh': '已评分' if row['state'] == 'completed' else '准备NA'} for row in pairs]
        scoring_packet = {'pairs': pairs}
        packet_ref = self.w.json('source/scoring_packet.json', scoring_packet)
        preparation = {'study_id': self.sid, 'module_id': 'A06_PREP', 'run_id': prep_id,
                       'config': {'version': 'synthetic.preparation.1'},
                       'inputs': {'system_input_ref': fixed_ref}}
        scoring = {'study_id': self.sid, 'module_id': 'A06', 'run_id': score_id,
                   'config': {'version': 'synthetic.scoring.1'},
                   'parent_runs': {'A06_PREP': prep_id}}
        prepared = {'summary': {'input_key': fixed['input_key']}, 'anomalies': [], 'outcome': 'success',
                    'tables': {'preparation_packet': [qual_ref], 'receptor_preparation': receptors}}
        scored = {'summary': {'input_key': fixed['input_key']}, 'anomalies': [], 'outcome': 'success',
                  'tables': {'scoring_packet': [packet_ref], 'plan_scoring_pairs': published}}
        for run, result in ((preparation, prepared), (scoring, scored)):
            self.w.manifest['runs'][run['run_id']] = {
                'run_file': self.w.json(f'source/{run["run_id"]}/run.json', run),
                'result_file': self.w.json(f'source/{run["run_id"]}/result.json', result)}
        return {'prep_id': prep_id, 'score_id': score_id, 'fixed': fixed, 'pairs': pairs, 'packet': scoring_packet,
                'scored': scored, 'prepared': prepared, 'receptors': receptors}

    def source_data(self, source):
        return science.source_data(self.w, self.w.load(self.sid), source['prep_id'], source['score_id'])

    def test_source_data_preserves_fixed_order_and_only_selects_original_unavailable_targets(self):
        source = self.source_fixture()
        value = self.source_data(source)
        self.assertEqual(value['targets'], ['HGNC:2'])
        self.assertEqual([(row['compound_id'], row['target_id']) for row in value['scoring_packet']['pairs']],
                         [('C1', 'HGNC:1'), ('C1', 'HGNC:2'), ('C2', 'HGNC:1'), ('C2', 'HGNC:2')])
        source['fixed']['receptors'].reverse()
        ref = self.w.json('source/fixed.json', {'study_id': self.sid, 'stage': 'A06_INPUT', 'payload': source['fixed']})
        prep = self.w.run(self.w.manifest, source['prep_id'])
        prep['inputs']['system_input_ref'] = ref
        self.w.manifest['runs'][source['prep_id']]['run_file'] = self.w.json(f'source/{source["prep_id"]}/run.json', prep)
        with self.assertRaises(ContractError):
            self.source_data(source)

    def test_source_data_rejects_reordered_or_duplicated_packet_pairs_with_valid_file_hash(self):
        source = self.source_fixture()
        source['packet']['pairs'] = list(reversed(source['pairs']))
        self.refresh_packet(source)
        with self.assertRaises(ContractError):
            self.source_data(source)
        source['packet']['pairs'] = [deepcopy(source['pairs'][0]) for _ in range(4)]
        self.refresh_packet(source)
        with self.assertRaises(ContractError):
            self.source_data(source)

    def refresh_packet(self, source):
        """测试明确篡改后登记实际新SHA，避免仅靠通用损坏检测覆盖领域校验。"""
        source['scored']['tables']['scoring_packet'] = [self.w.json('source/scoring_packet.json', source['packet'])]
        self.w.manifest['runs'][source['score_id']]['result_file'] = self.w.json(
            f'source/{source["score_id"]}/result.json', source['scored'])

    def test_source_data_rejects_published_pair_identity_tamper_even_with_same_score(self):
        source = self.source_fixture()
        source['scored']['tables']['plan_scoring_pairs'][0]['compound_id'] = 'different-compound'
        self.refresh_packet(source)
        with self.assertRaises(ContractError):
            self.source_data(source)

    def test_export_interruption_preserves_partial_directory_and_resumes_in_unique_directory(self):
        source = self.source_fixture()
        self.run['config'].update(vina_sha256=self.binary_ref['sha256'], implementation_sha256={})
        self.run['inputs'] = {'source_preparation_run': self.w.manifest['runs'][source['prep_id']]['run_file'],
                              'source_scoring_run': self.w.manifest['runs'][source['score_id']]['run_file'],
                              'source_binding': {'synthetic': True},
                              'rescue_request': self.w.json('source/rescue_request.json', {'synthetic': True})}
        unavailable = dict(source['receptors'][1], source_kind='rescue')
        self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, self.run['run_id'], 'receptor_HGNC_2', unavailable, [])
        directories = []
        def export(home, packet, folder):
            folder.mkdir(parents=True, exist_ok=False)
            directories.append(folder)
            partial = folder / 'plot.svg'
            partial.write_text('<svg>synthetic attempt</svg>', 'utf-8')
            if len(directories) == 1:
                raise RuntimeError('合成导出中断')
            return [file_record(home, partial, 'figure')], []
        from science_modules.a06 import system_rescue_display, system_rescue_runtime, system_scoring
        with patch.object(system_rescue_runtime, 'activate'), \
                patch.object(science, 'configuration', return_value=deepcopy(self.run['config'])), \
                patch.object(system_scoring, 'check_tools', return_value=self.binary), \
                patch.object(system_rescue_display, 'export', side_effect=export), \
                patch.object(pair_engine, 'execute', side_effect=AssertionError('原评分和NA不可重新计算')):
            with self.assertRaises(RuntimeError):
                science.compute(self.w, self.sid, self.run, tools=self.home, repair_packages=self.home, progress=lambda _: None)
            original = (directories[0] / 'plot.svg').read_bytes()
            stats, tables, _, _ = science.compute(self.w, self.sid, self.run, tools=self.home,
                                                 repair_packages=self.home, progress=lambda _: None)
        self.assertEqual(len(directories), 2)
        self.assertNotEqual(directories[0], directories[1])
        self.assertEqual((directories[0] / 'plot.svg').read_bytes(), original)
        self.assertEqual(stats['reused_scored_pairs'], 2)
        self.assertEqual(stats['new_scored_pairs'], 0)
        self.assertEqual(len(tables['plan_scoring_pairs']), 4)


if __name__ == '__main__':
    unittest.main()
