"""新版来源优先按精确原编号恢复；合成资料不联网、不生成三维。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from storage import file_record, write_json
from science_modules.a06 import compound_sources_v2 as source

KEY = 'AAAAAAAAAAAAAA-BBBBBBBBBB-C'
ROW = {'compound_id': 'CHEM_synthetic', 'name': 'Synthetic original name'}


class Fetch:
    """只接受测试中明确列出的官方请求，未知请求立即失败。"""
    def __init__(self, root, replies):
        self.root, self.replies, self.calls, self.records = root, replies, [], []

    def get(self, url, suffix='json'):
        self.calls.append(url)
        value = self.replies[url]
        if isinstance(value, Exception):
            raise value
        path = self.root / ('response_' + str(len(self.calls)) + '.' + suffix)
        path.write_text(json.dumps(value) if suffix == 'json' else value, encoding='utf8')
        ref = file_record(self.root, path, 'synthetic_source')
        self.records.append(ref)
        return value, ref


class CompoundSourceTests(TestCase):
    """先从来源稳定编号核实，再核对属性与实际坐标。"""
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.props = source.PUBCHEM + 'cid/456/property/InChIKey,MolecularFormula/JSON'
        self.sdf = source.PUBCHEM + 'cid/456/SDF?record_type=3d'

    def fetch(self, **updates):
        replies = {self.props: {'PropertyTable': {'Properties': [
            {'CID': 456, 'InChIKey': KEY, 'MolecularFormula': 'C2H6O'}]}}, self.sdf: 'source 3d',
            source.PUBCHEM + 'name/Synthetic%20original%20name/cids/JSON': {'IdentifierList': {'CID': [456]}}}
        replies.update(updates)
        return Fetch(self.root, replies)

    def test_exact_archived_cid_avoids_name_lookup_and_preserves_master_id(self):
        fetch = self.fetch()
        identities = [{'source': 'HERB', 'source_id': 'HBIN000001', 'name': ROW['name'],
                       'pubchem_id': '456', 'inchikey': KEY, 'formula': 'C2H6O'}]
        with patch('docking_audit.ligand_identity', return_value={'inchi_key': KEY}):
            result = source.resolve(ROW, fetch, identities)
        self.assertEqual(fetch.calls, [self.props, self.sdf])
        self.assertEqual(result['compound_id'], ROW['compound_id'])
        self.assertEqual(result['identity_resolution']['method'], 'archived_source_identity')

    def test_conflicting_source_keys_stop_before_network(self):
        fetch = self.fetch()
        identities = [{'source': 'HERB', 'source_id': 'HBIN1', 'inchikey': KEY},
                      {'source': 'TCMSP', 'source_id': 'MOL000123', 'inchikey': 'CCCCCCCCCCCCCC-DDDDDDDDDD-E'}]
        with self.assertRaises(source.SourceFailure) as caught:
            source.resolve(ROW, fetch, identities)
        self.assertEqual(caught.exception.stage, 'identity')
        self.assertEqual(fetch.calls, [])

    def test_found_cid_missing_3d_is_not_name_failure_or_generated_coordinates(self):
        fetch = self.fetch(**{self.sdf: HTTPError(self.sdf, 404, 'No 3D', {}, None)})
        with self.assertRaises(source.SourceFailure) as caught:
            source.resolve(ROW, fetch, [{'source': 'HERB', 'source_id': 'HBIN1', 'pubchem_id': '456'}])
        self.assertEqual(caught.exception.stage, 'source_3d')
        self.assertEqual(caught.exception.code, 'official_3d_unavailable')
        self.assertFalse(caught.exception.retryable)

    def test_source_formula_disagreement_is_not_accepted(self):
        fetch = self.fetch()
        with self.assertRaises(source.SourceFailure) as caught:
            source.resolve(ROW, fetch, [{'source': 'HERB', 'source_id': 'HBIN1', 'pubchem_id': '456', 'formula': 'C3H8O'}])
        self.assertEqual(caught.exception.stage, 'identity')
        self.assertNotIn(self.sdf, fetch.calls)

    def test_unique_name_conflicting_with_source_cid_is_not_silently_changed(self):
        url = source.PUBCHEM + 'name/Synthetic%20original%20name/cids/JSON'
        fetch = self.fetch(**{url: {'IdentifierList': {'CID': [789]}}})
        with self.assertRaises(source.SourceFailure) as caught:
            source.resolve(ROW, fetch, [{'source': 'HERB', 'source_id': 'HBIN1', 'pubchem_id': '456'}])
        self.assertEqual(caught.exception.stage, 'identity')
        self.assertNotIn(self.props, fetch.calls)

    def test_name_404_can_use_explicit_archived_cid_with_full_coordinate_check(self):
        url = source.PUBCHEM + 'name/Synthetic%20original%20name/cids/JSON'
        fetch = self.fetch(**{url: HTTPError(url, 404, 'Name absent', {}, None)})
        with patch('docking_audit.ligand_identity', return_value={'inchi_key': KEY}):
            result = source.resolve(ROW, fetch, [{'source': 'HERB', 'source_id': 'HBIN1', 'pubchem_id': '456'}])
        self.assertEqual(result['cid'], 456)

    def test_tcmsp_recovery_uses_original_mol_id_not_chem_id(self):
        url = 'https://old.tcmsp-e.com/molecule.php?qn=123'
        fetch = self.fetch(**{url: 'var mol = ' + json.dumps([{
            'MOL_ID': 'MOL000123', 'molecule_ID': '123', 'molecule_name': ROW['name'],
            'inchikey': KEY, 'pubchem_cid': '456'}]) + ';'})
        with patch('docking_audit.ligand_identity', return_value={'inchi_key': KEY}):
            result = source.resolve(ROW, fetch, [{'source': 'TCMSP', 'source_id': 'MOL000123', 'name': ROW['name']}])
        self.assertEqual(fetch.calls[0], url)
        self.assertEqual(result['compound_id'], ROW['compound_id'])
        self.assertEqual(result['identity_resolution']['original_source_id'], 'MOL000123')

    def test_name_fallback_requires_unique_cid(self):
        url = source.PUBCHEM + 'name/Synthetic%20original%20name/cids/JSON'
        fetch = self.fetch(**{url: {'IdentifierList': {'CID': [456, 457]}}})
        with self.assertRaises(source.SourceFailure) as caught:
            source.resolve(ROW, fetch, [])
        self.assertEqual(caught.exception.stage, 'name')
        self.assertEqual(fetch.calls, [url])

    def test_identity_404_is_classified_as_identity_not_name(self):
        fetch = self.fetch(**{self.props: HTTPError(self.props, 404, 'No property', {}, None)})
        with self.assertRaises(source.SourceFailure) as caught:
            source.resolve(ROW, fetch, [{'pubchem_id': '456', 'inchikey': KEY}])
        self.assertEqual(caught.exception.stage, 'identity')
        self.assertEqual(caught.exception.code, 'official_identity_unavailable')

    def test_herb_supplement_only_uses_original_stable_id_and_complete_identity(self):
        fetch = self.fetch(); calls = []
        def detail(identifier):
            calls.append(identifier)
            value = {'summary': [['Ingredient id','Ingredient name','InChIKey','PubChem id','Molecule formula'],
                                  [identifier, ROW['name'], KEY, '456', 'C2H6O']]}
            path = self.root / 'herb_detail.json'; write_json(path, value)
            return value, file_record(self.root, path, 'herb_source')
        fetch.herb_detail = detail
        with patch('docking_audit.ligand_identity', return_value={'inchi_key': KEY}):
            result = source.resolve(ROW, fetch, [{'source':'HERB','source_id':'HBIN000001','name':ROW['name']}])
        self.assertEqual(calls, ['HBIN000001'])
        self.assertEqual(fetch.calls, [self.props, self.sdf])
        self.assertEqual(result['cid'], 456)

    def test_wrong_herb_stable_id_is_not_accepted_as_another_source(self):
        fetch = self.fetch()
        fetch.herb_detail = lambda identifier: ({'summary': [['Ingredient id','Ingredient name'],
                                                          ['HBIN999999', ROW['name']]]}, {})
        with self.assertRaises(source.SourceFailure):
            source.resolve(ROW, fetch, [{'source':'HERB','source_id':'HBIN000001','name':ROW['name']}])
        self.assertEqual(fetch.calls, [])

    def test_production_herb_detail_response_is_registered_for_offline_replay(self):
        from science_modules.a06.source_context import Fetcher
        from science_modules.a06.source_replay import validate
        fetch = Fetcher(self.root, self.root / 'sources')
        fetch.replies, fetch.calls = self.fetch().replies, []
        detail = {'summary': [['Ingredient id','Ingredient name','InChIKey','PubChem id','Molecule formula'],
                              ['HBIN000001', ROW['name'], KEY, '456', 'C2H6O']]}
        identities = [{'source':'HERB','source_id':'HBIN000001','name':ROW['name']}]
        with patch('science_modules.a01.acquisition.Fetcher') as backend, \
             patch('science_modules.a06.source_context.OriginalFetcher.get', new=Fetch.get), \
             patch('docking_audit.ligand_identity', return_value={'inchi_key':KEY}):
            backend.return_value.herb.return_value = detail
            row = source.resolve(ROW, fetch, identities)
            row['source_requests'] = fetch.events
            validate(self.root, {'compounds':[ROW]}, {'compounds':[row],'files':fetch.records},
                     {ROW['compound_id']:identities})
        backend.return_value.herb.assert_called_once_with('detail_api', label='Ingredient', v='HBIN000001', key_id='HBIN000001')

    def test_offline_replay_rejects_forged_resolution_and_corrupt_response(self):
        from science_modules.a06.source_replay import validate
        identities = [{'source': 'HERB', 'source_id': 'HBIN000001', 'name': ROW['name'],
                       'pubchem_id': '456', 'inchikey': KEY}]
        fetch = self.fetch()
        with patch('docking_audit.ligand_identity', return_value={'inchi_key': KEY}):
            row = source.resolve(ROW, fetch, identities)
        refs = []
        for index, (url, ref) in enumerate(zip(fetch.calls, fetch.records)):
            path = self.root / ('request_' + str(index) + '.json')
            write_json(path, {'operation': 'get', 'url': url, 'suffix': 'sdf' if '/SDF?' in url else 'json', 'file': ref})
            refs.append(file_record(self.root, path, 'bound_source_request'))
        row['source_requests'] = refs
        connection = {'compounds': [row], 'files': fetch.records + refs}
        with patch('docking_audit.ligand_identity', return_value={'inchi_key': KEY}):
            validate(self.root, {'compounds': [ROW]}, connection, {ROW['compound_id']: identities})
            row['identity_resolution']['method'] = 'forged'
            with self.assertRaises(ValueError):
                validate(self.root, {'compounds': [ROW]}, connection, {ROW['compound_id']: identities})
            row['identity_resolution']['method'] = 'archived_source_identity'
            (self.root / fetch.records[0]['path']).write_text('{}', encoding='utf8')
            with self.assertRaises(ValueError):
                validate(self.root, {'compounds': [ROW]}, connection, {ROW['compound_id']: identities})

    def test_structure_counts_preserve_source_rows_without_reranking(self):
        rows = [{'compound_id': 'one', 'state': 'ready', 'preparation': {'identity': {'inchi_key': KEY}}},
                {'compound_id': 'two', 'state': 'ready', 'preparation': {'identity': {'inchi_key': KEY}}},
                {'compound_id': 'three', 'state': 'NA', 'reason_zh': '缺少三维'}]
        stats = source.structure_counts(rows)
        self.assertEqual(stats, {'source_record_count': 3, 'verified_structure_count': 1,
                                 'verified_record_count': 2, 'pending_structure_records': 1})
        self.assertEqual([r['compound_id'] for r in rows], ['one', 'two', 'three'])

    def test_merged_candidate_counts_all_original_relations_but_not_recovery_evidence_twice(self):
        rows = [{'state':'ready','preparation':{'identity':{'inchi_key':KEY}},
                 'original_sources':[{'source':'HERB'},{'source':'TCMSP'}]},
                {'state':'NA','original_sources':[{'source':'BATMAN'}]}]
        self.assertEqual(source.structure_counts(rows), {'source_record_count':3,'verified_structure_count':1,
            'verified_record_count':2,'pending_structure_records':1})
