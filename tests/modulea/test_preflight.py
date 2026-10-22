"""跨电脑预检使用临时来源；缺资料、篡改与未知代码版本均不能冒充计算就绪。"""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modulea.config import Settings
from modulea.preflight import REFERENCE_FILES, code_identity, inspect_environment, reference_status


class PreflightTests(unittest.TestCase):
    # 为每项预检生成明确标为测试用途的本地原件和清单。
    def fixture(self, root):
        refs = root / "references"
        refs.mkdir()
        (root / "studies").mkdir()
        for _, _, filename, manifest in REFERENCE_FILES:
            raw = ("synthetic-only-" + filename).encode()
            (refs / filename).write_bytes(raw)
            (refs / manifest).write_text(json.dumps({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}), encoding="utf-8")

    def test_missing_data_is_not_zero_or_three_source_success(self):
        with tempfile.TemporaryDirectory() as name, patch("modulea.preflight.code_identity", return_value={"status": "unknown"}):
            root = Path(name)
            result = inspect_environment(Settings(project_root=root, data_root=root, runtime_dir=root / "runtime"))
            self.assertFalse(result["studies_directory_exists"])
            self.assertFalse(result["shared_references_verified"])
            self.assertTrue(all(row["status"] == "missing" for row in result["references"]))
            self.assertEqual(result["three_source_status"], "not_assessed")
            self.assertEqual(result["science"]["status"], "not_checked")
            self.assertEqual(list(root.iterdir()), [])  # 检查不能创建环境、runtime或研究目录。

    def test_reference_checks_use_configured_data_and_do_not_write(self):
        with tempfile.TemporaryDirectory() as name, patch("modulea.preflight.code_identity", return_value={"status": "unknown"}):
            root = Path(name)
            self.fixture(root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = inspect_environment(Settings(project_root=root / "unrelated-code", data_root=root))
            self.assertTrue(result["shared_references_verified"])
            self.assertEqual(result["paths"]["data_root"], str(root.resolve()))
            self.assertEqual(result["three_source_status"], "not_assessed")
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_tampered_and_incomplete_manifests_are_invalid(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            spec = REFERENCE_FILES[0]
            (root / "references" / spec[2]).write_bytes(b"changed")
            self.assertEqual(reference_status(root, spec)["status"], "invalid")
            for invalid in ({}, [], {"bytes": True, "sha256": "a" * 64}, {"bytes": 1, "sha256": "wrong"}):
                with self.subTest(invalid=invalid):
                    (root / "references" / spec[3]).write_text(json.dumps(invalid), encoding="utf-8")
                    self.assertEqual(reference_status(root, spec)["status"], "invalid")

    def test_dependency_probe_result_is_explicit_not_assumed(self):
        with tempfile.TemporaryDirectory() as name, patch("modulea.preflight.code_identity", return_value={"status": "unknown"}):
            settings = Settings(project_root=Path(name), data_root=Path(name))
            self.assertEqual(inspect_environment(settings, science_probe={"passed": True})["science"]["status"], "verified")
            result = inspect_environment(settings, science_probe={"passed": False, "error_zh": "测试：缺依赖"})
            self.assertEqual(result["science"]["status"], "unavailable")
            self.assertEqual(result["science"]["detail_zh"], "测试：缺依赖")

    def test_git_identity_detects_dirty_and_detached_checkout(self):
        root = Path(".").resolve()
        with patch("modulea.preflight._git", side_effect=[str(root), "a" * 40, "HEAD", " M src/file.py"]):
            result = code_identity(root)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["commit"], "a" * 40)
            self.assertEqual(result["branch"], "HEAD")
            self.assertTrue(result["dirty"])

    def test_no_git_parent_repository_or_bad_hash_remains_unknown(self):
        root = Path(".").resolve()
        for responses in ([str(root.parent)], [str(root), "bad-hash"]):
            with self.subTest(responses=responses), patch("modulea.preflight._git", side_effect=responses):
                self.assertEqual(code_identity(root)["status"], "unknown")
        for failure in (OSError("no git"), subprocess.TimeoutExpired("git", 3)):
            with self.subTest(failure=failure), patch("modulea.preflight._git", side_effect=failure):
                self.assertIsNone(code_identity(root)["commit"])


if __name__ == "__main__":
    unittest.main()
