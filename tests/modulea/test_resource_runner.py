"""真实独立进程验证全局排队、取消、崩溃后代清理和磁盘关口，全部为合成任务。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from modulea.config import Settings,load_settings
from modulea.tasks.manager import TaskManager,_pid_alive


CHILD=r'''
import json,os,sys,time,subprocess
from pathlib import Path
from modulea.config import Settings
from modulea.tasks.manager import TaskManager
from modulea.tasks.resource_runner import run_with_budget
root=Path(sys.argv[1]);tid=sys.argv[2];mode=sys.argv[3]
settings=Settings(data_root=root,runtime_dir=root/'runtime',compute_min_free_bytes=0)
if mode=='disk':
    import modulea.tasks.resource_runner as rr
    rr.disk_space=lambda *_:{'free_bytes':1,'required_bytes':2,'sufficient':False}
def execute(settings,task_id):
    manager=TaskManager(settings)
    assert manager.claim(task_id,os.getpid())
    (root/(task_id+'.started')).write_text('started')
    if mode=='crash':
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(60)'])
        (root/(task_id+'.child')).write_text(str(child.pid))
        os._exit(17)
    if mode=='hold':
        while not (root/(task_id+'.release')).exists():time.sleep(.05)
    manager.finish(task_id,'succeeded',message_zh='合成资源测试完成')
    return 0
sys.exit(run_with_budget(settings,tid,execute))
'''


class ResourceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='resource_runner_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.settings=Settings(data_root=self.root,runtime_dir=self.root/'runtime',compute_min_free_bytes=0)
        self.manager=TaskManager(self.settings)

    def new_task(self,kind='continue'):
        """使用实际登记和互斥，暂不启动生产科学worker。"""
        with patch.object(self.manager,'_spawn'):
            task,created=self.manager.submit('synthetic_'+str(time.monotonic_ns()),kind,'资源测试')
        self.assertTrue(created);return task['task_id']

    def start(self,tid,mode='finish'):
        """每项测试实际启动独立进程，禁止给unittest主进程设置kill-on-close。"""
        process=subprocess.Popen([sys.executable,'-B','-c',CHILD,str(self.root),tid,mode],stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,encoding='utf8',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
            start_new_session=os.name!='nt')
        self.addCleanup(self.stop,process)
        with self.manager._connect() as db:
            db.execute("UPDATE tasks SET pid=? WHERE task_id=? AND state='queued' AND resource_owner_pid IS NULL",(process.pid,tid))
        return process

    def stop(self,process):
        """只清理本测试创建并持有句柄的进程。"""
        if process.poll() is None:process.terminate()
        process.communicate(timeout=10)

    def until(self,predicate):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.05)
        self.fail('合成任务未在12秒内达到预期资源状态')

    def test_two_real_workers_wait_and_release_without_overlapping(self):
        first=self.new_task();one=self.start(first,'hold')
        self.until(lambda:(self.root/(first+'.started')).exists())
        second=self.new_task();two=self.start(second)
        self.until(lambda:bool(self.manager.get(second).get('progress')))
        self.assertEqual(self.manager.get(second)['state'],'queued')
        self.assertIn('等待计算资源',self.manager.get(second)['progress']['step_zh'])
        self.assertFalse((self.root/(second+'.started')).exists())
        (self.root/(first+'.release')).write_text('release')
        self.assertEqual(one.wait(timeout=10),0)
        self.assertEqual(two.wait(timeout=10),0)
        self.assertEqual(self.manager.get(second)['state'],'succeeded')
        self.assertIsNone(self.manager.get(second)['progress'])

    def test_cancel_waiter_never_executes_and_does_not_cancel_holder(self):
        first=self.new_task();one=self.start(first,'hold')
        self.until(lambda:(self.root/(first+'.started')).exists())
        second=self.new_task();two=self.start(second)
        self.until(lambda:bool(self.manager.get(second).get('progress')))
        self.manager.cancel(second);two.wait(timeout=10)
        self.assertEqual(self.manager.get(second)['state'],'cancelled')
        self.assertFalse((self.root/(second+'.started')).exists())
        self.assertIsNone(one.poll())
        (self.root/(first+'.release')).write_text('release');self.assertEqual(one.wait(timeout=10),0)

    @unittest.skipUnless(os.name=='nt','Windows Job实际进程树测试，POSIX保留存活进程组阻断')
    def test_abrupt_worker_exit_kills_child_before_slot_reuse(self):
        first=self.new_task();one=self.start(first,'crash');self.assertEqual(one.wait(timeout=10),17)
        pid=int((self.root/(first+'.child')).read_text())
        self.until(lambda:not _pid_alive(pid))
        self.manager.reconcile();self.assertEqual(self.manager.get(first)['state'],'interrupted')
        second=self.new_task();two=self.start(second);self.assertEqual(two.wait(timeout=10),0)
        self.assertTrue((self.root/(second+'.started')).exists())
        self.assertFalse(_pid_alive(pid))

    def test_disk_failure_never_calls_scientific_handler(self):
        tid=self.new_task();process=self.start(tid,'disk');self.assertEqual(process.wait(timeout=10),1)
        row=self.manager.get(tid);self.assertEqual(row['state'],'failed')
        self.assertIn('低于服务器运行余量',row['error_zh'])
        self.assertFalse((self.root/(tid+'.started')).exists())

    def test_light_metadata_task_does_not_wait_for_science_slot(self):
        first=self.new_task();one=self.start(first,'hold')
        self.until(lambda:(self.root/(first+'.started')).exists())
        second=self.new_task('a06_plan_input');two=self.start(second)
        self.assertEqual(two.wait(timeout=10),0);self.assertIsNone(one.poll())
        (self.root/(first+'.release')).write_text('release');self.assertEqual(one.wait(timeout=10),0)

    def test_unknown_reservation_fails_closed_without_overwriting(self):
        folder=self.settings.runtime_dir/'compute_slots';folder.mkdir()
        path=folder/'slot_0.json';original='{"schema_version":999,"tree":{}}';path.write_text(original)
        tid=self.new_task();process=self.start(tid);self.assertEqual(process.wait(timeout=10),1)
        self.assertEqual(self.manager.get(tid)['state'],'failed');self.assertEqual(path.read_text(),original)
        self.assertFalse((self.root/(tid+'.started')).exists())

    def test_server_budget_is_propagated_to_real_spawn_environment(self):
        settings=Settings(data_root=self.root,runtime_dir=self.root/'other',compute_slots=2,compute_min_free_bytes=98765)
        manager=TaskManager(settings)
        with patch('modulea.tasks.manager.subprocess.Popen') as spawn:
            spawn.return_value.pid=os.getpid();manager.submit('synthetic_env','continue','资源测试')
        env=spawn.call_args.kwargs['env']
        self.assertEqual(env['MODULEA_COMPUTE_SLOTS'],'2');self.assertEqual(env['MODULEA_COMPUTE_MIN_FREE_BYTES'],'98765')
        with patch.dict(os.environ,{'MODULEA_COMPUTE_SLOTS':'3','MODULEA_COMPUTE_MIN_FREE_BYTES':'42'}),patch('modulea.config._read_local_toml',return_value={}):
            value=load_settings();self.assertEqual((value.compute_slots,value.compute_min_free_bytes),(3,42))
        for invalid in (False,0,33,1.2):
            with self.assertRaises(ValueError):Settings(compute_slots=invalid).validate_resources()
        with self.assertRaises(ValueError):Settings(compute_min_free_bytes=True).validate_resources()

    def test_duplicate_worker_cannot_steal_wait_or_execution(self):
        tid=self.new_task();one=self.start(tid,'hold')
        self.until(lambda:(self.root/(tid+'.started')).exists())
        before=self.manager._raw(tid);two=self.start(tid)
        self.assertEqual(two.wait(timeout=10),1)
        self.assertEqual(self.manager._raw(tid)['pid'],before['pid'])
        (self.root/(tid+'.release')).write_text('release');self.assertEqual(one.wait(timeout=10),0)

    def test_existing_unbudgeted_worker_blocks_upgrade_overlap(self):
        """升级前进程没有租约字段，仍必须按实际活进程保守等待。"""
        old=self.new_task();self.manager.update(old,state='running',pid=os.getpid())
        tid=self.new_task();process=self.start(tid)
        self.until(lambda:bool(self.manager.get(tid).get('progress')))
        self.assertFalse((self.root/(tid+'.started')).exists())
        self.manager.update(old,state='succeeded')
        self.assertEqual(process.wait(timeout=10),0)

    def test_actual_cli_worker_publishes_scientific_selection_without_review(self):
        """生产TaskManager→CLI资源关口→真实科学选择；不替换handler或模拟结果。"""
        from tests.modulea.test_plan_stages import fixture,body
        from science_modules import plan_compounds
        from intersection_flow import validate_selection
        from modulea.core import plan_compounds as flow
        from modulea.tasks.process_tree import tree_alive
        w,sid,_=fixture(self.root)
        w.validators['A03_SELECT']=plan_compounds.validator(self.root,validate_selection)
        a03=w.execute_analysis_plan_stage(sid,body(w,sid,'A03'))
        w.review(sid,a03['run_id'],'approved','资源隔离测试','合成上游已检查')
        before=w.load(sid);value=flow.info(w,sid)
        payload=dict({k:v for k,v in value.items() if k.startswith('expected_')},operator='资源隔离测试',
                     reason='仅测试本地科学选择与资源入口',confirmed=True)
        task,created=self.manager.submit(sid,'a03_plan_selection','资源隔离测试',payload)
        self.assertTrue(created)
        self.until(lambda:self.manager.get(task['task_id'])['state'] not in ('queued','running'))
        actual=self.manager.get(task['task_id']);self.assertEqual(actual['state'],'succeeded',self.manager.log(task['task_id']))
        after=w.load(sid);rid=after['current']['A03_SELECT'];result=w.result(after,rid)
        self.assertEqual(after['reviews'],before['reviews']);self.assertFalse(w.approved(after,rid))
        self.assertEqual(result['summary']['目标成分数'],15);self.assertEqual(result['summary']['主候选数'],1)
        self.assertEqual(after['current']['A03'],before['current']['A03'])
        record=json.loads((self.settings.runtime_dir/'compute_slots/slot_0.json').read_text('utf8'))
        self.assertEqual(record['task_id'],task['task_id'])
        self.until(lambda:not tree_alive(record['tree']))
