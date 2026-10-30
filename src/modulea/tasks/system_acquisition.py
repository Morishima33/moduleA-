"""明确三库原件获取使用独立科学子进程，沿用资源位、取消和运行日志。"""
import json,os,subprocess


def run(settings,task,manager):
    """排队后实际复核与获取；部分失败必须任务失败，合格原件和恢复记录保留。"""
    folder=settings.runtime_dir/'system_acquisition_requests'/task['task_id'];folder.mkdir(parents=True,exist_ok=False)
    request=folder/'request.json';output=folder/'result.json';request.write_text(task.get('payload') or '{}',encoding='utf8')
    command=[settings.science_python,'-I','-S','-B',str(settings.project_root/'tools/run_system_acquisition.py'),
        '--request-file',str(request),'--result-file',str(output),'--data-root',str(settings.data_root),'--study',task['study_id']]
    with subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf8',errors='replace',env=dict(os.environ,TEMP=str(folder),TMP=str(folder),
            PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')) as process:
        with process.stdout:
            for line in process.stdout:
                print(line,end='',flush=True)
                if line.startswith('PROGRESS '):manager.update(task['task_id'],progress={'step_zh':line[9:].strip(),'done':0,'total':3})
        code=process.wait()
    if code!=0 or not output.is_file():raise ValueError('三库获取未完成；成功原件及实际失败诊断保留，请查看任务日志后明确重试')
    result=json.loads(output.read_text('utf8'))
    if result.get('state')!='complete':
        reasons='；'.join(str(r['database'])+'：'+str(r['reason_zh']) for r in result.get('sources',[]) if r['state']=='failed')
        raise ValueError('三库原件尚未齐全，成功库已保留，不是零结果：'+reasons)
    manager.update(task['task_id'],progress={'step_zh':'三库原件已核验归档，尚未发布科学A01','done':3,'total':3})
    return '本研究三库原件已归档；未签署人工复核、切换旧暂存或发布科学A01。'
