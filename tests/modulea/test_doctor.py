"""实际科学解释器探测及 doctor 退出码回归检查。"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from modulea.__main__ import SCIENCE_DEPS, doctor, probe_science_python
from modulea.config import Settings

class DoctorTest(unittest.TestCase):
    def output(self, version=(3, 13, 1), missing=()):
        return json.dumps({"version": list(version), "executable": "configured-python", "dependencies": {name: name not in missing for name in SCIENCE_DEPS}})
    def test_uses_configured_interpreter_not_server(self):
        with patch("modulea.__main__.subprocess.run", return_value=Mock(returncode=0, stdout=self.output())) as run:
            self.assertTrue(probe_science_python("different-python")["passed"])
        self.assertEqual(run.call_args.args[0][0], "different-python")
        self.assertEqual(run.call_args.args[0][1], "-c")
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
    def test_dependencies_and_python_version_checked(self):
        for stdout in (self.output(missing=("numpy",)), self.output(version=(3, 10, 9))):
            with self.subTest(stdout=stdout), patch("modulea.__main__.subprocess.run", return_value=Mock(returncode=0, stdout=stdout)):
                self.assertFalse(probe_science_python("target")["passed"])
    def test_nonzero_invalid_response_and_timeout_fail(self):
        for code, stdout in ((1, ""), (0, "not-json"), (0, "{}"), (0, "[]")):
            with self.subTest(code=code, stdout=stdout), patch("modulea.__main__.subprocess.run", return_value=Mock(returncode=code, stdout=stdout)):
                self.assertFalse(probe_science_python("target")["passed"])
        with patch("modulea.__main__.subprocess.run", side_effect=subprocess.TimeoutExpired("target", 15)):
            self.assertFalse(probe_science_python("target")["passed"])
    def test_real_missing_executable_fails(self):
        with tempfile.TemporaryDirectory() as name:
            self.assertFalse(probe_science_python(str(Path(name) / "does-not-exist.exe"))["passed"])
    def test_real_current_python_probe_has_actual_identity(self):
        result = probe_science_python(sys.executable)
        self.assertEqual(Path(result["executable"]).resolve(), Path(sys.executable).resolve())
        self.assertEqual(result["version"], list(sys.version_info[:3]))
        self.assertEqual(set(result["dependencies"]), set(SCIENCE_DEPS))
    def test_doctor_exit_code_reports_environment_and_archive_failures(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "studies").mkdir()
            settings = Settings(data_root=root)
            workflow = Mock()
            workflow.studies.return_value = []
            with contextlib.redirect_stdout(io.StringIO()), patch("modulea.core.kernel.Kernel") as kernel, patch("modulea.__main__.probe_science_python") as probe:
                kernel.return_value.workflow.return_value = workflow
                probe.return_value = {"passed": False, "error_zh": "测试环境缺依赖"}
                self.assertEqual(doctor(settings), 1)
                probe.return_value = {"passed": True}
                self.assertEqual(doctor(settings), 0)
                workflow.studies.return_value = [{"study_id": "study_test"}]
                workflow.view.side_effect = RuntimeError("归档损坏")
                self.assertEqual(doctor(settings), 1)

if __name__ == "__main__":
    unittest.main()
