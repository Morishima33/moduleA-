"""自动结果按需读取：评分分页、单项证据、展示选择与附件分页。"""
from pathlib import Path
from storage import read_json, verified_file
from ..core.automatic_experience import batch_for, packet_for, pairs_page, pair_evidence, file_rows, page_rows, automatic_names
from ..core.compound_names import compound_names
from .errors import ApiError, not_found


def reader(app, sid, identity):
    """读取本研究批次，GET不创建授权或任务。"""
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    return workflow, manifest, batch_for(workflow, manifest, identity)


def pairs(app, req, sid, identity):
    workflow, manifest, batch = reader(app, sid, identity)
    return pairs_page(workflow, manifest, batch, req.query_int('page', 1), req.query_int('size', 20), req.query1('q') or '')


def evidence(app, req, sid, identity, key):
    workflow, manifest, batch = reader(app, sid, identity)
    return pair_evidence(workflow, manifest, batch, key)


def files(app, req, sid, identity):
    _, _, batch = reader(app, sid, identity)
    return page_rows(file_rows(sid, batch), req.query_int('page', 1), req.query_int('size', 20), req.query1('q') or '')


def matrix(app, req, sid, identity):
    """展示选择只改变绘图，不触发Vina或改变研究名单。"""
    from science_modules.a06.automatic_exports import build_view, heatmap_svg
    workflow, manifest, batch = reader(app, sid, identity)
    selected_c, selected_t = req.query1('compound_ids'), req.query1('target_ids')
    latest = next((r for r in reversed(manifest.get('automatic_displays', [])) if r['batch_id'] == identity and r['packet'] == batch.get('packet')), None)
    if latest and selected_c is None and selected_t is None:
        view = read_json(verified_file(workflow.location(sid), latest['view']))
    else:
        packet = packet_for(workflow, manifest, batch)
        run = workflow.run(manifest, batch['run_id'])
        names = automatic_names(workflow, manifest, packet, run['parent_runs']['A03'])
        view = build_view(packet, names, selected_c.split(',') if selected_c is not None else None, selected_t.split(',') if selected_t is not None else None)
    aligned = bool(latest and read_json(verified_file(workflow.location(sid), latest['view']))['heatmap'] == view['heatmap'])
    downloads = [{'name': Path(r['path']).name, 'url': f'/api/v1/studies/{sid}/automatic_displays/{latest["id"]}/files/{i}', 'role': r.get('role', '')} for i, r in enumerate(latest['files'])] if aligned else []
    if not latest and selected_c is None and selected_t is None and view.get('science_version') == 'A06.automatic.3':
        # 第三版执行已生成的六种图表可以直接下载，不要求重复点击导出。
        downloads = [r for r in file_rows(sid, batch) if '/display/' in r['path'] and Path(r['path']).suffix.lower() in ('.png', '.svg', '.xlsx', '.csv')]
    return {'view': view, 'svg': heatmap_svg(view), 'downloads': downloads, 'display_id': latest['id'] if latest else None,
            'expected_a06': batch['run_id'], 'enabled': not manifest.get('trashed') and manifest['current'].get('A06') == batch['run_id'] and workflow.active(manifest, batch['run_id']) and not app.tasks.active_for(sid)}


def display(app, req, sid):
    """点击才导出；过期、回收站和活动任务均拒绝。"""
    if app.tasks.active_for(sid):
        raise ApiError(409, 'GATE_BLOCKED', '请等待当前研究后台任务结束')
    payload = req.json()
    workflow = app.kernel.read_workflow()
    manifest, batch = workflow.automatic_display_source(sid, payload)
    from science_modules.a06.automatic_exports import build_view
    build_view(packet_for(workflow, manifest, batch), None, payload['compound_ids'], payload['target_ids'])
    task, created = app.tasks.submit(sid, 'a06_display', '网页生成同批图表与矩阵下载', payload)
    if not created:
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有后台任务')
    return {'task': task, 'message_zh': '生成所选展示及完整矩阵，不重新计算评分。'}, 202


def display_file(app, req, sid, identity, number):
    """只读本研究展示索引，逐次核验下载字节。"""
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    row = next((r for r in manifest.get('automatic_displays', []) if r['id'] == identity), None)
    if not row or not 0 <= int(number) < len(row['files']):
        raise not_found('本研究展示文件')
    path = verified_file(workflow.location(sid), row['files'][int(number)])
    mime = {'.png': 'image/png', '.svg': 'image/svg+xml', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.csv': 'text/csv; charset=utf-8'}.get(path.suffix.lower(), 'application/octet-stream')
    return ('file', path, path.name, mime, mime.startswith('image/'))
