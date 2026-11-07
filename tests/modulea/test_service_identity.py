"""轻量服务身份的虚构工程验证，不导入科学模块或访问研究。"""
import builtins
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modulea.service_identity import (PROTOCOL, ServiceIdentity, compare_identity,
                                     expected_identity, frontend_status,
                                     implementation_signature)


class ServiceIdentityTests(unittest.TestCase):
    """各测试只建立源码、静态文件和目录名，不建立真实研究。"""

    # 使用隔离工程核对本地源码和实际引用前端；数据目录保持不存在。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.static = self.root / 'frontend'
        (self.static / 'assets').mkdir(parents=True)
        (self.static / 'index.html').write_text('<script src="./assets/app.js"></script><link rel="stylesheet" href="/assets/app.css"><link rel="icon" href="favicon.svg">', encoding='utf-8')
        for name in ('assets/app.js', 'assets/app.css', 'favicon.svg'):
            (self.static / name).write_text(name, encoding='utf-8')
        for name in ('src/modulea/entry.py', 'src/science_modules/a/model.py', 'src/legacy.py', 'src/enrichment.R'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name, encoding='utf-8')
        self.settings = SimpleNamespace(project_root=self.root, data_root=self.root/'absent_data', runtime_dir=self.root/'absent_runtime', static_dir=self.static)

    # 真实引用逐项摘要，排序去重；未引用旧构建不混入运行版本。
    def test_frontend_hashes_only_actual_local_references(self):
        (self.static/'assets/stale.js').write_text('old')
        result = frontend_status(self.static)
        self.assertTrue(result['ready'])
        self.assertEqual(result['errors_zh'], [])
        self.assertEqual([a['path'] for a in result['assets']], ['assets/app.css', 'assets/app.js', 'favicon.svg'])
        self.assertEqual(result['index_sha256'], hashlib.sha256((self.static/'index.html').read_bytes()).hexdigest())
        for item in result['assets']:
            content = (self.static/item['path']).read_bytes()
            self.assertEqual(item['sha256'], hashlib.sha256(content).hexdigest())
            self.assertEqual(item['bytes'], len(content))

    # 缺入口、缺JS、远程和编码后的越界都必须显示不可运行。
    def test_missing_remote_traversal_and_invalid_html_are_not_ready(self):
        self.assertFalse(frontend_status(None)['ready'])
        self.assertFalse(frontend_status(self.root/'missing')['ready'])
        for href in ('https://remote/app.js', '//remote/app.js', '../secret.js', '%2e%2e/secret.js', r'..\secret.js', 'data:text/javascript,1', 'file:///x.js', 'assets/missing.js'):
            with self.subTest(href=href):
                (self.static/'index.html').write_text(f'<script src="{href}"></script>', encoding='utf-8')
                state = frontend_status(self.static)
                self.assertFalse(state['ready'])
                self.assertTrue(state['errors_zh'])
        (self.static/'index.html').write_text('<html><body>no bundle</body></html>')
        self.assertFalse(frontend_status(self.static)['ready'])

    # 目录链接逃逸同样不可读，不能用同名资源冒充项目文件。
    def test_asset_link_escape_is_rejected(self):
        outside = self.root/'outside.js'
        outside.write_text('secret')
        target = self.static/'assets/escape.js'
        try:
            target.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f'当前账户不能创建符号链接：{exc}')
        (self.static/'index.html').write_text('<script src="assets/escape.js"></script>')
        self.assertFalse(frontend_status(self.static)['ready'])

    # 不依赖Windows建链接权限，另核边界解析后不会读取根外文件。
    def test_resolved_escape_never_reads_external_bytes(self):
        target = self.static/'assets/escape.js'
        outside = self.root/'external.js'
        (self.static/'index.html').write_text('<script src="assets/escape.js"></script>')
        original_resolve, original_read = Path.resolve, Path.read_bytes
        def resolve(path, *args, **kwargs):
            return outside if path == target else original_resolve(path, *args, **kwargs)
        def read(path):
            self.assertNotEqual(path, outside)
            return original_read(path)
        with patch.object(Path, 'resolve', resolve), patch.object(Path, 'read_bytes', read):
            self.assertFalse(frontend_status(self.static)['ready'])

    # 预加载资源亦属实际引用，base改目录不允许静默采用。
    def test_preloads_and_base_directory_are_checked(self):
        index = self.static/'index.html'
        old = index.read_text(encoding='utf-8')
        index.write_text(old+'<link rel="preload" as="script" href="assets/missing.js">', encoding='utf-8')
        self.assertFalse(frontend_status(self.static)['ready'])
        index.write_text(old+'<base href="https://remote/">', encoding='utf-8')
        self.assertFalse(frontend_status(self.static)['ready'])

    # 代码和使用中的静态字节影响签名，研究/缓存/旧build不影响签名。
    def test_signature_is_deterministic_and_bound_to_source_and_frontend(self):
        first = implementation_signature(self.root, self.static)
        self.assertEqual(first, implementation_signature(self.root, self.static))
        for name in ('src/modulea/__pycache__/fake.py', 'src/modulea/data/fake.py', 'src/non_source.json', 'frontend/assets/stale.js', 'studies/manifest.json'):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('unrelated')
        self.assertEqual(first, implementation_signature(self.root, self.static))
        for name in ('src/modulea/entry.py', 'src/science_modules/a/model.py', 'src/legacy.py', 'src/enrichment.R', 'frontend/assets/app.js', 'frontend/index.html'):
            path = self.root/name
            old = path.read_bytes()
            path.write_bytes(old+b'\n')
            self.assertNotEqual(first, implementation_signature(self.root, self.static), name)
            path.write_bytes(old)

    # 无法读取源码目录不能悄悄形成缺少模块的“完整”签名。
    def test_unreadable_source_tree_is_not_silently_signed(self):
        def denied(*args, **kwargs):
            kwargs['onerror'](PermissionError('blocked source directory'))
            return iter(())
        with patch('modulea.service_identity.os.walk', side_effect=denied):
            with self.assertRaises(PermissionError):
                implementation_signature(self.root, self.static)

    # describe只重查前端，进程代码签名固定；独立新期待值检测旧服务。
    def test_identity_loaded_signature_is_fixed_and_new_expected_detects_stale_code(self):
        service = ServiceIdentity(self.settings)
        expected = expected_identity(self.settings)
        first = service.describe(8780)
        self.assertEqual(compare_identity(first, expected, 8780), [])
        self.assertEqual(first['schema_version'], PROTOCOL)
        self.assertIs(first['scientific_validation_performed'], False)
        self.assertFalse(self.settings.data_root.exists())
        self.assertFalse(self.settings.runtime_dir.exists())
        (self.root/'src/legacy.py').write_text('changed')
        with patch('modulea.service_identity.implementation_signature', side_effect=AssertionError('describe cannot scan source')):
            second = service.describe(8780)
        self.assertEqual(second['code_signature'], first['code_signature'])
        self.assertEqual(second['instance_id'], first['instance_id'])
        self.assertTrue(compare_identity(second, expected_identity(self.settings), 8780))
        (self.static/'assets/app.js').unlink()
        self.assertFalse(service.describe(8780)['frontend']['ready'])

    # 比较不信任任何远端字段，更不能解析响应提供的路径。
    def test_compare_rejects_wrong_types_paths_protocol_and_signature_without_io(self):
        expected = expected_identity(self.settings)
        actual = ServiceIdentity(self.settings).describe(8780)
        replacements = {'schema_version':'other', 'instance_id':'service_bad', 'pid':True, 'started_at':'yesterday', 'port':True, 'project_root':'https://remote/path', 'data_root':'other', 'runtime_dir':'other', 'static_dir':'other', 'code_signature':'x'*64, 'frontend':{'ready':False}, 'scientific_validation_performed':True}
        for key, value in replacements.items():
            with self.subTest(key=key):
                bad = deepcopy(actual)
                bad[key] = value
                with patch.object(Path, 'resolve', side_effect=AssertionError('response paths cannot be resolved')), patch.object(Path, 'read_bytes', side_effect=AssertionError('comparison cannot read files')):
                    self.assertTrue(compare_identity(bad, expected, 8780))
        self.assertTrue(compare_identity([], expected, 8780))
        self.assertTrue(compare_identity(actual, expected, True))
        for change in ({'bytes':True}, {'sha256':None}, {'path':None}):
            bad = deepcopy(actual)
            bad['frontend']['assets'][0].update(change)
            self.assertTrue(compare_identity(bad, expected, 8780))

    # 在第三方科学包均不可导入时，身份描述仍只靠标准库运行。
    def test_no_science_imports_or_workflow_needed(self):
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name.split('.')[0] in ('PIL', 'numpy', 'rdkit', 'networkx', 'workflow', 'science_modules'):
                raise AssertionError(f'forbidden import {name}')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded):
            spec = importlib.util.spec_from_file_location('isolated_service_identity', Path(__file__).parents[2]/'src/modulea/service_identity.py')
            isolated = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(isolated)
            actual = isolated.ServiceIdentity(self.settings).describe(8780)
            self.assertEqual(isolated.compare_identity(actual, isolated.expected_identity(self.settings), 8780), [])


if __name__ == '__main__':
    unittest.main()
