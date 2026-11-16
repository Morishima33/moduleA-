"""资源任务夹具的中文错误日志必须可读取，不能让后台读取线程异常漏出测试结果。"""
import threading
from unittest import TestCase
from unittest.mock import patch
from tests.modulea import test_resource_runner as fixture


class ResourceRunnerEncodingTests(TestCase):
    def test_expected_resource_failure_does_not_crash_output_reader(self):
        seed=fixture.ResourceRunnerTests('test_disk_failure_never_calls_scientific_handler')
        failures=[]
        with patch.object(threading,'excepthook',side_effect=failures.append):
            seed.setUp()
            try:seed.test_disk_failure_never_calls_scientific_handler()
            finally:seed.doCleanups()
        self.assertEqual(failures,[],'子进程本地编码与UTF8读取不一致，不能把漏报的线程异常记为通过')
