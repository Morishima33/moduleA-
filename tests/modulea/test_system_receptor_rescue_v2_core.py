"""第二轮正常A06补救的明确基线、幂等与检查点；只使用合成研究。"""
from copy import deepcopy
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from contracts import ContractError, fingerprint
from storage import file_record, new_id, read_json, write_json
from tests.modulea import test_system_receptor_rescue_core as fixture


class ReceptorRescueV2CoreTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / 'src/modulea/core/system_receptor_rescue_v2.py'
        self.assertTrue(path.is_file(), '第二版工作流尚未实现')
        self.core = importlib.import_module('modulea.core.system_receptor_rescue_v2')
        self.seed = fixture.SystemReceptorRescueCoreTests('test_other_versions_keep_original_active_branch')
        self.seed.setUp()
        self.addCleanup(self.seed.doCleanups)
        self.w = self.core.SystemReceptorRescueV2Workflow(self.seed.root, self.seed.w.validators)
        self.sid, self.prep, self.score = self.seed.sid, self.seed.prep_id, self.seed.score_id
        self.science = types.ModuleType('science_modules.a06.system_receptor_rescue_v2')
        self.science.VERSION = self.core.VERSION
        self.science.configuration = Mock(side_effect=lambda *_, **__: dict(self.seed.configuration, version=self.core.VERSION))
        self.science.compute = Mock(side_effect=self.seed.compute)
        name = self.science.__name__
        previous = sys.modules.get(name)
        sys.modules[name] = self.science
        self.addCleanup(lambda: sys.modules.pop(name, None) if previous is None else sys.modules.__setitem__(name, previous))
        self.patch = patch('science_modules.a06.system_receptor_rescue_v2', self.science, create=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.before = self.w.load(self.sid)

    def body(self):
        value = self.w.analysis_plan_receptor_rescue_v2_info(self.sid)
        self.assertTrue(value['enabled'], value['blockers'])
        return {key: value[key] for key in ('expected_preparation_run_id', 'expected_scoring_run_id', 'expected_input_hash')} | {
            'request_id': new_id('rescue'), 'author': '合成第二轮', 'note': '明确继承当前科学结果补救剩余对象', 'confirmed': True}

    def execute(self, body):
        return self.w.execute_analysis_plan_receptor_rescue_v2(self.sid, body, tools=self.seed.tools, repair_packages=self.seed.repair)

    def test_original_paths_baseline_publishes_normal_v2_without_changing_preparation_or_reviews(self):
        body = self.body()
        result = self.execute(body)
        final = self.w.load(self.sid)
        run = self.w.run(final, result['run_id'])
        self.assertEqual(run['config']['version'], 'A06.system_rescue.2')
        self.assertEqual(run['parent_runs'], {'A06_PREP': self.prep})
        self.assertEqual(final['current']['A06_PREP'], self.prep)
        self.assertEqual(final['runs'][self.score], self.before['runs'][self.score])
        self.assertEqual(final['reviews'], self.before['reviews'])
        self.assertEqual(run['inputs']['source_binding']['baseline_original_scoring_run_id'], self.score)
        self.assertIsNone(run['inputs']['source_binding']['partial_recovery'])
        self.assertTrue(self.w.active(final, run['run_id']))
        self.assertFalse(self.w.approved(final, run['run_id']))
        self.assertEqual(self.execute(body), result)
        self.assertEqual(self.science.compute.call_count, 1)

    def test_completed_v1_baseline_is_preserved_and_original_score_identity_remains_bound(self):
        first = self.seed.execute()
        baseline = deepcopy(self.w.load(self.sid)['runs'][first['run_id']])
        body = self.body()
        self.assertEqual(body['expected_scoring_run_id'], first['run_id'])
        result = self.execute(body)
        final = self.w.load(self.sid)
        run = self.w.run(final, result['run_id'])
        self.assertEqual(run['inputs']['source_scoring_result'], baseline['result_file'])
        self.assertEqual(run['inputs']['source_binding']['baseline_original_scoring_run_id'], self.score)
        self.assertIsNone(run['inputs']['source_binding']['partial_recovery'])
        self.assertEqual(final['runs'][first['run_id']], baseline)
        self.assertEqual(final['reviews'], self.before['reviews'])
        self.assertTrue(self.w.active(final, result['run_id']))

    def test_incomplete_v1_can_only_be_superseded_by_new_explicit_request_of_same_sources(self):
        self.seed.science.compute.side_effect = RuntimeError('合成第一轮中断')
        with self.assertRaises(RuntimeError):
            self.seed.execute()
        incomplete = self.w.load(self.sid)['current']['A06']
        body = self.body()
        self.assertEqual(body['expected_scoring_run_id'], self.score)
        with self.assertRaises(ContractError):
            self.execute(dict(body, request_id=self.seed.body['request_id']))
        result = self.execute(body)
        final = self.w.load(self.sid)
        self.assertIsNone(final['runs'][incomplete]['result_file'])
        self.assertTrue(self.w.active(final, result['run_id']))

    def test_exact_incomplete_v2_request_resumes_same_run_and_checkpoint_dispatches(self):
        body = self.body()
        self.science.compute.side_effect = RuntimeError('合成第二轮中断')
        with self.assertRaises(RuntimeError):
            self.execute(body)
        m = self.w.load(self.sid)
        rid = m['current']['A06']
        ref = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_000001_region_0001',
            {'state': 'completed', 'score': -8.25}, [])
        self.assertEqual(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_000001_region_0001')[0], ref)
        self.assertEqual(read_json(self.w.location(self.sid) / ref['path'])['schema_version'], self.core.VERSION)
        self.science.compute.side_effect = self.seed.compute
        self.assertEqual(self.execute(body)['run_id'], rid)
        self.assertEqual(len(self.w.load(self.sid)['runs']), len(self.before['runs']) + 1)

    def test_stale_hash_wrong_sources_and_extra_fields_do_not_create_v2(self):
        body = self.body()
        for change in ({'expected_input_hash': '0' * 64}, {'expected_scoring_run_id': new_id('run')},
                       {'parameters': {}}, {'confirmed': 1}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.execute(body | change)
        self.assertEqual(self.w.load(self.sid), self.before)

    def partial_first(self):
        """公开第一轮入口中断后登记真实对象文件与区域检查点，不发表占位结果。"""
        self.seed.science.compute.side_effect = RuntimeError('合成已保存对象后的中断')
        with self.assertRaises(RuntimeError):
            self.seed.execute()
        rid = self.w.load(self.sid)['current']['A06']
        path = self.w.location(self.sid) / 'runs/A06' / rid / 'rescue' / 'prepared_receptor.pdbqt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic prepared receptor')
        evidence = file_record(self.w.location(self.sid), path, 'prepared_receptor')
        receptor = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'receptor_HGNC_1',
            {'state': 'ready', 'quality': '探索', 'receptor': evidence}, [evidence])
        region = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_000001_region_0001',
            {'state': 'completed', 'score': -8.25, 'execution': evidence}, [evidence])
        return rid, [receptor, region], path

    def test_partial_binding_preserves_registered_objects_and_stays_identical_after_current_changes_to_v2(self):
        rid, checkpoints, _ = self.partial_first()
        body = self.body()
        before = self.w.load(self.sid)
        original_files = deepcopy(before['runs'][rid])
        bound = self.core.source_binding(self.w, before, self.prep, self.score)
        self.assertEqual(bound['partial_recovery'], {'run_id': rid, 'run_files': original_files, 'checkpoint_refs': checkpoints})
        self.science.compute.side_effect = RuntimeError('合成第二轮已建立，尚未发表')
        with self.assertRaises(RuntimeError):
            self.execute(body)
        after = self.w.load(self.sid)
        self.assertNotEqual(after['current']['A06'], rid)
        self.assertEqual(self.core.source_binding(self.w, after, self.prep, self.score), bound)
        self.assertEqual(after['runs'][rid], original_files)
        self.assertTrue(self.w.active(after, after['current']['A06']))
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'receptor_HGNC_1',
                {'state': 'ready', 'receptor': 'replaced'}, [])

    def test_partial_checkpoint_evidence_corruption_blocks_without_recomputation(self):
        _, _, path = self.partial_first()
        body = self.body()
        path.write_bytes(b'corrupt original checkpoint evidence')
        with self.assertRaises(ContractError):
            self.execute(body)
        self.science.compute.assert_not_called()

    def test_new_registered_partial_checkpoint_changes_request_hash_and_cannot_be_silently_added(self):
        rid, _, _ = self.partial_first()
        body = self.body()
        self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_000001_region_0002',
            {'state': 'completed', 'score': -7.125}, [])
        with self.assertRaises(ContractError):
            self.execute(body)
        self.science.compute.assert_not_called()

    def test_partial_source_hold_blocks_historical_binding_even_after_new_v2_pointer(self):
        rid, _, _ = self.partial_first()
        m = self.w.load(self.sid)
        run = self.w.run(m, rid)
        path = self.w.location(self.sid) / 'reviews' / (new_id('review') + '.json')
        write_json(path, {'artifact_id': run['artifact_id'], 'run_id': rid, 'review_id': new_id('review'), 'decision': 'rejected'})
        m['reviews'].append(file_record(self.w.location(self.sid), path, 'review'))
        self.w.save(m)
        with self.assertRaises(ContractError):
            self.core.source_binding(self.w, m, self.prep, self.score)

    def test_partial_checkpoint_config_tamper_with_updated_index_hash_is_rejected(self):
        _, checkpoints, _ = self.partial_first()
        m = self.w.load(self.sid)
        path = self.w.location(self.sid) / checkpoints[0]['path']
        value = read_json(path)
        value['config_hash'] = '0' * 64
        write_json(path, value, replace=True)
        replacement = file_record(self.w.location(self.sid), path, checkpoints[0]['role'])
        m[self.core.frozen.CHECKPOINTS] = [replacement if ref == checkpoints[0] else ref for ref in m[self.core.frozen.CHECKPOINTS]]
        self.w.save(m)
        with self.assertRaises(ContractError):
            self.core.source_binding(self.w, m, self.prep, self.score)

    def test_latest_matching_partial_run_is_selected_from_history_deterministically(self):
        old_id, _, _ = self.partial_first()
        newer_body = self.seed.body | {'request_id': new_id('rescue'), 'note': '明确新请求保留原第一轮尝试'}
        with self.assertRaises(RuntimeError):
            self.seed.execute(newer_body)
        m = self.w.load(self.sid)
        newest = m['current']['A06']
        self.assertNotEqual(newest, old_id)
        recovery = self.core.source_binding(self.w, m, self.prep, self.score)['partial_recovery']
        self.assertEqual(recovery['run_id'], newest)
        self.assertEqual(recovery['checkpoint_refs'], [])

    def test_successful_partial_object_cannot_be_overridden_in_a_forged_registered_chain(self):
        rid, checkpoints, _ = self.partial_first()
        m = self.w.load(self.sid)
        old = read_json(self.w.location(self.sid) / checkpoints[0]['path'])
        path = self.w.location(self.sid) / 'runs/A06' / rid / 'rescue_checkpoints/receptor_HGNC_1' / (new_id('checkpoint') + '.json')
        old.update(previous=checkpoints[0], payload={'state': 'ready', 'quality': '严格'})
        write_json(path, old)
        m[self.core.frozen.CHECKPOINTS].append(file_record(self.w.location(self.sid), path, 'receptor_rescue_checkpoint'))
        self.w.save(m)
        with self.assertRaises(ContractError):
            self.core.source_binding(self.w, m, self.prep, self.score)


if __name__ == '__main__':
    unittest.main()
