"""统一启动器补齐真实Windows架构元数据；合成服务，不改系统或真实研究。"""
import ctypes
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,skipUnless
from unittest.mock import patch

from modulea.config import Settings
from modulea.launcher import start_service
from modulea import child_environment as environment


class LauncherChildEnvironmentTests(TestCase):
    def test_non_windows_returns_copy_without_reading_or_adding_windows_metadata(self):
        for platform_name in ('darwin','linux'):
            with self.subTest(platform_name=platform_name):
                original={'PATH':'explicit_fixture'}
                with patch.object(environment,'_native_windows_architecture',side_effect=AssertionError('非Windows不能读Windows API')):
                    result=environment.child_environment(original,platform_name=platform_name)
                self.assertEqual(result,original);self.assertIsNot(result,original)

    def test_existing_value_is_preserved_without_reading_host(self):
        original={'PROCESSOR_ARCHITECTURE':'explicit_existing_value','PATH':'explicit_fixture'}
        with patch.object(environment,'_native_windows_architecture',side_effect=AssertionError('已有值不覆盖')):
            result=environment.child_environment(original,platform_name='win32')
        self.assertEqual(result,original);self.assertIsNot(result,original)

    def test_missing_or_blank_value_uses_native_measurement_and_preserves_parent(self):
        for value in (None,'','  '):
            original={'PATH':'explicit_fixture'}
            if value is not None:original['PROCESSOR_ARCHITECTURE']=value
            before=dict(original)
            # 明确模拟ARM64主机，不声称在该硬件实测，更不将它写入真实系统。
            with patch.object(environment,'_native_windows_architecture',return_value='ARM64') as native:
                result=environment.child_environment(original,platform_name='win32')
            native.assert_called_once_with();self.assertEqual(result['PROCESSOR_ARCHITECTURE'],'ARM64')
            self.assertEqual(original,before)

    def test_unknown_native_architecture_and_uninitialized_info_are_rejected(self):
        for unknown in (False,True):
            def read(pointer):
                if unknown:
                    pointer._obj.architecture=255;pointer._obj.processors=1;pointer._obj.page_size=4096
            with patch.object(ctypes,'WinDLL',return_value=SimpleNamespace(GetNativeSystemInfo=read),create=True):
                with self.assertRaises(ValueError):environment._native_windows_architecture()

    def test_native_read_error_does_not_change_parent_or_invent_value(self):
        original={'PATH':'explicit_fixture'}
        with patch.object(environment,'_native_windows_architecture',side_effect=OSError('明确合成API错误')):
            with self.assertRaisesRegex(OSError,'明确合成API错误'):
                environment.child_environment(original,platform_name='win32')
        self.assertEqual(original,{'PATH':'explicit_fixture'})

    @skipUnless(os.name=='nt','仅实际Windows API；其他平台规则另行验证')
    def test_existing_start_entry_fills_missing_real_architecture_only_in_child_copy(self):
        # 用独立的原生SYSTEM_INFO缓冲读取核对主机，不猜测AMD64或复用缺失变量。
        info=ctypes.create_string_buffer(64)
        ctypes.windll.kernel32.GetNativeSystemInfo(ctypes.byref(info))
        expected={0:'x86',5:'ARM',9:'AMD64',12:'ARM64'}[int.from_bytes(info.raw[:2],'little')]
        with TemporaryDirectory() as directory:
            root=Path(directory);settings=Settings(data_root=root/'data',runtime_dir=root/'runtime')
            before={'state':'not_running','ready':False,'preflight_ready':True,'expected':{'version':'test'}}
            after={'state':'running','ready':True,'expected':before['expected'],'actual':{'pid':1},'url':'http://127.0.0.1:12345'}
            process=SimpleNamespace(pid=1,wait=lambda:0,poll=lambda:None)
            with patch.dict(os.environ):
                os.environ.pop('PROCESSOR_ARCHITECTURE',None)
                with patch('modulea.launcher.probe_service',side_effect=[before,after]), \
                        patch('modulea.platform_preflight.inspect_platform',return_value={'browse_available':True}), \
                        patch('modulea.launcher.identity',return_value={'pid':1}), \
                        patch('modulea.launcher.owns_service_process',return_value=True), \
                        patch('modulea.launcher.subprocess.Popen',return_value=process) as spawn:
                    result=start_service(settings,12345,open_browser=False)
                self.assertTrue(result['ready'])
                self.assertEqual(spawn.call_args.kwargs['env'].get('PROCESSOR_ARCHITECTURE'),expected)
                self.assertNotIn('PROCESSOR_ARCHITECTURE',os.environ)
                self.assertFalse((settings.data_root/'studies').exists())

    def test_reused_ready_service_does_not_read_architecture_or_spawn(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);settings=Settings(data_root=root/'data',runtime_dir=root/'runtime')
            ready={'state':'running','ready':True,'url':'http://127.0.0.1:12345'}
            with patch('modulea.launcher.probe_service',return_value=ready), \
                    patch.object(environment,'_native_windows_architecture',side_effect=AssertionError('复用不需读架构')), \
                    patch('modulea.launcher.subprocess.Popen',side_effect=AssertionError('复用不得新建')):
                self.assertTrue(start_service(settings,12345,open_browser=False)['reused'])

    @skipUnless(os.name=='nt','Windows的实际R清理回归；非Mac实机验证')
    def test_existing_r_cli_exits_normally_with_constructed_child_environment(self):
        import subprocess
        from tests.modulea.test_plan_a05 import RSCRIPT
        if not RSCRIPT.is_file():self.skipTest('需已有Rscript；实际R子环境未验证')
        original=dict(os.environ);base=dict(original);base.pop('PROCESSOR_ARCHITECTURE',None)
        result=subprocess.run([str(RSCRIPT),'--vanilla','-e',
            'suppressPackageStartupMessages(library(cli));cat("BEFORE\\n");cli:::unload();cat("AFTER\\n")'],
            env=environment.child_environment(base),capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
        self.assertIn(b'AFTER',result.stdout);self.assertEqual(dict(os.environ),original)
