"""三类准备事实仅在同次证据范围复用；使用真实临时原件和退出SHA检查。"""
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FunctionType, SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import file_record, read_json, verified_file
from modulea.core import system_preparation_checkpoints as checkpoints
from modulea.core.read_evidence import read_evidence_scope


def _read_fact(workflow, manifest, reference):
    """合成只读函数保留实际原件核验，计数只用于观察是否重复执行。"""
    calls.append(reference['path'])
    home = workflow.root / 'studies' / manifest['study_id']
    value = read_json(verified_file(home, reference))
    return {'rows': value['rows'], 'revision': manifest['revision']}


class RescueReadRecordsTests(unittest.TestCase):
    def setUp(self):
        """只建立本次测试的研究外观，任何原始研究目录均不参与。"""
        temporary = TemporaryDirectory(prefix='rescue_read_records_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sid = 'study_' + 'e' * 32
        self.home = self.root / 'studies' / self.sid
        self.home.mkdir(parents=True)
        (self.home / 'manifest.json').write_text('{"current":1}', encoding='utf-8')
        self.path = self.home / 'fact.json'
        self.raw = b'{"rows":[{"value":1,"nested":[2,3]}]}'
        self.path.write_bytes(self.raw)
        self.reference = file_record(self.home, self.path, 'preparation_fact')
        self.manifest = {'study_id': self.sid, 'revision': 1}
        self.workflow = SimpleNamespace(root=self.root)

    def scope(self):
        """调用生产证据范围，保留开始和退出完整SHA复验。"""
        return read_evidence_scope(self.root, self.sid)

    def synthetic(self, name, *, module=None):
        """仅替换被白名单发现的测试函数；生产绑定、散列和序列化均实际执行。"""
        calls = []
        namespace = {'__name__': module or checkpoints.__name__, 'calls': calls,
                     'read_json': read_json, 'verified_file': verified_file}
        return FunctionType(_read_fact.__code__, namespace, name), calls

    def test_each_of_the_three_read_facts_runs_once_and_keeps_full_exit_sha(self):
        for name in ('read_session', 'read_object', 'read_packet'):
            with self.subTest(function=name):
                function, calls = self.synthetic(name)
                with patch.object(checkpoints, name, function), self.scope() as evidence:
                    bound = evidence.bind(function)
                    first = bound(self.workflow, self.manifest, self.reference)
                    second = bound(self.workflow, deepcopy(self.manifest), deepcopy(self.reference))
                    self.assertEqual(first, {'rows': [{'value': 1, 'nested': [2, 3]}], 'revision': 1})
                    self.assertEqual(second, first)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(evidence.stats['first_sha_checks'], 1)
                self.assertEqual(evidence.stats['exit_sha_checks'], 1)
                self.assertEqual(evidence.stats['exit_bytes_hashed'], len(self.raw))

    def test_changed_manifest_content_reexecutes_even_when_same_object_is_used(self):
        function, calls = self.synthetic('read_object')
        with patch.object(checkpoints, 'read_object', function), self.scope() as evidence:
            bound = evidence.bind(function)
            self.assertEqual(bound(self.workflow, self.manifest, self.reference)['revision'], 1)
            self.manifest['revision'] = 2
            self.assertEqual(bound(self.workflow, self.manifest, self.reference)['revision'], 2)
            self.assertEqual(len(calls), 2)

    def test_different_reference_and_workflow_reexecute_original_function(self):
        other_path = self.home / 'other.json'
        other_path.write_bytes(self.raw)
        other = file_record(self.home, other_path, 'preparation_fact')
        function, calls = self.synthetic('read_session')
        with patch.object(checkpoints, 'read_session', function), self.scope() as evidence:
            bound = evidence.bind(function)
            bound(self.workflow, self.manifest, self.reference)
            bound(self.workflow, self.manifest, other)
            bound(SimpleNamespace(root=self.root), self.manifest, self.reference)
            self.assertEqual(len(calls), 3)
            self.assertEqual(evidence.stats['first_sha_checks'], 2)

    def test_returned_nested_containers_cannot_poison_any_of_the_three_cached_facts(self):
        for name in ('read_session', 'read_object', 'read_packet'):
            with self.subTest(function=name):
                function, calls = self.synthetic(name)
                with patch.object(checkpoints, name, function), self.scope() as evidence:
                    bound = evidence.bind(function)
                    first = bound(self.workflow, self.manifest, self.reference)
                    first['rows'][0]['value'] = 999
                    first['rows'][0]['nested'].append(999)
                    first['rows'].append({'value': 'caller mutation'})
                    actual = bound(self.workflow, self.manifest, self.reference)
                    self.assertEqual(actual, {'rows': [{'value': 1, 'nested': [2, 3]}], 'revision': 1})
                    self.assertIsNot(actual, first)
                    self.assertEqual(len(calls), 1)

    def test_same_size_file_change_with_restored_mtime_blocks_scope_exit(self):
        function, calls = self.synthetic('read_object')
        stamp = self.path.stat()
        changed = self.raw.replace(b'"value":1', b'"value":9')
        self.assertEqual(len(changed), len(self.raw))
        with patch.object(checkpoints, 'read_object', function), self.assertRaises(ContractError):
            with self.scope() as evidence:
                bound = evidence.bind(function)
                bound(self.workflow, self.manifest, self.reference)
                self.path.write_bytes(changed)
                os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                self.assertEqual(self.path.stat().st_mtime_ns, stamp.st_mtime_ns)
                self.assertEqual(bound(self.workflow, self.manifest, self.reference)['rows'][0]['value'], 1)
                self.assertEqual(len(calls), 1)

    def test_next_independent_scope_revalidates_and_does_not_reuse_old_fact(self):
        function, calls = self.synthetic('read_packet')
        with patch.object(checkpoints, 'read_packet', function):
            for _ in range(2):
                with self.scope() as evidence:
                    evidence.bind(function)(self.workflow, self.manifest, self.reference)
                    self.assertEqual(evidence.stats['first_sha_checks'], 1)
                self.assertEqual(evidence.stats['exit_sha_checks'], 1)
            self.assertEqual(len(calls), 2)
            self.path.write_bytes(self.raw.replace(b'"value":1', b'"value":9'))
            with self.assertRaises(ContractError):
                with self.scope() as fresh:
                    fresh.bind(function)(self.workflow, self.manifest, self.reference)
            self.assertEqual(len(calls), 3)

    def test_bound_function_after_scope_exit_falls_back_to_uncached_original_checks(self):
        function, calls = self.synthetic('read_session')
        with patch.object(checkpoints, 'read_session', function):
            with self.scope() as evidence:
                bound = evidence.bind(function)
                bound(self.workflow, self.manifest, self.reference)
            bound(self.workflow, self.manifest, self.reference)
            bound(self.workflow, self.manifest, self.reference)
            self.assertEqual(len(calls), 3)
            self.path.write_bytes(b'corrupt')
            with self.assertRaises(ContractError):
                bound(self.workflow, self.manifest, self.reference)

    def test_other_read_function_and_write_function_are_never_memoized(self):
        for name in ('files', 'append'):
            with self.subTest(function=name):
                function, calls = self.synthetic(name)
                with patch.object(checkpoints, name, function), self.scope() as evidence:
                    bound = evidence.bind(function)
                    bound(self.workflow, self.manifest, self.reference)
                    bound(self.workflow, self.manifest, self.reference)
                    self.assertEqual(len(calls), 2)
                    if name == 'append':
                        self.assertIs(bound, function)
                    self.assertIs(function.__globals__['verified_file'], verified_file)

    def test_same_function_name_from_another_module_is_not_memoized(self):
        function, calls = self.synthetic('read_object', module='synthetic_other_module')
        with patch.object(checkpoints, 'read_object', function), self.scope() as evidence:
            bound = evidence.bind(function)
            bound(self.workflow, self.manifest, self.reference)
            bound(self.workflow, self.manifest, self.reference)
            self.assertEqual(len(calls), 2)

    def test_failed_original_checks_are_repeated_instead_of_cached_as_results(self):
        function, calls = self.synthetic('read_object')
        invalid = dict(self.reference, sha256='0' * 64)
        with patch.object(checkpoints, 'read_object', function), self.scope() as evidence:
            bound = evidence.bind(function)
            for _ in range(2):
                with self.assertRaises(ContractError):
                    bound(self.workflow, self.manifest, invalid)
            self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
