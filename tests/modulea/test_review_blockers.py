"""核对阻塞解释、原表入口及不改变复核许可。"""

import unittest

from modulea.api.review_blockers import blockers


class ReviewBlockerTests(unittest.TestCase):
    def setUp(self):
        self.view = {'review': {'can_review': True, 'allowed_decisions': ['pending', 'rejected']},
                     'module': {'module_id': 'A02'}, 'disease_scope': {'items': []}}
        self.result = {'summary': {}, 'tables': {}}

    def test_disease_scope_names_only_unresolved_and_preserves_decisions(self):
        self.result['tables']['scope_groups'] = [
            {'database': 'OMIM', 'disease_term': 'Example', 'scope': 'pending'},
            {'database': 'OTP', 'disease_term': 'Already decided', 'scope': 'direct'}]
        row, = blockers(self.view, self.result, 'study_test')
        self.assertEqual(row['examples'], ['OMIM · Example'])
        self.assertEqual(row['section_id'], 'disease-scope-review')
        self.assertEqual(self.view['review']['allowed_decisions'], ['pending', 'rejected'])

    def test_formula_uses_current_evidence_not_all_structure_pending(self):
        self.view.update(module={'module_id': 'A01'}, special={'system_component_publication': {'identity_tools_available': True}},
                         files=[{'name': 'tcmsp_source_issues.csv', 'key': 'run_test.2'}])
        self.result['summary']['结构待核分组数'] = 10
        self.result['tables']['tcmsp_source_issues'] = [
            {'herb': '白术', 'compound_id': 'MOL1', 'reason': '物种缺失'}]
        row, = blockers(self.view, self.result, 'study_test')
        self.assertEqual(row['section_id'], 'component-source-evidence')
        self.assertEqual(row['file_key'], 'run_test.2')
        self.assertIn('物种缺失', row['examples'][0])

    def test_approved_or_read_only_has_no_actions(self):
        self.view['review']['allowed_decisions'].append('approved')
        self.assertEqual(blockers(self.view, self.result, 'study_test'), [])
        self.view['review'].update(can_review=False, allowed_decisions=['pending'])
        self.assertEqual(blockers(self.view, self.result, 'study_test'), [])
