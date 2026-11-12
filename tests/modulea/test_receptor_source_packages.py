"""官方受体响应导入的真实字节、旧登记链和当前元数据核验；只用合成资料。"""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from contracts import ContractError, encoded, fingerprint
from storage import file_record, new_id, read_json, write_json


class PackageStudy:
    """最小研究索引读者；真实临时原件与公开登记方法的文件副作用照常执行。"""
    def __init__(self, root):
        self.root, self.sid = root, new_id('study')
        self.home = root / 'studies' / self.sid
        self.home.mkdir(parents=True)

    def location(self, sid):
        assert sid == self.sid
        return self.home

    def load(self, sid):
        return read_json(self.location(sid) / 'manifest.json')

    def save(self, value):
        write_json(self.home / 'manifest.json', value, replace=(self.home / 'manifest.json').exists())

    def run(self, m, rid):
        return read_json(self.home / m['runs'][rid]['run_file']['path'])

    def result(self, m, rid):
        return read_json(self.home / m['runs'][rid]['result_file']['path'])

    def approved(self, m, rid):
        return m['current'].get('A06_PREP') == rid

    def active(self, m, rid):
        return rid in m['current'].values()

    def latest_review(self, *_):
        return None

    def json(self, path, value):
        target = self.home / path
        write_json(target, value, replace=target.exists())
        return file_record(self.home, target, 'synthetic_source')


class ReceptorSourcePackageTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / 'src/modulea/core/receptor_source_packages.py'
        self.assertTrue(path.is_file(), '官方受体来源登记尚未实现')
        self.core = importlib.import_module('modulea.core.receptor_source_packages')
        self.temp = tempfile.TemporaryDirectory(prefix='receptor_source_package_')
        self.addCleanup(self.temp.cleanup)
        self.w = PackageStudy(Path(self.temp.name) / 'data')
        self.sid, self.prep, self.score = self.w.sid, new_id('run'), new_id('run')
        self.old_sid, self.old_run = new_id('study'), new_id('run')
        self.target, self.uniprot = 'HGNC:123', 'P00001'
        self.metadata = [{'entryId': 'AF-P00001-F1', 'latestVersion': 6, 'uniprotAccession': self.uniprot,
                          'uniprotStart': 1, 'uniprotEnd': 2,
                          'cifUrl': 'https://alphafold.ebi.ac.uk/files/AF-P00001-F1-model_v6.cif',
                          'paeDocUrl': 'https://alphafold.ebi.ac.uk/files/AF-P00001-F1-predicted_aligned_error_v6.json'},
                         {'entryId': 'AF-P00001-2-F1', 'uniprotAccession': 'P00001-2'}]
        self.artifacts = {'metadata': encoded(self.metadata), 'model': b'data_synthetic_model\n',
                          'pae': encoded([{'predicted_aligned_error': [[0, 1], [1, 0]]}])}
        self.staging = {'target': {'hgnc_id': self.target, 'uniprot': self.uniprot, 'model_id': 'AF-P00001-F1',
                                  'model_version': 6, 'sequence_start': 1, 'sequence_end': 2},
                        'source_archive_membership': {'study_id': self.old_sid, 'run_id': self.old_run}, 'sources': [],
                        'identity_validation': {'coordinate_sequence_matches_current_human_uniprot': True},
                        'previous_registered_preparation': {'state': 'ready', 'quality': '探索', 'regions': ['not-a-proof']}}
        self.old_result = {'study_id': self.old_sid, 'run_id': self.old_run, 'module_id': 'A06',
                           'artifact_id': 'old_artifact', 'outcome': 'success', 'files': []}
        for kind, url in (('metadata', 'https://alphafold.ebi.ac.uk/api/prediction/' + self.uniprot),
                          ('model', self.metadata[0]['cifUrl']), ('pae', self.metadata[0]['paeDocUrl'])):
            suffix = 'cif' if kind == 'model' else 'json'
            original = self.ref(f'old/{kind}.{suffix}', self.artifacts[kind])
            request = {'state': 'success', 'status': 200, 'url': url, 'created_at': '2026-10-22T00:00:00Z', 'file': original}
            self.artifacts[kind + '_request'] = encoded(request)
            request_ref = self.ref(f'old/{kind}_request.json', self.artifacts[kind + '_request'])
            self.old_result['files'].extend([original, request_ref])
            self.staging['sources'].append({'kind': kind, 'url': url, 'original_ref': original,
                'original_request_registered_in_result_as': request_ref, 'original_downloaded_at': request['created_at'],
                'original_http_status': 200, 'staged_file': self.ref('staged/' + kind, self.artifacts[kind])})
        self.artifacts['old_run'] = encoded({'study_id': self.old_sid, 'run_id': self.old_run, 'module_id': 'A06', 'artifact_id': 'old_artifact'})
        self.refresh_old_proof()
        fixed_ref = self.w.json('current/fixed.json', {'payload': {'receptors': [{'target_id': self.target}]}})
        fact = self.w.json('current/preparation_fact.json', {'connection': {'receptors': [{'target_id': self.target, 'uniprot': self.uniprot}]}})
        prep = {'run_id': self.prep, 'module_id': 'A06_PREP', 'artifact_id': 'prep', 'inputs': {'system_input_ref': fixed_ref}}
        prepared = {'outcome': 'success', 'tables': {'preparation_packet': [fact]}}
        baseline = {'run_id': self.score, 'module_id': 'A06', 'artifact_id': 'score', 'config': {'version': 'A06.system_rescue.1'}}
        score = {'outcome': 'success', 'files': []}
        self.m = {'study_id': self.sid, 'current': {'A06_PREP': self.prep, 'A06': self.score}, 'runs': {}, 'reviews': []}
        for run, result in ((prep, prepared), (baseline, score)):
            self.m['runs'][run['run_id']] = {'run_file': self.w.json('current/' + run['run_id'] + '/run.json', run),
                                            'result_file': self.w.json('current/' + run['run_id'] + '/result.json', result)}
        metadata_ref = self.w.json('current/metadata.json', self.metadata)
        current_request = {'state': 'success', 'status': 200, 'url': self.staging['sources'][0]['url'],
                           'file': metadata_ref, 'created_at': '2026-11-11T00:00:00Z'}
        req_ref = self.w.json('current/metadata_request.json', current_request)
        checkpoint = {'study_id': self.sid, 'run_id': self.score, 'key': 'receptor_HGNC_123', 'files': [metadata_ref, req_ref]}
        checkpoint_ref = self.w.json('current/checkpoint.json', checkpoint)
        self.m['analysis_plan_receptor_rescue_checkpoints'] = [checkpoint_ref]
        self.w.save(self.m)
        self.artifacts.update(current_metadata=encoded(self.metadata), current_metadata_request=encoded(current_request),
                              current_checkpoint=encoded(checkpoint))
        self.staging['current_v1_api_comparison'] = {'run_id': self.score, 'checkpoint_ref': checkpoint_ref, 'metadata_ref': metadata_ref}
        self.body = {'request_id': new_id('sourcepkg'), 'expected_preparation_run_id': self.prep,
                     'expected_scoring_run_id': self.score, 'target_id': self.target,
                     'author': '合成来源登记', 'note': '只采用官方原响应，不采用旧准备或评分', 'confirmed': True}

    def ref(self, path, raw):
        return {'path': path, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest(), 'role': 'synthetic_source'}

    def refresh_old_proof(self):
        self.artifacts['old_result'] = encoded(self.old_result)
        run_ref = self.ref('runs/A06/' + self.old_run + '/run.json', self.artifacts['old_run'])
        result_ref = self.ref('runs/A06/' + self.old_run + '/result.json', self.artifacts['old_result'])
        record = {'run_file': run_ref, 'result_file': result_ref}
        self.artifacts['old_manifest'] = encoded({'study_id': self.old_sid, 'runs': {self.old_run: record}})
        member = self.staging['source_archive_membership']
        member.update(run_record_in_manifest=record,
                      manifest=self.ref('staged/manifest.json', self.artifacts['old_manifest']),
                      run=self.ref('staged/run.json', self.artifacts['old_run']),
                      result=self.ref('staged/result.json', self.artifacts['old_result']))

    def register(self):
        return self.core.register(self.w, self.sid, self.body, self.staging, self.artifacts)

    def test_register_copies_originals_and_dates_without_replacing_science_or_adopting_old_preparation(self):
        ref = self.register()
        m = self.w.load(self.sid)
        for key in ('current', 'runs', 'reviews'):
            self.assertEqual(m[key], self.m[key])
        value = self.core.read_record(self.w.home, m, ref)
        mapping = self.core.url_mapping(self.w.home, m, [ref])
        self.assertEqual(len(mapping), 3)
        self.assertFalse(value['new_http_request_performed'])
        self.assertFalse(value['human_review_written'])
        self.assertEqual([row['original_downloaded_at'] for row in value['responses']], ['2026-10-22T00:00:00Z'] * 3)
        for row in value['responses']:
            self.assertEqual((self.w.home / row['file']['path']).read_bytes(), self.artifacts[row['kind']])
        self.assertEqual(self.register(), ref)
        self.assertEqual(len(self.w.load(self.sid)[self.core.INDEX]), 1)

    def test_declared_booleans_cannot_replace_old_result_membership(self):
        self.old_result['files'] = self.old_result['files'][:-1]
        self.refresh_old_proof()
        with self.assertRaises(ContractError):
            self.register()
        self.assertEqual(self.w.load(self.sid), self.m)

    def test_original_http200_fact_is_checked_even_after_all_hashes_are_updated(self):
        request = json.loads(self.artifacts['pae_request'])
        request['status'] = 503
        self.artifacts['pae_request'] = encoded(request)
        source = next(row for row in self.staging['sources'] if row['kind'] == 'pae')
        source['original_request_registered_in_result_as'] = self.ref('old/pae_request.json', self.artifacts['pae_request'])
        self.old_result['files'][-1] = source['original_request_registered_in_result_as']
        self.refresh_old_proof()
        with self.assertRaises(ContractError):
            self.register()

    def test_wrong_target_current_metadata_and_corrupt_model_never_register(self):
        for key in ('model', 'current_metadata'):
            old = self.artifacts[key]
            self.artifacts[key] = b'corrupt'
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.register()
            self.artifacts[key] = old
        self.body['target_id'] = 'HGNC:999'
        with self.assertRaises(ContractError):
            self.register()

    def test_registered_corruption_is_not_replaced_and_new_package_changes_binding_selection(self):
        first = self.register()
        selected = self.core.for_baseline(self.w.home, self.w.load(self.sid), self.prep, self.score)
        self.assertEqual(selected, [first])
        record = self.core.read_record(self.w.home, self.w.load(self.sid), first)
        model = self.w.home / record['artifact_files']['model']['path']
        model.write_bytes(b'corrupt')
        with self.assertRaises(ContractError):
            self.core.read_record(self.w.home, self.w.load(self.sid), first)
        with self.assertRaises(ContractError):
            self.register()
        self.assertEqual(model.read_bytes(), b'corrupt')

    def test_registered_url_tamper_with_updated_package_hash_cannot_change_exact_url_mapping(self):
        ref = self.register()
        m = self.w.load(self.sid)
        record = read_json(self.w.home / ref['path'])
        record['responses'][0]['url'] = 'https://alphafold.ebi.ac.uk/api/prediction/OTHER'
        path = self.w.home / ref['path']
        write_json(path, record, replace=True)
        changed_ref = file_record(self.w.home, path, ref['role'])
        m[self.core.INDEX] = [changed_ref]
        self.w.save(m)
        with self.assertRaises(ContractError):
            self.core.url_mapping(self.w.home, m, [changed_ref])

    def install_hgnc_history(self, identifiers):
        """合成同稳定编号的真实失败/成功历史，刷新原准备事实引用而不伪造通过字段。"""
        refs = [self.w.json('current/hgnc_failed_request.json', {
            'state': 'failed', 'status': 503, 'url': 'https://rest.genenames.org/fetch/hgnc_id/HGNC%3A123',
            'error_zh': '明确历史临时失败'})]
        for number, identifier in enumerate(identifiers):
            raw = self.w.json(f'current/hgnc_{number}.json', {'response': {'docs': [{
                'hgnc_id': self.target, 'status': 'Approved', 'uniprot_ids': [identifier]}]}})
            refs.append(self.w.json(f'current/hgnc_{number}_request.json', {'state': 'success', 'status': 200,
                'url': 'https://rest.genenames.org/fetch/hgnc_id/HGNC%3A123', 'file': raw}))
        fact = {'connection': {'receptors': [{'target_id': self.target}]}, 'files': refs}
        fact_ref = self.w.json('current/preparation_fact.json', fact)
        prepared = self.w.result(self.m, self.prep)
        prepared['tables']['preparation_packet'] = [fact_ref]
        self.m['runs'][self.prep]['result_file'] = self.w.json('current/' + self.prep + '/result.json', prepared)
        self.w.save(self.m)

    def test_prior_failed_hgnc_request_does_not_hide_later_unique_success(self):
        self.install_hgnc_history([self.uniprot])
        failed = self.w.home / 'current/hgnc_failed_request.json'
        previous = failed.read_bytes()
        ref = self.register()
        record = self.core.read_record(self.w.home, self.w.load(self.sid), ref)
        self.assertEqual(record['validated']['uniprot'], self.uniprot)
        self.assertEqual(failed.read_bytes(), previous)

    def test_conflicting_successful_hgnc_responses_after_failure_remain_blocked(self):
        self.install_hgnc_history([self.uniprot, 'P99999'])
        with self.assertRaises(ContractError):
            self.register()
        self.assertNotIn(self.core.INDEX, self.w.load(self.sid))

    def incomplete_first(self):
        """保留当前第一轮元数据CP，将原paths评分另存为明确原来源供登记门控核对。"""
        original_id = new_id('run')
        prep = self.w.run(self.m, self.prep)
        original = {'run_id': original_id, 'module_id': 'A06', 'artifact_id': 'original_score',
                    'config': {'version': 'A06.system_scoring_paths.1'}, 'parent_runs': {'A06_PREP': self.prep},
                    'inputs': {'system_input_ref': prep['inputs']['system_input_ref']}}
        self.m['runs'][original_id] = {'run_file': self.w.json('current/' + original_id + '/run.json', original),
                                       'result_file': self.w.json('current/' + original_id + '/result.json', {'outcome': 'success', 'files': []})}
        body = {'request_id': new_id('rescue'), 'expected_preparation_run_id': self.prep,
                'expected_scoring_run_id': original_id, 'expected_input_hash': fingerprint({'synthetic': True}),
                'author': '合成第一轮', 'note': '真实未完成来源', 'confirmed': True}
        request = {'schema_version': 'A06.system_rescue.1', 'study_id': self.sid, 'request': body,
                   'request_hash': fingerprint(body), 'input_hash': body['expected_input_hash'],
                   'binding': {'synthetic': True}, 'human_review_written': False, 'implementation_files': []}
        req_ref = self.w.json('decisions/A06_rescue/' + body['request_id'] + '/request.json', request)
        current = self.w.run(self.m, self.score)
        current.update(parent_runs={'A06_PREP': self.prep}, inputs={
            'source_scoring_run': self.m['runs'][original_id]['run_file'],
            'source_scoring_result': self.m['runs'][original_id]['result_file'],
            'source_preparation_run': self.m['runs'][self.prep]['run_file'],
            'source_preparation_result': self.m['runs'][self.prep]['result_file'],
            'system_input_ref': prep['inputs']['system_input_ref'], 'source_binding': {'synthetic': True}, 'rescue_request': req_ref})
        self.m['runs'][self.score] = {'run_file': self.w.json('current/' + self.score + '/run.json', current), 'result_file': None}
        self.m['analysis_plan_receptor_rescue_requests'] = [req_ref]
        self.w.save(self.m)
        self.body['expected_scoring_run_id'] = original_id
        return current

    def test_original_source_package_registration_allows_same_current_incomplete_v1_and_preserves_science(self):
        current = self.incomplete_first()
        ref = self.register()
        m = self.w.load(self.sid)
        self.assertEqual(m['current'], self.m['current'])
        self.assertEqual(m['runs'], self.m['runs'])
        self.assertIsNone(m['runs'][current['run_id']]['result_file'])
        value = self.core.read_record(self.w.home, m, ref)
        self.assertEqual(value['request']['expected_scoring_run_id'], self.body['expected_scoring_run_id'])
        self.assertEqual(value['validated']['current_checkpoint_ref'], self.staging['current_v1_api_comparison']['checkpoint_ref'])

    def test_current_incomplete_v2_cannot_use_v1_source_package_admission_exception(self):
        current = self.incomplete_first()
        current['config']['version'] = 'A06.system_rescue.2'
        self.m['runs'][self.score]['run_file'] = self.w.json('current/' + self.score + '/run.json', current)
        self.w.save(self.m)
        with self.assertRaises(ContractError):
            self.register()

    def test_current_incomplete_v1_hold_cannot_register_original_source_package(self):
        self.incomplete_first()
        from unittest.mock import patch
        with patch.object(self.w, 'latest_review', return_value={'decision': 'rejected'}), self.assertRaises(ContractError):
            self.register()


if __name__ == '__main__':
    unittest.main()
