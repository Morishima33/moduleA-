"""真实独立进程树取消与PID归属保护；不使用真实研究或科学工具。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulea.config import Settings
from modulea.tasks.manager import TaskManager
from modulea.tasks.process_identity import identity, terminate_owned


class NativeProcessCancelTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='任务树 取消 ');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()

    def launch(self,command):
        """每个测试子进程使用自己的组；清理只操作测试创建的句柄。"""
        value=subprocess.Popen(command,start_new_session=os.name!='nt',stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def cleanup():
            if value.poll() is None:
                value.kill()
            value.communicate(timeout=5)
        self.addCleanup(cleanup)
        return value

    def test_real_task_tree_cancel_leaves_unrelated_process_alive(self):
        marker=self.root/'child.json'
        child="import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)"
        script=("import sys,subprocess,json,time; from pathlib import Path; "
                "from modulea.tasks.process_tree import contain_current_worker; contain_current_worker(); "
                "p=subprocess.Popen([sys.executable,'-c',sys.argv[2]]); "
                "Path(sys.argv[1]).write_text(json.dumps({'pid':p.pid})); time.sleep(120)")
        parent=self.launch([sys.executable,'-c',script,str(marker),child])
        unrelated=self.launch([sys.executable,'-c','import time;time.sleep(120)'])
        until=time.monotonic()+10
        while not marker.is_file() and parent.poll() is None and time.monotonic()<until:time.sleep(.05)
        self.assertTrue(marker.is_file(),'合成任务树未能启动')
        kid=json.loads(marker.read_text())['pid']
        proof=identity(parent.pid)
        self.assertIsNotNone(proof,'操作系统无法核对本任务出生标识')
        manager=TaskManager(Settings(data_root=self.root/'data',runtime_dir=self.root/'runtime'))
        with patch.object(manager,'_spawn'):
            task,_=manager.submit('study_synthetic','plan_system_receptor_rescue_v2','隔离取消核验',{})
        manager.update(task['task_id'],state='running',pid=parent.pid,process_identity=json.dumps(proof))
        value=manager.cancel(task['task_id'])
        self.assertEqual(value['state'],'cancelled')
        parent.wait(timeout=5)
        until=time.monotonic()+5
        while identity(kid) and time.monotonic()<until:time.sleep(.05)
        self.assertIsNone(identity(kid),'本任务后代仍存在')
        self.assertIsNone(unrelated.poll(),'取消影响了另一个独立进程')
        self.assertFalse((self.root/'data/studies').exists())

    def test_foreign_or_stale_birth_identity_never_sends_a_signal(self):
        live=self.launch([sys.executable,'-c','import time;time.sleep(120)'])
        correct=identity(live.pid)
        self.assertIsNotNone(correct)
        changed=dict(correct,birth='another-process')
        with patch('modulea.tasks.process_identity.os.killpg',side_effect=AssertionError('不可发送信号'),create=True):
            with self.assertRaises(ValueError):terminate_owned(live.pid,changed)
            with self.assertRaises(ValueError):terminate_owned(live.pid,None)
        self.assertIsNone(live.poll())


if __name__=='__main__':unittest.main()
