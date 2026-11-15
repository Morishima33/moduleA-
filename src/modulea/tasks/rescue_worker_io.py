"""有界I/O恢复沿用原单研究队列、资源预算和进程树，不建立独立调度。"""
import json
import os
import subprocess
from pathlib import Path

from contracts import require
from modulea.core.worker_io import VERSION


def budget_owns_current_process(active, runtime_dir):
    """核原预算位、worker出生及实际Job归属，兼容Windows虚拟环境启动中间进程。"""
    from .process_identity import identity
    try:
        if not active or active.get('state') != 'running' or active.get('kind') != 'plan_rescue_worker_io':
            return False
        pid = active.get('pid')
        expected = json.loads(active.get('process_identity') or 'null')
        if not expected or active.get('resource_owner_pid') != pid or identity(pid) != expected:
            return False
        root = Path(runtime_dir).resolve()
        folder = (root / 'compute_slots').resolve()
        if not folder.is_relative_to(root):
            return False
        for path in folder.glob('slot_*.json'):
            if not path.resolve().is_relative_to(folder):
                continue
            raw = path.read_bytes()
            record = json.loads(raw)
            if record.get('schema_version') != 1 or record.get('task_id') != active['task_id'] or record.get('pid') != pid:
                continue
            tree = record.get('tree', {})
            if os.name == 'nt':
                import re
                from .process_tree import _windows
                name = tree.get('job_name')
                if tree.get('platform') != 'windows' or not isinstance(name, str) or not re.fullmatch(r'Local\\ModuleACompute_[0-9a-f]{32}', name):
                    continue
                c, w, kernel = _windows()
                handle = kernel.OpenJobObjectW(4, False, name)  # 只读JOB_OBJECT_QUERY。
                if not handle:
                    continue
                try:
                    query = kernel.IsProcessInJob
                    query.argtypes = [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)]
                    query.restype = w.BOOL
                    member = w.BOOL()
                    owned = bool(query(kernel.GetCurrentProcess(), handle, c.byref(member)) and member.value)
                finally:
                    kernel.CloseHandle(handle)
            else:
                owned = (tree.get('platform') == 'posix' and tree.get('pgid') == pid
                         and os.getppid() == pid and os.getpgrp() == pid and os.getpgid(pid) == pid)
            if owned and identity(pid) == expected and path.read_bytes() == raw:
                return True
        return False
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def run(settings, task, manager):
    """只有当前预算worker可启动隔离科学子进程，服务器配置决定工具和解释器。"""
    # 科学-I子进程忽略PYTHONUTF8环境变量；两端显式UTF-8保留真实进度与错误。
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    value = json.loads(task['payload'])
    require(set(value) == {'request','run_id','adapter_version'} and value['adapter_version'] == VERSION,
            'I/O恢复任务字段或适配版本不同')
    active = manager.active_for(task['study_id'])
    require(active and active['task_id'] == task['task_id'], '本研究已有其他活动任务')
    require(settings.science_tools_root is not None and settings.science_repair_packages is not None,
            '未配置原科学工具和修补环境')
    folder = settings.runtime_dir/'worker_io_requests'/task['task_id']
    folder.mkdir(parents=True,exist_ok=False)
    request, output = folder/'request.json',folder/'result.json'
    request.write_text(json.dumps(value['request'],ensure_ascii=False),encoding='utf-8')
    command = [settings.science_python,'-I','-S','-B','-X','utf8',str(settings.project_root/'tools/run_rescue_worker_io.py'),
        'execute','--authorize-adapter','--task-id',task['task_id'],'--runtime-dir',str(settings.runtime_dir),
        '--request-file',str(request),'--result-file',str(output),'--data-root',str(settings.data_root),
        '--tools-root',str(settings.science_tools_root),'--repair-packages',str(settings.science_repair_packages),
        '--study',task['study_id'],'--expected-run-id',value['run_id']]
    with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
            encoding='utf-8',errors='replace',env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')) as process:
        for line in process.stdout:
            print(line,end='',flush=True)
            if line.startswith('PROGRESS '):
                manager.update(task['task_id'],progress={'step_zh':line[9:].strip(),'done':0,'total':1})
        require(process.wait() == 0 and output.is_file(), '原二版恢复未完整结束，已登记对象与失败日志保持')
    result = json.loads(output.read_text('utf-8'))
    require(result.get('result_run_id') == value['run_id'] and result.get('outcome') == 'success',
            '恢复没有形成指定原运行的完整成功结果')
    return '原二版已完整归档：'+value['run_id']+'；新结果仍须独立科研复核'
