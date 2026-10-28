"""参考资格新准备版本：隔离归档、独立复算和重复请求。"""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from science_modules.a06 import reference_review
from science_modules.a06.plan_reference_publication_v2 import validator
from tests.modulea.test_plan_pockets import PocketReviewTests


class ReferencePublicationV2Tests(unittest.TestCase):
    def test_publish_recomputes_archives_and_remains_blocked(self):
        base = PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
        base.setUp()
        self.addCleanup(base.doCleanups)
        workflow, sid = base.workflow, base.sid
        old = deepcopy(workflow.load(sid)['runs'][base.source_run_id])
        request = {'expected_input_id': base.input_record['input_id'],
                   'expected_preparation_run_id': base.source_run_id,
                   'request_id': 'refreq_' + uuid4().hex, 'reviewer': '隔离测试',
                   'note': '空参考选择', 'confirmed': True, 'choices': []}
        review = reference_review.run(workflow, sid, request, Path(base.base.temp.name), lambda _: None)['review']
        payload = {'expected_input_id': base.input_record['input_id'],
                   'expected_preparation_run_id': base.source_run_id, 'expected_review_id': review['review_id'],
                   'request_id': 'refprep_' + uuid4().hex, 'reviewer': '隔离测试',
                   'note': '发布隔离复算', 'confirmed': True}
        result = workflow.publish_analysis_plan_a06_reference_qualification_v2(sid, payload)
        manifest = workflow.load(sid)
        run = workflow.run(manifest, result['run_id'])
        self.assertEqual(run['config']['version'], 'A06.plan_reference_preparation.2')
        self.assertEqual(manifest['runs'][base.source_run_id], old)
        self.assertEqual(result['summary']['ready_pairs'], 0)
        self.assertTrue(result['summary']['handoff_blocked'])
        self.assertEqual(result['summary']['scored_pairs'], 0)
        self.assertFalse(workflow.approved(manifest, result['run_id']))
        self.assertEqual(workflow.publish_analysis_plan_a06_reference_qualification_v2(sid, payload)['run_id'], result['run_id'])
        with self.assertRaises(ContractError):
            workflow.publish_analysis_plan_a06_reference_qualification_v2(sid, dict(payload, note='改动'))
        altered = dict(result['summary'], ready_pairs=999)
        with self.assertRaises(ContractError):
            validator(workflow.root, lambda *args: None)(run, altered, result['tables'], [], 'success')

    def test_selected_reference_updates_published_matrix_with_simulated_science(self):
        base = PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
        base.setUp()
        self.addCleanup(base.doCleanups)
        workflow, sid = base.workflow, base.sid
        amended = workflow.publish_analysis_plan_a06_pocket_review(sid, base.payload())
        choice = {'target_id': base.packet['receptors'][0]['target_id'],
                  'candidate_key': 'a' * 64, 'reference_key': 'b' * 64}
        request = {'expected_input_id': base.input_record['input_id'],
                   'expected_preparation_run_id': amended['run_id'], 'request_id': 'refreq_' + uuid4().hex,
                   'reviewer': '隔离测试', 'note': '模拟成功参考', 'confirmed': True, 'choices': [choice]}
        assessment = {'state': 'ready', 'quality': '严格', 'reason_zh': '模拟严格通过'}
        fake = {'choice': choice, 'state': 'ready', 'evidence': {'files': []}}
        # 归档路径和准备校验真实执行；参考科学结果明确为模拟。
        with patch('science_modules.a06.reference_review.validate_choices'), \
             patch('science_modules.a06.reference_candidates.validate_choices'), \
             patch('science_modules.a06.reference_review.prepare_selected', return_value=fake), \
             patch('science_modules.a06.reference_review.validate_ready', return_value=assessment), \
             patch('science_modules.a06.plan_reference_qualification_v2.validate_choices'), \
             patch('science_modules.a06.plan_reference_qualification_v2.validate_ready', return_value=assessment):
            review = reference_review.run(workflow, sid, request, Path(base.base.temp.name), lambda _: None)['review']
            payload = {'expected_input_id': base.input_record['input_id'],
                       'expected_preparation_run_id': amended['run_id'], 'expected_review_id': review['review_id'],
                       'request_id': 'refprep_' + uuid4().hex, 'reviewer': '隔离测试',
                       'note': '模拟参考资格发布', 'confirmed': True}
            result = workflow.publish_analysis_plan_a06_reference_qualification_v2(sid, payload)
        self.assertEqual(result['summary']['reference_ready_count'], 1)
        self.assertEqual(result['tables']['receptor_preparation'][0]['quality'], '严格')
        self.assertEqual(result['summary']['ready_pairs'], 1)
        self.assertEqual(result['summary']['scored_pairs'], 0)
        self.assertTrue(result['summary']['handoff_blocked'])
        self.assertTrue(all(row['score'] is None for row in result['tables']['planned_pairs']))


if __name__ == '__main__':
    unittest.main()
