"""评分前置预检的隔离集成测试：来源、阻断、请求隔离和只读行为。"""
from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from modulea.api.server import App
from science_modules.a06 import reference_review
from storage import verified_file
import tests.modulea.test_plan_pockets as fixture


class ScoringPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """只建立一份真实归档的合成准备；每项测试恢复临时材料。"""
        cls.base = fixture.PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
        cls.base.setUp()
        cls.addClassCleanup(cls.base.doCleanups)
        cls.workflow, cls.sid = cls.base.workflow, cls.base.sid
        cls.study_dir = cls.base.home
        review = reference_review.run(cls.workflow, cls.sid, {
            'expected_input_id': cls.base.input_record['input_id'],
            'expected_preparation_run_id': cls.base.source_run_id,
            'request_id': 'refreq_' + uuid4().hex, 'reviewer': '隔离测试',
            'note': '只测试预检，参考为空', 'confirmed': True, 'choices': []},
            Path(cls.base.base.temp.name), lambda _: None)['review']
        cls.result = cls.workflow.publish_analysis_plan_a06_reference_qualification_v2(cls.sid, {
            'expected_input_id': cls.base.input_record['input_id'],
            'expected_preparation_run_id': cls.base.source_run_id,
            'expected_review_id': review['review_id'], 'request_id': 'refprep_' + uuid4().hex,
            'reviewer': '隔离测试', 'note': '预检绑定输入', 'confirmed': True})
        cls.app = App(cls.base.base.settings)

    def setUp(self):
        self.manifest_path = self.study_dir / 'manifest.json'
        self.before = self.manifest_path.read_bytes()
        self.files_before = {str(p.relative_to(self.study_dir)) for p in self.study_dir.rglob('*') if p.is_file()}
        self.payload = {'expected_preparation_run_id': self.result['run_id'],
                        'reviewer': '隔离预检', 'note': '只核对前置条件', 'confirmed': True}

    def tearDown(self):
        self.assertEqual(self.manifest_path.read_bytes(), self.before)
        self.assertEqual({str(p.relative_to(self.study_dir)) for p in self.study_dir.rglob('*') if p.is_file()}, self.files_before)

    def check(self, payload=...):
        return self.workflow.validate_analysis_plan_a06_scoring_request(self.sid, self.payload if payload is ... else payload)

    def test_actual_source_parameters_and_batch_are_reported(self):
        value = self.check()
        manifest = self.workflow.load(self.sid)
        source = self.workflow.run(manifest, self.base.source_run_id)
        self.assertEqual(value['scoring_parameters'], source['config']['vina_parameters'])
        self.assertTrue(value['scoring_parameters'])
        self.assertEqual(value['config_hash'], source['config_hash'])
        self.assertEqual(value['source_preparation_run_id'], self.base.source_run_id)
        self.assertEqual(value['pair_count'], self.base.packet['pair_count'])
        self.assertEqual(value['input_id'], self.base.input_record['input_id'])
        self.assertIsNone(value['latest_preparation_review_id'])
        self.assertFalse(value['allowed'])
        self.assertTrue(value['read_only'])

    def test_api_handler_never_submits_tasks(self):
        from modulea.api.analysis_reference_preparation_view import validate_scoring
        with patch.object(self.app.tasks, 'submit', side_effect=AssertionError('预检不得提交任务')) as submit:
            value = validate_scoring(self.app, SimpleNamespace(json=lambda: self.payload), self.sid)
        submit.assert_not_called()
        self.assertFalse(value['execution_available'])
        self.assertFalse(value['allowed'])
        readiness = self.workflow.analysis_plan_a06_scoring_readiness(self.sid)
        self.assertTrue(readiness['preflight_available'])
        self.assertFalse(readiness['scoring_allowed'])

    def test_api_preflight_runs_without_scientific_site_packages(self):
        script = """import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from modulea.config import Settings
from modulea.core.kernel import Kernel
w=Kernel(Settings(data_root=Path(sys.argv[2]))).workflow()
value=w.validate_analysis_plan_a06_scoring_request(sys.argv[3],json.loads(sys.argv[4]))
print(json.dumps({'allowed':value['allowed'],'parameters':value['scoring_parameters']}))
"""
        completed = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script,
            str(Path(__file__).resolve().parents[2] / 'src'), str(self.workflow.root), self.sid,
            json.dumps(self.payload)], capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(json.loads(completed.stdout)['allowed'])

    def test_invalid_payload_and_scientific_overrides_are_rejected(self):
        invalid = [None, [], {}, dict(self.payload, confirmed=False), dict(self.payload, reviewer=''),
                   dict(self.payload, note=' '), dict(self.payload, expected_preparation_run_id=None),
                   dict(self.payload, scoring_parameters={'seed': 2}), dict(self.payload, approved=True)]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ContractError):
                self.check(payload)

    def test_stale_preparation_is_rejected(self):
        with self.assertRaises(ContractError):
            self.check(dict(self.payload, expected_preparation_run_id=self.base.source_run_id))

    def test_trashed_study_is_rejected(self):
        manifest = self.workflow.load(self.sid)
        manifest['trashed'] = True
        self.workflow.save(manifest)
        try:
            with self.assertRaises(ContractError):
                self.check()
        finally:
            self.manifest_path.write_bytes(self.before)

    def test_invalid_upstream_is_blocked(self):
        with patch.object(self.workflow, 'active', return_value=False):
            value = self.check()
        self.assertFalse(value['allowed'])
        self.assertTrue(any('失效' in reason for reason in value['blockers']))

    def test_changed_input_is_blocked(self):
        with patch.object(self.workflow, 'analysis_plan_info', return_value={'a06_preparation_input': None}):
            value = self.check()
        self.assertFalse(value['allowed'])
        self.assertTrue(any('输入或方案已更新' in reason for reason in value['blockers']))

    def test_no_ready_pairs_and_unapproved_preparation_remain_blocked(self):
        value = self.check()
        self.assertEqual(value['ready_pairs'], 0)
        self.assertTrue(any('没有可评分组合' in r for r in value['blockers']))
        self.assertTrue(any('人工整体复核' in r for r in value['blockers']))

    def test_no_implicit_execution_even_when_other_blockers_are_empty(self):
        with patch('modulea.core.reference_preparation.scoring_readiness', return_value={'blockers': []}):
            value = self.check()
        self.assertFalse(value['allowed'])
        self.assertFalse(value['execution_available'])
        self.assertIn('新版评分执行入口尚未接通', value['blockers'])

    def test_source_file_tampering_is_rejected(self):
        manifest = self.workflow.load(self.sid)
        run = self.workflow.run(manifest, self.result['run_id'])
        path = verified_file(self.study_dir, run['inputs']['source_run'])
        original = path.read_bytes()
        try:
            path.write_bytes(original + b' ')
            with self.assertRaises(ContractError):
                self.check()
        finally:
            path.write_bytes(original)

    def test_wrong_source_study_cannot_be_mixed(self):
        real_run = self.workflow.run
        def wrong_source(manifest, run_id):
            run = real_run(manifest, run_id)
            if run_id == self.result['run_id']:
                run = deepcopy(run)
                run['inputs']['source_run'] = dict(run['inputs']['source_run'], path='../other/run.json')
            return run
        with patch.object(self.workflow, 'run', side_effect=wrong_source), self.assertRaises(ContractError):
            self.check()

    def test_concurrent_manifest_change_is_rejected(self):
        real_load = self.workflow.load
        calls = 0
        def changing(sid):
            nonlocal calls
            calls += 1
            value = real_load(sid)
            if calls > 1:
                value['updated_at'] = 'changed-during-read'
            return value
        with patch.object(self.workflow, 'load', side_effect=changing), self.assertRaises(ContractError):
            self.check()


if __name__ == '__main__':
    unittest.main()
