"""受体补救沿既有重任务预算及服务器配置隔离执行；不启动真实科学任务。"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from storage import new_id
from modulea.config import Settings
from modulea.tasks import manager, resource_runner, worker


class SystemReceptorRescueWorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('plan_system_receptor_rescue', worker.HANDLERS, '受体补救尚未登记后台任务')
        self.temp = tempfile.TemporaryDirectory(prefix='rescue_worker_')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.settings = Settings(project_root=root, runtime_dir=root / 'runtime', data_root=root / 'data',
                                 science_python='configured-python', science_tools_root=root / 'tools',
                                 science_repair_packages=root / 'repair')
        self.task = {'task_id': new_id('task'), 'study_id': new_id('study'), 'kind': 'plan_system_receptor_rescue',
                     'payload': json.dumps({'private': 'immutable body'})}
        self.manager = Mock()
        self.manager.active_for.return_value = self.task

    def test_registered_heavy_task_uses_fixed_isolated_interpreter_and_server_paths(self):
        self.assertIn(self.task['kind'], manager.KINDS)
        self.assertNotIn(self.task['kind'], resource_runner.LIGHTWEIGHT)
        def launch(command, **kwargs):
            self.assertEqual(command[:4], ['configured-python', '-I', '-S', '-B'])
            self.assertIn(str(self.settings.science_repair_packages), command)
            self.assertIn(str(self.settings.science_tools_root), command)
            self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertEqual(kwargs['env']['PYTHONUTF8'], '1')
            path = Path(command[command.index('--request-file') + 1])
            self.assertEqual(path.read_text('utf-8'), self.task['payload'])
            output = Path(command[command.index('--result-file') + 1])
            output.write_text(json.dumps({'run_id': new_id('run'), 'outcome': 'success'}), 'utf-8')
            process = Mock()
            process.stdout = io.StringIO('PROGRESS 合成进度\n')
            process.wait.return_value = 0
            process.__enter__ = Mock(return_value=process)
            process.__exit__ = Mock(return_value=False)
            return process
        with patch('subprocess.Popen', side_effect=launch) as popen:
            result = worker.HANDLERS[self.task['kind']](self.settings, self.task, self.manager)
        self.assertIn('未自动批准', result)
        self.assertEqual(popen.call_count, 1)

    def test_another_active_task_or_missing_server_tools_blocks_launch(self):
        self.manager.active_for.return_value = dict(self.task, task_id=new_id('task'))
        with patch('subprocess.Popen') as popen, self.assertRaises(ValueError):
            worker.HANDLERS[self.task['kind']](self.settings, self.task, self.manager)
        popen.assert_not_called()
        self.manager.active_for.return_value = self.task
        self.settings.science_repair_packages = None
        with patch('subprocess.Popen') as popen, self.assertRaises(ValueError):
            worker.HANDLERS[self.task['kind']](self.settings, self.task, self.manager)
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
