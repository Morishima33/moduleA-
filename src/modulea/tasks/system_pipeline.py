"""统一系统批次的隔离科学子进程包装，沿用资源位、取消和日志。"""
import json,os,subprocess


def run(settings,task,manager):
    """同研究只有一个后台任务；GET和重启不提交，显式重试仍复核排队指纹。"""
    folder=settings.runtime_dir/'system_pipeline_requests'/task['task_id'];folder.mkdir(parents=True,exist_ok=False)
    request=folder/'request.json';output=folder/'result.json';request.write_text(task.get('payload') or '{}',encoding='utf8')
    command=[settings.science_python,'-I','-S','-B',str(settings.project_root/'tools/run_system_pipeline.py'),
        '--request-file',str(request),'--result-file',str(output),'--data-root',str(settings.data_root),'--study',task['study_id']]
    if settings.science_tools_root:command+=['--tools-root',str(settings.science_tools_root)]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',
        env=dict(os.environ,TEMP=str(folder),TMP=str(folder),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1'))
    with process.stdout:
        for line in process.stdout:
            print(line,end='',flush=True)
            if line.startswith('PROGRESS '):manager.update(task['task_id'],progress={'step_zh':line[9:].strip(),'done':0,'total':1})
    if process.wait()!=0 or not output.is_file():raise ValueError('系统编排未完成；已有科学原件、阶段结果和失败诊断保留，请查看日志')
    result=json.loads(output.read_text('utf8'))
    if result.get('state')!='awaiting_report_review':raise ValueError('系统编排未形成实际报告终态')
    manager.update(task['task_id'],progress={'step_zh':'本批适用分支及双报告已归档，等待结论复核','done':1,'total':1})
    return '统一系统批次已归档：'+result['report_run_id']+'；不适用与NA保留，未签署人工复核。'
