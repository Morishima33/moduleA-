"""补救名称和图表沿原重任务资源、单研究任务及取消状态，不启动对接或Word。"""
import json
import os

from contracts import require
from modulea.core.kernel import Kernel
from .process_identity import identity


def run(settings, task, manager):
    """仅消费服务端明确登记的严格请求，字体取配置；每次写锁前重核当前任务。"""
    payload = json.loads(task['payload'])
    require(isinstance(payload, dict) and set(payload) == {'stage', 'request'}
            and payload['stage'] in ('publish', 'original_name', 'archive') and isinstance(payload['request'], dict),
            '名称图表任务字段或阶段不同，不接受工具路径或参数覆盖')

    def check_task():
        """取消、输入替换、另一worker或同研究其他活动任务均不允许登记成功产物。"""
        current = manager._raw(task['task_id'])
        actual = identity(os.getpid())
        require(current and current['state'] == 'running' and current['kind'] == 'plan_rescue_presentation'
                and current['study_id'] == task['study_id'] and current['payload'] == task['payload']
                and current['pid'] == current['resource_owner_pid'] == os.getpid()
                and actual and json.loads(current.get('process_identity') or 'null') == actual
                and [row['task_id'] for row in manager.list(task['study_id'], active_only=True)] == [task['task_id']],
                '名称图表任务已取消、中断、变更或不属于当前单研究worker')

    check_task()
    w = Kernel(settings).workflow()
    manager.update(task['task_id'], progress={'step_zh': '核对本批评分、名称依据和明确许可', 'done': 0, 'total': 1})
    if payload['stage'] == 'original_name':
        value = w.register_rescue_original_name_decision(task['study_id'], payload['request'], check_task=check_task)
        result = '本批精确原专名许可已登记；不计入已核中文，未改变评分或人工复核。'
    elif payload['stage'] == 'archive':
        value = w.publish_rescue_acceptance_archive(task['study_id'], payload['request'],
            min_free_bytes=settings.compute_min_free_bytes, check_task=check_task)
        result = '本批完整包已另存：' + value['archive_id'] + '；未改变原评分、科学状态或人工复核。'
    else:
        value = w.publish_rescue_presentation(task['study_id'], payload['request'],
            font_path=settings.font_regular, check_task=check_task)
        result = '本批名称图表已另存：' + value['revision_id'] + '；未改变原评分、科学状态或人工复核。'
    check_task()
    manager.update(task['task_id'], progress={'step_zh': '本批明确技术附件已归档，未生成Word', 'done': 1, 'total': 1})
    return result
