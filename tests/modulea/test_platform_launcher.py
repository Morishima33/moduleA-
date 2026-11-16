"""实际本机启动/重复启动/停止；隔离中文、空格、长路径及占用端口。"""
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulea.config import Settings, load_settings, resolve_local_path
from modulea.launcher import start_service
from modulea.platform_preflight import binary_platform, inspect_platform
from modulea.service_control import probe_service, stop_service


class PlatformLauncherTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='Module A 中文 路径 ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        # 常规业务不应在同一个长路径setUp失败而全部失去覆盖；长路径有独立真实生命周期检查。
        self.data = self.root / '研究 数据 中文 空格'
        self.data.mkdir(parents=True)
        self.settings = Settings(data_root=self.data, runtime_dir=self.root/'运行 目录',
            static_dir=Path(__file__).resolve().parents[2]/'src/modulea/static')
        with socket.socket() as stream:
            stream.bind(('127.0.0.1', 0))
            self.port = stream.getsockname()[1]

    def test_real_start_duplicate_status_and_normal_stop_with_unicode_spaces(self):
        self.check_lifecycle()

    def test_real_lifecycle_with_over_320_character_path_and_bounded_components(self):
        long = self.root
        while len(str(long)) < 340:
            long = long / ('中文 空格 路径 ' + 'x'*24)
        # Windows明确使用扩展绝对路径，避免把操作系统目录策略错误混作启动故障。
        if os.name == 'nt':
            text = str(long.absolute())
            if not text.startswith('\\\\?\\'):
                long = Path('\\\\?\\UNC\\' + text[2:] if text.startswith('\\\\') else '\\\\?\\' + text)
        self.assertGreater(len(str(long)),320)
        self.assertTrue(all(len(part.encode('utf-8')) < 255 for part in long.parts))
        long.mkdir(parents=True)
        self.data=long
        self.settings.data_root=long
        self.check_lifecycle()

    def check_lifecycle(self):
        """真正启动服务并检验重复识别/状态/正常停止，长短中文路径共用同一断言。"""
        first = start_service(self.settings, self.port, open_browser=False)
        self.addCleanup(lambda: stop_service(self.settings,self.port,confirmed=True))
        self.assertTrue(first['ready'], first)
        second = start_service(self.settings, self.port, open_browser=False)
        self.assertTrue(second['reused'])
        self.assertEqual(first['actual']['instance_id'], second['actual']['instance_id'])
        self.assertEqual(first['actual']['pid'], second['actual']['pid'])
        self.assertEqual(first['actual']['data_root'], str(self.data))
        self.assertTrue(probe_service(self.settings,self.port)['ready'])
        self.assertEqual(stop_service(self.settings,self.port)['state'], 'confirmation_required')
        self.assertTrue(probe_service(self.settings,self.port)['ready'])
        self.assertEqual(stop_service(self.settings,self.port,confirmed=True)['state'], 'stopped')
        self.assertEqual(probe_service(self.settings,self.port)['state'], 'not_running')
        self.assertFalse((self.data/'studies').exists())

    def test_occupied_port_does_not_spawn_replace_or_stop_other_service(self):
        with socket.socket() as stream:
            stream.bind(('127.0.0.1', self.port));stream.listen()
            with patch('modulea.launcher.subprocess.Popen', side_effect=AssertionError('不可启动第二服务')):
                value = start_service(self.settings,self.port,open_browser=False)
            self.assertFalse(value['ready'])
            self.assertEqual(stream.getsockname()[1],self.port)

    def test_missing_frontend_or_data_blocks_before_spawning(self):
        for key in ('static_dir','data_root'):
            original = getattr(self.settings,key)
            setattr(self.settings,key,self.root/'missing')
            with patch('modulea.launcher.subprocess.Popen',side_effect=AssertionError('预检失败不可启动')):
                value=start_service(self.settings,self.port,open_browser=False)
            self.assertFalse(value['ready'])
            setattr(self.settings,key,original)

    def test_browser_open_is_explicit_and_reuses_only_matching_instance(self):
        with patch('modulea.launcher.probe_service',return_value={
                'state':'running','ready':True,'url':'http://127.0.0.1:8780','preflight_ready':True}), \
                patch('modulea.launcher.webbrowser.open') as opened:
            start_service(self.settings,open_browser=False)
            opened.assert_not_called()
            start_service(self.settings,open_browser=True)
            opened.assert_called_once_with('http://127.0.0.1:8780')

    def test_preflight_separates_browsing_from_missing_science_tools(self):
        value=inspect_platform(self.settings,port=self.port,probe_tools=False)
        self.assertTrue(value['browse_available'],value)
        self.assertFalse(value['science_available'])
        self.assertFalse(value['same_batch_resume_verified'])
        self.assertTrue({'platform','python','frontend','data','runtime','port','science_python','tools','font_regular','font_bold'}
                        <= {row['id'] for row in value['checks']})

    def test_config_relative_paths_resolve_against_project_and_windows_paths_are_rejected_on_mac(self):
        self.assertEqual(resolve_local_path('数据 目录',self.root),self.root/'数据 目录')
        if os.name!='nt':
            with self.assertRaises(ValueError):resolve_local_path('D:/个人目录',self.root)
        local=self.root/'example.toml'
        local.write_text('[paths]\ndata_root="数据 目录"\nfont_regular="字体/常规.ttf"\n',encoding='utf-8')
        settings=Settings(project_root=self.root,data_root=self.root,runtime_dir=self.root/'runtime')
        with patch('modulea.config.Settings',return_value=settings),patch.dict(os.environ,{'MODULEA_CONFIG':str(local)}):
            value=load_settings()
        self.assertEqual(value.data_root,self.root/'数据 目录')

    def test_pe_binary_is_identified_as_windows_without_execution(self):
        raw=bytearray(256);raw[:2]=b'MZ';raw[60:64]=(128).to_bytes(4,'little');raw[132:134]=(0x8664).to_bytes(2,'little')
        exe=self.root/'vina';exe.write_bytes(raw)
        self.assertEqual(binary_platform(exe),('Windows','x86_64'))


if __name__=='__main__':unittest.main()
