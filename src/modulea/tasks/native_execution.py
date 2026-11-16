"""本平台计算使用原任务队列与进程树；隔离子进程只从服务器配置取得工具。"""
import json
import os
import subprocess
import sys
from pathlib import Path

from contracts import require
from modulea.core.bounded_evidence import digest_file


def budget_owns_current_process(active, runtime_dir):
    """复用原预算出生/计算位/实际Job核验语义，明确只接受原生任务。"""
    from .process_identity import identity
    try:
        if not active or active.get('state') != 'running' or active.get('kind') != 'native_a06':
            return False
        pid = active.get('pid')
        expected = json.loads(active.get('process_identity') or 'null')
        if not expected or active.get('resource_owner_pid') != pid or identity(pid) != expected:
            return False
        root = Path(runtime_dir).resolve(); folder = (root/'compute_slots').resolve()
        if not folder.is_relative_to(root): return False
        for path in folder.glob('slot_*.json'):
            if not path.resolve().is_relative_to(folder): continue
            raw = path.read_bytes(); record = json.loads(raw)
            if record.get('schema_version') != 1 or record.get('task_id') != active['task_id'] or record.get('pid') != pid:
                continue
            tree = record.get('tree', {})
            if os.name == 'nt':
                import re
                from .process_tree import _windows
                name = tree.get('job_name')
                if tree.get('platform') != 'windows' or not isinstance(name, str) or not re.fullmatch(r'Local\\ModuleACompute_[0-9a-f]{32}', name):
                    continue
                c, w, kernel = _windows(); handle = kernel.OpenJobObjectW(4, False, name)
                if not handle: continue
                try:
                    query = kernel.IsProcessInJob
                    query.argtypes = [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)]; query.restype = w.BOOL
                    member = w.BOOL()
                    owned = bool(query(kernel.GetCurrentProcess(), handle, c.byref(member)) and member.value)
                finally:
                    kernel.CloseHandle(handle)
            else:
                owned = (tree.get('platform') == 'posix' and tree.get('pgid') == pid
                         and os.getppid() == pid and os.getpgrp() == pid and os.getpgid(pid) == pid)
            if owned and identity(pid) == expected and path.read_bytes() == raw: return True
        return False
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def run(settings,task,manager):
    """核当前配置再启动-I子进程，进度及完整日志沿原任务登记。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    value=json.loads(task['payload'])
    require(set(value)=={'stage','request','profile_sha256'} and settings.tools_profile
        and digest_file(settings.tools_profile)[1]==value['profile_sha256'],'本平台工具配置与提交时不同')
    folder=settings.runtime_dir/'native_requests'/task['task_id'];folder.mkdir(parents=True,exist_ok=False)
    request=folder/'request.json';output=folder/'result.json'
    request.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    command=[settings.science_python,'-I','-B','-X','utf8',str(settings.project_root/'tools/run_native_execution.py'),
        'execute','--request-file',str(request),'--result-file',str(output),'--study',task['study_id'],
        '--task-id',task['task_id'],'--data-root',str(settings.data_root),'--runtime-dir',str(settings.runtime_dir),
        '--tools-profile',str(settings.tools_profile),'--font-regular',str(settings.font_regular),'--font-bold',str(settings.font_bold)]
    with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
            errors='replace',env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')) as child:
        for line in child.stdout:
            print(line,end='',flush=True)
            if line.startswith('PROGRESS '):manager.update(task['task_id'],progress={'step_zh':line[9:].strip(),'done':0,'total':1})
        require(child.wait()==0 and output.is_file(),'原生任务未完整成功，已登记对象及失败日志保留；请核查后明确重试')
    result=json.loads(output.read_text('utf-8'))
    require(result.get('outcome')=='success','原生任务无成功结果，失败诊断保留')
    return '本平台结果已归档：'+result['run_id']+'；未提交科研批准'
