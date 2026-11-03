"""补执行端到端隔离夹具：保留原下载/预测和科学拒绝，只替换真实目录故障。"""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import file_record, new_id, read_json, write_json
from science_modules.a06 import receptor_path_repair as repair
from science_modules.a06 import two_pass


class ReceptorPathRepairTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.test-tmp'
        parent.mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix='repair_', dir=parent))
        self.home = root / new_id('study')
        self.home.mkdir()
        self.tools = root / 'tools'
        (self.tools / 'environments' / 'docking_packages').mkdir(parents=True)
        self.repair_id = new_id('receptorpathrepair')
        self.batch_id = new_id('systembatch')
        self.batch = self.save('batch.json', {'study_id': self.home.name, 'batch_id': self.batch_id})
        self.text = 'ATOM      1  CA  ALA A   1       1.250  -2.500   3.750  1.00 10.00           C\nTER\nEND\n'
        self.pdbqt = self.text.splitlines()[0][:70] + ' 0.000 C\n'
        self.box = {'center': [1.25, -2.5, 3.75], 'size': [10.5, 11.25, 12.75]}
        self.folder = self.home / 'decisions/analysis_plans/system_batches' / self.batch_id / 'receptor_path_repairs' / self.repair_id
        compounds = [{'compound_id': 'C1', 'state': 'ready', 'reason_zh': '有原配体'},
                     {'compound_id': 'C2', 'state': 'NA', 'reason_zh': '缺原配体'}]
        rows, connected, fixed = [], [], []
        for index in range(4):
            symbol = 'FIXTURE' + str(index)
            tid = 'HGNC:' + str(index + 1)
            spec = {'pdb_id': '1AB' + str(index), 'uniprot': 'P00001', 'chains': ['A'],
                    'pocket': 'p2rank', 'source_type': 'experimental'}
            candidate = {'spec': spec}
            source = self.save_text(f'original/{index}/prediction_input.pdb', self.text)
            input_file = self.save_text(f'original/{index}/receptors/{symbol}_input.pdb', self.text)
            pocket = {'rank': 1, 'runs': [{'rank': 1}, {'rank': 1}], 'mapped_indices': ['A_1'], 'confirmation': {}}
            pocket['pocket_key'] = two_pass.pocket_key(spec, pocket)
            evidence = {'identity': {'target_id': tid, 'uniprot': 'P00001', 'chains': ['A'],
                                     'species': 9606, 'polymer_type': 'Protein', 'sequence_matches': True},
                        'structure_id': spec['pdb_id'], 'receptor_ready': False, 'pocket_complete': True,
                        'environment_resolved': index != 2, 'box': self.box, 'pocket': pocket,
                        'predicted_pocket': {'input_pdb': source, 'files': [source]},
                        'files': [source, input_file],
                        'error_zh': '[WinError 267] 目录名称无效。' if index != 3 else '原工具模板失败'}
            trace = {'candidate': candidate, 'evidence': evidence,
                     'assessment': {'state': 'failed', 'reason_zh': '原尝试不可用'}}
            rows.append({'target_id': tid, 'symbol': symbol, 'state': 'NA', 'quality': '待核查',
                         'reason_zh': '原尝试不可用', 'attempts': [trace]})
            connected.append({'target_id': tid, 'symbol': symbol, 'candidates': [candidate]})
            fixed.append({'target_id': tid, 'symbol': symbol})
        self.fixed = {'input_key': 'fixed', 'compounds': compounds, 'receptors': fixed, 'pair_count': 8,
                      'human_reviews': {}, 'replacement_after_preparation_failure': False}
        decision = self.save('fixed.json', {'study_id': self.home.name, 'batch_id': self.batch_id,
                                            'stage': 'A06_INPUT', 'human_review_written': False, 'payload': self.fixed})
        self.fact = {'schema_version': 'A06.system_preparation.2', 'study_id': self.home.name,
                     'human_review_written': False, 'batch_file': self.batch, 'system_input_ref': decision,
                     'input_key': 'fixed', 'compounds': compounds, 'receptors': rows, 'config': {},
                     'connection': {'receptors': connected, 'compounds': compounds}}
        self.source = self.save('original_packet.json', self.fact)

    def save(self, name, value):
        target = self.home / name
        write_json(target, value)
        return file_record(self.home, target, 'fixture')

    def save_text(self, name, text):
        target = self.home / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('ascii'))
        return file_record(self.home, target, 'fixture')

    def cli(self, arguments, **kwargs):
        inp = Path(arguments[4])
        self.assertEqual(inp.read_bytes(), self.text.encode('ascii'))
        if 'FIXTURE1' in inp.resolve().name:
            return subprocess.CompletedProcess(arguments, 1, '', '盒内缺失残基')
        Path(arguments[6] + '.pdbqt').write_bytes(self.pdbqt.encode('ascii'))
        return subprocess.CompletedProcess(arguments, 0, 'OK', '')

    def execute(self):
        return repair.compute(self.home, self.source, self.repair_id, self.tools, lambda _: None)

    def test_only_eligible_candidates_run_and_old_order_and_evidence_survive(self):
        with patch.object(repair.receptor_cli_paths.subprocess, 'run', side_effect=self.cli) as run:
            reference, (facts, receptors, decisions) = self.execute()
            self.assertEqual(run.call_count, 2)
        self.assertEqual([r['state'] for r in receptors], ['ready', 'NA', 'NA', 'NA'])
        self.assertEqual(receptors[0]['quality'], '探索')
        self.assertIn('原始日志', receptors[1]['reason_zh'])
        self.assertEqual(facts['receptors'][2:], self.fact['receptors'][2:])
        self.assertEqual(facts['compounds'], self.fact['compounds'])
        self.assertEqual([r['target_id'] for r in receptors], [r['target_id'] for r in self.fixed['receptors']])
        self.assertTrue(all(d['human_review_written'] is False for d in decisions))
        self.assertEqual(read_json(self.home / self.source['path']), self.fact)
        self.assertEqual(repair.read_packet(self.home, reference)[2], (facts, receptors, decisions))

    def test_completed_replay_never_reinvokes_tools(self):
        with patch.object(repair.receptor_cli_paths.subprocess, 'run', side_effect=self.cli) as run:
            first = self.execute()
            self.assertEqual(self.execute(), first)
            self.assertEqual(run.call_count, 2)

    def test_incomplete_second_attempt_preserves_first_and_only_retries_missing(self):
        def interrupt(arguments, **kwargs):
            if 'FIXTURE1' in Path(arguments[4]).resolve().name:
                raise OSError('测试中断')
            return self.cli(arguments, **kwargs)
        with patch.object(repair.receptor_cli_paths.subprocess, 'run', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.execute()
        self.assertFalse((self.folder / 'packet.json').exists())
        self.assertEqual(len(list((self.folder / 'candidate_000_000').glob('*/receipt.json'))), 1)
        with patch.object(repair.receptor_cli_paths.subprocess, 'run', side_effect=self.cli) as run:
            self.execute()
            self.assertEqual(run.call_count, 1)
            self.assertIn('FIXTURE1', Path(run.call_args.args[0][4]).resolve().name)
        self.assertEqual(len(list((self.folder / 'candidate_001_000').iterdir())), 2)

    def test_changed_source_and_corrupted_output_are_rejected(self):
        with patch.object(repair.receptor_cli_paths.subprocess, 'run', side_effect=self.cli):
            ref, _ = self.execute()
        packet = read_json(self.home / ref['path'])
        receipt = read_json(self.home / packet['patches'][0]['path'])
        (self.home / receipt['receptor']['path']).write_text('corrupted', 'ascii')
        with patch.object(repair.receptor_cli_paths.subprocess, 'run') as run:
            with self.assertRaises(ContractError):
                self.execute()
            run.assert_not_called()
        changed = deepcopy(self.fact)
        changed['input_key'] = 'changed'
        self.source = self.save('changed.json', changed)
        with self.assertRaises(ContractError):
            self.execute()

    def test_predictor_input_mismatch_stops_before_any_new_folder(self):
        changed = deepcopy(self.fact)
        ev = changed['receptors'][0]['attempts'][0]['evidence']
        ev['predicted_pocket']['input_pdb'] = self.save_text('different.pdb', 'different bytes')
        self.source = self.save('mismatch.json', changed)
        with patch.object(repair.receptor_cli_paths.subprocess, 'run') as run:
            with self.assertRaises(ContractError):
                self.execute()
            run.assert_not_called()
        self.assertFalse(self.folder.exists())

    def test_cross_study_and_changed_candidate_scope_stop(self):
        changed = deepcopy(self.fact)
        changed['study_id'] = new_id('study')
        self.source = self.save('cross.json', changed)
        with self.assertRaises(ContractError):
            self.execute()
        changed = deepcopy(self.fact)
        changed['connection']['receptors'][0]['candidates'][0]['spec']['pdb_id'] = '9ZZZ'
        self.source = self.save('candidate_changed.json', changed)
        with self.assertRaises(ContractError):
            self.execute()


if __name__ == '__main__':
    unittest.main()
