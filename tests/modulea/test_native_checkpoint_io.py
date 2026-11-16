"""原生检查点规模与损坏回归；合成原件完整校验，不调用科学工具。"""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError, fingerprint
from modulea.core import native_execution as core
from modulea.core.bounded_evidence import file_record
from modulea.core.worker_io import WorkerIO
from storage import new_id, write_json


class NativeCheckpointIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.sid, self.rid = new_id("study"), new_id("run")
        self.run = {"run_id": self.rid, "module_id": "A06_PREP",
                    "config": {"version": core.PREPARATION}, "config_hash": fingerprint({})}
        self.manifest = {core.CHECKPOINTS: []}
        self.adapter = WorkerIO()
        self.addCleanup(self.adapter.close)
        self.w = SimpleNamespace(load=lambda _: deepcopy(self.manifest), location=lambda _: self.home,
                                 run=lambda *_: self.run, _worker_io=self.adapter)

    def append(self, key, *, previous=None, retryable=False):
        """创建标准登记对象，padding仅模拟较大JSON，没有科研结果。"""
        value = {"schema_version": core.SCORING, "study_id": self.sid, "run_id": self.rid,
                 "key": key, "previous": previous, "config_hash": self.run["config_hash"],
                 "human_review_written": False, "files": [],
                 "payload": {"state": "NA", "retryable": retryable, "padding": "x" * 65536}}
        path = self.home / f"runs/A06_PREP/{self.rid}/native_checkpoints/{key}/{new_id('attempt')}.json"
        write_json(path, value)
        ref = file_record(self.home, path, "native_checkpoint")
        self.manifest[core.CHECKPOINTS].append(ref)
        return ref, value

    def test_many_objects_parse_only_headers_once_and_requested_payload(self):
        count = 32
        expected = [self.append(f"compound_{i:06d}") for i in range(count)]
        with patch("json.loads", wraps=json.loads) as loads:
            for index, pair in enumerate(expected):
                self.assertEqual(core.read_object(self.w, self.sid, self.rid, f"compound_{index:06d}"), pair)
        self.assertEqual(loads.call_count, count * 2 - 1)
        self.assertEqual(self.adapter.stats["checkpoint_sha_checks"], count * count)
        self.assertLessEqual(len(self.adapter.headers), self.adapter.header_limit)

    def test_cached_unrelated_corruption_still_blocks(self):
        self.append("compound_000001")
        unrelated, _ = self.append("compound_000002")
        core.read_object(self.w, self.sid, self.rid, "compound_000001")
        (self.home / unrelated["path"]).write_bytes(b"corrupt unrelated original")
        with self.assertRaises(ContractError):
            core.read_object(self.w, self.sid, self.rid, "compound_000001")

    def test_previous_chain_and_terminal_object_rules_remain_enforced(self):
        first, _ = self.append("compound_000001", retryable=True)
        second = self.append("compound_000001", previous=first)
        self.assertEqual(core.read_object(self.w, self.sid, self.rid, "compound_000001"), second)
        self.append("compound_000001", previous=second[0])
        with self.assertRaises(ContractError):
            core.read_object(self.w, self.sid, self.rid, "compound_000001")

    def test_header_cache_is_bounded_and_does_not_retain_payload(self):
        self.adapter.header_limit = 2
        for index in range(8):
            self.append(f"compound_{index:06d}")
        core.read_object(self.w, self.sid, self.rid, "compound_000000")
        self.assertLessEqual(len(self.adapter.headers), 2)
        self.assertTrue(all(isinstance(h, tuple) and all(isinstance(v, str) and len(v) <= 256 for v in h)
                            for h in self.adapter.headers.values()))
        self.adapter.close()
        self.assertEqual(len(self.adapter.headers), 0)

    def test_manifest_changes_during_read_are_rejected(self):
        self.append("compound_000001")
        calls = 0

        def changing(_):
            """模拟读取期间登记被另一线程更新，不写实际研究。"""
            nonlocal calls
            calls += 1
            return deepcopy(self.manifest) if calls == 1 else {**self.manifest, "changed": True}

        self.w.load = changing
        with self.assertRaises(ContractError):
            core.read_object(self.w, self.sid, self.rid, "compound_000001")


if __name__ == "__main__":
    unittest.main()
