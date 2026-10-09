"""GitHub 上传脚本的行为测试：使用隔离临时仓库和本地 bare 远端，不向 GitHub 推送测试。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "github_upload.ps1"
PWSH = os.environ.get("MODULEA_PWSH") or shutil.which("pwsh")


@unittest.skipUnless(PWSH and shutil.which("git"), "需要 PowerShell 7.2+ 和 Git")
class GithubUploadTests(unittest.TestCase):
    """每项测试使用独立远端，验证范围、错误路径、重试及并发保护。"""

    def setUp(self):
        parent = os.environ.get("MODULEA_UPLOAD_TEST_ROOT")
        self.temporary = tempfile.TemporaryDirectory(prefix="github-upload-", dir=parent)
        self.base = Path(self.temporary.name).resolve()
        if parent:
            assert self.base.is_relative_to(Path(parent).resolve())
        self.repo = self.base / "code"
        self.remote = self.base / "remote.git"
        self.repo.mkdir()
        self.git("init", "--bare", str(self.remote), cwd=self.base)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "隔离上传测试")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.hooksPath", str(self.repo / ".git" / "hooks"))
        self.git("remote", "add", "origin", str(self.remote))
        self.write(".gitattributes", "* -text\n")
        self.write(".gitignore", "studies/\nnode_modules/\n*.log\nconfig/local.toml\n")
        self.write("README.md", "独立测试基线\n")
        self.write("src/selected.py", "value = 1\n")
        self.write("src/unrelated.py", "other = 1\n")
        self.policy = {
            "schema_version": 1,
            "remote_name": "origin",
            "remote_url": str(self.remote),
            "branch": "development",
            "max_file_bytes": 90 * 1024 * 1024,
        }
        self.write("tools/github_upload_policy.json", json.dumps(self.policy, ensure_ascii=False))
        self.git("add", "--all")
        self.git("commit", "-m", "独立初始基线")
        self.git("push", "origin", "main")
        self.git("switch", "-c", "development")
        self.git("push", "-u", "origin", "development")
        self.initial = self.git("rev-parse", "HEAD").stdout.strip()
        self.addCleanup(self.temporary.cleanup)

    # 不使用 shell=True，文件名和中文说明只作为参数传递。
    def git(self, *args, cwd=None, check=True):
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=check,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
        )

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def remote_head(self):
        return self.git("rev-parse", "refs/heads/development", cwd=self.remote).stdout.strip()

    def upload(self, paths, *, passed=True, records=None):
        if records is None:
            records = []
            for rel in paths:
                path = self.repo / rel
                if path.is_file():
                    records.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                elif not path.exists():
                    records.append({"path": rel, "deleted": True})
        report = {
            "schema_version": 1, "module": "上传测试", "passed": passed,
            "checks": [{"name": "本地测试检查", "passed": passed, "exit_code": 0 if passed else 1}],
            "files": records,
        }
        report_path = self.base / "checks.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        request_path = self.base / "request.json"
        request_path.write_text(json.dumps({
            "module": "上传测试", "message": "核对本次模块文件", "paths": paths,
            "check_report": str(report_path),
        }, ensure_ascii=False), encoding="utf-8")
        process = subprocess.run([
            PWSH, "-NoProfile", "-File", str(SCRIPT), "-RequestFile", str(request_path),
            "-RepositoryRoot", str(self.repo), "-LogDirectory", str(self.base / "logs"),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=160)
        self.assertTrue(process.stdout.strip(), process.stderr)
        result = json.loads(process.stdout)
        return process.returncode, result

    def test_upload_only_explicit_files(self):
        self.write("src/selected.py", "value = 2\n")
        self.write("src/unrelated.py", "other = 99\n")
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(self.remote_head(), result["commit"])
        self.assertEqual(self.git("show", "HEAD:src/unrelated.py").stdout, "other = 1\n")
        self.assertIn("src/unrelated.py", self.git("status", "--short").stdout)

    def test_no_change_creates_no_commit(self):
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "no_changes")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertEqual(self.remote_head(), self.initial)

    def test_failed_checks_preserve_work_without_commit(self):
        self.write("src/selected.py", "value = 3\n")
        code, result = self.upload(["src/selected.py"], passed=False)
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "CHECKS_FAILED")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        self.assertEqual((self.repo / "src/selected.py").read_text(), "value = 3\n")

    def test_excluded_and_escape_paths_never_upload(self):
        for rel, expected in [
            ("studies/private.json", "EXCLUDED_PATH"),
            ("config/local.toml", "EXCLUDED_PATH"),
            ("src/node_modules/secret.js", "EXCLUDED_PATH"),
            ("src/.env", "EXCLUDED_PATH"),
            ("../outside.txt", "INVALID_PATH"),
            ("src/*.py", "INVALID_PATH"),
        ]:
            with self.subTest(path=rel):
                code, result = self.upload([rel], records=[])
                self.assertEqual(code, 1)
                self.assertEqual(result["error_code"], expected)
                self.assertEqual(self.remote_head(), self.initial)

    def test_changes_after_checks_are_rejected(self):
        record = {"path": "src/selected.py", "sha256": hashlib.sha256((self.repo / "src/selected.py").read_bytes()).hexdigest()}
        self.write("src/selected.py", "value = 4\n")
        code, result = self.upload(["src/selected.py"], records=[record])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "CHECKED_FILE_CHANGED")
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_unchecked_file_is_rejected(self):
        self.write("src/selected.py", "value = 4\n")
        code, result = self.upload(["src/selected.py"], records=[])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "UNCHECKED_FILE")

    def test_existing_staging_is_preserved(self):
        self.write("src/unrelated.py", "other = 7\n")
        self.git("add", "src/unrelated.py")
        self.write("src/selected.py", "value = 7\n")
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "DIRTY_INDEX")
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.strip(), "src/unrelated.py")

    def test_push_failure_retains_commit_and_retry_reuses_it(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="")
        hook.chmod(0o755)
        self.write("src/selected.py", "value = 8\n")
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "PUSH_FAILED")
        failed_head = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(failed_head, self.initial)
        self.assertEqual(self.remote_head(), self.initial)
        hook.unlink()
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["commit"], failed_head)
        self.assertEqual(self.remote_head(), failed_head)
        self.assertEqual(self.git("rev-list", "--count", "HEAD").stdout.strip(), "2")

    def test_remote_new_commit_stops_without_local_commit(self):
        other = self.base / "other"
        self.git("clone", "--branch", "development", str(self.remote), str(other), cwd=self.base)
        self.git("config", "user.name", "另一个测试提交", cwd=other)
        self.git("config", "user.email", "other@example.invalid", cwd=other)
        (other / "README.md").write_text("远端新提交\n", encoding="utf-8")
        self.git("add", "README.md", cwd=other)
        self.git("commit", "-m", "远端变化", cwd=other)
        self.git("push", "origin", "development", cwd=other)
        changed_remote = self.remote_head()
        self.write("src/selected.py", "value = 9\n")
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "REMOTE_CHANGED")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.initial)
        self.assertEqual(self.remote_head(), changed_remote)

    def test_wrong_branch_is_rejected(self):
        self.git("switch", "main")
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "WRONG_BRANCH")

    def test_selected_deletion_is_recorded(self):
        (self.repo / "src/selected.py").unlink()
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 0, result)
        self.assertEqual(self.git("ls-tree", "HEAD", "src/selected.py").stdout, "")
        self.assertEqual(self.remote_head(), result["commit"])

    def test_directory_scope_does_not_collect_ignored_data(self):
        self.write("src/selected.py", "value = 10\n")
        self.write("src/node_modules/private.js", "private test data")
        self.write("src/temporary.log", "private log")
        records = [{"path": "src/selected.py", "sha256": hashlib.sha256((self.repo / "src/selected.py").read_bytes()).hexdigest()}]
        code, result = self.upload(["src"], records=records)
        self.assertEqual(code, 0, result)
        self.assertNotIn("private.js", self.git("ls-files").stdout)
        self.assertNotIn("temporary.log", self.git("ls-files").stdout)

    def test_excluded_file_in_pending_history_is_rejected(self):
        self.write("studies/private.json", "{}")
        self.git("add", "-f", "studies/private.json")
        self.git("commit", "-m", "错误纳入资料的本地测试提交")
        self.git("rm", "studies/private.json")
        self.git("commit", "-m", "移除资料但历史仍包含它")
        code, result = self.upload(["src/selected.py"])
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "EXCLUDED_PATH")
        self.assertEqual(self.remote_head(), self.initial)


if __name__ == "__main__":
    unittest.main(verbosity=2)
