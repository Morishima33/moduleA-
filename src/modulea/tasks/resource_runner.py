"""CLI后台任务资源关口：全局排队、磁盘余量和真实进程树保护，不运行科学计算。"""
import os
import time
from .compute_budget import ComputeBudget,disk_space
from .manager import TaskManager,_now,_pid_alive
from .process_tree import contain_current_worker

# 仅保存已有明确决定、固定名单或元数据的轻任务不占科学计算位。
LIGHTWEIGHT={'a02_scope_review','a03_selection','a04_plan_selection','a06_plan','a06_candidates',
             'a06_plan_input','a01_resolve','a06_coverage_confirm'}


def queued_update(manager,task_id,**fields):
    """只更新仍排队的本任务，不能覆盖并发取消或另一worker的认领。"""
    import json
    if fields.get('progress') is not None:fields['progress']=json.dumps(fields['progress'],ensure_ascii=False)
    keys=', '.join(f'{key}=?' for key in fields)
    with manager._connect() as db:
        return db.execute(f"UPDATE tasks SET {keys} WHERE task_id=? AND state='queued' AND (pid IS NULL OR pid=?)",
            (*fields.values(),task_id,os.getpid())).rowcount==1


def older_unbudgeted_processes(manager,task_id):
    """兼容升级前已启动的旧worker；未纳入租约的存活重任务先完成，不并行抢占。"""
    with manager._connect() as db:
        rows=db.execute("SELECT task_id,kind,pid FROM tasks WHERE state IN ('queued','running') AND resource_owner_pid IS NULL AND task_id!=?",(task_id,)).fetchall()
    return any(row['kind'] not in LIGHTWEIGHT and _pid_alive(row['pid']) for row in rows)


def run_with_budget(settings,task_id,runner):
    """独立CLI进程先取得资源再交原worker认领；等待/失败期间没有科学运行。"""
    manager=TaskManager(settings);task=manager._raw(task_id)
    if not task:return 2
    if not manager.claim_resources(task_id,os.getpid()):return 1
    if task['kind'] in LIGHTWEIGHT:return runner(settings,task_id)
    lease=None
    try:
        budget=ComputeBudget(settings.runtime_dir,settings.compute_slots)
        waiting=False
        while lease is None:
            current=manager._raw(task_id)
            if not current or current['state']!='queued' or current.get('resource_owner_pid')!=os.getpid():return 1
            lease=None if older_unbudgeted_processes(manager,task_id) else budget.try_acquire()
            if lease is None:
                if not waiting:
                    if not queued_update(manager,task_id,message_zh='等待计算资源，尚未开始科学执行',
                         progress={'step_zh':'等待计算资源，尚未计算','done':0,'total':1}):return 1
                    print('等待计算资源，尚未计算；取消不会开始科学运行。',flush=True);waiting=True
                time.sleep(0.25)
        # 先绑定真实进程树。即使取消/崩溃发生在科学子进程创建期间，也不会误放计算位。
        tree=contain_current_worker();lease.bind(task_id,tree)
        for label,path in (('研究磁盘',settings.data_root),('运行磁盘',settings.runtime_dir)):
            fact=disk_space(path,settings.compute_min_free_bytes)
            if not fact['sufficient']:
                raise ValueError(f"{label}可用{fact['free_bytes']}字节，低于服务器运行余量{fact['required_bytes']}字节，尚未开始计算；后续科学产物大小仍未知")
        if not queued_update(manager,task_id,message_zh=None,progress=None):return 1
        return runner(settings,task_id)
    except Exception as error:
        print(f'计算资源预检失败（{type(error).__name__}）：{error}',flush=True)
        queued_update(manager,task_id,state='failed',finished_at=_now(),error_zh=f'计算资源预检失败：{error}；原任务未自动重跑，研究原件保留')
        return 1
    finally:
        if lease:lease.close()
