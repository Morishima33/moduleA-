"""参考资格新准备版本：隔离归档、独立复算和重复请求。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from contracts import ContractError
from science_modules.a06 import reference_review
from science_modules.a06.plan_reference_publication_v2 import validator
from modulea.core.reference_preparation import qualification, scoring_readiness
from modulea.core.reference_preparation import review_packet
from modulea.api.server import App
from tests.modulea.test_plan_pockets import PocketReviewTests


class ReferencePublicationV2Tests(unittest.TestCase):
    def test_v2_api_and_actual_worker_empty_reference(self):
        from modulea.api.analysis_reference_preparation_view import info_v2, prepare_v2
        from modulea.tasks.worker import run_a06_plan_reference_preparation
        tools = Path(r'D:\codex-重大专项\moduleA\environment\a06_runtime_v1')
        if not tools.is_dir():
            self.skipTest('只读参考科学环境不存在')
        base = PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
        base.setUp()
        self.addCleanup(base.doCleanups)
        workflow, sid = base.workflow, base.sid
        review_request = {'expected_input_id': base.input_record['input_id'],
                          'expected_preparation_run_id': base.source_run_id,
                          'request_id': 'refreq_' + uuid4().hex, 'reviewer': '隔离测试',
                          'note': '空参考选择', 'confirmed': True, 'choices': []}
        review = reference_review.run(workflow, sid, review_request, Path(base.base.temp.name), lambda _: None)['review']
        payload = {'expected_input_id': base.input_record['input_id'],
                   'expected_preparation_run_id': base.source_run_id, 'expected_review_id': review['review_id'],
                   'request_id': 'refprep_' + uuid4().hex, 'reviewer': '隔离测试',
                   'note': '发布隔离复算', 'confirmed': True}
        settings = base.base.settings
        settings.science_python, settings.science_tools_root = sys.executable, tools
        tasks = Mock()
        tasks.active_for.return_value = False
        tasks.submit.return_value = ({'task_id': 'task_' + uuid4().hex}, True)
        app = SimpleNamespace(kernel=SimpleNamespace(workflow=lambda: workflow), settings=settings, tasks=tasks)
        req = SimpleNamespace(json=lambda: payload)
        before = deepcopy(workflow.load(sid))
        self.assertTrue(info_v2(app, None, sid)['enabled'])
        self.assertEqual(workflow.load(sid), before)
        response, status = prepare_v2(app, req, sid)
        self.assertEqual(status, 202)
        self.assertEqual(tasks.submit.call_args.args[1], 'a06_plan_reference_qualification_v2')
        task = {'task_id': response['task']['task_id'], 'study_id': sid,
                'kind': 'a06_plan_reference_qualification_v2', 'payload': json.dumps(payload)}
        run_a06_plan_reference_preparation(settings, task, Mock())
        current = workflow.load(sid)['current']['A06_PREP']
        self.assertEqual(workflow.run(workflow.load(sid), current)['config']['version'], 'A06.plan_reference_preparation.2')
        state = info_v2(app, None, sid)
        self.assertEqual(state['state'], 'bound')
        self.assertFalse(state['execution_available'])
        response, status = prepare_v2(app, req, sid)
        self.assertEqual((status, response['run_id']), (200, current))

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
        check = qualification(workflow, sid)
        self.assertTrue(check['supported'])
        self.assertTrue(check['qualified'], check)
        self.assertFalse(check['can_enter_review'])
        gate = scoring_readiness(workflow, sid)
        self.assertTrue(gate['supported'])
        self.assertFalse(gate['scoring_allowed'])
        page = App(base.base.settings).views.module(sid, 'A06_PREP')
        self.assertIsNone(page['automatic_docking'])
        self.assertIsNone(page['operation_guide'])
        self.assertNotEqual(page['module']['title_zh'], '对接准备与自动计算')

        packet = review_packet(workflow, sid)
        self.assertTrue(packet['supported'])
        self.assertFalse(packet['review_available'])
        self.assertFalse(packet['can_enter_review'])
        self.assertFalse(packet['scoring']['scoring_allowed'])
        self.assertEqual(packet['summary']['scored_pairs'], 0)
        before = deepcopy(workflow.load(sid))
        self.assertEqual(review_packet(workflow, sid)['current_run_id'], result['run_id'])
        self.assertEqual(workflow.load(sid), before)
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
