"""只在纯读取范围复用完整SHA，退出复验与有界绑定缓存；全部为隔离合成数据。"""
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError
import storage


class ScopedEvidenceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='scoped_worker_'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.sid = 'study_'+'d'*32
        self.home = self.root/'studies'/self.sid; self.home.mkdir(parents=True)
        (self.home/'manifest.json').write_text('{"revision":1}', encoding='utf-8')
        self.path = self.home/'input.json'; self.path.write_text('{"items":[1,2]}', encoding='utf-8')
        self.ref = storage.file_record(self.home, self.path, 'test')

    def model(self):
        path = Path(__file__).resolve().parents[2]/'src/modulea/core/scoped_worker_io.py'
        self.assertTrue(path.is_file(), '尚未实现明确二版纯读取范围')
        return importlib.import_module('modulea.core.scoped_worker_io')

    def test_duplicate_references_reuse_only_inside_scope_and_exit_rehashes(self):
        model = self.model()
        original = storage.verified_file
        with model.source_scope(self.root, self.sid) as evidence:
            for _ in range(24): self.assertEqual(model.scoped_verified_file(self.home, self.ref), self.path.resolve())
            self.assertEqual(evidence.stats['first_sha_checks'], 1)
            self.assertEqual(evidence.stats['duplicate_references'], 23)
        self.assertEqual(evidence.stats['exit_sha_checks'], 1)
        self.assertFalse(evidence.proofs); self.assertIs(storage.verified_file, original)
        with patch.object(model.bounded, 'verified_file', wraps=model.bounded.verified_file) as full:
            for _ in range(3): model.scoped_verified_file(self.home, self.ref)
        self.assertEqual(full.call_count, 3)

    def test_same_size_mutation_with_restored_mtime_is_rejected_at_scope_exit(self):
        model = self.model()
        with self.assertRaises(ContractError):
            with model.source_scope(self.root, self.sid):
                model.scoped_verified_file(self.home, self.ref)
                stamp = self.path.stat(); self.path.write_bytes(self.path.read_bytes().replace(b'1,2', b'9,2'))
                os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def test_json_and_binding_cache_are_bounded_isolated_and_released(self):
        model = self.model()
        with model.source_scope(self.root, self.sid, binding_bytes=256) as evidence:
            model.scoped_verified_file(self.home, self.ref)
            first = model.scoped_read_json(self.path); first['items'].append(9)
            self.assertEqual(model.scoped_read_json(self.path)['items'], [1, 2])
            for index in range(30):
                evidence.store_binding(('synthetic', index), {'data': 'x'*70})
                self.assertLessEqual(evidence.binding_size, 256)
            value = evidence.get_binding(('synthetic', 29)); value['data'] = 'poison'
            self.assertNotEqual(evidence.get_binding(('synthetic', 29))['data'], 'poison')
        self.assertFalse(evidence.binding_cache); self.assertEqual(evidence.binding_size, 0)
        self.assertEqual(evidence.cache_size, 0)

    def test_manifest_change_is_rejected_and_exception_clears_cache(self):
        model = self.model()
        with self.assertRaises(ContractError):
            with model.source_scope(self.root, self.sid) as evidence:
                model.scoped_verified_file(self.home, self.ref)
                evidence.store_binding(('test',), {'x': 1})
                (self.home/'manifest.json').write_text('{"revision":2}', encoding='utf-8')
        self.assertFalse(evidence.binding_cache); self.assertFalse(evidence.proofs)

    def test_copied_context_in_other_thread_cannot_reuse_original_proof(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        model = self.model(); original = self.path.read_bytes()
        with model.source_scope(self.root, self.sid) as evidence:
            model.scoped_verified_file(self.home, self.ref)
            context = copy_context(); self.path.write_bytes(b'wrong')
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(context.run, model.scoped_verified_file, self.home, self.ref)
                    with self.assertRaises(ContractError): future.result()
            finally:
                self.path.write_bytes(original)
            self.assertEqual(evidence.stats['first_sha_checks'], 1)

    def test_large_document_does_not_evict_small_json_cache_and_budget_stays_bounded(self):
        import json
        model = self.model()
        with model.source_scope(self.root, self.sid, cache_bytes=16384, document_bytes=8000) as evidence:
            for index in range(20):
                path = self.home/(str(index)+'.json'); path.write_text(json.dumps({'data': 'x'*4000}))
                model.scoped_read_json(path)
                self.assertLessEqual(evidence.cache_size, 16384)
            old_size = evidence.cache_size
            large = self.home/'large.json'; large.write_text(json.dumps({'data': 'y'*12000}))
            self.assertEqual(len(model.scoped_read_json(large)['data']), 12000)
            self.assertEqual(evidence.cache_size, old_size)
            self.assertEqual(evidence.stats['large_json_parses'], 1)
        self.assertEqual(evidence.cache_size, 0)


class ScopedWorkerBindingTests(TestCase):
    def setUp(self):
        from tests.modulea.test_system_receptor_rescue_v2_core import ReceptorRescueV2CoreTests
        from modulea.core.scoped_worker_io import ScopedWorkerIO
        self.seed = ReceptorRescueV2CoreTests('test_original_paths_baseline_publishes_normal_v2_without_changing_preparation_or_reviews')
        self.seed.setUp(); self.addCleanup(self.seed.doCleanups)
        self.io = ScopedWorkerIO(); self.addCleanup(self.io.close)
        self.w = self.io.wrap(self.seed.w); self.sid = self.seed.sid

    def test_real_synthetic_source_binding_matches_original_and_scope_returns_independent_values(self):
        from modulea.core import scoped_worker_io as model
        m = self.w.load(self.sid)
        expected = self.seed.core.source_binding(self.seed.w, m, self.seed.prep, self.seed.score)
        bound = self.io.bind(self.seed.core.source_binding)
        before = self.seed.core.source_binding.__globals__['verified_file']
        with model.source_scope(self.w.root, self.sid) as evidence:
            first = bound(self.w, m, self.seed.prep, self.seed.score)
            stores = evidence.stats['source_binding_stores']
            first['poison'] = True
            second = bound(self.w, m, self.seed.prep, self.seed.score)
            self.assertEqual(second, expected); self.assertNotIn('poison', second)
            self.assertGreater(evidence.stats['source_binding_hits'], 0)
            self.assertEqual(evidence.stats['source_binding_stores'], stores)
            changed = dict(m, synthetic_extra='new binding key')
            self.assertEqual(bound(self.w, changed, self.seed.prep, self.seed.score), expected)
            self.assertGreater(evidence.stats['source_binding_stores'], stores)
        self.assertIs(self.seed.core.source_binding.__globals__['verified_file'], before)

    def test_separate_calls_do_not_reuse_previous_scope_sha(self):
        fn = self.io.bind(self.seed.core.source_binding); m = self.w.load(self.sid)
        first = fn(self.w, m, self.seed.prep, self.seed.score)
        checks = self.io.stats['scope_first_sha_checks']
        self.assertGreater(checks, 0)
        self.assertEqual(fn(self.w, m, self.seed.prep, self.seed.score), first)
        self.assertGreater(self.io.stats['scope_first_sha_checks'], checks)
        self.assertTrue(all(row['first_sha_checks'] == row['exit_sha_checks'] for row in self.io.last_scopes))

    def test_nested_read_adapter_uses_the_same_bounded_binding_memo(self):
        from modulea.core import scoped_worker_io as model
        m = self.w.load(self.sid)
        with model.source_scope(self.w.root, self.sid) as evidence:
            first = evidence.call(self.seed.core.source_binding, self.w, m, self.seed.prep, self.seed.score)
            stores = evidence.stats['source_binding_stores']
            second = evidence.call(self.seed.core.source_binding, self.w, m, self.seed.prep, self.seed.score)
            self.assertEqual(first, second)
            self.assertGreater(evidence.stats['source_binding_hits'], 0)
            self.assertEqual(evidence.stats['source_binding_stores'], stores)

    def test_different_workflow_instances_cannot_share_binding_memo(self):
        from modulea.core import scoped_worker_io as model
        m = self.w.load(self.sid); fn = self.io.bind(self.seed.core.source_binding)
        other = self.io.wrap(self.seed.w)
        with model.source_scope(self.w.root, self.sid) as evidence:
            first = fn(self.w, m, self.seed.prep, self.seed.score)
            stores = evidence.stats['source_binding_stores']
            self.assertEqual(fn(other, m, self.seed.prep, self.seed.score), first)
            self.assertGreater(evidence.stats['source_binding_stores'], stores)

    def test_binding_identity_tokens_do_not_keep_discarded_workflow_alive(self):
        import gc, weakref
        from modulea.core import scoped_worker_io as model
        other = self.io.wrap(self.seed.w); reference = weakref.ref(other)
        with model.source_scope(self.w.root, self.sid) as evidence:
            token = evidence.workflow_key(other)
            self.io.bind(self.seed.core.source_binding)(other, self.w.load(self.sid), self.seed.prep, self.seed.score)
            del other; gc.collect()
            self.assertIsNone(reference())
            replacement = self.io.wrap(self.seed.w)
            self.assertNotEqual(evidence.workflow_key(replacement), token)

    def test_actual_review_change_is_not_hidden_by_same_scope_binding_memo(self):
        from modulea.core import scoped_worker_io as model
        fn = self.io.bind(self.seed.core.source_binding); m = self.w.load(self.sid)
        prep = self.w.run(m, self.seed.prep)
        review = self.w.latest_review(m, prep['artifact_id'])
        with self.assertRaises(ContractError):
            with model.source_scope(self.w.root, self.sid):
                fn(self.w, m, self.seed.prep, self.seed.score)
                self.seed.w.review(self.sid, self.seed.prep, 'pending', '明确合成复核', '撤回测试准备', review['review_id'])
                fn(self.w, self.w.load(self.sid), self.seed.prep, self.seed.score)

    def test_unregistered_v2_cannot_start_scientific_execution_or_create_run(self):
        before = self.w.load(self.sid); body = self.seed.body()
        error = None
        with patch.object(self.seed.science, 'compute', side_effect=AssertionError('未登记不能执行')) as compute:
            try:
                self.w.execute_analysis_plan_receptor_rescue_v2(self.sid, body,
                    tools=self.seed.seed.tools, repair_packages=self.seed.seed.repair)
            except Exception as caught:
                error = caught
        self.assertIsInstance(error, ContractError)
        compute.assert_not_called()
        self.assertEqual(self.w.load(self.sid), before)

    def test_registration_requires_complete_v2_snapshot_and_exact_scientific_run(self):
        from modulea.core import scoped_worker_io as model
        from copy import deepcopy
        import storage
        body = self.seed.body()
        self.seed.science.compute.side_effect = RuntimeError('合成中断，仅留原运行')
        with self.assertRaises(RuntimeError): self.seed.execute(body)
        before = self.w.load(self.sid); rid = before['current']['A06']
        ref = self.w.register_worker_io(self.sid, rid, body)
        self.io.activate_registration(self.w, self.sid, ref)
        after = self.w.load(self.sid)
        self.assertEqual(after['runs'], before['runs']); self.assertEqual(after['reviews'], before['reviews'])
        home = self.w.location(self.sid); value = storage.read_json(home/ref['path'])
        self.assertEqual(set(value['implementation_sha256']), set(model.IMPLEMENTATIONS))
        self.assertEqual(self.w.register_worker_io(self.sid, rid, body), ref)
        changes = [dict(schema_version='ModuleA.science_worker_io.1'), dict(run_id='other_run'),
                   dict(scientific_config_hash='wrong'), dict(human_review_written=True),
                   dict(request={}), dict(implementation_sha256={}), dict(files=[]),
                   dict(files=value['files']+[value['files'][0]])]
        for change in changes:
            with self.subTest(change=tuple(change)):
                altered = dict(deepcopy(value), **change)
                path = home/ref['path']; storage.write_json(path, altered, replace=True)
                wrong = storage.file_record(home, path, ref['role'])
                manifest = self.w.load(self.sid); manifest['worker_io_adaptations'][-1] = wrong; self.w.save(manifest)
                self.io.adapter_binding = None
                with self.assertRaises(ContractError): self.io.activate_registration(self.w, self.sid, wrong)
                self.assertIsNone(self.io.adapter_binding)
        storage.write_json(home/ref['path'], value, replace=True)
        manifest = self.w.load(self.sid); manifest['worker_io_adaptations'][-1] = ref; self.w.save(manifest)
        self.io.activate_registration(self.w, self.sid, ref)
        (home/value['files'][0]['path']).write_bytes(b'changed implementation snapshot')
        with self.assertRaises(ContractError): self.io.guard(self.w, self.sid)


from tests.modulea import test_worker_io_regions as regions


class ScopedRegionRecoveryTests(regions.WorkerRegionRecoveryTests):
    """相同实际区域校验合同，用新明确登记验证只补缺区及稳定失败不重算。"""
    def setUp(self):
        from modulea.core.scoped_worker_io import ScopedWorkerIO
        with patch.object(regions, 'WorkerIO', ScopedWorkerIO):
            super().setUp()
        request = storage.read_json(self.home/self.run['inputs']['rescue_request']['path'])
        reference = self.w.register_worker_io(self.sid, self.rid, request['request'])
        self.io.activate_registration(self.w, self.sid, reference)
