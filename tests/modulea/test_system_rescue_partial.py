"""未发表一版的完整登记区域恢复；真实合成执行原件，不运行Vina。"""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import read_json, verified_file
from science_modules.a06 import plan_score_pair
from science_modules.a06 import system_rescue_partial as partial
from science_modules.a06 import system_receptor_rescue_v2 as science
from tests.modulea import test_system_receptor_rescue_science as fixture


class PartialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.seed = fixture.SystemReceptorRescueScienceTests('test_regional_scoring_selects_lowest_valid_top1_and_resumes_without_execution')
        self.seed.setUp()
        self.addCleanup(self.seed.doCleanups)
        s = self.seed
        binary = s.folder / 'software/vina.exe'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(s.binary.read_bytes())
        s.binary = binary
        s.run['config']['vina_sha256'] = s.binary_ref['sha256']
        with patch.object(plan_score_pair, 'execute', side_effect=s.synthetic_execution):
            self.old = s.score_pair()
        self.checkpoints = [(ref, dict(read_json(verified_file(s.home, ref)), key=key))
                            for (rid, key), ref in s.w.checkpoints.items() if rid == s.run['run_id']]
        self.fixed = {'receptors': [{'target_id': s.receptor['target_id']}]}

    def restore(self, checkpoints=None):
        s = self.seed
        return partial.completed_pairs(s.home, s.run, self.checkpoints if checkpoints is None else checkpoints,
                                       [s.compound], [s.receptor], self.fixed)

    def test_all_registered_regions_restore_the_same_pair_without_execution_or_writes(self):
        before = {str(p): p.read_bytes() for p in self.seed.folder.rglob('*') if p.is_file()}
        with patch.object(plan_score_pair, 'execute', side_effect=AssertionError('成功区域禁止重算')):
            restored = self.restore()
        self.assertEqual(restored, [self.old])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.seed.folder.rglob('*') if p.is_file()})

    def test_missing_checkpoint_cannot_be_replaced_by_an_existing_top1_file(self):
        self.assertEqual(self.restore(self.checkpoints[:-1]), [])

    def test_cross_region_registered_execution_is_rejected(self):
        checkpoints = deepcopy(self.checkpoints)
        checkpoints[0][1]['payload']['execution'] = checkpoints[1][1]['payload']['execution']
        with self.assertRaises(ContractError):
            self.restore(checkpoints)

    def test_derived_top1_must_match_registered_scoring_pose_bytes(self):
        path = self.seed.home / self.old['top1_pose']['path']
        path.write_bytes(path.read_bytes().replace(b'-9.25', b'-1.00'))
        with self.assertRaises(ContractError):
            self.restore()

    def test_recovered_identity_cannot_change_key_symbol_stable_id_or_original_ready_object(self):
        target = {'target_id': 'HGNC:1', 'symbol': 'R1'}
        source = {'original_targets': ['HGNC:1']}
        value = dict(target, source_kind='rescue', state='ready', expected_uniprot='P00001')
        with patch.object(partial.prior, '_source_uniprot', return_value='P00001'):
            partial.verify_identity(self.seed.home, source, target, value)
            for change in ({'target_id': 'HGNC:2'}, {'symbol': 'R2'}, {'expected_uniprot': 'P00002'},
                           {'source_kind': 'original'}):
                with self.subTest(change=change), self.assertRaises(ContractError):
                    partial.verify_identity(self.seed.home, source, target, value | change)
            with self.assertRaises(ContractError):
                partial.verify_identity(self.seed.home, {'original_targets': []}, target, value)

    def test_preparation_counts_exclude_inherited_ready_receptors_and_keep_cumulative_scope(self):
        source = {'targets': ['HGNC:1', 'HGNC:2'], 'original_targets': ['HGNC:1', 'HGNC:2'],
                  'prepare_targets': ['HGNC:2'], 'fixed': {'compounds': [], 'input_key': 'fixed', 'analysis_parameter_hash': 'same'}}
        receptors = [{'target_id': target, 'state': 'ready', 'quality': '探索'} for target in source['targets']]
        stats = science.summary(source, receptors, [], [], [])
        self.assertEqual(stats['rescue_target_count'], 1)
        self.assertEqual(stats['rescued_receptors'], 1)
        self.assertEqual(stats['reused_prepared_receptors'], 1)
        self.assertEqual(stats['cumulative_rescued_receptors'], 2)
        self.assertEqual(stats['cumulative_rescue_target_count'], 2)


if __name__ == '__main__':
    unittest.main()
