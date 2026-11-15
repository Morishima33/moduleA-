"""有界I/O恢复沿用原单研究队列、资源预算和进程树，不建立独立调度。"""
import json
import os
import subprocess

from contracts import require
from modulea.core.worker_io import VERSION


def run(settings, task, manager):
    """只有当前预算worker可启动隔离科学子进程，服务器配置决定工具和解释器。"""
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
    command = [settings.science_python,'-I','-S','-B',str(settings.project_root/'tools/run_rescue_worker_io.py'),
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
