"""已批准的个性化交集同时供给 PPI 与富集，不相互等待结果。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from contracts import require
from science_modules.plan_stages_contract import info as stage_info, is_current
from storage import wait_for_parallel_publication
from ..core import plan_a05


def current_approval(workflow, sid, payload):
    require(set(payload) == {'run_id', 'review_id', 'plan_id'}, '接续只接受交集、复核和方案编号')
    manifest = workflow.load(sid)
    rid = manifest['current'].get('A03')
    require(not manifest.get('trashed') and rid == payload['run_id'] and
            is_current(workflow, manifest) and workflow.approved(manifest, rid),
            'A03 已改变或尚未有效通过')
    run = workflow.run(manifest, rid)
    review = workflow.latest_review(manifest, run['artifact_id'])
    plans = workflow._analysis_plan_records(manifest)
    require(review and review['review_id'] == payload['review_id'] and plans and
            plans[-1]['plan_id'] == payload['plan_id'] == run['inputs']['analysis_plan_id'] and
            plans[-1]['plan']['mode'] == 'personalized', 'A03 复核或个性化方案已改变')
    return review


def execute(new_workflow, sid, payload, *, rscript, progress):
    workflow = new_workflow()
    current_approval(workflow, sid, payload)
    result = workflow.result(workflow.load(sid), payload['run_id'])
    if not result['summary']['交集靶点数']:
        return 'A03 交集为零，A04 与 A05 均不适用'
    ppi_started = Event()

    def ppi():
        # A04 仍走既有指纹校验。完成其短预检后，A05 可立即开始，无需等待 STRING。
        def report(text):
            ppi_started.set()
            progress('A04 · ' + text)

        try:
            with wait_for_parallel_publication():
                workflow = new_workflow()
                review = current_approval(workflow, sid, payload)
                status = stage_info(workflow, sid)
                stage = next(row for row in status['stages'] if row['stage'] == 'A04')
                if stage['active']:
                    run = workflow.run(workflow.load(sid), stage['current_run'])
                    if run['inputs'].get('analysis_plan_id') == payload['plan_id']:
                        return 'A04 已有当前有效结果'
                require(stage['enabled'], '；'.join(stage['blockers']))
                request = {key: status[key] for key in ('expected_a00', 'expected_plan_id', 'expected_input_hash')}
                result = workflow.execute_analysis_plan_stage(
                    sid, dict(request, stage='A04', operator=review['reviewer'], confirmed=True,
                              reason='按 A03 通过记录 ' + review['review_id'] + ' 接续'), progress=report)
                return 'A04 已归档 ' + result['run_id']
        finally:
            ppi_started.set()

    def enrichment():
        with wait_for_parallel_publication():
            workflow = new_workflow()
            review = current_approval(workflow, sid, payload)
            status = plan_a05.info(workflow, sid)
            if status['completed']:
                return 'A05 已有当前有效结果'
            if not status['applicable']:
                return 'A05 按本方案不适用'
            require(status['enabled'], '；'.join(status['blockers']))
            require(rscript and Path(rscript).is_file(), '本机尚未配置有效固定R工具，请核对 science_rscript')
            request = {key: status[key] for key in plan_a05.FIELDS - {'reason'}}
            ppi_started.wait()
            current_approval(workflow, sid, payload)
            result = workflow.publish_analysis_plan_a05(
                sid, dict(request, reason='按 A03 通过记录 ' + review['review_id'] + ' 接续'),
                progress=lambda text: progress('A05 · ' + text))
            return 'A05 已归档 ' + result['run_id']

    messages, failures = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {'A04': pool.submit(ppi), 'A05': pool.submit(enrichment)}
        for stage, job in jobs.items():
            try:
                messages.append(job.result())
            except Exception as error:
                failures.append(stage + ' · ' + str(error))
    require(not failures, '；'.join(messages + failures))
    return '；'.join(messages)


def run(settings, task, manager):
    import json
    from ..core.kernel import full_workflow

    def progress(text):
        print(text, flush=True)
        manager.update(task['task_id'], progress={'step_zh': text, 'done': 0, 'total': 2})

    result = execute(lambda: full_workflow(settings.data_root), task['study_id'],
                     json.loads(task['payload']), rscript=settings.science_rscript, progress=progress)
    manager.update(task['task_id'], progress={'step_zh': result, 'done': 2, 'total': 2})
    return result
