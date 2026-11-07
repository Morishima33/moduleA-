"""第三版准备沿用原逐对象恢复与系统资格，旧批次不升级。"""
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError

from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core.kernel import full_workflow
from modulea.core import system_decisions, system_preparation_checkpoints_v2 as cp
from storage import read_json, verified_file
from tests.modulea import test_system_decisions as upstream
from tests.modulea.plan_report_nonempty_fixture import unavailable_sources
from science_modules.a06 import source_preparation as adapter
from tests.modulea.foundation_source_fixture import stable_ids, bound_connector


class SystemSourcesTests(unittest.TestCase):
    """以真实Workflow和固定工具验证新协议，不借人工批准放行。"""
    @classmethod
    def setUpClass(cls):
        from tests.modulea import plan_report_fixture
        with patch.object(plan_report_fixture, 'multi_target_package', stable_ids(plan_report_fixture.multi_target_package)), patch.object(AnalysisPlanWorkflow, 'start_analysis_plan_system_batch',
                          AnalysisPlanWorkflow.start_analysis_plan_foundation_system_batch):
            upstream.SystemDecisionTests.setUpClass.__func__(cls)
        w = full_workflow(cls.base)
        for stage in ('A04_SELECTION', 'A06_INPUT'):
            w.execute_analysis_plan_system_decision(cls.sid, {'batch_id': cls.batch_id,
                'stage': stage, 'expected_decision_id': None})
        cls.tools = Path(os.environ.get('MODULEA_A06_TOOLS', 'D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='foundation_sources_'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'; shutil.copytree(self.base, self.root)
        self.w = full_workflow(self.root); self.before = self.w.load(self.sid)
        self.body = {'batch_id': self.batch_id, 'stage': 'A06_PREP', 'expected_current_run_id': None}

    def execute(self, **kwargs):
        return self.w.execute_analysis_plan_system_stage(self.sid, self.body, tools=self.tools, **kwargs)

    def test_new_protocol_has_separate_checkpoints_and_complete_trace(self):
        from modulea.core.trace_export import build_trace
        with patch.object(adapter, 'connect', side_effect=unavailable_sources):
            result = self.execute()
        manifest = self.w.load(self.sid)
        self.assertEqual(self.w.run(manifest, result['run_id'])['config']['version'], 'A06.system_preparation.3')
        fixed = system_decisions.current(self.w, manifest, self.batch_id, 'A06_INPUT')[1]['payload']
        self.assertEqual(result['summary']['na_pairs'], fixed['pair_count'])
        self.assertEqual(result['summary']['source_record_count'], len(fixed['compounds']))
        self.assertEqual(result['summary']['verified_structure_count'], 0)
        self.assertEqual(len(manifest[cp.SESSIONS]), 1)
        self.assertNotIn('analysis_plan_system_preparation_sessions', manifest)
        qualified = self.w.qualify_analysis_plan_system_preparation(self.sid,
            {'batch_id': self.batch_id, 'expected_preparation_run_id': result['run_id']})
        self.assertEqual(self.w.run(self.w.load(self.sid), qualified['run_id'])['config']['version'], 'A06.system_qualification.3')
        self.assertEqual(self.w.load(self.sid)['reviews'], self.before['reviews'])
        info = self.w.analysis_plan_system_exports_info(self.sid)
        self.assertTrue(info['enabled'], info['blockers'])
        exported = self.w.export_analysis_plan_system_results(self.sid, {key: info[key]
            for key in ('expected_module', 'expected_run_id', 'expected_input_hash')} | {
            'request_id': 'sysexportreq_' + uuid4().hex, 'author': '明确合成来源测试',
            'note': '全NA原值导出，不是研究复核', 'confirmed': True})
        self.assertEqual(exported['schema_version'], 'A06.system_exports.4')
        self.assertEqual(len(exported['files']), 6)
        for ref in build_trace(self.w, self.sid, include_data=True)['files']:
            verified_file(self.w.location(self.sid), ref)

    def test_completed_packet_is_read_only_on_explicit_resume(self):
        with patch.object(adapter, 'connect', side_effect=unavailable_sources):
            first = self.execute()
        manifest = self.w.load(self.sid)
        with patch.object(adapter, 'connect', side_effect=AssertionError('完整包不能重新请求')):
            again = self.execute()
        self.assertEqual(first['run_id'], again['run_id'])
        self.assertEqual(self.w.load(self.sid)[cp.OBJECTS], manifest[cp.OBJECTS])

    def test_interrupted_ready_ligand_and_real_vina_use_original_fixed_parameters(self):
        from tests.modulea.preparation_object_fixture import ObjectSources
        fixed = system_decisions.current(self.w, self.w.load(self.sid), self.batch_id, 'A06_INPUT')[1]['payload']
        source = ObjectSources(fixed)
        def stop(message):
            if message.startswith('已保存准备对象：'):
                raise KeyboardInterrupt('合成来源配体保存后中断')
        with patch.object(adapter, 'connect', side_effect=bound_connector(source)), patch.object(adapter, 'attempt', side_effect=source.attempt):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(progress=stop)
            before = self.w.load(self.sid)
            saved = cp.read_object(self.w, before, before[cp.OBJECTS][-1])
            self.assertEqual(saved['payload']['state'], 'ready')
            result = self.execute()
        cid = fixed['compounds'][0]['compound_id']
        self.assertEqual(source.calls.count(('compound', cid)), 1)
        self.assertEqual(cp.read_object(self.w, self.w.load(self.sid), before[cp.OBJECTS][-1]), saved)
        qualified = self.w.qualify_analysis_plan_system_preparation(self.sid,
            {'batch_id': self.batch_id, 'expected_preparation_run_id': result['run_id']})
        request = {'batch_id': self.batch_id, 'expected_preparation_run_id': qualified['run_id'], 'expected_scoring_run_id': None}
        scored = self.w.score_analysis_plan_system_preparation(self.sid, request, tools=self.tools)
        self.assertEqual(scored['summary']['scored_pairs'], 1)
        self.assertEqual(scored['summary']['na_pairs'], fixed['pair_count'] - 1)
        self.assertEqual(scored['summary']['verified_structure_count'], 1)
        run = self.w.run(self.w.load(self.sid), scored['run_id'])
        self.assertEqual(run['config']['version'], 'A06.system_scoring.3')
        self.assertEqual(run['config']['vina_parameters']['seed'], 1)
        with patch('science_modules.a06.system_scoring_sources.execute_pair', side_effect=AssertionError('完成组合不得重算')):
            repeated = self.w.score_analysis_plan_system_preparation(self.sid, request, tools=self.tools)
        self.assertEqual(repeated['run_id'], scored['run_id'])
        self.assertEqual(self.w.load(self.sid)['reviews'], self.before['reviews'])

    def test_interrupted_checkpoint_rejects_tool_change_corruption_and_human_hold(self):
        from science_modules.a06 import system_preparation_sources as science
        def stop(message):
            if message.startswith('已保存准备对象：'):
                raise KeyboardInterrupt('明确合成中断')
        with patch.object(adapter, 'connect', side_effect=unavailable_sources), self.assertRaises(KeyboardInterrupt):
            self.execute(progress=stop)
        saved = self.w.load(self.sid)
        session = cp.read_session(self.w, saved, saved[cp.SESSIONS][0])
        changed = dict(session['binding'], vina_sha256='0' * 64)
        with self.assertRaises(ContractError):
            cp.find_session(self.w, saved, session['batch_file'], session['system_input_ref'], changed)
        from copy import deepcopy
        changed = deepcopy(session['binding'])
        changed['configuration']['vina_parameters']['seed'] += 1
        with self.assertRaises(ContractError):
            cp.find_session(self.w, saved, session['batch_file'], session['system_input_ref'], changed)
        with patch.object(science, 'CODE_NAMES', science.CODE_NAMES[:-1]), self.assertRaises(ContractError):
            self.execute()
        original = cp.read_object(self.w, saved, saved[cp.OBJECTS][0])['payload']['files'][0]
        path = verified_file(self.w.location(self.sid), original)
        raw = path.read_bytes(); path.write_bytes(b'corrupt synthetic evidence')
        with patch.object(adapter, 'connect', side_effect=AssertionError('损坏不能重下')), self.assertRaises(ContractError):
            self.execute()
        path.write_bytes(raw)
        self.w.review(self.sid, saved['current']['A04'], 'pending', '明确合成测试', '恢复前暂停')
        with patch.object(adapter, 'connect', side_effect=AssertionError('暂存不能重下')), self.assertRaises(ContractError):
            self.execute()
        self.assertEqual(len(self.w.load(self.sid)[cp.OBJECTS]), len(saved[cp.OBJECTS]))
