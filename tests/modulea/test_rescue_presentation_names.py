"""名称目录只解释同批归档身份或原术语，不按相似名称补身份。"""
from copy import deepcopy
import unittest

from contracts import ContractError, fingerprint
from modulea.core import rescue_presentation_names as naming


class RescuePresentationNamesTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(naming, 'derive_names', None)), '尚未实现同批名称证据派生')
        self.assertTrue(callable(getattr(naming, 'checked_catalog', None)), '尚未实现名称目录核验')
        self.basis = {
            'compounds': [{'compound_id': key, 'name': name} for key, name in
                          [('C1', 'Alpha'), ('C2', 'Alpha'), ('C3', 'Source beta'), ('C4', 'Original term')]],
            'prepared': [{'compound_id': 'C1', 'state': 'ready', 'cid': 1},
                         {'compound_id': 'C2', 'state': 'ready', 'cid': 1},
                         {'compound_id': 'C3', 'state': 'NA'}, {'compound_id': 'C4', 'state': 'NA'}],
            'herb_sources': {
                'C3': [{'id': 'HBIN000001', 'name': 'Source beta', 'file': self.ref('beta.json')}],
                'C4': [{'id': 'HBIN000002', 'name': 'Original term', 'file': self.ref('term.json')}]},
            'evidence': [self.ref('fixed.json'), self.ref('prepared.json')],
        }
        self.catalog = {'schema_version': 'ModuleA.rescue_display_name_catalog.1', 'entries': [
            self.entry('PubChem', '1', ['Alpha'], '甲成分', 'prepared_identity_translation'),
            self.entry('HERB', 'HBIN000001', ['Source beta'], '乙术语', 'source_term_translation_only'),
            self.entry('HERB', 'HBIN000002', ['Original term'], '', 'original_name_requires_user_decision')]}

    @staticmethod
    def ref(path):
        return {'path': path, 'bytes': 1, 'sha256': 'a' * 64}

    @staticmethod
    def entry(scheme, identity, aliases, zh, scope):
        return {'identity': {'scheme': scheme, 'id': identity}, 'source_names': aliases,
                'display_name_zh': zh, 'scope': scope, 'translation_basis': '合成核译依据，仅用于测试',
                'sources': [{'url': 'https://example.invalid/names', 'label': '合成来源'}]}

    def test_prepared_duplicates_and_source_terms_keep_separate_identity_scope(self):
        before = fingerprint(self.basis)
        value = naming.derive_names(self.basis, self.catalog)
        self.assertEqual([row['compound_id'] for row in value['names']], ['C1', 'C2', 'C3', 'C4'])
        self.assertEqual(value['missing_ids'], ['C4'])
        self.assertEqual(value['names'][0]['display_name_zh'], '甲成分')
        self.assertEqual(value['names'][1]['display_name_zh'], '甲成分')
        self.assertEqual(value['names'][2]['identity'], {'scheme': 'HERB', 'id': 'HBIN000001'})
        self.assertEqual(value['names'][2]['scope'], 'source_term_translation_only')
        self.assertNotIn('resolved_cid', value['names'][2])
        self.assertIn(self.ref('beta.json'), value['names'][2]['evidence'])
        self.assertEqual(fingerprint(self.basis), before)

    def test_explicit_original_name_range_only_clears_that_missing_name(self):
        value = naming.derive_names(self.basis, self.catalog, allowed_original_names={'C4'})
        self.assertEqual(value['missing_ids'], [])
        row = value['names'][3]
        self.assertEqual(row['display_name_zh'], '')
        self.assertEqual(row['scope'], 'original_proper_name')
        self.assertEqual(row['translation_status'], 'original_term_retained')
        self.assertEqual(self.basis['prepared'][3]['state'], 'NA')
        for invalid in ({'C1'}, {'C3'}, {'another'}):
            with self.subTest(allowed=invalid), self.assertRaises(ContractError):
                naming.derive_names(self.basis, self.catalog, allowed_original_names=invalid)

    def test_wrong_cid_does_not_fall_back_to_same_source_name(self):
        basis = deepcopy(self.basis)
        basis['prepared'][0]['cid'] = 2
        value = naming.derive_names(basis, self.catalog)
        self.assertIn('C1', value['missing_ids'])
        self.assertEqual(value['names'][0]['display_name_zh'], '')
        self.assertEqual(value['names'][1]['display_name_zh'], '甲成分')

    def test_wrong_herb_id_or_source_name_is_not_accepted(self):
        for change in ({'id': 'HBIN999999'}, {'name': 'Another term'}):
            basis = deepcopy(self.basis)
            basis['herb_sources']['C3'][0].update(change)
            value = naming.derive_names(basis, self.catalog)
            self.assertIn('C3', value['missing_ids'])
            self.assertEqual(value['names'][2]['display_name_zh'], '')

    def test_catalog_rejects_duplicates_fake_chinese_and_invalid_scope(self):
        cases = []
        duplicate = deepcopy(self.catalog)
        duplicate['entries'].append(deepcopy(duplicate['entries'][0]))
        cases.append(duplicate)
        for change in ({'display_name_zh': 'English only'}, {'display_name_zh': '中文待核译'},
                       {'scope': 'source_term_translation_only'}, {'sources': []}):
            catalog = deepcopy(self.catalog)
            catalog['entries'][0].update(change)
            cases.append(catalog)
        for catalog in cases:
            with self.subTest(catalog=catalog), self.assertRaises(ContractError):
                naming.checked_catalog(catalog)

    def test_missing_and_duplicate_prepared_objects_are_rejected(self):
        for rows in (self.basis['prepared'][:-1], [self.basis['prepared'][0]] * 4):
            basis = deepcopy(self.basis)
            basis['prepared'] = deepcopy(rows)
            with self.assertRaises(ContractError):
                naming.derive_names(basis, self.catalog)

    def test_conflicting_herb_sources_are_not_silently_selected(self):
        basis = deepcopy(self.basis)
        basis['herb_sources']['C3'].append({'id': 'HBIN000002', 'name': 'Source beta', 'file': self.ref('conflict.json')})
        value = naming.derive_names(basis, self.catalog)
        self.assertIn('C3', value['missing_ids'])

    def test_output_evidence_and_names_are_independent_containers(self):
        value = naming.derive_names(self.basis, self.catalog)
        value['names'][0]['evidence'][0]['sha256'] = 'f' * 64
        value['names'][0]['display_name_zh'] = '修改后的显示'
        self.assertEqual(self.basis['evidence'][0]['sha256'], 'a' * 64)
        self.assertEqual(self.catalog['entries'][0]['display_name_zh'], '甲成分')
        self.assertEqual(value['names'][1]['display_name_zh'], '甲成分')
