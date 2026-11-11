"""受体补救的正常A06交接、过期防护和精确恢复；只使用合成研究。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from contracts import ContractError, MODULES, fingerprint
from storage import file_record, new_id, read_json, write_json
from workflow import Workflow
from modulea.core import kernel


class SystemReceptorRescueCoreTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(kernel.DockingWorkflow, 'execute_analysis_plan_receptor_rescue', None)),
                        '受体补救尚未接入正常Workflow')
        self.temp = tempfile.TemporaryDirectory(prefix='rescue_core_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'
        validators = {module: lambda *_: None for module in MODULES}
        seed = Workflow(self.root, validators)
        self.sid = seed.create({'formula': '合成方剂', 'herbs': '合成药味', 'disease': '合成疾病',
                                'disease_scope': '仅测试', 'operator': '测试', 'species': 9606}, 'contract_test')
        m = seed.load(self.sid)
        seed.review(self.sid, m['current']['A00'], 'approved', '合成复核人', '允许测试')
        self.home = seed.location(self.sid)
        plan = {'study_id': self.sid, 'plan_id': new_id('plan'), 'expected_a00': m['current']['A00'],
                'plan': {'parameter_hash': fingerprint({'frozen': True}), 'parameters': {'synthetic': True}}}
        write_json(self.home / 'decisions/plan.json', plan)
        self.plan_ref = file_record(self.home, self.home / 'decisions/plan.json', 'analysis_plan_draft')
        fixed = {'study_id': self.sid, 'payload': {'input_key': fingerprint({'fixed': True})}}
        write_json(self.home / 'decisions/system_input.json', fixed)
        self.fixed_ref = file_record(self.home, self.home / 'decisions/system_input.json', 'system_docking_input')
        m = seed.load(self.sid)
        m['analysis_plan_records'] = [self.plan_ref]
        seed.save(m)
        inputs = {'study_id': self.sid, 'bound_a00': m['current']['A00'], 'analysis_plan_id': plan['plan_id'],
                  'analysis_plan_file': self.plan_ref, 'analysis_parameter_hash': plan['plan']['parameter_hash'],
                  'system_input_ref': self.fixed_ref}
        for module in ('A01', 'A02', 'A03', 'A03_SELECT', 'A04', 'A05', 'A06_PREP', 'A06'):
            version = {'A06_PREP': 'A06.system_qualification_paths.1', 'A06': 'A06.system_scoring_paths.1'}.get(module, 'synthetic.1')
            run = seed.begin(self.sid, module, deepcopy(inputs), {'version': version}, '合成原始运行')
            m = seed.load(self.sid)
            seed._finish(m, run['run_id'], {'scored_pairs': 1} if module == 'A06' else {},
                         {'plan_scoring_pairs': [{'compound_id': 'compound', 'target_id': 'target', 'score': -7.25}]} if module == 'A06' else {}, [], 'success')
            seed.save(m)
            if module != 'A06':
                seed.review(self.sid, run['run_id'], 'approved', '合成复核人', '保持原有批准')
        self.w = kernel.DockingWorkflow(self.root, validators)
        self.before = self.w.load(self.sid)
        self.prep_id = self.before['current']['A06_PREP']
        self.score_id = self.before['current']['A06']
        self.tools = Path(self.temp.name) / 'tools'
        self.repair = Path(self.temp.name) / 'repair'
        self.tools.mkdir()
        self.repair.mkdir()
        self.configuration = {'version': 'A06.system_rescue.1', 'policy': {'synthetic': True},
                              'source_preparation_config': self.w.run(self.before, self.prep_id)['config'],
                              'vina_sha256': fingerprint('synthetic Vina'), 'implementation_sha256': {}, 'repair_metadata': {}}
        self.science = types.ModuleType('science_modules.a06.system_receptor_rescue')
        self.science.VERSION = 'A06.system_rescue.1'
        self.science.POLICY = self.configuration['policy']
        self.science.configuration = Mock(side_effect=lambda *_, **__: deepcopy(self.configuration))
        self.science.compute = Mock(side_effect=self.compute)
        self.addCleanup(patch.stopall)
        module_name = 'science_modules.a06.system_receptor_rescue'
        missing = object()
        previous_module = sys.modules.get(module_name, missing)
        sys.modules[module_name] = self.science

        def restore_science_module():
            """只恢复本测试替换项，保留读取范围后来延迟加载的真实模块及其身份。"""
            if previous_module is missing:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module

        self.addCleanup(restore_science_module)
        patch('science_modules.a06.system_receptor_rescue', self.science, create=True).start()
        info = self.w.analysis_plan_receptor_rescue_info(self.sid)
        self.assertTrue(info['enabled'], info['blockers'])
        self.body = {'request_id': new_id('rescue'), 'expected_preparation_run_id': self.prep_id,
                     'expected_scoring_run_id': self.score_id, 'expected_input_hash': info['expected_input_hash'],
                     'author': '合成测试', 'note': '明确补救本批受体并保留原评分', 'confirmed': True}

    def compute(self, w, sid, run, **_):
        path = w.location(sid) / 'runs/A06' / run['run_id'] / ('synthetic_packet_' + new_id('attempt') + '.json')
        write_json(path, {'source_score': run['inputs']['source_scoring_result'], 'run_id': run['run_id']})
        ref = file_record(self.home, path, 'system_scoring_packet')
        return {'protocol_version': self.science.VERSION, 'scored_pairs': 1, 'pair_count': 1, 'na_pairs': 0}, {
            'scoring_packet': [ref], 'plan_scoring_pairs': [{'compound_id': 'compound', 'target_id': 'target', 'score': -7.25}],
            'receptor_preparation': [{'target_id': 'target', 'source_diagnostic': '合成原诊断'}],
            'rescue_summary': [{'preserved_scored_pairs': 1}]}, [ref], []

    def execute(self, body=None):
        return self.w.execute_analysis_plan_receptor_rescue(self.sid, body or self.body, tools=self.tools, repair_packages=self.repair)

    def pause(self, run_id):
        m = self.w.load(self.sid)
        previous = self.w.latest_review(m, self.w.run(m, run_id)['artifact_id'])
        return self.w.review(self.sid, run_id, 'pending', '合成复核人', '明确暂停',
                             expected_review=previous['review_id'] if previous else None)

    def test_new_a06_keeps_original_preparation_source_scores_reviews_and_files(self):
        original = {str(p.relative_to(self.home)): sha256(p.read_bytes()).hexdigest()
                    for p in self.home.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        result = self.execute()
        after = self.w.load(self.sid)
        run = self.w.run(after, result['run_id'])
        self.assertEqual(run['parent_runs'], {'A06_PREP': self.prep_id})
        self.assertEqual(after['current']['A06_PREP'], self.prep_id)
        self.assertEqual(after['reviews'], self.before['reviews'])
        self.assertEqual(after['runs'][self.score_id], self.before['runs'][self.score_id])
        self.assertEqual(run['inputs']['source_scoring_run'], self.before['runs'][self.score_id]['run_file'])
        self.assertEqual(run['inputs']['source_scoring_result'], self.before['runs'][self.score_id]['result_file'])
        self.assertEqual(run['inputs']['source_preparation_result'], self.before['runs'][self.prep_id]['result_file'])
        self.assertNotIn('execution_protocol', run)
        self.assertEqual(run['config'], self.configuration)
        self.assertTrue(self.w.active(after, run['run_id']))
        self.assertFalse(self.w.approved(after, run['run_id']))
        self.assertEqual(self.w.result(after, self.score_id)['tables']['plan_scoring_pairs'][0]['score'], -7.25)
        self.assertEqual(len(after['runs']), len(self.before['runs']) + 1)
        for name, digest in original.items():
            self.assertEqual(sha256((self.home / name).read_bytes()).hexdigest(), digest, name)

    def test_completed_request_is_idempotent_without_new_compute_or_reviews(self):
        first = self.execute()
        self.assertEqual(self.execute(), first)
        self.assertEqual(self.science.compute.call_count, 1)
        self.assertEqual(self.w.load(self.sid)['reviews'], self.before['reviews'])
        info = self.w.analysis_plan_receptor_rescue_info(self.sid)
        self.assertFalse(info['enabled'])
        self.assertEqual(info['state'], 'complete')

    def test_request_id_cannot_change_note_after_failure_or_success(self):
        self.execute()
        with self.assertRaises(ContractError):
            self.execute(dict(self.body, note='另一个内容'))
        self.assertEqual(self.science.compute.call_count, 1)

    def test_stale_hash_and_run_ids_do_not_create_a06(self):
        for change in ({'expected_input_hash': '0' * 64}, {'expected_preparation_run_id': new_id('run')},
                       {'expected_scoring_run_id': new_id('run')}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.execute(dict(self.body, **change))
        self.assertEqual(self.w.load(self.sid), self.before)
        self.science.compute.assert_not_called()

    def test_strict_fields_and_confirmation_are_validated_before_begin(self):
        for change in ({'confirmed': False}, {'confirmed': 1}, {'tools': 'outside'}, {'request_id': '../bad'},
                       {'expected_input_hash': None}, {'author': '  '}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.execute(dict(self.body, **change))
        self.assertEqual(self.w.load(self.sid), self.before)

    def test_manual_hold_on_source_score_or_upstream_blocks_execution(self):
        self.pause(self.score_id)
        with self.assertRaises(ContractError):
            self.execute()
        self.science.compute.assert_not_called()
        self.assertEqual(self.w.load(self.sid)['current'], self.before['current'])

    def test_original_preparation_requires_actual_approval(self):
        self.pause(self.prep_id)
        with self.assertRaises(ContractError):
            self.execute()
        self.science.compute.assert_not_called()

    def test_trashed_study_is_read_only(self):
        m = self.w.load(self.sid)
        m['trashed'] = True
        self.w.save(m)
        with self.assertRaises(ContractError):
            self.execute()
        self.science.compute.assert_not_called()

    def test_same_incomplete_request_resumes_exact_run_after_real_failure(self):
        self.science.compute.side_effect = RuntimeError('合成中断，保留原件')
        with self.assertRaises(RuntimeError):
            self.execute()
        failed = self.w.load(self.sid)
        rid = failed['current']['A06']
        self.assertIsNone(failed['runs'][rid]['result_file'])
        self.assertTrue(self.w.active(failed, rid))
        failures = list((self.home / 'decisions/A06_rescue' / self.body['request_id']).glob('failures/*.json'))
        self.assertEqual(len(failures), 1)
        self.science.compute.side_effect = self.compute
        result = self.execute()
        self.assertEqual(result['run_id'], rid)
        self.assertEqual(len(self.w.load(self.sid)['runs']), len(self.before['runs']) + 1)
        self.assertTrue(failures[0].is_file())

    def test_retry_rejects_changed_tool_configuration_or_code(self):
        self.science.compute.side_effect = RuntimeError('合成中断')
        with self.assertRaises(RuntimeError):
            self.execute()
        old_digest = self.configuration['vina_sha256']
        self.configuration['vina_sha256'] = 'changed'
        with self.assertRaises(ContractError):
            self.execute()
        self.configuration['vina_sha256'] = old_digest
        self.w.code_version = fingerprint('changed code')
        with self.assertRaises(ContractError):
            self.execute()
        self.assertEqual(self.science.compute.call_count, 1)

    def test_human_review_change_during_compute_prevents_publication_and_invalidates_run(self):
        def changed(*args, **kwargs):
            output = self.compute(*args, **kwargs)
            self.pause(self.prep_id)
            return output
        self.science.compute.side_effect = changed
        with self.assertRaises(ContractError):
            self.execute()
        after = self.w.load(self.sid)
        self.assertIsNone(after['runs'][after['current']['A06']]['result_file'])
        self.assertFalse(self.w.active(after, after['current']['A06']))

    def test_baseline_scoring_current_pointer_is_excluded_from_post_begin_binding(self):
        result = self.execute()
        after = self.w.load(self.sid)
        self.assertNotEqual(after['current']['A06'], self.score_id)
        self.assertTrue(self.w.active(after, result['run_id']))
        self.assertTrue(self.w.active(after, self.prep_id))
        self.pause(self.prep_id)
        self.assertFalse(self.w.active(self.w.load(self.sid), result['run_id']))

    def test_source_attachment_corruption_is_blocked_even_on_completed_replay(self):
        result = self.execute()
        source = self.before['runs'][self.score_id]['result_file']
        (self.home / source['path']).write_bytes(b'corrupt')
        with self.assertRaises(ContractError):
            self.execute()
        self.assertFalse(self.w.active(self.w.load(self.sid), result['run_id']))

    def test_other_versions_keep_original_active_branch(self):
        self.assertTrue(self.w.active(self.before, self.score_id))
        self.assertTrue(self.w.approved(self.before, self.prep_id))
        self.assertEqual(self.w.run(self.before, self.score_id)['config']['version'], 'A06.system_scoring_paths.1')

    def test_registered_checkpoint_reuses_original_payload_and_detects_corrupt_files(self):
        self.science.compute.side_effect = RuntimeError('合成中断')
        with self.assertRaises(RuntimeError):
            self.execute()
        rid = self.w.load(self.sid)['current']['A06']
        path = self.home / 'runs/A06' / rid / 'evidence.txt'
        path.write_text('synthetic evidence', 'utf-8')
        ref = file_record(self.home, path, 'synthetic_evidence')
        saved = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0001', {'score': -7.25}, [ref])
        self.assertIn(saved, self.w.load(self.sid)['analysis_plan_receptor_rescue_checkpoints'])
        loaded_ref, loaded = self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0001')
        self.assertEqual(saved, loaded_ref)
        self.assertEqual(loaded['payload'], {'score': -7.25})
        self.assertEqual(self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0001', {'score': -7.25}, [ref]), saved)
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0001', {'score': -9}, [ref])
        self.assertIsNone(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0002'))
        path.write_text('corrupt', 'utf-8')
        with self.assertRaises(ContractError):
            self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0001')

    def test_checkpoint_rejects_unregistered_path_unsafe_key_and_stale_source(self):
        self.science.compute.side_effect = RuntimeError('合成中断')
        with self.assertRaises(RuntimeError):
            self.execute()
        rid = self.w.load(self.sid)['current']['A06']
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, '../bad', {}, [])
        folder = self.home / 'runs/A06' / rid / 'rescue_checkpoints'
        write_json(folder / 'pair_0001.json', {'self_signed': True})
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0001', {}, [])
        self.pause(self.prep_id)
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'pair_0002', {}, [])

    def test_retryable_failed_checkpoint_adds_immutable_attempt_then_freezes_success(self):
        self.science.compute.side_effect = RuntimeError('合成中断')
        with self.assertRaises(RuntimeError):
            self.execute()
        rid = self.w.load(self.sid)['current']['A06']
        failed = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'source_HGNC_1',
            {'state': 'failed', 'retryable': True, 'reason': 'temporary failure'}, [])
        ready = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'source_HGNC_1',
            {'state': 'ready', 'retryable': False, 'value': 'actual source'}, [])
        self.assertNotEqual(failed, ready)
        self.assertEqual(read_json(self.home / ready['path'])['previous'], failed)
        self.assertTrue((self.home / failed['path']).is_file())
        self.assertEqual(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'source_HGNC_1')[0], ready)
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, rid, 'source_HGNC_1',
                {'state': 'failed', 'retryable': True}, [])

    def interrupt_publication(self):
        original = self.w._finish
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('合成中断：结果已写入，索引尚未保存')
        with patch.object(self.w, '_finish', side_effect=interrupted), self.assertRaises(RuntimeError):
            self.execute()
        return self.w.load(self.sid)['current']['A06']

    def test_interrupted_publication_keeps_partial_files_and_reuses_validated_candidate(self):
        rid = self.interrupt_publication()
        folder = self.home / 'runs/A06' / rid
        old = {path.name: sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()
               if path.is_file() and path.name != 'run.json' and not path.name.startswith('synthetic_packet_')}
        result = self.execute()
        self.assertEqual(result['run_id'], rid)
        self.assertEqual(self.science.compute.call_count, 1)
        archives = list((folder / 'publication_attempts').glob('*/archive.json'))
        self.assertEqual(len(archives), 1)
        archived = read_json(archives[0])
        self.assertEqual({Path(ref['path']).name: ref['sha256'] for ref in archived['files']}, old)
        for ref in archived['files']:
            self.assertEqual(sha256((self.home / ref['path']).read_bytes()).hexdigest(), ref['sha256'])
        self.assertEqual(self.w.load(self.sid)['reviews'], self.before['reviews'])

    def test_corrupt_partial_publication_is_an_integrity_error_and_is_not_archived(self):
        rid = self.interrupt_publication()
        folder = self.home / 'runs/A06' / rid
        table = folder / 'plan_scoring_pairs.csv'
        table.write_bytes(b'corrupt')
        with self.assertRaises(ContractError):
            self.execute()
        self.assertEqual(table.read_bytes(), b'corrupt')
        self.assertEqual(self.science.compute.call_count, 1)
        self.assertEqual(list((folder / 'publication_attempts').glob('*/archive.json')), [])

    def test_explicit_new_request_after_tool_correction_preserves_abandoned_incomplete_run(self):
        self.science.compute.side_effect = RuntimeError('合成工具故障')
        with self.assertRaises(RuntimeError):
            self.execute()
        old_manifest = self.w.load(self.sid)
        old_id = old_manifest['current']['A06']
        checkpoint = self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid, old_id, 'pair_0001',
            {'state': 'completed', 'score': -7.25}, [])
        old_record = deepcopy(self.w.load(self.sid)['runs'][old_id])
        self.configuration['vina_sha256'] = fingerprint('corrected synthetic tool')
        with self.assertRaises(ContractError):
            self.execute()
        new_body = dict(self.body, request_id=new_id('rescue'), note='明确以修正后的工具另开本批补救，不改变科学阈值')
        self.science.compute.side_effect = self.compute
        result = self.execute(new_body)
        final = self.w.load(self.sid)
        self.assertNotEqual(result['run_id'], old_id)
        self.assertEqual(final['runs'][old_id], old_record)
        self.assertIsNone(final['runs'][old_id]['result_file'])
        self.assertIn(checkpoint, final['analysis_plan_receptor_rescue_checkpoints'])
        self.assertEqual(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, old_id, 'pair_0001')[0], checkpoint)
        self.assertTrue(self.w.active(final, result['run_id']))
        self.assertFalse(self.w.active(final, old_id))
        new_run = self.w.run(final, result['run_id'])
        self.assertEqual(new_run['inputs']['source_scoring_run'], self.before['runs'][self.score_id]['run_file'])
        self.assertEqual(self.execute(new_body), result)
        with self.assertRaises(ContractError):
            self.execute()


if __name__ == '__main__':
    unittest.main()
