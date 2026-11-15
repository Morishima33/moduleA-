"""有界恢复仍走原重任务、固定服务器配置与子进程日志；不直接启动真实科学工具。"""
import io
import json
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch

from contracts import ContractError
from modulea.config import Settings
from modulea.tasks.rescue_worker_io import run
from modulea.tasks.manager import KINDS
from modulea.tasks.resource_runner import LIGHTWEIGHT
from modulea.core.worker_io import VERSION


class RescueWorkerIOTaskTests(unittest.TestCase):
    def test_task_keeps_original_resource_lane_and_server_paths(self):
        self.assertIn('plan_rescue_worker_io',KINDS)
        self.assertNotIn('plan_rescue_worker_io',LIGHTWEIGHT)
        with TemporaryDirectory() as temp:
            root=Path(temp)
            settings=Settings(project_root=root,runtime_dir=root/'runtime',data_root=root/'data',
                science_python='fixed-python',science_tools_root=root/'tools',science_repair_packages=root/'repair')
            task={'study_id':'study_'+'a'*32,'task_id':'task_'+'b'*32,
                'payload':json.dumps({'request':{'request_id':'rescue_'+'c'*32},'run_id':'run_'+'d'*32,'adapter_version':VERSION})}
            manager=Mock();manager.active_for.return_value=task
            def launch(command,**kwargs):
                self.assertEqual(command[:4],['fixed-python','-I','-S','-B'])
                self.assertIn('--authorize-adapter',command)
                self.assertEqual(command[command.index('--task-id')+1],task['task_id'])
                self.assertEqual(command[command.index('--tools-root')+1],str(settings.science_tools_root))
                output=Path(command[command.index('--result-file')+1])
                output.write_text(json.dumps({'result_run_id':'run_'+'d'*32,'outcome':'success'}))
                process=Mock();process.stdout=io.StringIO('PROGRESS 已核验区域\n');process.wait.return_value=0
                process.__enter__=Mock(return_value=process);process.__exit__=Mock(return_value=False)
                return process
            with patch('subprocess.Popen',side_effect=launch):
                self.assertIn('独立科研复核',run(settings,task,manager))

    def test_wrong_version_or_busy_study_is_blocked_before_child_spawn(self):
        manager=Mock();manager.active_for.return_value={'task_id':'other'}
        task={'study_id':'synthetic','task_id':'this','payload':json.dumps({'request':{},'run_id':'x','adapter_version':VERSION})}
        with patch('subprocess.Popen',side_effect=AssertionError('不应启动')):
            with self.assertRaises(ContractError):run(Settings(),task,manager)
            task['payload']=json.dumps({'request':{},'run_id':'x','adapter_version':'unknown'})
            with self.assertRaises(ContractError):run(Settings(),task,manager)

    def test_internal_execute_cannot_bypass_task_manager(self):
        path=Path(__file__).resolve().parents[2]/'tools/run_rescue_worker_io.py'
        spec=importlib.util.spec_from_file_location('worker_io_cli_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with TemporaryDirectory() as temp:
            root=Path(temp);request=root/'request.json';request.write_text('{}')
            argv=['execute','--authorize-adapter','--study','study_'+'a'*32,'--expected-run-id','run_'+'b'*32,
                '--request-file',str(request),'--result-file',str(root/'output.json'),
                '--data-root',str(root/'data'),'--runtime-dir',str(root/'runtime'),
                '--tools-root',str(root/'tools'),'--repair-packages',str(root/'repair')]
            with patch('subprocess.Popen',side_effect=AssertionError('不应启动科学进程')):
                with self.assertRaisesRegex(ContractError,'原任务管理器'):module.main(argv)
            self.assertFalse((root/'data/studies').exists())


if __name__=='__main__':unittest.main()
