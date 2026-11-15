"""报告网页分派：新批显式展示二版，旧请求和全部历史仍按原协议读取。"""
from copy import deepcopy
from contracts import require
from . import plan_reports as original, plan_reports_v2 as revised, plan_reports_v3 as rescue

PROTOCOLS = (original, revised, rescue)


def current(workflow, manifest):
    """仅本批第三版结构或已发表二版报告使用二版入口，不静默升级旧批。"""
    for module in ('A06', 'A07'):
        rid = manifest['current'].get(module)
        if rid and workflow.run(manifest, rid)['config'].get('version') in (
                'A06.system_rescue.1', 'A06.system_rescue.2', rescue.VERSION):
            return rescue
    for module in ('A06_PREP', 'A07'):
        rid = manifest['current'].get(module)
        if rid and workflow.run(manifest, rid)['config'].get('version') in (
                'A06.system_preparation.3', 'A06.system_qualification.3', 'A07.plan_report.2'):
            return revised
    # 空交集没有结构分支，仍须按实际A03所绑定原批的报告协议分派。
    rid = manifest['current'].get('A03')
    if rid:
        from . import system_execution
        reference = workflow.run(manifest, rid).get('batch_file')
        if reference in manifest.get(system_execution.BATCHES, []):
            batch, _ = system_execution.read_batch(workflow, manifest, reference)
            if batch.get('report_protocol') == revised.VERSION:
                return revised
    return original


def info(workflow, sid):
    """只读合并两版历史；当前生成资格仍来自当前实际协议。"""
    manifest = workflow.load(sid); model = current(workflow, manifest)
    value = model.info(workflow, sid)
    for other in PROTOCOLS:
        if other is model:
            continue
        for ref in manifest.get(other.RECEIPTS, []):
            record = other.read_receipt(workflow, manifest, ref)
            active = bool(manifest['current'].get('A07') == record['run_id'] and workflow.active(manifest, record['run_id']))
            approved = bool(active and workflow.approved(manifest, record['run_id']))
            value['history'].append(dict(record, file=deepcopy(ref), active=active, approved=approved,
                status_zh='已明确复核通过' if approved else '本批报告已生成，待独立复核' if active else '历史版本保留'))
    value['history'].sort(key=lambda record: record['created_at'])
    return value


def queued_payload(workflow, sid, body):
    """HTTP预检后固定后台协议；客户端不接收或提供协议覆盖字段。"""
    model = current(workflow, workflow.load(sid))
    model.validate_request(workflow, sid, body)
    return body if model is original else {'report_protocol': model.VERSION, 'request': deepcopy(body)}


def publish_queued(workflow, sid, payload):
    """旧任务原样执行；新任务保持排队时协议并由生产发布器重核全部输入。"""
    if isinstance(payload, dict) and 'report_protocol' in payload:
        require(set(payload) == {'report_protocol', 'request'} and payload['report_protocol'] in (revised.VERSION, rescue.VERSION),
                '报告后台任务协议或请求字段不同')
        if payload['report_protocol'] == rescue.VERSION:
            return workflow.publish_analysis_plan_rescue_report(sid, payload['request'])
        return workflow.publish_analysis_plan_report_revision(sid, payload['request'])
    return workflow.publish_analysis_plan_report(sid, payload)
