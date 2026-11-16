"""二版I/O只走明确重任务和预算归属，旧任务不升级；全部隔离合成。"""
import importlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from contracts import ContractError
from modulea.config import Settings


class ScopedRescueWorkerTests(TestCase):
    def model(self):
        path = Path(__file__).resolve().parents[2]/'src/modulea/tasks/scoped_rescue_worker.py'
        self.assertTrue(path.is_file(), '尚未实现二版独立预算worker')
        return importlib.import_module('modulea.tasks.scoped_rescue_worker')

    def test_explicit_v2_keeps_original_heavy_lane_and_does_not_replace_v1_handler(self):
        model = self.model()
        from modulea.tasks.manager import KINDS
        from modulea.tasks.resource_runner import LIGHTWEIGHT
        from modulea.tasks.worker import HANDLERS
        from modulea.tasks.rescue_worker_io import run as legacy
        self.assertIn('plan_rescue_worker_io_v2', KINDS)
        self.assertNotIn('plan_rescue_worker_io_v2', LIGHTWEIGHT)
        self.assertIs(HANDLERS['plan_rescue_worker_io_v2'], model.run)
        self.assertIs(HANDLERS['plan_rescue_worker_io'], legacy)

    def test_v2_child_uses_explicit_adapter_utf8_and_fixed_server_paths(self):
        model = self.model()
        from modulea.core.scoped_worker_io import VERSION
        with TemporaryDirectory() as folder:
            root = Path(folder)
            settings = Settings(project_root=root, runtime_dir=root/'runtime', data_root=root/'data',
                science_python='fixed-python', science_tools_root=root/'tools', science_repair_packages=root/'repair')
            task = {'task_id': 'task_synthetic', 'study_id': 'study_synthetic', 'payload': json.dumps({
                'request': {'request_id': 'synthetic'}, 'run_id': 'run_synthetic', 'adapter_version': VERSION})}
            manager = Mock(); manager.active_for.return_value = task
            def launch(command, **kwargs):
                self.assertEqual(command[:6], ['fixed-python', '-I', '-S', '-B', '-X', 'utf8'])
                self.assertTrue(Path(command[6]).as_posix().endswith('tools/run_scoped_rescue_worker.py'))
                self.assertIn('--authorize-adapter', command)
                self.assertEqual(command[command.index('--tools-root')+1], str(settings.science_tools_root))
                Path(command[command.index('--result-file')+1]).write_text(json.dumps({
                    'result_run_id': 'run_synthetic', 'outcome': 'success'}), encoding='utf-8')
                process = Mock(); process.stdout = io.StringIO('PROGRESS 明确合成二版接续\n'); process.wait.return_value = 0
                process.__enter__ = Mock(return_value=process); process.__exit__ = Mock(return_value=False)
                return process
            with patch('subprocess.Popen', side_effect=launch):
                self.assertIn('独立科研复核', model.run(settings, task, manager))
            task['payload'] = json.dumps({'request': {}, 'run_id': 'run_synthetic', 'adapter_version': 'ModuleA.science_worker_io.1'})
            with patch('subprocess.Popen', side_effect=AssertionError('旧协议不可升级')):
                with self.assertRaises(ContractError): model.run(settings, task, manager)

    def test_direct_execute_without_current_budget_worker_is_rejected(self):
        self.model()
        path = Path(__file__).resolve().parents[2]/'tools/run_scoped_rescue_worker.py'
        self.assertTrue(path.is_file(), '缺少二版明确CLI')
        spec = importlib.util.spec_from_file_location('scoped_worker_cli_test', path)
        model = importlib.util.module_from_spec(spec); spec.loader.exec_module(model)
        with TemporaryDirectory() as folder:
            root = Path(folder); request = root/'request.json'; request.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ContractError, '原任务管理器'):
                model.main(['execute', '--authorize-adapter', '--study', 'study_'+'a'*32,
                    '--expected-run-id', 'run_'+'b'*32, '--request-file', str(request),
                    '--result-file', str(root/'output.json'), '--data-root', str(root/'data'),
                    '--runtime-dir', str(root/'runtime'), '--tools-root', str(root/'tools'),
                    '--repair-packages', str(root/'repair')])
            self.assertFalse((root/'data/studies').exists())
