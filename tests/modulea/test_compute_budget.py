"""跨进程资源位的实际互斥与释放，不运行任何科学计算。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from collections import namedtuple
from modulea.tasks.compute_budget import ComputeBudget,disk_space


class ComputeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='compute_budget_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def child(self,mode):
        """真实新进程共享相同资源文件，不能用进程内线程锁冒充全局预算。"""
        script="from modulea.tasks.compute_budget import ComputeBudget;import sys;b=ComputeBudget(sys.argv[1]);r=b.try_acquire();print('acquired' if r else 'busy');sys.exit(0 if bool(r)==(sys.argv[2]=='free') else 1)"
        return subprocess.run([sys.executable,'-B','-c',script,str(self.root),mode],capture_output=True,text=True,timeout=15)

    def test_real_process_contention_and_release(self):
        lease=ComputeBudget(self.root).try_acquire();self.assertIsNotNone(lease)
        busy=self.child('busy');self.assertEqual(busy.returncode,0,busy.stderr);self.assertEqual(busy.stdout.strip(),'busy')
        lease.close();lease.close()
        free=self.child('free');self.assertEqual(free.returncode,0,free.stderr)
        # 上一个子进程已经退出；系统锁必须确实释放。
        with ComputeBudget(self.root).try_acquire() as again:self.assertEqual(again.index,0)

    def test_configured_two_slots_are_not_unbounded(self):
        budget=ComputeBudget(self.root,2);first=budget.try_acquire();second=budget.try_acquire()
        self.addCleanup(first.close);self.addCleanup(second.close)
        self.assertNotEqual(first.index,second.index);self.assertIsNone(budget.try_acquire())
        first.close();third=budget.try_acquire();self.addCleanup(third.close);self.assertIsNotNone(third)

    def test_exception_releases_without_deleting_lock(self):
        with self.assertRaises(ValueError):
            with ComputeBudget(self.root).try_acquire():raise ValueError('合成任务失败')
        self.assertTrue((self.root/'compute_slots/slot_0.lock').is_file())
        lease=ComputeBudget(self.root).try_acquire();self.assertIsNotNone(lease);lease.close()

    def test_disk_check_is_read_only_and_uses_actual_minimum(self):
        usage=namedtuple('Usage','total used free')(1000,900,100)
        with patch('modulea.tasks.compute_budget.shutil.disk_usage',return_value=usage):
            self.assertFalse(disk_space(self.root/'not-created',101)['sufficient'])
            self.assertTrue(disk_space(self.root,100)['sufficient'])
        self.assertFalse((self.root/'not-created').exists())
        for invalid in (-1,True,1.2):
            with self.assertRaises(ValueError):disk_space(self.root,invalid)
        for invalid in (0,False,1.2):
            with self.assertRaises(ValueError):ComputeBudget(self.root,invalid)
