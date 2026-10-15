"""虚构文件验证只读提速仍拒绝篡改、缺失、跨目录，并隔离并发读取。"""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from contracts import ContractError
from modulea.config import Settings
from modulea.core.kernel import Kernel
from modulea.core.read_archive import ReadArchive, SnapshotFlight
from modulea.devtools.demo_data import build
from storage import file_record


class ReadArchiveTests(unittest.TestCase):
    """核验原始字节和路径边界，不使用任何真实研究。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "study"
        self.root.mkdir()
        self.path = self.root / "sample.txt"
        self.path.write_bytes(b"original")
        self.record = file_record(self.root, self.path, "test")

    def test_tamper_after_first_read_is_rejected_even_with_restored_mtime(self):
        reader = ReadArchive()
        reader.verify(self.root, self.record)
        info = self.path.stat()
        self.path.write_bytes(b"modified")
        os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaises(ContractError):
            reader.verify(self.root, self.record)
        with self.assertRaises(ContractError):
            ReadArchive().verify(self.root, self.record)

    def test_missing_and_invalid_fingerprint_are_rejected(self):
        with self.assertRaises(ContractError):
            ReadArchive().verify(self.root, dict(self.record, sha256="0" * 64))
        self.path.unlink()
        with self.assertRaises(ContractError):
            ReadArchive().verify(self.root, self.record)

    def test_parallel_batch_rejects_any_bad_attachment(self):
        records = []
        for index in range(70):
            path = self.root / f"part-{index}.txt"
            path.write_bytes(b"archive")
            records.append(file_record(self.root, path, "test"))
        ReadArchive().verify_all(self.root, records)
        (self.root / records[35]["path"]).write_bytes(b"tampered")
        with self.assertRaises(ContractError):
            ReadArchive().verify_all(self.root, records)

    def test_path_traversal_and_absolute_external_path_are_rejected(self):
        outside = self.root.parent / "outside.txt"
        outside.write_bytes(b"original")
        for path in ("../outside.txt", str(outside)):
            with self.assertRaises(ContractError):
                ReadArchive().verify(self.root, dict(self.record, path=path))

    def test_file_and_directory_symlinks_cannot_escape(self):
        outside = self.root.parent / "external"
        outside.mkdir()
        (outside / "sample.txt").write_bytes(b"original")
        try:
            (self.root / "file-link.txt").symlink_to(outside / "sample.txt")
            (self.root / "dir-link").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest("当前Windows账户不能创建符号链接：" + str(error))
        for path in ("file-link.txt", "dir-link/sample.txt"):
            with self.assertRaises(ContractError):
                ReadArchive().verify(self.root, dict(self.record, path=path))

    def test_next_view_rechecks_tampered_artifact_and_write_path_is_original(self):
        data = self.root / "data"
        sid = build(data)
        kernel = Kernel(Settings(data_root=data))
        display = kernel.display_workflow()
        expected = kernel.workflow().view(sid)
        expected["manifest"]["trashed"] = False
        self.assertEqual(display.view(sid), expected)
        manifest = display.load(sid)
        rid = manifest["current"]["A07"]
        record = manifest["runs"][rid]["result_file"]
        target = data / "studies" / sid / record["path"]
        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaises(ContractError):
            display.view(sid)
        self.assertFalse(hasattr(kernel.workflow(), "_read_archive"))


class SnapshotFlightTests(unittest.TestCase):
    """并发只合并正在读取的同一版本，结束、失败或新版本都重新读取。"""

    def test_concurrent_read_is_shared_but_results_are_independent(self):
        flight = SnapshotFlight()
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def read():
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(10))
            return {"rows": [1]}

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(flight.run, "version1", read)
            self.assertTrue(entered.wait(10))
            second_entered = threading.Event()

            def second_read():
                second_entered.set()
                return flight.run("version1", read)

            second = pool.submit(second_read)
            self.assertTrue(second_entered.wait(10))
            # 等待第二个线程确实进入Future等待，避免以固定睡眠猜测调度顺序。
            future = flight._pending["version1"]
            with future._condition:
                future._condition.wait_for(lambda: len(future._condition._waiters) >= 1, timeout=.1)
            release.set()
            a, b = first.result(), second.result()
        self.assertEqual(len(calls), 1)
        a["rows"].append(2)
        self.assertEqual(b, {"rows": [1]})
        self.assertEqual(flight.run("version1", lambda: {"fresh": True}), {"fresh": True})
        self.assertEqual(flight._pending, {})

    def test_version_change_and_failed_read_do_not_reuse_old_snapshot(self):
        flight = SnapshotFlight()
        self.assertEqual(flight.run("old", lambda: 1), 1)
        self.assertEqual(flight.run("new", lambda: 2), 2)
        with self.assertRaises(ValueError):
            flight.run("new", lambda: (_ for _ in ()).throw(ValueError("bad archive")))
        self.assertEqual(flight.run("new", lambda: 3), 3)


if __name__ == "__main__":
    unittest.main()
