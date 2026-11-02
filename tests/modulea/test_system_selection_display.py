"""核查系统最终名单的来源隔离、原顺序及缺失语义，不执行科学选择。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from contracts import ContractError, fingerprint
from storage import file_record, write_json


class SystemSelectionDisplayTests(unittest.TestCase):
    """使用虚构归档，只读显示不能生成决定或借用其他网络。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='selection_display_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sid = 'study_' + '1' * 32
        self.rid = 'run_' + '2' * 32
        self.batch_id = 'systembatch_' + '3' * 32
        self.batch = self.save('batch.json', {'schema_version': 'ModuleA.system_execution.1',
            'study_id': self.sid, 'batch_id': self.batch_id, 'human_review_written': False})
        self.run = {'study_id': self.sid, 'run_id': self.rid, 'module_id': 'A04',
            'execution_protocol': 'ModuleA.system_execution.1', 'batch_file': self.batch}
        self.rows = [dict(target_id='HGNC:2', symbol='B', selection_order=1, candidate_grade='A', degree=8, bc=2.0, cc=.4),
                     dict(target_id='HGNC:1', symbol='A', selection_order=2, candidate_grade='B', degree=7, bc=1.0, cc=.3)]
        self.manifest = {'study_id': self.sid, 'current': {'A04': self.rid},
                         'runs': {self.rid: {'run_file': {'actual': 'run'}, 'result_file': {'actual': 'result'}}},
                         'analysis_plan_system_batch_records': [self.batch], 'analysis_plan_system_decisions': [], 'reviews': []}
        root = self.root
        class Reader:
            def location(self, sid):
                return root
        self.reader = Reader()

    def save(self, name, value):
        """只在临时目录保存虚构不可变文件及其指纹。"""
        target = self.root / name
        write_json(target, value)
        return file_record(self.root, target, 'synthetic_readonly_record')

    def decision(self, stage, payload, *, suffix='one', parents=None):
        """构造带真实文件指纹的虚构展示档案。"""
        body = {'batch_id': self.batch_id, 'stage': stage, 'expected_decision_id': None}
        binding = {'batch_file': self.batch, 'parent_runs': parents or {'A04': self.rid},
                   'parent_files': {'A04': self.manifest['runs'][self.rid]}}
        if stage == 'A06_INPUT':
            binding['selection_ref'] = payload['a04_system_selection_ref']
        value = {'schema_version': 'ModuleA.system_decision.1', 'study_id': self.sid,
            'decision_id': 'systemdecision_' + ('4' if stage == 'A04_SELECTION' else '5') * 32,
            'batch_id': self.batch_id, 'stage': stage, 'state': 'completed',
            'authority_kind': 'system_validation', 'human_review_written': False,
            'request': body, 'request_hash': fingerprint(body), 'binding': binding,
            'input_hash': fingerprint(binding), 'payload': payload, 'payload_hash': fingerprint(payload)}
        ref = self.save(stage + '_' + suffix + '.json', value)
        self.manifest['analysis_plan_system_decisions'].append(ref)
        return ref

    def selection(self):
        """目标一项但保留边界并列两项，展示不能重新截断或排序。"""
        return self.decision('A04_SELECTION', {'network_run_id': self.rid, 'mode': 'dual_ab',
            'requested_count': 1, 'actual_count': 2, 'boundary_ties_retained': True,
            'replacement_after_preparation_failure': False, 'selected': self.rows})

    def view(self, **kwargs):
        """委托生产展示桥接，测试不调用科学计算器。"""
        from modulea.api.system_selection_view import context
        return context(self.reader, self.manifest, self.run, **kwargs)

    def test_missing_selection_is_pending_not_zero_and_does_not_write(self):
        before = deepcopy(self.manifest)
        result = self.view()
        self.assertEqual(result['archive_state'], 'pending')
        self.assertIsNone(result['actual_count'])
        self.assertIsNone(result['pair_count'])
        self.assertEqual(result['selected'], [])
        self.assertEqual(self.manifest, before)

    def test_exact_order_ties_and_metrics_survive_without_fake_approval(self):
        self.selection(); before = deepcopy(self.manifest)
        result = self.view()
        self.assertEqual(result['archive_state'], 'archived')
        self.assertEqual(result['selected'], self.rows)
        self.assertEqual((result['requested_count'], result['actual_count']), (1, 2))
        self.assertIsNone(result['pair_count'])
        self.assertNotIn('approved', result)
        self.assertNotIn('enabled', result)
        self.assertEqual(self.manifest, before)

    def test_fixed_range_only_from_matching_archived_input(self):
        selection_ref = self.selection()
        self.decision('A06_INPUT', {'receptors': self.rows, 'compounds': [{'compound_id': 'C1'}, {'compound_id': 'C2'}],
            'pair_count': 4, 'human_reviews': {}, 'human_review_written': False,
            'a04_system_selection_ref': selection_ref})
        result = self.view()
        self.assertEqual((result['compound_count'], result['pair_count']), (2, 4))

    def test_other_network_or_historical_page_does_not_borrow_current_list(self):
        self.selection()
        self.assertIsNone(self.view(historical=True))
        self.manifest['current']['A04'] = 'run_' + '9' * 32
        self.assertIsNone(self.view())

    def test_old_manual_protocol_is_unchanged(self):
        self.run.pop('execution_protocol')
        self.assertIsNone(self.view())

    def test_changed_parent_reference_does_not_show_old_list_as_current(self):
        self.selection()
        self.manifest['runs'][self.rid] = {'run_file': {'new': 'run'}, 'result_file': {'new': 'result'}}
        result = self.view()
        self.assertEqual(result['archive_state'], 'source_changed')
        self.assertEqual(result['selected'], [])
        self.assertIsNone(result['actual_count'])

    def test_tampered_archived_bytes_are_rejected(self):
        ref = self.selection()
        (self.root / ref['path']).write_text('{}', encoding='utf-8')
        with self.assertRaises(ContractError):
            self.view()

    def test_mismatched_input_rows_are_rejected(self):
        selection_ref = self.selection()
        self.decision('A06_INPUT', {'receptors': list(reversed(self.rows)), 'compounds': [{'compound_id': 'C1'}],
            'pair_count': 2, 'human_reviews': {}, 'human_review_written': False,
            'a04_system_selection_ref': selection_ref})
        with self.assertRaises(ContractError):
            self.view()

    def test_another_batch_list_is_not_presented_as_this_network(self):
        other_id = 'systembatch_' + '8' * 32
        original = self.batch_id
        self.batch_id = other_id
        self.selection()
        self.batch_id = original
        self.assertEqual(self.view()['archive_state'], 'pending')

    def test_boolean_count_is_not_a_valid_scientific_count(self):
        payload = {'network_run_id': self.rid, 'mode': 'degree', 'requested_count': 1,
                   'actual_count': True, 'boundary_ties_retained': True, 'selected': self.rows[:1]}
        self.decision('A04_SELECTION', payload)
        with self.assertRaises(ContractError):
            self.view()

    def test_legitimate_empty_selection_is_distinct_from_pending(self):
        self.decision('A04_SELECTION', {'network_run_id': self.rid, 'mode': 'degree',
            'requested_count': 15, 'actual_count': 0, 'boundary_ties_retained': True, 'selected': []})
        result = self.view()
        self.assertEqual(result['archive_state'], 'archived')
        self.assertEqual(result['actual_count'], 0)
        self.assertIsNone(result['pair_count'])

    def test_other_study_record_is_rejected(self):
        original = self.sid
        self.sid = 'study_' + '8' * 32
        self.selection()
        self.sid = original
        with self.assertRaises(ContractError):
            self.view()

    def test_payload_fingerprint_is_checked_even_if_outer_file_reference_is_updated(self):
        ref = self.selection()
        from storage import read_json
        value = read_json(self.root / ref['path'])
        value['payload']['selected'].reverse()
        changed = self.save('tampered_replacement.json', value)
        self.manifest['analysis_plan_system_decisions'] = [changed]
        with self.assertRaises(ContractError):
            self.view()
