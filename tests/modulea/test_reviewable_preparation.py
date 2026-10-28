"""可复核准备隔离验收：实际证据复算、明确人工决定、旧评分隔离与失效。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from storage import read_json, verified_file, write_json
from modulea.api.server import App
from modulea.api.errors import ApiError
from science_modules.a06 import reference_review
from science_modules.a06.plan_reviewable_preparation import validator, derive
import tests.modulea.test_plan_pockets as fixture


class ReviewablePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """使用真实Meeko准备与真实预测口袋证据复核；上游和结构为合成夹具。"""
        cls.base = fixture.PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
        cls.base.setUp()
        cls.addClassCleanup(cls.base.doCleanups)
        cls.sid, cls.home = cls.base.sid, cls.base.home
        w = cls.base.workflow
        w.validators['A06_PREP'] = validator(w.root, w.validators['A06_PREP'])
        cls.validators = w.validators
        pocket = w.publish_analysis_plan_a06_pocket_review(cls.sid, cls.base.payload())
        ref = reference_review.run(w, cls.sid, {
            'expected_input_id': cls.base.input_record['input_id'], 'expected_preparation_run_id': pocket['run_id'],
            'request_id': 'refreq_' + uuid4().hex, 'reviewer': '隔离测试', 'note': '合成预测口袋用于探索',
            'confirmed': True, 'choices': []}, Path(cls.base.base.temp.name), lambda _: None)['review']
        cls.source = w.publish_analysis_plan_a06_reference_qualification_v2(cls.sid, {
            'expected_input_id': cls.base.input_record['input_id'], 'expected_preparation_run_id': pocket['run_id'],
            'expected_review_id': ref['review_id'], 'request_id': 'refprep_' + uuid4().hex,
            'reviewer': '隔离测试', 'note': '仅验证人工复核接入', 'confirmed': True})
        cls.manifest = w.load(cls.sid)
        cls.original_bytes = (cls.home / 'manifest.json').read_bytes()

    def setUp(self):
        self.w = type(self.base.workflow)(self.base.workflow.root, self.validators)
        self.body = {'expected_preparation_run_id': self.source['run_id'],
                     'expected_input_id': self.base.input_record['input_id'],
                     'request_id': 'reviewprep_' + uuid4().hex, 'reviewer': '隔离复验人',
                     'note': '测试资料进入人工复核，未运行评分', 'confirmed': True}
        self.addCleanup((self.home / 'manifest.json').write_bytes, self.original_bytes)

    def publish(self):
        """调用真实公开Workflow生产入口。"""
        return self.w.publish_analysis_plan_a06_reviewable(self.sid, self.body)

    def test_scientific_publication_and_explicit_review(self):
        result = self.publish()
        m = self.w.load(self.sid)
        self.assertEqual((result['summary']['ready_pairs'], result['summary']['na_pairs']), (1, 3))
        self.assertFalse(result['summary']['handoff_blocked'])
        self.assertEqual(result['summary']['scored_pairs'], 0)
        self.assertTrue(all(row['score'] is None for row in result['tables']['planned_pairs']))
        self.assertEqual(m['reviews'], self.manifest['reviews'])
        self.assertFalse(self.w.approved(m, result['run_id']))
        self.assertTrue(self.w.analysis_plan_a06_reference_qualification(self.sid)['can_enter_review'])
        self.assertTrue(self.w.analysis_plan_a06_review_gate(self.sid)['can_submit'])
        old = self.w.result(m, self.source['run_id'])
        self.assertTrue(old['summary']['handoff_blocked'])
        self.assertEqual(old, self.source)
        review = self.w.review(self.sid, result['run_id'], 'approved', '合成测试复核者', '仅批准合成准备资料')
        self.assertTrue(self.w.approved(self.w.load(self.sid), result['run_id']))
        with self.assertRaises(ContractError):
            self.w.begin(self.sid, 'A06', {}, {}, '禁止旧协议')
        value = self.w.validate_analysis_plan_a06_scoring_request(self.sid, {
            'expected_preparation_run_id': result['run_id'], 'reviewer': '隔离预检', 'note': '复核后仍不评分', 'confirmed': True})
        self.assertFalse(value['allowed'])
        self.assertEqual(value['latest_preparation_review_id'], review['review_id'])
        self.assertNotIn('当前准备仍处于handoff_blocked阻断状态', value['blockers'])
        self.w.review(self.sid, result['run_id'], 'pending', '合成测试复核者', '撤回本次决定', review['review_id'])
        self.assertFalse(self.w.approved(self.w.load(self.sid), result['run_id']))

    def test_repeated_submission_and_conflicting_request(self):
        result = self.publish()
        before = (self.home / 'manifest.json').read_bytes()
        self.assertEqual(self.publish(), result)
        self.assertEqual((self.home / 'manifest.json').read_bytes(), before)
        self.body['note'] = '同编号改内容'
        with self.assertRaises(ContractError):
            self.publish()
        self.assertEqual((self.home / 'manifest.json').read_bytes(), before)

    def test_invalid_and_stale_requests_do_not_write(self):
        for body in (dict(self.body, confirmed=False), dict(self.body, approved=True),
                     dict(self.body, expected_preparation_run_id=self.base.source_run_id),
                     dict(self.body, expected_input_id='input_' + uuid4().hex), dict(self.body, reviewer='')):
            with self.subTest(body=body), self.assertRaises(ContractError):
                self.w.validate_analysis_plan_a06_reviewable(self.sid, body)
        self.assertEqual((self.home / 'manifest.json').read_bytes(), self.original_bytes)

    def test_source_corruption_is_rejected(self):
        ref = self.manifest['runs'][self.source['run_id']]['run_file']
        path = verified_file(self.home, ref)
        saved = path.read_bytes()
        self.addCleanup(path.write_bytes, saved)
        path.write_bytes(saved + b' ')
        with self.assertRaises(ContractError):
            self.publish()
        self.assertEqual((self.home / 'manifest.json').read_bytes(), self.original_bytes)

    def test_matrix_and_source_mismatch_fail_independent_validator(self):
        result = self.publish()
        run = self.w.run(self.w.load(self.sid), result['run_id'])
        bad = deepcopy(result['summary']); bad['ready_pairs'] += 1
        with self.assertRaises(ContractError):
            self.validators['A06_PREP'](run, bad, result['tables'], [], 'success')
        crossed = deepcopy(run['inputs']); crossed['reference_preparation_run']['path'] = '../other/run.json'
        with self.assertRaises(ContractError):
            derive(self.w.root, self.sid, crossed)

    def test_upstream_withdrawal_and_trashed_are_blocked(self):
        result = self.publish()
        m = self.w.load(self.sid)
        parent = self.w.run(m, result['run_id'])['parent_runs']['A04']
        previous = self.w.latest_review(m, self.w.run(m, parent)['artifact_id'])
        self.w.review(self.sid, parent, 'pending', '隔离测试', '撤回上游', previous['review_id'])
        self.assertFalse(self.w.analysis_plan_a06_review_gate(self.sid)['can_submit'])
        with self.assertRaises(ContractError):
            self.publish()

    def test_independent_selection_review_withdrawal_blocks_normal_approval(self):
        result = self.publish()
        info = self.w.analysis_plan_info(self.sid)
        selection, review = info['a04_selection'], info['a04_selection_review']
        self.w.review_analysis_plan_a04_selection(self.sid, {
            'request_id': 'planreq_' + uuid4().hex, 'expected_a00': selection['expected_a00'],
            'expected_a04': selection['expected_a04'], 'selection_id': selection['selection_id'],
            'expected_review_id': review['review_id'], 'decision': 'pending',
            'reviewer': '隔离测试', 'note': '撤回独立受体选择决定'})
        self.assertFalse(self.w.active(self.w.load(self.sid), result['run_id']))
        with self.assertRaises(ContractError):
            self.w.review(self.sid, result['run_id'], 'approved', '隔离测试', '不能绕过独立复核撤回')
        m = deepcopy(self.manifest); m['trashed'] = True
        write_json(self.home / 'manifest.json', m, replace=True)
        with self.assertRaises(ContractError):
            self.publish()

    def test_page_review_and_legacy_continuation_are_isolated(self):
        result = self.publish()
        app = App(self.base.base.settings)
        view = app.views.module(self.sid, 'A06_PREP')
        self.assertTrue(view['review']['can_review'])
        self.assertIn('approved', view['review']['allowed_decisions'])
        self.assertFalse(view['review']['continue']['available'])
        self.assertIsNone(view['automatic_docking'])
        self.assertIsNone(view['operation_guide'])
        with patch.object(app.tasks, 'submit', side_effect=AssertionError('不能提交旧任务')):
            req = SimpleNamespace(json=lambda: {'run_id': result['run_id'], 'decision': 'approved',
                'reviewer': '合成测试复核者', 'note': '明确测试决定', 'after': 'continue'})
            value, code = app.post_review(req, self.sid, 'A06_PREP')
            self.assertEqual(code, 201)
            self.assertIsNone(value['task'])
            with self.assertRaises(ApiError) as error:
                app.post_continue(SimpleNamespace(), self.sid)
            self.assertEqual(error.exception.code, 'GATE_BLOCKED')
        from modulea.tasks.worker import run_continue
        with patch('modulea.tasks.worker.full_workflow', return_value=self.w), \
             patch('auto_continue.continue_after_review', side_effect=AssertionError('不能调用旧评分')):
            message = run_continue(self.base.base.settings, {'study_id': self.sid, 'task_id': 'isolated'}, SimpleNamespace(update=lambda *a, **k: None))
        self.assertIn('没有调用旧计算', message)

    def test_all_na_preparation_cannot_become_reviewable(self):
        m = deepcopy(self.manifest); m['current']['A06_PREP'] = self.base.source_run_id
        write_json(self.home / 'manifest.json', m, replace=True)
        ref = reference_review.run(self.w, self.sid, {
            'expected_input_id': self.base.input_record['input_id'], 'expected_preparation_run_id': self.base.source_run_id,
            'request_id': 'refreq_' + uuid4().hex, 'reviewer': '隔离测试', 'note': '不采用预测口袋',
            'confirmed': True, 'choices': []}, Path(self.base.base.temp.name), lambda _: None)['review']
        source = self.w.publish_analysis_plan_a06_reference_qualification_v2(self.sid, {
            'expected_input_id': self.base.input_record['input_id'], 'expected_preparation_run_id': self.base.source_run_id,
            'expected_review_id': ref['review_id'], 'request_id': 'refprep_' + uuid4().hex,
            'reviewer': '隔离测试', 'note': '全NA验证', 'confirmed': True})
        self.assertFalse(self.w.analysis_plan_a06_reviewable_info(self.sid)['enabled'])
        self.body['expected_preparation_run_id'] = source['run_id']
        before = (self.home / 'manifest.json').read_bytes()
        with self.assertRaises(ContractError):
            self.publish()
        self.assertEqual((self.home / 'manifest.json').read_bytes(), before)
