"""二版请求内复用回归；真实临时原件、同尺寸破坏及退出全SHA检查。"""
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FunctionType, SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import file_record, read_json, verified_file
from modulea.api import receptor_rescue_v2 as api
from modulea.api.server import App
from modulea.core import system_receptor_rescue_v2 as core


def source(workflow, manifest, reference, scoring):
    """合成绑定只消费真实登记文件；观察完整原函数是否重复执行。"""
    calls.append(reference['path'])
    value = read_json(verified_file(workflow.root / 'studies' / manifest['study_id'], reference))
    return {'value': value, 'revision': manifest['revision'], 'scoring': scoring}


def info(workflow, manifest, reference, scoring, change=None):
    """同请求读取两遍；可在返回前破坏原件，生产退出核验必须发现。"""
    first = core.source_binding(workflow, manifest, reference, scoring)
    if change:
        change()
    second = core.source_binding(workflow, deepcopy(manifest), deepcopy(reference), scoring)
    return first, second


class RescueReadEvidenceV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='补救 读取 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sid = 'study_' + 'd' * 32
        self.home = self.root / 'studies' / self.sid
        self.home.mkdir(parents=True)
        (self.home / 'manifest.json').write_text('{"current":1}', encoding='utf-8')
        self.path = self.home / '登记 原件.json'
        self.raw = b'{"value":1,"nested":[2,3]}'
        self.path.write_bytes(self.raw)
        self.ref = file_record(self.home, self.path, 'source')
        self.workflow = SimpleNamespace(root=self.root)
        self.manifest = {'study_id': self.sid, 'revision': 1}
        self.app = SimpleNamespace(settings=SimpleNamespace(data_root=self.root))
        self.calls = []
        namespace = {'__name__': core.__name__, 'calls': self.calls,
                     'read_json': read_json, 'verified_file': verified_file}
        self.bound_source = FunctionType(source.__code__, namespace, 'source_binding')
        self.bound_info = FunctionType(info.__code__, {'__name__': api.__name__, 'core': core,
                                      'deepcopy': deepcopy}, 'info', info.__defaults__)
        self.enterContext(patch.object(core, 'source_binding', self.bound_source))
        self.enterContext(patch.object(api, 'info', self.bound_info))

    def read(self, change=None):
        """使用生产HTTP只读入口，不能在测试里另套一个成功的缓存。"""
        return App._json_read(self.app, self.sid, api.info, self.workflow, self.manifest,
                              self.ref, 'run_original', change)

    def test_same_request_reuses_verified_binding_and_next_request_rechecks(self):
        first, second = self.read()
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 1)
        second['value']['nested'].append(99)
        self.assertEqual(self.read()[0]['value']['nested'], [2, 3])
        self.assertEqual(len(self.calls), 2)

    def test_same_size_change_with_restored_mtime_is_rejected_before_response(self):
        stamp = self.path.stat()
        def corrupt():
            self.path.write_bytes(self.raw.replace(b':1', b':9'))
            os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaises(ContractError):
            self.read(corrupt)

    def test_manifest_changed_before_response_is_rejected(self):
        with self.assertRaises(ContractError):
            self.read(lambda: (self.home / 'manifest.json').write_text('{"current":2}'))

    def test_next_request_cannot_reuse_success_after_corruption(self):
        self.read()
        self.path.write_bytes(self.raw.replace(b':1', b':9'))
        with self.assertRaises(ContractError):
            self.read()

    def test_original_namespace_and_unscoped_calls_keep_strict_reads(self):
        original = self.bound_source.__globals__['verified_file']
        self.read()
        self.assertIs(self.bound_source.__globals__['verified_file'], original)
        self.path.write_bytes(b'broken')
        with self.assertRaises(ContractError):
            core.source_binding(self.workflow, self.manifest, self.ref, 'run_original')


if __name__ == '__main__':
    unittest.main()
