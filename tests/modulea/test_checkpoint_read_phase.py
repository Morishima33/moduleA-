"""只合并原检查点写前纯读取；原锁、首次写前复验、幂等及异常保持。"""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError
import storage
from modulea.core import read_evidence
from modulea.core.scoped_worker_io import ScopedWorkerIO
from tests.modulea import test_scoped_worker_io as fixture


class CheckpointReadPhaseTests(TestCase):
    def setUp(self):
        self.seed = fixture.ScopedRegionRecoveryTests('test_interruption_reuses_registered_success_and_completes_only_missing_region')
        self.seed.setUp(); self.addCleanup(self.seed.doCleanups)
        self.w, self.io, self.sid, self.rid = self.seed.w, self.seed.io, self.seed.sid, self.seed.rid

    def append(self, key='pair_000003_region_0001'):
        return self.w.append_analysis_plan_receptor_rescue_v2_checkpoint(self.sid, self.rid, key,
                   {'state': 'failed', 'retryable': False, 'reason_zh': '明确合成测试失败'}, [])

    def test_original_lock_is_held_and_scope_finishes_before_every_write(self):
        from modulea.core.scoped_worker_io import SourceEvidence
        events = []
        finishes = []
        finish = SourceEvidence.finish
        def finished(evidence):
            finishes.append(True)
            return finish(evidence)
        original = storage.write_json
        def checked(path, data, **kwargs):
            self.assertIsNone(read_evidence.current_evidence(self.w.root))
            with self.assertRaises(ContractError):
                with storage.write_lock(self.w.root): pass
            events.append(Path(path).name)
            return original(path, data, **kwargs)
        value = self.io.value
        # 仅本实例私有函数副本使用观测writer，不改原模块全局函数。
        with patch.object(self.io, 'value', side_effect=lambda item: checked if item is original else value(item)), \
             patch.object(SourceEvidence, 'finish', finished):
            self.io.functions.clear(); self.io.namespaces.clear(); self.io.modules.clear(); self.io.scope_wrappers.clear()
            ref = self.append()
        self.assertEqual(len(events), 2)
        self.assertEqual(len(finishes), 1, '同次检查点写前纯读取应只做一次统一退出复验')
        self.assertEqual(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid, self.rid,
                         'pair_000003_region_0001')[0], ref)
        checks = self.io.stats['checkpoint_read_phases']
        self.assertEqual(self.append(), ref)
        self.assertEqual(self.io.stats['checkpoint_read_phases'], checks+1)

    def test_source_mutation_after_validation_blocks_before_first_write(self):
        from modulea.core import scoped_worker_io as scoped
        original = scoped.SourceEvidence.finish
        before = self.w.load(self.sid)
        path = self.w.location(self.sid)/self.seed.run['inputs']['rescue_request']['path']
        raw = path.read_bytes(); seen = []
        def corrupt(evidence):
            if not seen:
                seen.append(True); path.write_bytes(b' ' * len(raw))
            return original(evidence)
        try:
            with patch.object(scoped.SourceEvidence, 'finish', corrupt), self.assertRaises(ContractError):
                self.append()
        finally:
            path.write_bytes(raw)
        self.assertEqual(self.w.load(self.sid), before)
        self.assertFalse((self.w.location(self.sid)/f'runs/A06/{self.rid}/rescue_checkpoints/pair_000003_region_0001').exists())
        self.assertIsNone(read_evidence.current_evidence(self.w.root))

    def test_write_failure_releases_scope_and_lock_without_manifest_registration(self):
        before = self.w.load(self.sid)
        def fail(*args, **kwargs):
            self.assertIsNone(read_evidence.current_evidence(self.w.root))
            raise OSError('明确合成磁盘错误')
        original, value = storage.write_json, self.io.value
        with patch.object(self.io, 'value', side_effect=lambda item: fail if item is original else value(item)):
            self.io.functions.clear(); self.io.namespaces.clear(); self.io.modules.clear(); self.io.scope_wrappers.clear()
            with self.assertRaises(OSError): self.append()
        self.assertEqual(self.w.load(self.sid), before)
        self.assertIsNone(read_evidence.current_evidence(self.w.root))
        with storage.write_lock(self.w.root): pass

    def old_checkpoint_mutation(self, target, *, idempotent=False):
        from modulea.core.scoped_worker_io import SourceEvidence
        home = self.w.location(self.sid); key = 'pair_000003_region_0001'
        evidence = home/'old_checkpoint_evidence.dat'; evidence.write_bytes(b'old verified evidence')
        record = storage.file_record(home, evidence, 'checkpoint_evidence')
        payload = {'state': 'failed', 'retryable': True, 'reason_zh': '明确合成可重试失败'}
        ref = self.w.append_analysis_plan_receptor_rescue_v2_checkpoint(self.sid, self.rid, key, payload, [record])
        before = self.w.load(self.sid)
        path = home/ref['path'] if target == 'checkpoint' else evidence
        raw = path.read_bytes(); finish = SourceEvidence.finish
        def corrupt(proof):
            path.write_bytes(b' ' * len(raw))
            return finish(proof)
        try:
            with patch.object(SourceEvidence, 'finish', corrupt), self.assertRaises(ContractError):
                if idempotent:
                    self.w.append_analysis_plan_receptor_rescue_v2_checkpoint(self.sid, self.rid, key, payload, [record])
                else:
                    self.append(key)
        finally:
            path.write_bytes(raw)
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(len(list((home/ref['path']).parent.glob('*.json'))), 1)
        self.assertIsNone(read_evidence.current_evidence(self.w.root))

    def test_previous_checkpoint_mutation_at_exit_cannot_register_a_broken_chain(self):
        self.old_checkpoint_mutation('checkpoint')

    def test_previous_checkpoint_attachment_mutation_at_exit_cannot_register_a_broken_chain(self):
        self.old_checkpoint_mutation('attachment')

    def test_idempotent_return_cannot_return_previous_checkpoint_changed_at_exit(self):
        self.old_checkpoint_mutation('checkpoint', idempotent=True)
