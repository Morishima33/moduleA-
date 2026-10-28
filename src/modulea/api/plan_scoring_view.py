"""新版评分接口：标准库预检后提交后台任务，下载仅用固定结果索引。"""
from contracts import ContractError
from pathlib import Path
from storage import read_json, verified_file
from .errors import ApiError, from_contract


def execution_blocker(settings, active_task):
    """同一响应用一次任务快照核对固定工具是否实际存在，不在HTTP中启动工具。"""
    if active_task:
        return '请等待当前研究后台任务结束'
    if settings.science_tools_root is None:
        return '本机未配置固定科学工具目录'
    binary = Path(settings.science_tools_root) / 'environments/vina_1.2.7/vina_1.2.7_win.exe'
    if not binary.is_file():
        return '固定Vina 1.2.7工具文件不存在，请核对科学工具目录'
    return None


def info(app, req, sid):
    """真实执行资格同时考虑本机工具与研究后台忙碌状态。"""
    try:
        value = app.kernel.workflow().analysis_plan_a06_scoring_info(sid)
    except ContractError as error:
        raise from_contract(str(error))
    if value['enabled']:
        reason = execution_blocker(app.settings, app.tasks.active_for(sid))
        if reason:
            value.update(enabled=False, execution_available=False, reason_zh=reason, blockers=[reason])
    return value


def submit(app, req, sid):
    """显式授权只能由严格请求形成，不从GET、批准或页面加载自动执行。"""
    body = req.json()
    try:
        value = app.kernel.workflow().validate_analysis_plan_a06_scoring(sid, body)
    except ContractError as error:
        raise from_contract(str(error))
    if value['repeated']:
        return {'run_id': value['run_id'], 'created': False, 'message_zh': '沿用本次已归档评分，未重复计算'}, 200
    reason = execution_blocker(app.settings, app.tasks.active_for(sid))
    if reason:
        raise ApiError(409, 'GATE_BLOCKED', reason)
    task, created = app.tasks.submit(sid, 'a06_plan_scoring', body['operator'].strip(), body)
    if not created:
        raise ApiError(409, 'GATE_BLOCKED', '当前研究已有后台任务')
    return {'task': task, 'created': True, 'message_zh': '新版评分任务已提交；NA保留，结果仍须独立人工复核'}, 202


def export_csv(app, req, sid):
    """只下载当前评分事实包中唯一的同批CSV，不接受任意文件名。"""
    from ..core.plan_scoring import VERSION
    workflow = app.kernel.workflow()
    manifest = workflow.load(sid)
    rid = manifest.get('current', {}).get('A06')
    if not rid or workflow.run(manifest, rid)['config'].get('version') != VERSION:
        raise ApiError(404, 'NOT_FOUND', '当前没有新版评分结果')
    try:
        result = workflow.result(manifest, rid)
        if not result:
            raise ApiError(409, 'GATE_BLOCKED', '当前评分尚未完整归档')
        home = workflow.location(sid)
        packet = read_json(verified_file(home, result['tables']['scoring_packet'][0]))
        ref = packet['matrix_csv']
        if ref not in result['files'] or ref['path'] != f'runs/A06/{rid}/plan_scoring/matrix.csv':
            raise ApiError(409, 'GATE_BLOCKED', '评分导出未绑定当前运行')
        path = verified_file(home, ref)
    except ContractError as error:
        raise from_contract(str(error))
    return ('file', path, 'A06_' + rid + '_matrix.csv', 'text/csv; charset=utf-8', False)
