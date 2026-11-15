"""Windows科学子进程与worker日志端到端编码；仅运行隔离合成脚本。"""
from io import BytesIO, TextIOWrapper
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import json


class WorkerUtf8Tests(TestCase):
    def test_isolated_child_and_gbk_parent_preserve_unicode_progress_and_result(self):
        """实际-I子进程不依赖PYTHONUTF8环境变量，日志不得因不可编码字符终止。"""
        from modulea.tasks.rescue_worker_io import run, VERSION
        with TemporaryDirectory() as folder:
            root = Path(folder); (root/'tools').mkdir()
            (root/'tools/run_rescue_worker_io.py').write_text(
                "import sys,json,pathlib\n"
                "print('PROGRESS \\u8865\\u7b97 \\u2212 \\U0001f9ec',flush=True)\n"
                "p=pathlib.Path(sys.argv[sys.argv.index('--result-file')+1])\n"
                "p.write_text(json.dumps({'result_run_id':'run_synthetic','outcome':'success',"
                "'encoding':sys.stdout.encoding}),encoding='utf-8')\n", encoding='utf-8')
            settings = SimpleNamespace(project_root=root, runtime_dir=root/'runtime', data_root=root/'data',
                science_python=sys.executable, science_tools_root=root/'tools', science_repair_packages=root/'repair')
            task = {'study_id': 'study_synthetic', 'task_id': 'task_synthetic', 'payload': json.dumps({
                'request': {}, 'run_id': 'run_synthetic', 'adapter_version': VERSION})}
            manager = Mock(); manager.active_for.return_value = task
            buffer = BytesIO(); stream = TextIOWrapper(buffer, encoding='gbk', errors='strict')
            error = None
            with patch('sys.stdout', stream):
                try: run(settings, task, manager)
                except Exception as caught: error = caught
            stream.flush()
            self.assertIsNone(error, repr(error))
            result = json.loads((root/'runtime/worker_io_requests/task_synthetic/result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['encoding'], 'utf-8')
            self.assertIn('PROGRESS 补算 − 🧬', buffer.getvalue().decode('utf-8'))
            self.assertEqual(manager.update.call_args.kwargs['progress']['step_zh'], '补算 − 🧬')
