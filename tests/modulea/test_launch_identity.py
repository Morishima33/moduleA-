"""启动归属守卫：正常进程/Windows启动器后代通过，未知和PID复用拒绝。"""
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch


class LaunchIdentityTests(TestCase):
    def model(self):
        """缺失守卫作为明确失败，不能把模块导入错误充当红测。"""
        path = Path(__file__).resolve().parents[2]/'src/modulea/launch_identity.py'
        self.assertTrue(path.is_file(), '启动器尚未核验实际服务归属')
        return importlib.import_module('modulea.launch_identity')

    def fixture(self):
        process = SimpleNamespace(pid=100, poll=lambda: None)
        parent = {'platform': 'windows', 'pid': 100, 'birth': 10}
        child = {'platform': 'windows', 'pid': 101, 'birth': 20}
        return process, parent, child

    def test_same_process_requires_unchanged_birth_and_live_popen_handle(self):
        model = self.model(); process, parent, _ = self.fixture()
        with patch.object(model, 'identity', return_value=parent):
            self.assertTrue(model.owns_service_process(process, parent, process.pid))
            self.assertFalse(model.owns_service_process(process, None, process.pid))
            process.poll = lambda: 0
            self.assertFalse(model.owns_service_process(process, parent, process.pid))
        process.poll = lambda: None
        with patch.object(model, 'identity', return_value=dict(parent, birth=30)):
            self.assertFalse(model.owns_service_process(process, parent, process.pid))

    @skipUnless(os.name == 'nt', 'Windows虚拟环境启动器专测')
    def test_only_proven_windows_child_with_stable_birth_can_replace_launcher_pid(self):
        model = self.model(); process, parent, child = self.fixture()
        with patch.object(model, 'identity', side_effect=lambda pid: {100: parent, 101: child}.get(pid)), \
                patch.object(model, '_windows_parent', return_value=100):
            self.assertTrue(model.owns_service_process(process, parent, 101))
        with patch.object(model, 'identity', side_effect=lambda pid: {100: parent, 101: child}.get(pid)), \
                patch.object(model, '_windows_parent', return_value=999):
            self.assertFalse(model.owns_service_process(process, parent, 101))
        with patch.object(model, 'identity', side_effect=lambda pid: parent if pid == 100 else dict(child, birth=5)), \
                patch.object(model, '_windows_parent', return_value=100):
            self.assertFalse(model.owns_service_process(process, parent, 101))

    def test_invalid_unknown_or_reused_pid_is_not_accepted(self):
        model = self.model(); process, parent, child = self.fixture()
        for pid in (True, None, 0, -1, '101'):
            self.assertFalse(model.owns_service_process(process, parent, pid))
        with patch.object(model, 'identity', return_value=None):
            self.assertFalse(model.owns_service_process(process, parent, 101))
        with patch.object(model, 'identity', side_effect=[parent, child, dict(parent, birth=11)]), \
                patch.object(model, '_windows_parent', return_value=100):
            self.assertFalse(model.owns_service_process(process, parent, 101))

    @skipUnless(os.name == 'nt', '实际只读Windows进程父链')
    def test_toolhelp_reads_real_current_parent_without_changing_processes(self):
        model = self.model()
        self.assertEqual(model._windows_parent(os.getpid()), os.getppid())

    @skipUnless(os.name == 'nt', 'Windows虚拟环境启动器专测')
    def test_child_identity_change_or_disappearance_is_rejected_after_parent_query(self):
        model = self.model(); process, parent, child = self.fixture()
        for last in (None, dict(child, birth=21)):
            with patch.object(model, 'identity', side_effect=[parent, child, parent, last]), \
                    patch.object(model, '_windows_parent', return_value=100):
                self.assertFalse(model.owns_service_process(process, parent, 101))

    @skipUnless(os.name == 'nt', 'Windows只读父链异常')
    def test_unknown_parent_or_toolhelp_error_never_authorizes_service(self):
        model = self.model(); process, parent, child = self.fixture()
        with patch.object(model, 'identity', side_effect=lambda pid: {100: parent, 101: child}.get(pid)), \
                patch.object(model, '_windows_parent', side_effect=OSError('明确合成查询失败')):
            self.assertFalse(model.owns_service_process(process, parent, 101))
        with patch.object(model, 'identity', side_effect=lambda pid: {100: parent, 101: child}.get(pid)), \
                patch.object(model, '_windows_parent', return_value=None):
            self.assertFalse(model.owns_service_process(process, parent, 101))


class LauncherGuardTests(TestCase):
    """启动入口的未知归属和中途变化不能被就绪健康响应覆盖。"""
    def case(self, *, owned=True, changed=False, open_browser=False):
        from tempfile import TemporaryDirectory
        from unittest.mock import Mock
        from modulea.config import Settings
        from modulea.launcher import start_service
        with TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(data_root=root, runtime_dir=root/'runtime')
            before = {'state': 'not_running', 'ready': False, 'preflight_ready': True,
                      'expected': {'signature': 'same'}}
            ready = {'state': 'running', 'ready': True, 'url': 'http://127.0.0.1:8780',
                     'expected': {'signature': 'different' if changed else 'same'},
                     'actual': {'pid': 101, 'instance_id': 'service_synthetic'}}
            process = Mock(pid=100); process.poll.return_value = None
            with patch('modulea.launcher.probe_service', side_effect=[before, ready]), \
                    patch('modulea.platform_preflight.inspect_platform', return_value={'browse_available': True}), \
                    patch('modulea.launcher.subprocess.Popen', return_value=process), \
                    patch('modulea.launcher.threading.Thread'), \
                    patch('modulea.launcher.identity', return_value={'pid': 100, 'birth': 10}), \
                    patch('modulea.launcher.owns_service_process', return_value=owned) as owner, \
                    patch('modulea.launcher.stop_service') as stop, \
                    patch('modulea.launcher.webbrowser.open') as browser:
                result = start_service(settings, open_browser=open_browser)
            stop.assert_not_called()
            return result, owner, browser

    def test_proven_child_keeps_successful_start(self):
        result, owner, browser = self.case()
        self.assertTrue(result['ready']); owner.assert_called_once()
        browser.assert_not_called()

    def test_unknown_owner_does_not_open_browser_or_stop_unknown_instance(self):
        result, owner, browser = self.case(owned=False, open_browser=True)
        self.assertFalse(result['ready']); self.assertEqual(result['state'], 'instance_changed')
        browser.assert_not_called()

    def test_code_or_directory_change_rejects_even_proven_child(self):
        result, owner, browser = self.case(changed=True, open_browser=True)
        self.assertFalse(result['ready']); self.assertEqual(result['state'], 'instance_changed')
        owner.assert_not_called(); browser.assert_not_called()
