"""显式一次确认串行接续的隔离测试；不提交真实研究任务。"""
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from modulea.core.automatic_start import validate, run


def request():
    """虚构授权绑定，不从生产研究复制名单。"""
    return dict(expected_binding='a'*64, expected_connection_id=None, expected_a06='old',
                request_id='auto_'+'1'*32, policy_version='A06.automatic.3', reviewer='test',
                note='explicit synthetic execution', confirmed=True, reference_choices=[], continuation_version='A06.connect_run.1')


def workflow():
    """保留校验调用顺序，模拟最小Workflow公开接口。"""
    return SimpleNamespace(automatic_binding=Mock(return_value=({'current': {'A06': 'old'}}, {})),
                           validate_extended_scope=Mock(), current_automatic_connection=Mock(return_value=None),
                           validate_automatic_request=Mock())


class AutomaticStartTests(unittest.TestCase):
    def test_cancel_continuous_task_preserves_same_automatic_failure_record(self):
        from modulea.config import Settings
        from modulea.tasks.manager import TaskManager
        with TemporaryDirectory() as folder:
            root = Path(folder)
            manager = TaskManager(Settings(project_root=root, data_root=root, runtime_dir=root/'runtime'))
            with patch.object(manager, '_spawn'):
                task, _ = manager.submit('synthetic', 'a06_auto_start', 'test', request())
            fail = Mock()
            with patch('modulea.core.kernel.Kernel', return_value=SimpleNamespace(workflow=lambda: SimpleNamespace(fail_automatic=fail))):
                cancelled = manager.cancel(task['task_id'])
            self.assertEqual(cancelled['state'], 'cancelled')
            self.assertEqual(fail.call_args.args[:2], ('synthetic', request()['request_id']))

    def test_background_wrapper_dispatches_one_continuous_science_process(self):
        from modulea.tasks.automatic_docking import execute
        with TemporaryDirectory() as folder:
            root = Path(folder)
            settings = SimpleNamespace(runtime_dir=root, project_root=root, data_root=root,
                                       science_tools_root=root, science_repair_packages=None)
            task = {'task_id': 'synthetic', 'study_id': 'synthetic', 'kind': 'a06_auto_start',
                    'payload': json.dumps(request())}
            def process(command, **kwargs):
                self.assertEqual(command[command.index('--mode')+1], 'connect-run')
                output = Path(command[command.index('--result-file')+1])
                output.write_text(json.dumps({'message_zh': 'synthetic completed'}), encoding='utf-8')
                return SimpleNamespace(stdout=['PROGRESS synthetic connect\n', 'PROGRESS synthetic score\n'], wait=lambda: 0)
            with patch('modulea.tasks.automatic_docking.subprocess.Popen', side_effect=process) as start:
                self.assertEqual(execute(settings, task, SimpleNamespace(update=Mock())), 'synthetic completed')
            start.assert_called_once()

    def test_api_requires_real_confirmation_before_submitting_a_task(self):
        from modulea.api.server import App
        from modulea.api.errors import ApiError
        submitted = []
        app = SimpleNamespace(_automatic_ready=lambda _: workflow(),
                              tasks=SimpleNamespace(submit=lambda *args: (submitted.append(args) or {'task_id': 'synthetic'}, True)))
        with self.assertRaises(ApiError):
            App.post_automatic_start(app, SimpleNamespace(json=lambda: dict(request(), confirmed=False)), 'synthetic')
        self.assertFalse(submitted)
        _, status = App.post_automatic_start(app, SimpleNamespace(json=request), 'synthetic')
        self.assertEqual(status, 202)
        self.assertEqual(submitted[0][1], 'a06_auto_start')
        self.assertEqual(submitted[0][3], request())

    def test_confirmation_cannot_be_defaulted_or_invented(self):
        for change in ({'confirmed': False}, {'continuation_version': 'unapproved'}, {'reviewer': ''}, {'reference_choices': [{'target_id': 'hidden'}]},
                       {'expected_connection_id': 'stale'}, {'expected_a06': 'changed'}):
            p = dict(request(), **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(workflow(), 'synthetic', p)

    def test_once_confirmed_connects_then_runs_without_second_gate(self):
        w = workflow(); order = []
        def connect(*args):
            order.append('connect')
            return {'id': 'new_connection'}
        def calculate(payload):
            order.append('calculate')
            self.assertEqual(payload['expected_connection_id'], 'new_connection')
            self.assertTrue(payload['confirmed'])
            self.assertEqual(payload['reference_choices'], [])
            return {'run_id': 'new_run'}
        self.assertEqual(run(w, 'synthetic', request(), connect, calculate, lambda _: None)['run_id'], 'new_run')
        self.assertEqual(order, ['connect', 'calculate'])
        w.validate_automatic_request.assert_called_once()

    def test_connection_failure_or_changed_binding_never_starts_scoring(self):
        w = workflow(); calculate = Mock()
        with self.assertRaises(TimeoutError):
            run(w, 'synthetic', request(), Mock(side_effect=TimeoutError('official source unavailable')), calculate, lambda _: None)
        calculate.assert_not_called()
        w = workflow(); w.validate_automatic_request.side_effect = ValueError('binding changed')
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            run(w, 'synthetic', request(), Mock(return_value={'id': 'new'}), calculate, lambda _: None)
        calculate.assert_not_called()

    def test_up_to_date_connection_is_reused_but_actual_execution_still_validated(self):
        w = workflow(); conn = {'id': 'existing', 'packet': {}}
        w.current_automatic_connection.return_value = conn
        w.location = Mock(return_value='synthetic')
        p = dict(request(), expected_connection_id='existing')
        connect, calculate = Mock(), Mock(return_value={'run_id': 'new'})
        with patch('modulea.core.automatic_start.verified_file', return_value='file'), \
             patch('modulea.core.automatic_start.read_json', return_value={'compound_resolution_version': 'A06.compound_identity.1'}), \
             patch('science_modules.a06.reference_candidates.validate_choices'):
            run(w, 'synthetic', p, connect, calculate, lambda _: None)
        connect.assert_not_called()
        calculate.assert_called_once()
