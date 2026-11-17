"""完整包私有下载快照：有界读写、原件SHA与句柄清理，不写研究记录。"""
from hashlib import sha256
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError
from modulea.core.bounded_evidence import file_record


class DownloadSnapshotTests(TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[2]/'src/modulea/api/download_snapshot.py'
        self.assertTrue(path.is_file(),'缺少完整包有界私有下载快照')
        self.api=importlib.import_module('modulea.api.download_snapshot')
        temp=TemporaryDirectory(prefix='下载快照 ');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.home=self.root/'studies/study_synthetic';self.home.mkdir(parents=True)
        self.source=self.home/'complete.zip';self.source.write_bytes(b'fixed archive\x00'*300)
        self.ref=file_record(self.home,self.source,'archive');self.runtime=self.root/'runtime'

    def capture(self):return self.api.capture_verified(self.home,self.ref,self.runtime,min_free_bytes=0)

    def read_all(self,value):
        blocks=[]
        while raw:=value.read(256*1024):blocks.append(raw)
        return b''.join(blocks)

    def test_snapshot_contains_exact_bytes_and_closes_without_persistent_files(self):
        before=self.source.read_bytes()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('下载不能整件read_bytes')):value=self.capture()
        try:
            self.assertEqual((value.bytes,value.sha256),(len(before),sha256(before).hexdigest()))
            self.assertEqual(self.read_all(value),before);value.rewind();self.assertEqual(value.read(5),before[:5])
        finally:value.close()
        self.assertTrue(value.closed);value.close()
        self.assertEqual(list(self.runtime.rglob('*')),[])

    def test_original_replacement_after_capture_does_not_change_download_bytes(self):
        before=self.source.read_bytes();value=self.capture()
        try:
            self.source.write_bytes(b'x'*len(before))
            self.assertEqual(self.read_all(value),before)
        finally:value.close()

    def test_corrupt_same_length_and_mtime_original_cannot_create_snapshot(self):
        raw=self.source.read_bytes();stamp=self.source.stat()
        self.source.write_bytes(bytes([raw[0]^1])+raw[1:]);os.utime(self.source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with self.assertRaises(ContractError):self.capture()
        self.assertFalse(self.runtime.exists() and list(self.runtime.rglob('*')))

    def test_path_escape_and_low_disk_are_rejected_before_copy(self):
        self.ref=dict(self.ref,path='../outside.zip')
        with self.assertRaises(ContractError):self.capture()
        self.ref=file_record(self.home,self.source,'archive')
        with patch.object(self.api.shutil,'disk_usage',return_value=SimpleNamespace(free=0)),self.assertRaises(ContractError):self.capture()
        self.assertFalse(self.runtime.exists() and list(self.runtime.rglob('*')))

    def test_copy_failure_closes_temporary_handle(self):
        with patch.object(self.api,'_copy_verified',side_effect=OSError('合成磁盘写失败')),self.assertRaises(OSError):self.capture()
        self.assertFalse(list(self.runtime.rglob('*')))

    def test_unbounded_snapshot_read_is_rejected(self):
        value=self.capture()
        try:
            with self.assertRaises(ContractError):value.read(-1)
        finally:value.close()
