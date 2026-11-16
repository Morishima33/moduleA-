"""本平台计算使用原任务队列与进程树；隔离子进程只从服务器配置取得工具。"""
import json
import os
import subprocess

from contracts import require
from modulea.core.bounded_evidence import digest_file


def run(settings,task,manager):
    """核当前配置再启动-I子进程，进度及完整日志沿原任务登记。"""
    value=json.loads(task['payload'])
    require(set(value)=={'stage','request','profile_sha256'} and settings.tools_profile
        and digest_file(settings.tools_profile)[1]==value['profile_sha256'],'本平台工具配置与提交时不同')
    folder=settings.runtime_dir/'native_requests'/task['task_id'];folder.mkdir(parents=True,exist_ok=False)
    request=folder/'request.json';output=folder/'result.json'
    request.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    command=[settings.science_python,'-I','-B',str(settings.project_root/'tools/run_native_execution.py'),
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
