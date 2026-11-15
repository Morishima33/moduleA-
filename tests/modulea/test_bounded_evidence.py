"""验证有界缓存、完整流式SHA、退出重核和冻结字节保持。"""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from contracts import ContractError
import storage
from modulea.core.bounded_evidence import bounded_scope, file_record, verified_file


class BoundedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='bounded_evidence_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sid = 'study_' + 'e' * 32
        self.home = self.root / 'studies' / self.sid
        self.home.mkdir(parents=True)
        (self.home/'manifest.json').write_text('{"revision":1}')

    def document(self, name, size=4096):
        path = self.home / (name + '.json')
        path.write_text(json.dumps({'data': 'x' * size, 'nested': [1, 2]}))
        return path, storage.file_record(self.home, path, 'test')

    def test_content_cache_stays_within_budget_and_closes_without_gc(self):
        refs = [self.document(str(i))[1] for i in range(96)]
        with bounded_scope(self.root, self.sid, cache_bytes=16384) as evidence:
            for ref in refs:
                self.assertEqual(len(evidence.reader.read(self.home, ref)['data']), 4096)
                self.assertLessEqual(evidence.cache_size, 16384)
            self.assertEqual(len(evidence.json_bytes), 0)
            self.assertEqual(len(evidence.parsed), 0)
            self.assertEqual(len(evidence.proofs), 96)
        self.assertEqual(evidence.cache_size, 0)
        self.assertFalse(evidence.proofs)
        self.assertFalse(evidence.functions)

    def test_large_binary_verification_and_record_do_not_call_read_bytes(self):
        p = self.home/'large.bin'
        with p.open('wb') as stream:
            for _ in range(32):stream.write(b'x' * 1024 * 1024)
        old = storage.file_record(self.home, p, 'large')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('必须分块')):
            self.assertEqual(file_record(self.home, p, 'large'), old)
            self.assertEqual(verified_file(self.home, old), p.resolve())

    def test_mutated_same_size_restored_mtime_still_fails_at_exit(self):
        path, ref = self.document('same')
        with self.assertRaises(ContractError):
            with bounded_scope(self.root, self.sid) as evidence:
                evidence.reader.read(self.home, ref)
                stamp = path.stat()
                path.write_bytes(path.read_bytes().replace(b'xx', b'zz', 1))
                os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def test_parse_cannot_use_changed_bytes_and_return_values_are_isolated(self):
        path, ref = self.document('isolated')
        with bounded_scope(self.root, self.sid) as evidence:
            first = evidence.reader.read(self.home, ref)
            first['nested'].append(9)
            self.assertEqual(evidence.reader.read(self.home, ref)['nested'], [1, 2])
        with self.assertRaises(ContractError):
            with bounded_scope(self.root, self.sid, cache_bytes=0) as evidence:
                evidence.reader.verify(self.home, ref)
                path.write_bytes(b'corrupted')
                evidence.reader.read(self.home, ref)

    def test_manifest_change_and_outside_path_are_blocked(self):
        with self.assertRaises(ContractError):
            with bounded_scope(self.root, self.sid):
                (self.home/'manifest.json').write_text('{"revision":2}')
        with self.assertRaises(ContractError):
            verified_file(self.home, {'path': '../outside', 'bytes': 0, 'sha256': '0'*64})


if __name__ == '__main__':unittest.main()
