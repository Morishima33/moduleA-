"""真实Windows虚拟环境后代核验；只建合成预算位，不访问研究或启动科学工具。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CHILD = '''
import json,os,sys
from pathlib import Path
from modulea.tasks import rescue_worker_io
active=json.loads(sys.argv[1]);runtime=Path(sys.argv[2])
check=getattr(rescue_worker_io,'budget_owns_current_process',lambda a,r:a['pid']==os.getppid())
bad=dict(active);proof=json.loads(active['process_identity']);proof['birth']+=1
bad['process_identity']=json.dumps(proof)
wrong=dict(active,task_id='task_'+'f'*32)
print(json.dumps(dict(accepted=check(active,runtime),stale=check(bad,runtime),wrong_task=check(wrong,runtime),no_lease=check(active,runtime/'missing'),parent=os.getppid())))
'''

WORKER = '''
import json,os,subprocess,sys
from pathlib import Path
from modulea.tasks.compute_budget import ComputeBudget
from modulea.tasks.process_tree import contain_current_worker
from modulea.tasks.process_identity import identity
root=Path(sys.argv[1]);lease=ComputeBudget(root).try_acquire()
assert lease is not None
task='task_'+'a'*32;tree=contain_current_worker();lease.bind(task,tree)
active=dict(task_id=task,pid=os.getpid(),resource_owner_pid=os.getpid(),process_identity=json.dumps(identity(os.getpid())),state='running',kind='plan_rescue_worker_io')
result=subprocess.run([sys.executable,'-c',sys.argv[2],json.dumps(active),str(root)],capture_output=True,text=True,timeout=20)
assert result.returncode==0,result.stderr
print(json.dumps(dict(active=active,child=json.loads(result.stdout))),flush=True)
sys.stdin.readline();lease.close()
'''


@unittest.skipUnless(os.name=='nt','Windows虚拟环境与Job实际验证')
class WorkerBudgetOriginTests(unittest.TestCase):
    def test_venv_job_descendant_is_owned_and_other_process_is_rejected(self):
        """合法Job后代通过；旧出生、错任务、缺预算和Job外进程保持拒绝。"""
        with TemporaryDirectory(prefix='worker_origin_') as temp:
            worker=subprocess.Popen([sys.executable,'-c',WORKER,temp,CHILD],stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                line=worker.stdout.readline()
                self.assertTrue(line,'合成预算worker未就绪')
                value=json.loads(line)
                self.assertTrue(value['child']['accepted'],value)
                self.assertFalse(value['child']['stale'])
                self.assertFalse(value['child']['wrong_task'])
                self.assertFalse(value['child']['no_lease'])
                unrelated=subprocess.run([sys.executable,'-c',CHILD,json.dumps(value['active']),temp],
                                         capture_output=True,text=True,timeout=20)
                self.assertEqual(unrelated.returncode,0,unrelated.stderr)
                self.assertFalse(json.loads(unrelated.stdout)['accepted'])
            finally:
                if worker.poll() is None:
                    worker.stdin.write('stop\n');worker.stdin.flush()
                _,stderr=worker.communicate(timeout=20)
                self.assertEqual(worker.returncode,0,stderr)


if __name__=='__main__':unittest.main()
