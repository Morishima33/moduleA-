"""官方原件补救二版的归档复用、成功评分保全和逐对象身份失败。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import read_json, verified_file
from tests.modulea.test_system_receptor_rescue_science import ArchiveStudy
from science_modules.a06 import system_receptor_rescue_v2 as science


class ArchivedSourceRescueTests(unittest.TestCase):
    """真实临时归档字节；不连接网络，不更改任何研究。"""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rescue_v2_science_')
        self.addCleanup(self.temp.cleanup)
        self.w = ArchiveStudy(Path(self.temp.name))
        self.home, self.sid = self.w.home, self.w.sid
        self.url = 'https://alphafold.ebi.ac.uk/api/prediction/P00001'
        self.ref = self.w.json('registered/metadata.json', [{'uniprotAccession': 'P00001'}])
        self.request = self.w.json('registered/request.json', {
            'url': self.url, 'state': 'success', 'status': 200, 'file': self.ref,
            'created_at': '2026-10-22T00:00:00+00:00'})
        self.catalog = {self.url: {'kind': 'metadata', 'url': self.url, 'file': self.ref,
            'original_request': self.request, 'original_downloaded_at': '2026-10-22T00:00:00+00:00'}}
        self.run = {'run_id': 'run_new', 'study_id': self.sid, 'config': {'version': science.VERSION}}

    def test_exact_archive_reuse_keeps_original_http_fact_and_records_no_new_download(self):
        original = verified_file(self.home, self.request).read_bytes()
        fetch = science.archived_fetcher(self.home, self.home / 'reuse', self.catalog)
        with patch('urllib.request.urlopen', side_effect=AssertionError('已核验官方原件不得重复联网')):
            value, ref = fetch.get(self.url)
        self.assertEqual(value, [{'uniprotAccession': 'P00001'}])
        self.assertEqual(ref, self.ref)
        self.assertEqual(verified_file(self.home, self.request).read_bytes(), original)
        facts = [read_json(verified_file(self.home, item)) for item in fetch.records
                 if item['role'] == 'archived_official_reuse']
        self.assertEqual(len(facts), 1)
        self.assertFalse(facts[0]['new_http_request_performed'])
        self.assertEqual(facts[0]['original_request'], self.request)
        self.assertEqual(facts[0]['original_downloaded_at'], '2026-10-22T00:00:00+00:00')
        self.assertNotIn('status', facts[0])

    def test_corrupt_archived_bytes_block_instead_of_silently_falling_back_to_network(self):
        (self.home / self.ref['path']).write_text('corrupt', encoding='utf-8')
        fetch = science.archived_fetcher(self.home, self.home / 'reuse', self.catalog)
        with patch('urllib.request.urlopen', side_effect=AssertionError('损坏原件不能静默替换')):
            with self.assertRaises(ContractError):
                fetch.get(self.url)

    def test_url_with_similar_id_is_not_matched_as_archived_source(self):
        fetch = science.archived_fetcher(self.home, self.home / 'reuse', self.catalog)
        with patch('science_modules.a06.automatic_coverage_sources.Fetcher.get', return_value=({}, self.ref)) as network:
            fetch.get(self.url + '0')
        network.assert_called_once_with(self.url + '0', 'json')

    def test_missing_unique_identity_is_evidenced_na_for_this_object(self):
        original = {'target_id': 'HGNC:1', 'symbol': '合成对象'}
        with patch.object(science.prior, '_source_uniprot', side_effect=ContractError('无唯一稳定编号')):
            value = science.prepare_target(self.w, self.sid, self.run, {}, original,
                self.home / 'receptor', Path('unused'), Path('unused'), lambda _: None)
        self.assertEqual(value['state'], 'NA')
        self.assertEqual(value['failure_stage'], 'identity_verification')
        self.assertIn('无唯一稳定编号', value['reason_zh'])
        self.assertFalse(value['retryable'])
        self.assertTrue(value['evidence_files'])
        self.assertIsNone(value['expected_uniprot'])

    def test_completed_pair_is_kept_whole_and_only_remaining_ready_pair_is_executed(self):
        # 继承记录故意包含旧代次、Top-1和额外证据；整对象必须保持，不能重建或改成original。
        kept = {'compound_id': 'C1', 'target_id': 'HGNC:1', 'state': 'completed', 'score': -9.125,
                'quality': '探索', 'source_kind': 'rescue', 'reason_zh': '', 'execution': {'path': 'old'},
                'top1_pose': {'path': 'old/top1'}, 'extra_original_evidence': {'all': [1, 2]}}
        missing = {'compound_id': 'C1', 'target_id': 'HGNC:2', 'state': 'NA', 'score': None,
                   'quality': '未通过', 'source_kind': 'rescue', 'reason_zh': '下载失败', 'execution': None}
        source = {'targets': ['HGNC:2'], 'baseline_packet': {'pairs': [kept, missing]},
                  'fixed': {'receptors': [{'target_id': 'HGNC:1'}, {'target_id': 'HGNC:2'}]}}
        compounds = [{'compound_id': 'C1', 'state': 'ready'}]
        receptors = [{'target_id': 'HGNC:1', 'state': 'ready'},
                     {'target_id': 'HGNC:2', 'state': 'ready', 'quality': '探索'}]
        scored = dict(missing, state='completed', score=-7.5, reason_zh='', regions=[{'execution': {}}])
        with patch.object(science.prior, '_score_pair', return_value=scored) as score:
            pairs, reused, fresh = science.merge_pairs(self.w, self.sid, self.run, source,
                compounds, receptors, self.home / 'binary', self.home / 'scores', lambda _: None)
        self.assertEqual(pairs[0], kept)
        self.assertIsNot(pairs[0], kept)
        self.assertEqual(reused, [['C1', 'HGNC:1']])
        self.assertEqual(fresh, [['C1', 'HGNC:2']])
        self.assertEqual(score.call_count, 1)
        self.assertEqual(score.call_args.args[3], 2)

    def test_pending_ligand_keeps_empty_score_and_both_missing_reasons(self):
        original = {'compound_id': 'C1', 'target_id': 'HGNC:1', 'state': 'NA', 'score': None,
                    'reason_zh': '旧原因', 'quality': '未通过'}
        source = {'targets': ['HGNC:1'], 'baseline_packet': {'pairs': [original]},
                  'fixed': {'receptors': [{'target_id': 'HGNC:1'}]}}
        with patch.object(science.prior, '_score_pair', side_effect=AssertionError('准备未完成不能评分')):
            pairs, reused, fresh = science.merge_pairs(self.w, self.sid, self.run, source,
                [{'compound_id': 'C1', 'state': 'NA', 'reason_zh': '配体缺官方三维'}],
                [{'target_id': 'HGNC:1', 'state': 'NA', 'quality': '待核查', 'reason_zh': '受体身份不足'}],
                self.home / 'binary', self.home / 'scores', lambda _: None)
        self.assertEqual(pairs[0]['reason_zh'], '配体缺官方三维；受体身份不足')
        self.assertIsNone(pairs[0]['score'])
        self.assertEqual((reused, fresh), ([], []))

    def test_baseline_failed_execution_for_an_already_ready_receptor_stays_failed_with_evidence(self):
        failed = {'compound_id': 'C1', 'target_id': 'HGNC:1', 'state': 'failed', 'score': None,
                  'quality': '探索', 'source_kind': 'rescue', 'reason_zh': '原Vina非零退出',
                  'regions': [{'execution': {'path': 'old/execution.json'}, 'state': 'failed'}]}
        source = {'targets': [], 'baseline_packet': {'pairs': [failed]},
                  'fixed': {'receptors': [{'target_id': 'HGNC:1'}]}}
        with patch.object(science.prior, '_score_pair', side_effect=AssertionError('非本轮对象不重算')):
            pairs, reused, fresh = science.merge_pairs(self.w, self.sid, self.run, source,
                [{'compound_id': 'C1', 'state': 'ready'}],
                [{'target_id': 'HGNC:1', 'state': 'ready', 'quality': '探索'}],
                self.home / 'binary', self.home / 'scores', lambda _: None)
        self.assertEqual(pairs[0], failed)
        self.assertEqual((reused, fresh), ([], []))

    def test_prepared_model_must_use_all_three_exact_registered_responses(self):
        model_url = 'https://alphafold.ebi.ac.uk/files/AF-P00001-F1-model_v6.cif'
        pae_url = 'https://alphafold.ebi.ac.uk/files/AF-P00001-F1-predicted_aligned_error_v6.json'
        model = self.w.save('registered/model.cif', 'synthetic exact archived model bytes')
        pae = self.w.json('registered/pae.json', [{'predicted_aligned_error': [[0]]}])
        info = {'uniprotAccession': 'P00001', 'entryId': 'AF-P00001-F1', 'latestVersion': 6,
                'cifUrl': model_url, 'paeDocUrl': pae_url}
        metadata = self.w.json('registered/exact_metadata.json', [info])
        catalog = {self.url: {'file': metadata}, model_url: {'file': model}, pae_url: {'file': pae}}
        row = {'target_id': 'HGNC:1', 'expected_uniprot': 'P00001',
               'origin': {'spec': {'source_type': 'alphafold'}, 'model_metadata': info,
                          'model_metadata_file': metadata, 'cif': model, 'pae_file': pae}}
        source = {'baseline_scoring': {'config': {'version': 'A06.system_scoring_paths.1'}},
                  'baseline_receptors': [{'target_id': 'HGNC:1', 'state': 'NA'}]}
        science.validate_source_use(self.home, source, row, catalog)
        for key, raw in [('cif', b'different but individually correctly hashed model'),
                         ('pae_file', b'[{"predicted_aligned_error":[[1]]}]'),
                         ('model_metadata_file', json.dumps([dict(info, latestVersion=5)]).encode())]:
            altered = deepcopy(row)
            altered['origin'][key] = self.w.save('substitute/' + key, raw)
            with self.subTest(key=key), self.assertRaises(ContractError):
                science.validate_source_use(self.home, source, altered, catalog)

    def test_claim_of_completed_old_experimental_route_requires_its_actual_audit(self):
        row = {'target_id': 'HGNC:1', 'expected_uniprot': 'P00001',
               'prior_experimental_run_id': 'run_old', 'origin': {'spec': {'source_type': 'experimental'}}}
        source = {'baseline_scoring': {'run_id': 'run_old', 'config': {'version': science.prior.VERSION}},
                  'baseline_receptors': [{'target_id': 'HGNC:1', 'state': 'NA', 'evidence_files': []}]}
        with self.assertRaises(ContractError):
            science.validate_source_use(self.home, source, row, {'some registered response': {}})

    def test_registered_baseline_official_sequence_is_reused_without_network(self):
        official = {'primaryAccession': 'P00001', 'organism': {'taxonId': 9606}, 'sequence': {'value': 'MAGA'}}
        ref = self.w.json('baseline/sequence.json', official)
        request = self.w.json('baseline/sequence_request.json', {
            'url': 'https://rest.uniprot.org/uniprotkb/P00001.json', 'state': 'success', 'status': 200, 'file': ref})
        fetch = unittest.mock.Mock()
        fetch.get.side_effect = AssertionError('本批成功官方序列不应重复联网')
        value, used = science._official_sequence(self.home, {}, 'P00001', fetch,
                                                  previous={'evidence_files': [ref, request]})
        self.assertEqual((value, used), (official, ref))
        fetch.get.assert_not_called()

    def test_saved_regions_accept_only_json_container_roundtrip_not_changed_geometry(self):
        rebuilt = [{'region_id': 'p1', 'center': [1.0, 2.0, 3.0],
                    'environment': {'pocket_residues': [('A', '207')]}}]
        saved = json.loads(json.dumps(rebuilt))
        row = {'quality': '探索', 'expected_uniprot': 'P00001',
               'origin': {'spec': {'uniprot': 'P00001'}}, 'regions': saved, 'rejected_regions': []}
        with patch('science_modules.a06.automatic_coverage_prepare.check_exploration', return_value=(rebuilt, [])):
            with self.assertRaises(ContractError):
                science.prior._verify_prepared(self.home, row)
            science.verify_prepared(self.home, row)
            changed = deepcopy(row)
            changed['regions'][0]['center'][0] += 0.001
            with self.assertRaises(ContractError):
                science.verify_prepared(self.home, changed)

    def test_scoring_receives_json_canonical_region_without_altering_original(self):
        receptor = {'regions': [{'environment': {'pocket_residues': [('A', '207')]}}]}
        before = deepcopy(receptor)
        with patch.object(science.prior, '_score_pair', return_value={'state': 'completed'}) as score:
            science.score_pair(self.w, self.sid, self.run, 1, {}, receptor, self.home / 'vina',
                               self.home / 'scores', lambda _: None)
        self.assertEqual(score.call_args.args[5]['regions'][0]['environment']['pocket_residues'], [['A', '207']])
        self.assertEqual(receptor, before)


if __name__ == '__main__':
    unittest.main()
