"""A05分离根目录运行、真实R手算核验、归档及失败保护；全部使用虚构研究。"""

import hashlib
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from science_modules.a05 import flow
from storage import verified_file
from tests.a05_fixture import annotations, seed


class A05RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    # 实际启动固定R包的ORA，使用独立概率及实际有效输入分母核对。
    def test_real_r_ora_and_empty_input_in_separate_root(self):
        groups, _ = annotations()
        result, _ = flow.r_call(self.root, "analyze", {"genes": ["1", "2", "3", "4", "5", "999"], "annotations": groups})
        for data in result.values():
            self.assertEqual(len(data["all"]), 1)
            row = data["all"][0]
            self.assertAlmostEqual(row["pvalue"], math.comb(10, 5) / math.comb(40, 5), places=12)
            self.assertEqual(row["GeneRatio"], "5/5")
            self.assertEqual(row["BgRatio"], "10/40")
            self.assertEqual(len(data["significant"]), 1)
        empty, _ = flow.r_call(self.root, "analyze", {"genes": ["999"], "annotations": groups})
        self.assertTrue(all(not data["all"] for data in empty.values()))
        self.assertFalse((self.root / "src").exists())

    # 校验完整发布链及旧文件不变，不借用当前真实研究，也不自动批准。
    def test_real_publish_and_validator_keep_inputs_and_history(self):
        w, sid = seed(self.root)
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in w.location(sid).rglob("*") if p.is_file() and p.name != "manifest.json"}
        a03 = w.load(sid)["current"]["A03"]
        result = flow.run_enrichment(w, sid, a03, "", "隔离真实R链路自测")
        manifest = w.load(sid)
        self.assertFalse(w.approved(manifest, result["run_id"]))
        self.assertNotIn("A06", manifest["current"])
        self.assertNotIn("A07", manifest["current"])
        self.assertEqual(result["summary"]["交集输入数"], 6)
        self.assertEqual(result["summary"]["Entrez映射数"], 6)
        self.assertEqual(result["summary"]["身份待核验数"], 0)
        self.assertEqual(len([f for f in result["files"] if f["role"] == "figure"]), 8)
        for record in result["files"]: verified_file(w.location(sid), record)
        self.assertTrue(all(hashlib.sha256(Path(name).read_bytes()).hexdigest() == sha for name, sha in before.items()))
        self.assertIs(flow.legacy.CONFIG, flow.CONFIG)

    # 首次来源目录缺失时可建立；同一明确来源索引继续只读复用。
    def test_first_source_directory_and_frozen_module_not_mutated(self):
        groups, sources = annotations()
        go = {"annotations": {key: groups[key] for key in ("BP", "CC", "MF")}, "metadata": {"fixture": "synthetic"}}
        original = flow.legacy.r_call
        def download(endpoint):
            if endpoint == "list/pathway/hsa": return sources["names"]
            if endpoint == "link/pathway/hsa": return sources["links"]
            return {"response_text": "Synthetic release"}
        with patch.object(flow, "r_call", return_value=(go, "synthetic export")), patch.object(flow.legacy, "download", side_effect=download):
            record = flow.source_snapshot(self.root)
        self.assertIs(flow.legacy.r_call, original)
        self.assertEqual(record, flow.source_snapshot(self.root))
        flow.legacy.read_source(verified_file(self.root, record))

    # R失败原文不丢失，也不能伪装成0条富集。
    def test_r_failure_in_stdout_is_visible(self):
        process = subprocess.CompletedProcess([], 1, stdout=b"Fatal error: synthetic R failure", stderr=b"")
        with patch.object(flow.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(ContractError, "synthetic R failure"):
                flow.r_call(self.root, "analyze", {})
        self.assertFalse((self.root / "studies").exists())

    # 已过期上游在执行R前阻断，不能给新研究错误归档。
    def test_stale_upstream_rejected_before_r(self):
        w, sid = seed(self.root)
        before = w.load(sid)
        with patch.object(flow, "r_call") as call:
            with self.assertRaises(ContractError):
                flow.run_enrichment(w, sid, "run_foreign", "", "过期测试")
        call.assert_not_called()
        self.assertEqual(before, w.load(sid))


if __name__ == "__main__":
    unittest.main(verbosity=2)
