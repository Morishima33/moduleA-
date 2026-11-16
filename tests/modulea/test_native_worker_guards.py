"""原生任务复用已验证预算归属语义与显式UTF8；只用临时记录和合成子进程。"""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from modulea.config import Settings
from modulea.tasks import native_execution as model
from modulea.core.bounded_evidence import digest_file
from tests.modulea import test_worker_io_budget_origin as origin


class NativeBudgetOriginTests(origin.WorkerBudgetOriginTests):
    def setUp(self):
        self.enterContext(patch.object(origin, 'CHILD', origin.CHILD.replace('rescue_worker_io', 'native_execution')))
        self.enterContext(patch.object(origin, 'WORKER', origin.WORKER.replace('plan_rescue_worker_io', 'native_a06')))


class NativeWorkerUtf8Tests(TestCase):
    def exercise(self, *, check_command, western):
        with TemporaryDirectory() as folder:
            root = Path(folder); profile = root/'profile.json'; profile.write_text('{}', encoding='utf-8')
            settings = Settings(project_root=root, runtime_dir=root/'runtime', data_root=root/'data',
                science_python='fixed-python', tools_profile=profile, font_regular=root/'regular.ttf', font_bold=root/'bold.ttf')
            task = dict(task_id='task_synthetic', study_id='study_synthetic', payload=json.dumps(dict(
                stage='prepare', request={}, profile_sha256=digest_file(profile)[1])))
            manager = Mock()
            def launch(command, **kwargs):
                if check_command:
                    self.assertEqual(command[:5], ['fixed-python', '-I', '-B', '-X', 'utf8'])
                self.assertEqual(kwargs['encoding'], 'utf-8')
                Path(command[command.index('--result-file')+1]).write_text(
                    json.dumps(dict(run_id='run_synthetic', outcome='success')), encoding='utf-8')
                child = Mock(); child.stdout = io.StringIO('PROGRESS 原生中文进度 🧪\n' if western else 'PROGRESS test\n')
                child.wait.return_value = 0
                child.__enter__ = Mock(return_value=child); child.__exit__ = Mock(return_value=False)
                return child
            output = io.BytesIO(); errors = io.BytesIO()
            stdout = io.TextIOWrapper(output, encoding='cp1252' if western else 'utf-8')
            stderr = io.TextIOWrapper(errors, encoding='cp1252' if western else 'utf-8')
            with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(model.subprocess, 'Popen', side_effect=launch):
                result = model.run(settings, task, manager)
            self.assertIn('run_synthetic', result)
            stdout.flush()
            if western: self.assertIn('原生中文进度 🧪', output.getvalue().decode('utf-8'))

    def test_isolated_child_has_explicit_utf8_switch(self):
        self.exercise(check_command=True, western=False)

    def test_western_parent_preserves_unicode_progress(self):
        self.exercise(check_command=False, western=True)
