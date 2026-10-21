"""后台导出已有自动评分，独立发布展示索引，不调用对接引擎。"""
import json
from storage import file_record, new_id, write_json
from ..core.kernel import full_workflow
from ..core.automatic_experience import packet_for, automatic_names
from ..core.compound_names import compound_names


def run(settings, task, manager):
    """失败的未发布文件保留，不能作为已完成下载。"""
    from science_modules.a06.automatic_exports import build_view, export
    workflow = full_workflow(settings.data_root)
    sid, payload = task['study_id'], json.loads(task['payload'])
    manifest, batch = workflow.automatic_display_source(sid, payload)
    packet = packet_for(workflow, manifest, batch)
    source_run = workflow.run(manifest, batch['run_id'])
    names = automatic_names(workflow, manifest, packet, source_run['parent_runs']['A03'])
    view = build_view(packet, names, payload['compound_ids'], payload['target_ids'])
    folder = workflow.location(sid) / 'derived/A06_displays' / new_id('display')
    folder.mkdir(parents=True, exist_ok=False)
    manager.update(task['task_id'], progress={'step_zh': '生成同批PNG、SVG、Excel和CSV', 'done': 0, 'total': 1})
    files = export(view, folder)
    path = folder / 'view.json'
    write_json(path, view)
    root = workflow.location(sid)
    records = [file_record(root, p, 'automatic_display') for p in files.values()]
    record = workflow.publish_automatic_display(sid, payload, file_record(root, path, 'automatic_display_view'), records)
    manager.update(task['task_id'], progress={'step_zh': '展示及完整矩阵已归档，原评分和复核保持', 'done': 1, 'total': 1})
    return '图表修订已生成：' + record['id'] + '；未重新计算对接。'
