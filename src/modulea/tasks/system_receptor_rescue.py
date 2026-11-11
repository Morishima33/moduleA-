"""明确受体补救的重任务适配；沿原队列、预算和整进程树取消。"""
import json
import os
import subprocess


def run(settings, task, manager):
    """服务器路径进入固定隔离子进程，研究与原请求由公开Workflow再次核验。"""
    active = manager.active_for(task['study_id'])
    if not active or active['task_id'] != task['task_id']:
        raise ValueError('本研究已有其他活动任务，不能并发启动受体补救')
    if settings.science_tools_root is None or settings.science_repair_packages is None:
        raise ValueError('尚未配置固定对接工具或有限修补依赖')
    folder = settings.runtime_dir / 'system_receptor_rescue_requests' / task['task_id']
    folder.mkdir(parents=True, exist_ok=False)
    request, output = folder / 'request.json', folder / 'result.json'
    request.write_text(task['payload'], encoding='utf-8')
    command = [settings.science_python, '-I', '-S', '-B',
               str(settings.project_root / 'tools/run_system_receptor_rescue.py'),
               '--request-file', str(request), '--result-file', str(output),
               '--data-root', str(settings.data_root), '--tools-root', str(settings.science_tools_root),
               '--repair-packages', str(settings.science_repair_packages), '--study', task['study_id']]
    manager.update(task['task_id'], progress={'step_zh': '重核本批原准备、原评分和明确补救请求', 'done': 0, 'total': 1})
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding='utf-8', errors='replace',
                          env=dict(os.environ, TEMP=str(folder), TMP=str(folder),
                                   PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')) as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            if line.startswith('PROGRESS '):
                manager.update(task['task_id'], progress={'step_zh': line[9:].strip(), 'done': 0, 'total': 1})
        if process.wait() != 0 or not output.is_file():
            raise ValueError('本批受体补救未完整结束；原评分、已保存对象和实际失败日志均保留')
    result = json.loads(output.read_text('utf-8'))
    if result.get('outcome') != 'success':
        raise ValueError('本批受体补救尚无完整可用结果，请查看实际失败和NA原因')
    message = '受体补救及完整矩阵已另存：' + result['run_id'] + '；未自动批准新A06结果'
    manager.update(task['task_id'], progress={'step_zh': message, 'done': 1, 'total': 1})
    return message
