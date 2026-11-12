"""第二轮隔离worker仅选择第二轮脚本与独立请求目录；不执行实际科学子进程。"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modulea.config import Settings
from modulea.tasks.system_receptor_rescue_v2 import run
from storage import new_id


class RescueV2WorkerTests(unittest.TestCase):
    def test_second_runner_receives_original_private_body_and_server_tools(self):
        with tempfile.TemporaryDirectory(prefix='rescue_v2_worker_') as name:
            root = Path(name)
            settings = Settings(project_root=root, runtime_dir=root / 'rt', data_root=root / 'data',
                                science_python='fixed-python', science_tools_root=root / 'tools', science_repair_packages=root / 'repair')
            task = {'study_id': new_id('study'), 'task_id': new_id('task'), 'payload': json.dumps({'strict': 'private body'})}
            manager = Mock()
            manager.active_for.return_value = task
            def launch(command, **kwargs):
                self.assertEqual(command[:4], ['fixed-python', '-I', '-S', '-B'])
                self.assertEqual(command[4], str(root / 'tools/run_system_receptor_rescue_v2.py'))
                request = Path(command[command.index('--request-file') + 1])
                self.assertTrue(request.is_relative_to(settings.runtime_dir / 'receptor_rescue_v2'))
                self.assertEqual(request.read_text('utf-8'), task['payload'])
                self.assertEqual(command[command.index('--repair-packages') + 1], str(settings.science_repair_packages))
                output = Path(command[command.index('--result-file') + 1])
                output.write_text(json.dumps({'run_id': new_id('run'), 'outcome': 'success'}), 'utf-8')
                process = Mock()
                process.stdout = io.StringIO('PROGRESS 合成第二轮\n')
                process.wait.return_value = 0
                process.__enter__ = Mock(return_value=process)
                process.__exit__ = Mock(return_value=False)
                return process
            with patch('subprocess.Popen', side_effect=launch):
                self.assertIn('未自动批准', run(settings, task, manager))
            self.assertFalse((settings.runtime_dir / 'system_receptor_rescue_requests').exists())


if __name__ == '__main__':
    unittest.main()
