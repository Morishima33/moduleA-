"""原始来源绑定必须沿本批父链和文件指纹，不能读取另一批current。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from storage import file_record, write_json
from science_modules.a06.source_context import bound_sources


class SourceContextTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        herb = self.home / 'HERB_ingredient_info_v2.txt'
        herb.write_text('Ingredient_id\tPubChem_id\tTCMSP_id\nHBIN1\t456\tMOL000123\n', encoding='utf8')
        self.herb = file_record(self.home, herb, 'source')
        path = self.home / 'staging.json'
        write_json(path, {'datasets': [{'database': 'HERB', 'files': [self.herb]}]})
        self.staging = file_record(self.home, path, 'staging')
        self.rows = [{'compound_id': 'CHEM_fixed', 'source': 'HERB', 'source_id': 'HBIN1'},
                     {'compound_id': 'CHEM_batman', 'source': 'BATMAN', 'source_id': '123'}]
        result = self.home / 'a01.json'; write_json(result, {'tables': {'component_sources': self.rows}})
        self.result_ref = file_record(self.home, result, 'result')
        outer = self
        class Workflow:
            def location(self, sid): return outer.home
            def run(self, manifest, rid):
                return {'parent_runs': {'A01': 'a01_fixed'}} if rid == 'a03_fixed' else {'inputs': {'staging_file': outer.staging}}
            def result(self, manifest, rid):
                outer.assertEqual(rid, 'a01_fixed')
                return {'tables': {'component_sources': outer.rows}}
        self.workflow = Workflow()
        self.manifest = {'study_id': 'study_synthetic', 'current': {'A01': 'other_batch'},
                         'runs': {'a01_fixed': {'result_file': self.result_ref}}}
        self.packet = {'runs': {'A03': 'a03_fixed'}, 'compounds': [{'compound_id': row['compound_id']} for row in self.rows]}

    def test_exact_parent_archive_and_explicit_batman_cid_preserve_source_ids(self):
        values = bound_sources(self.workflow, self.manifest, self.packet)
        herb = values['CHEM_fixed'][0]
        self.assertEqual((herb['pubchem_id'], herb['tcmsp_id']), ('456', 'MOL000123'))
        self.assertEqual(herb['a01_result'], self.result_ref)
        self.assertEqual(values['CHEM_batman'][0]['pubchem_id'], '123')

    def test_corrupt_archived_identity_table_blocks_without_fallback(self):
        (self.home / self.herb['path']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            bound_sources(self.workflow, self.manifest, self.packet)

    def test_missing_original_source_cannot_fall_back_to_chem_display_name(self):
        self.packet['compounds'].append({'compound_id': 'CHEM_unbound', 'name': 'display only'})
        with self.assertRaisesRegex(ValueError, '原始来源关系'):
            bound_sources(self.workflow, self.manifest, self.packet)

    def test_internal_chem_id_cannot_be_used_as_batman_pubchem_number(self):
        self.rows[1]['source_id'] = 'CHEM_other'
        with self.assertRaises(ValueError):
            bound_sources(self.workflow, self.manifest, self.packet)
