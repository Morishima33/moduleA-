"""任务启动、恢复和数据库释放的回归检查；仅使用临时任务库。"""
from __future__ import annotations
import gc
import os
import subprocess
import sys
import tempfile
import unittest
import time
import warnings
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from modulea.config import Settings
from modulea.tasks.manager import TaskManager, _pid_alive
from modulea.tasks.worker import run_task

class TaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = Settings(project_root=root, data_root=root, runtime_dir=root / "runtime", science_python=str(root / "missing-python.exe"))
        self.manager = TaskManager(self.settings)
    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()
    def seed(self, task_id="task_test", state="queued", pid=None, age=0):
        created = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
        with self.manager._connect() as db:
            db.execute("INSERT INTO tasks (task_id,study_id,kind,state,pid,log_path,created_at) VALUES (?,?,?,?,?,?,?)", (task_id,"study_test","continue",state,pid,str(self.manager.log_dir / (task_id+".log")),created))
        return task_id

    def test_spawn_retains_real_child_until_exit_without_changing_queued_state_or_resource_warning(self):
        """真实短子进程退出前保留句柄，等待回收不代表科研任务成功或消耗资源位。"""
        tid=self.seed();popen=subprocess.Popen;children=[]
        def start(*args,**kwargs):
            process=popen([sys.executable,'-c','import time; time.sleep(1)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            children.append(weakref.ref(process));return process
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always',ResourceWarning)
            with patch('modulea.tasks.manager.subprocess.Popen',side_effect=start):
                self.manager._spawn(tid,self.manager.log_dir/(tid+'.log'))
            gc.collect();self.assertIsNotNone(children[0]())
            self.assertEqual(self.manager.get(tid)['state'],'queued')
            deadline=time.monotonic()+5
            while children[0]() is not None and time.monotonic()<deadline:time.sleep(.05);gc.collect()
            self.assertIsNone(children[0]());self.assertFalse(any(issubclass(row.category,ResourceWarning) for row in seen))
        self.assertEqual(self.manager.get(tid)['state'],'queued');self.assertIsNone(self.manager._raw(tid)['resource_owner_pid'])
    def test_spawn_failure_is_terminal_and_retry_creates_new_task(self):
        first, created = self.manager.submit("study_test", "continue", "测试")
        self.assertTrue(created)
        self.assertEqual(first["state"], "failed")
        self.assertIn("启动", first["error_zh"])
        self.assertIsNotNone(first["finished_at"])
        self.assertIsNone(self.manager.active_for("study_test"))
        second, created = self.manager.retry(first["task_id"], "重试")
        self.assertTrue(created)
        self.assertNotEqual(first["task_id"], second["task_id"])
    def test_spawn_always_closes_log_stream(self):
        opened = []
        real_open = open
        def track(*args, **kwargs):
            stream = real_open(*args, **kwargs)
            opened.append(stream)
            return stream
        with patch("modulea.tasks.manager.open", side_effect=track, create=True), patch("modulea.tasks.manager.subprocess.Popen", side_effect=OSError("启动测试失败")):
            try:
                self.manager.submit("study_test", "continue", "测试")
            except OSError:
                pass
        self.assertTrue(opened)
        self.assertTrue(all(s.closed for s in opened))
    def test_connections_release_database_without_gc(self):
        self.seed()
        gc.collect()  # 清理测试准备阶段对象；后续操作不得依赖 GC。
        for _ in range(5):
            self.manager.get("task_test")
            self.manager.list()
            self.manager.update("task_test", message_zh="数据库释放检查")
        renamed = self.manager.db_path.with_suffix(".renamed")
        self.manager.db_path.rename(renamed)
        renamed.rename(self.manager.db_path)
    def test_transaction_rolls_back_and_closes_on_error(self):
        self.seed()
        with self.assertRaises(RuntimeError):
            with self.manager._connect() as db:
                db.execute("UPDATE tasks SET state='failed' WHERE task_id='task_test'")
                raise RuntimeError("回滚检查")
        self.assertEqual(self.manager.get("task_test")["state"], "queued")
        with self.assertRaises(Exception):
            db.execute("SELECT 1")  # 上下文退出之后连接必须已经关闭。
    def test_reconcile_preserves_startup_and_marks_abandoned_queue(self):
        self.seed("task_recent")
        self.seed("task_abandoned", age=120)
        self.seed("task_running", state="running", pid=99999999)
        self.manager.reconcile()
        self.assertEqual(self.manager.get("task_recent")["state"], "queued")
        self.assertEqual(self.manager.get("task_abandoned")["state"], "interrupted")
        self.assertEqual(self.manager.get("task_running")["state"], "interrupted")
        self.assertIn("重试", self.manager.get("task_abandoned")["error_zh"])
    def test_process_probe_never_terminates_live_child(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], creationflags=flags)
        try:
            for _ in range(3):
                self.assertTrue(_pid_alive(child.pid))
                self.assertIsNone(child.poll())
            child.terminate()
            child.wait(timeout=10)
            self.assertFalse(_pid_alive(child.pid))
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)

    @unittest.skipUnless(os.name == "nt", "仅 Windows 禁止使用 os.kill 探测")
    def test_windows_probe_does_not_use_kill(self):
        with patch("modulea.tasks.manager.os.kill", side_effect=AssertionError("禁止终止")) as kill:
            self.assertTrue(_pid_alive(os.getpid()))
        kill.assert_not_called()

    def test_live_queued_task_not_interrupted(self):
        self.seed(pid=os.getpid(), age=120)
        self.manager.reconcile()
        self.assertEqual(self.manager.get("task_test")["state"], "queued")
    def test_duplicate_submission_does_not_spawn_twice(self):
        with patch.object(self.manager, "_spawn") as spawn:
            first, new = self.manager.submit("study_test", "continue", "测试")
            second, repeated = self.manager.submit("study_test", "continue", "测试")
        self.assertTrue(new)
        self.assertFalse(repeated)
        self.assertEqual(first["task_id"], second["task_id"])
        spawn.assert_called_once()
    def test_worker_claims_own_pid_before_handler(self):
        self.seed()
        def handler(settings, task, manager):
            row = manager._raw(task["task_id"])
            self.assertEqual(row["state"], "running")
            self.assertEqual(row["pid"], os.getpid())
            return "只运行测试处理器"
        with patch.dict("modulea.tasks.worker.HANDLERS", {"continue": handler}):
            self.assertEqual(run_task(self.settings, "task_test"), 0)
        self.assertEqual(self.manager.get("task_test")["state"], "succeeded")
    def test_worker_completion_preserves_cancelled_state(self):
        self.seed(state="running", pid=os.getpid())
        self.manager.update("task_test", state="cancelled")
        self.manager.finish("task_test", "succeeded", message_zh="不应覆盖取消")
        self.assertEqual(self.manager.get("task_test")["state"], "cancelled")

    def test_worker_does_not_start_cancelled_task(self):
        self.seed(state="cancelled")
        handler = Mock(return_value="不应调用")
        with patch.dict("modulea.tasks.worker.HANDLERS", {"continue": handler}):
            self.assertNotEqual(run_task(self.settings, "task_test"), 0)
        handler.assert_not_called()
        self.assertEqual(self.manager.get("task_test")["state"], "cancelled")

if __name__ == "__main__":
    unittest.main()
