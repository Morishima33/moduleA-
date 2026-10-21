"""共晶稳定键和实际原子完整性回归，不下载、不运行研究计算。"""
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch, Mock
from contracts import fingerprint
from storage import file_record
from science_modules.a06.reference_candidates import discover, validate_choices, apply_choices, cif_categories
from science_modules.a06.reference_prepare import complete_reference
from science_modules.a06.reference_rules import POLICY, VERSION
from science_modules.a06.automatic_coverage_rules import POLICY as V2_POLICY


def fixture(code='LIG', distance=2, covalent=False):
    text = """data_TEST
_entry.id TEST
loop_
_pdbx_entity_nonpoly.entity_id
_pdbx_entity_nonpoly.comp_id
_pdbx_entity_nonpoly.name
2 {code} 'Candidate ligand'
loop_
_chem_comp.id
_chem_comp.name
{code} 'Candidate ligand'
loop_
_atom_site.group_PDB
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.pdbx_PDB_ins_code
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
ATOM C CA . ALA A 1 1 0 0 0 ? 1 ALA A 1
""".format(code=code)
    text += ''.join(f'HETATM C C{i} . {code} B 2 . {distance} {i/10} 0 ? 500 {code} A 1\n' for i in range(8))
    if covalent:
        text += f'loop_\n_struct_conn.conn_type_id\n_struct_conn.ptnr1_label_comp_id\n_struct_conn.ptnr1_auth_asym_id\n_struct_conn.ptnr1_label_asym_id\ncovale {code} A B\n'
    return text


class ReferenceCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'source.cif'

    def tearDown(self):
        self.temp.cleanup()

    def connection(self, **kwargs):
        self.path.write_text(fixture(**kwargs), 'utf-8')
        origin = {'spec': {'pdb_id': 'TEST', 'source_type': 'experimental', 'chains': ['A'], 'uniprot': 'P00001', 'pocket': 'p2rank', 'altloc': None}, 'cif': file_record(self.root, self.path, 'test_source'), 'identity': [{'uniprot': 'P00001', 'identity_check': 'matched'}]}
        return {'study_id': 'synthetic', 'id': 'connection_test', 'compounds': [], 'receptors': [{'target_id': 'HGNC:1', 'symbol': 'TEST', 'state': 'connected', 'candidates': [origin]}]}

    def choice(self, row):
        return {k: row[k] for k in ('target_id', 'candidate_key', 'reference_key')}

    def test_stable_keys_and_no_automatic_selection(self):
        connection = self.connection()
        rows = discover(self.root, connection)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['selectable'])
        self.assertEqual(validate_choices(self.root, connection, []), [])
        self.assertEqual(validate_choices(self.root, connection, [self.choice(rows[0])]), rows)
        self.assertEqual(rows, discover(self.root, connection))

    def test_additive_covalent_and_distant_candidates_rejected(self):
        for options in ({'code': 'PEG'}, {'covalent': True}, {'distance': 8}, {'code': 'A1CB0'}):
            with self.subTest(options=options):
                connection = self.connection(**options)
                row = discover(self.root, connection)[0]
                self.assertFalse(row['selectable'])
                with self.assertRaises(ValueError):
                    validate_choices(self.root, connection, [self.choice(row)])

    def test_no_paths_or_duplicate_or_stale_choices(self):
        connection = self.connection()
        choice = self.choice(discover(self.root, connection)[0])
        for choices in ([dict(choice, path='bad')], [choice, choice], [dict(choice, candidate_key='0'*64)]):
            with self.assertRaises(ValueError):
                validate_choices(self.root, connection, choices)

    def test_hash_failure_precedes_candidate_use(self):
        connection = self.connection()
        self.path.write_text(fixture()+'# modified\n', 'utf-8')
        with self.assertRaises(ValueError):
            discover(self.root, connection)

    def test_apply_does_not_mutate_original_or_claim_atom_completeness(self):
        connection = self.connection()
        before = deepcopy(connection)
        choice = self.choice(discover(self.root, connection)[0])
        adapted = apply_choices(self.root, connection, [choice])
        self.assertEqual(connection, before)
        chosen = adapted['receptors'][0]['candidates'][0]
        self.assertEqual(chosen['spec']['pocket'], 'reference')
        self.assertFalse(chosen['reference_audit']['reference_count_matches'])

    def test_actual_ccd_atom_completeness_and_identity(self):
        connection = self.connection()
        choice = self.choice(discover(self.root, connection)[0])
        origin = apply_choices(self.root, connection, [choice])['receptors'][0]['candidates'][0]
        ccd = 'data_LIG\n_chem_comp.id LIG\nloop_\n_chem_comp_atom.comp_id\n_chem_comp_atom.atom_id\n_chem_comp_atom.type_symbol\n'+''.join(f'LIG C{i} C\n' for i in range(8))
        self.assertTrue(complete_reference(self.root, origin, ccd)['reference_audit']['reference_count_matches'])
        for broken in (ccd+'LIG C8 C\n', ccd.replace('_chem_comp.id LIG', '_chem_comp.id BAD')):
            with self.assertRaises(ValueError):
                complete_reference(self.root, origin, broken)

    def test_cif_multiline_and_quotes(self):
        tables = cif_categories("data_X\n_test.name\n;first\nsecond\n;\nloop_\n_other.id\n_other.name\n1 'a b'\n2 \"c d\"\n")
        self.assertEqual(tables['_test'][0]['name'], 'first\nsecond')
        self.assertEqual(tables['_other'][1]['name'], 'c d')

    def test_protocol_does_not_relax_scientific_thresholds(self):
        self.assertEqual(VERSION, 'A06.automatic.3')
        self.assertEqual(POLICY['alphafold_confidence'], V2_POLICY['alphafold_confidence'])
        self.assertEqual(POLICY['reference_rmsd_max_A'], 2)
        self.assertEqual(POLICY['vina'], V2_POLICY['vina'])
        self.assertNotEqual(fingerprint(POLICY), fingerprint(V2_POLICY))

    def test_strict_reference_uses_actual_unchanged_rmsd_gate(self):
        from science_modules.a06.reference_prepare import prepare
        connection = self.connection()
        connection['reference_choices'] = [self.choice(discover(self.root, connection)[0])]
        spec = apply_choices(self.root, connection, connection['reference_choices'])['receptors'][0]['candidates'][0]['spec']
        ccd = self.root/'CCD.cif'
        ccd.write_text('data_LIG\n_chem_comp.id LIG\nloop_\n_chem_comp_atom.comp_id\n_chem_comp_atom.atom_id\n_chem_comp_atom.type_symbol\n'+''.join(f'LIG C{i} C\n' for i in range(8)), 'utf-8')
        evidence = {'structure_id': 'TEST', 'identity': {'target_id': 'HGNC:1', 'uniprot': 'P00001', 'chains': ['A'], 'species': 9606, 'polymer_type': 'Protein', 'sequence_matches': True}, 'pocket_complete': True, 'environment_resolved': True, 'receptor_ready': True, 'reference': {k: spec[k] for k in ('reference_code', 'reference_chain', 'reference_sequence')}, 'top1_rmsd': 1.99, 'box': {'center': [0,0,0], 'size': [20,20,20]}, 'receptor': {'path': 'mock'}}
        workflow = Mock(location=lambda sid: self.root)
        with patch('science_modules.a06.reference_prepare.verify_sequence', return_value={'mock':'sequence matched'}), patch('science_modules.a06.quality_engine.download_ccd', return_value=ccd), patch('science_modules.a06.quality_engine.attempt', return_value=evidence), patch('science_modules.a06.automatic_coverage_prepare.prepare') as fallback:
            result = prepare(workflow, 'synthetic', connection, connection['receptors'][0], self.root/'pass', self.root, None, self.root, 'auto_test', lambda value: None)
            self.assertEqual(result['quality'], '严格')
            fallback.assert_not_called()
        evidence['top1_rmsd'] = 2.01
        with patch('science_modules.a06.reference_prepare.verify_sequence', return_value={'mock':'sequence matched'}), patch('science_modules.a06.quality_engine.download_ccd', return_value=ccd), patch('science_modules.a06.quality_engine.attempt', return_value=evidence), patch('science_modules.a06.automatic_coverage_prepare.prepare', return_value={'state':'ready','quality':'探索','attempts':[]}) as fallback:
            result = prepare(workflow, 'synthetic', connection, connection['receptors'][0], self.root/'fail', self.root, None, self.root, 'auto_test', lambda value: None)
            self.assertEqual(result['quality'], '探索')
            self.assertIn('超过2', result['attempts'][0]['reason_zh'])
            fallback.assert_called_once()

    def test_unselected_old_reference_is_not_upgraded(self):
        from science_modules.a06.reference_prepare import prepare
        connection = self.connection()
        choice = self.choice(discover(self.root, connection)[0])
        connection = apply_choices(self.root, connection, [choice])
        with patch('science_modules.a06.automatic_coverage_prepare.prepare', return_value={'state':'NA'}) as fallback:
            prepare(Mock(), 'synthetic', connection, connection['receptors'][0], self.root, self.root, None, self.root, 'auto_test', lambda value: None)
            row = fallback.call_args.args[3]
            self.assertTrue(all(c['spec']['pocket'] == 'p2rank' for c in row['candidates']))
        self.assertEqual(connection['receptors'][0]['candidates'][0]['spec']['pocket'], 'reference')

    def test_sequence_conflict_stops_strict_before_tools(self):
        from science_modules.a06.reference_prepare import prepare
        connection = self.connection()
        connection['reference_choices'] = [self.choice(discover(self.root, connection)[0])]
        with patch('science_modules.a06.reference_prepare.verify_sequence', side_effect=ValueError('实际残基映射冲突')), patch('science_modules.a06.quality_engine.download_ccd') as download, patch('science_modules.a06.quality_engine.attempt') as strict, patch('science_modules.a06.automatic_coverage_prepare.prepare', return_value={'state':'NA','quality':'未通过','attempts':[]}):
            result = prepare(Mock(location=lambda sid:self.root), 'synthetic', connection, connection['receptors'][0], self.root/'conflict', self.root, None, self.root, 'auto_test', lambda value:None)
            self.assertEqual(result['state'], 'NA')
            self.assertIn('映射冲突', result['attempts'][0]['reason_zh'])
            download.assert_not_called()
            strict.assert_not_called()

    def test_old_validator_delegated_without_loading_science(self):
        from science_modules.a06.reference_engine import validator
        previous = Mock(return_value='old_verified')
        actual = validator(self.root, previous)({'config':{'schema_version':'A06.automatic.2'}}, {}, {}, [], 'success')
        self.assertEqual(actual, 'old_verified')
        previous.assert_called_once()


if __name__ == '__main__':
    unittest.main()
