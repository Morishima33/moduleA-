"""从已保存的 A00 复核接续本方案 A01/A02，沿原资料、批次和阶段校验。"""
import json
from concurrent.futures import ThreadPoolExecutor

from contracts import ContractError, fingerprint, require
from storage import read_json, verified_file, wait_for_parallel_publication
from ..core import system_acquisition as formula
from ..core import system_component_sources as formula_binding
from ..core import system_disease_acquisition as disease
from ..core import system_disease_manual_sources as manual
from ..core import system_disease_publication as publication
from ..core import system_execution as execution, system_pipeline


def current_approval(workflow, sid, payload):
    """执行和重试都以当前登记、同一方案、真实仍有效的 A00 决定为准。"""
    require(isinstance(payload, dict) and set(payload) == {'run_id', 'review_id', 'plan_id'},
            '接续只接受登记、复核和方案编号')
    m = workflow.load(sid)
    rid = m['current'].get('A00')
    require(not m.get('trashed') and rid and rid == payload['run_id'], 'A00 登记已改变或研究只读')
    plans = workflow._analysis_plan_records(m)
    require(plans and plans[-1]['plan_id'] == payload['plan_id'] and plans[-1]['expected_a00'] == rid,
            '当前登记的计算方案已改变，请刷新后接续')
    review = workflow.latest_review(m, workflow.run(m, rid)['artifact_id'])
    require(review and review['decision'] == 'approved' and review['review_id'] == payload['review_id']
            and workflow.approved(m, rid), 'A00 复核已改变或尚未有效通过，请刷新后接续')
    return m, review


def _acquisition_request(workflow, m, core, payload, fields, prefix, label, make_request):
    """复用本登记同方案仍有效的请求，否则按当前原件重核，保留原恢复记录。"""
    for ref in reversed(m.get(core.REQUESTS, [])):
        saved = core.read_record(workflow, m, ref, kind='request')
        body = saved['request']
        if (body['expected_a00'], body['expected_plan_id']) != (payload['run_id'], payload['plan_id']):
            continue
        try:
            core.require_current(workflow, m, saved)
        except ContractError:
            continue
        return body
    return make_request(prefix, fields, label)


def _complete(result, label):
    missing = [row['database'] + '：' + row['reason_zh'] for row in result['sources'] if row['state'] != 'ready']
    require(result['state'] == 'complete', label + '原件未齐。' + '；'.join(missing))


def execute(workflow, sid, payload, *, progress, new_workflow=None):
    """新版个性化接续走独立资料链，旧批次留作原协议回放。"""
    def check():
        return current_approval(workflow, sid, payload)[0]

    def request(prefix, fields, label):
        request_id = prefix + '_' + fingerprint({'approval': payload, 'fields': fields})[:32]
        return dict(fields, request_id=request_id, author=review['reviewer'],
                    note=f'依据 A00 通过记录 {review["review_id"]} 接续：{label}', confirmed=True)

    def acquire(core, method, prefix, label):
        m = check()
        status = core.info(workflow, sid)
        require(status['enabled'], '；'.join(status['blockers']))
        require(status['expected_a00'] == payload['run_id'] and status['expected_plan_id'] == payload['plan_id'],
                '开始获取前登记或方案已改变')
        fields = {key: status[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}
        body = _acquisition_request(workflow, m, core, payload, fields, prefix, label, request)
        result = method(sid, body, progress=progress)
        _complete(result, label)
        return body['request_id']

    m, review = current_approval(workflow, sid, payload)
    draft = workflow._analysis_plan_records(m)[-1]
    current_a02 = m['current'].get('A02')
    a02_version = workflow.run(m, current_a02)['config'].get('version') if current_a02 else None
    modern_disease = a02_version in (None, 'A02.system_collection.1',
                                    'A02.system_normalization.3', 'A02.system_normalization.6')
    if draft['plan']['mode'] == 'personalized' and modern_disease and not m.get('current_analysis_plan_identity_exception'):
        return execute_parallel(new_workflow or (lambda: type(workflow)(workflow.root)), sid, payload, progress=progress)

    batch_request_id = 'systembatchreq_' + fingerprint(payload)[:32]
    batch = None
    for ref in m.get(execution.BATCHES, []):
        saved = read_json(verified_file(workflow.location(sid), ref))
        if saved['request']['request_id'] == batch_request_id:
            batch, _ = execution.read_batch(workflow, m, ref)
            break

    if batch is None:
        require(not m['current'].get('A01'), '已存在 A01 计算版本，请在计算工作台查看或续做原批次')
        if not m['current'].get('A02'):
            sources = manual.info(workflow, sid)['sources']
            missing = {'GeneCards', 'OMIM'} - {row['database'] for row in sources}
            require(not missing, '请先提供本研究原件：' + '、'.join(sorted(missing)) + '，然后接续 A01/A02')
            progress('核验并整理本研究疾病五库资料')
            acquisition_id = acquire(disease, workflow.acquire_analysis_plan_system_disease_sources,
                                     'diseaseacqreq', '疾病五库')
            binding = publication.info(workflow, check(), acquisition_id)
            require(binding['enabled'], '；'.join(binding['blockers']))
            workflow.publish_analysis_plan_system_disease_candidates(
                sid, request('diseasepublishreq', binding['request'], '整理疾病候选'))
        system_pipeline.required_inputs(workflow, check())

        if not execution.source_for(workflow, check(), payload['plan_id'])[0]:
            progress('获取并核验方剂三库资料')
            acquisition_id = acquire(formula, workflow.acquire_analysis_plan_system_a01_sources,
                                     'systemacqreq', '方剂三库')
            binding = formula_binding.info(workflow, check(), acquisition_id)
            require(binding['enabled'], '；'.join(binding['blockers']))
            workflow.bind_analysis_plan_system_a01_sources(
                sid, request('systemsourcebindreq', binding['request'], '绑定方剂三库'))

        status = execution.info(workflow, sid)
        require(status['enabled'], '；'.join(status['blockers']))
        require(status['expected_a00'] == payload['run_id'] and status['expected_plan_id'] == payload['plan_id'],
                '开始计算前登记或方案已改变')
        fields = {key: status[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}
        check()
        batch = workflow.start_analysis_plan_foundation_system_batch(
            sid, dict(request('systembatchreq', fields, '计算 A01 与 A02'), request_id=batch_request_id))

    m = check()
    ref, batch, _ = system_pipeline.batch_for(workflow, m, batch['batch_id'])
    system_pipeline.required_inputs(workflow, m, batch)
    for stage in ('A01', 'A02'):
        m = check()
        rid = m['current'].get(stage)
        expected = batch['initial_binding']['current'].get(stage)
        if rid != expected:
            run = workflow.run(m, rid) if rid else {}
            require(run.get('batch_file') == ref, '当前科学版本已改变：' + stage)
            system_pipeline.usable(workflow, m, rid)
            continue
        progress('计算 ' + stage)
        result = workflow.execute_analysis_plan_system_stage(
            sid, {'batch_id': batch['batch_id'], 'stage': stage, 'expected_current_run_id': expected},
            progress=progress)
        system_pipeline.usable(workflow, check(), result['run_id'])
    return 'A01、A02 已归档，请一并复核结果。'


def execute_parallel(new_workflow, sid, payload, *, progress):
    """每侧只等自己的资料，最终从 A03 复核输入。"""
    workflow = new_workflow()
    current_approval(workflow, sid, payload)
    with wait_for_parallel_publication():
        execution.ensure_parents(workflow, sid, {'A00':payload['run_id']})

    def branch(stage):
        workflow = new_workflow()
        with wait_for_parallel_publication():
            def check():
                return current_approval(workflow, sid, payload)[0]

            def request(prefix, fields, label):
                request_id = prefix + '_' + fingerprint({'approval': payload, 'stage':stage, 'fields': fields})[:32]
                return dict(fields, request_id=request_id, author=review['reviewer'], confirmed=True,
                            note=f'依据 A00 通过记录 {review["review_id"]} 接续：{label}')

            def acquire(core, method, prefix, label):
                m = check()
                status = core.info(workflow, sid)
                require(status['enabled'], '；'.join(status['blockers']))
                require((status['expected_a00'], status['expected_plan_id']) ==
                        (payload['run_id'], payload['plan_id']), '开始获取前登记或方案已改变')
                fields = {key:status[key] for key in ('expected_a00', 'expected_plan_id', 'expected_input_hash')}
                body = _acquisition_request(workflow, m, core, payload, fields, prefix, label, request)
                _complete(method(sid, body, progress=lambda text:progress(stage+' · '+text)), label)
                return body['request_id']

            m, review = current_approval(workflow, sid, payload)
            rid = m['current'].get(stage)
            if rid:
                run = workflow.run(m, rid)
                if stage == 'A01' or run['config'].get('version') in {
                        'A02.system_normalization.3','A02.system_normalization.6'}:
                    require(run['inputs'].get('analysis_plan_id') == payload['plan_id'], '已有其他方案结果，请核对当前版本')
                    system_pipeline.usable(workflow, m, rid)
                    return stage + ' 已有本方案计算结果'

            if stage == 'A01':
                if not execution.source_for(workflow, m, payload['plan_id'])[0]:
                    aid = acquire(formula, workflow.acquire_analysis_plan_system_a01_sources, 'systemacqreq', '方剂三库')
                    binding = formula_binding.info(workflow, check(), aid)
                    require(binding['enabled'], '；'.join(binding['blockers']))
                    workflow.bind_analysis_plan_system_a01_sources(sid, request('systemsourcebindreq', binding['request'], '绑定方剂三库'))
            else:
                if not rid:
                    missing = {'GeneCards', 'OMIM'} - {row['database'] for row in manual.info(workflow, sid)['sources']}
                    require(not missing, '请先提供本研究原件：'+'、'.join(sorted(missing)))
                    aid = acquire(disease, workflow.acquire_analysis_plan_system_disease_sources, 'diseaseacqreq', '疾病五库')
                    binding = publication.info(workflow, check(), aid)
                    require(binding['enabled'], '；'.join(binding['blockers']))
                    workflow.publish_analysis_plan_system_disease_candidates(sid, request('diseasepublishreq', binding['request'], '整理疾病候选'))
                system_pipeline.required_inputs(workflow, check())

            progress('计算 ' + stage)
            fields = {'expected_a00':payload['run_id'], 'expected_plan_id':payload['plan_id'], 'expected_input_hash':None}
            body = request('systembatchreq', fields, '独立计算 '+stage)
            batch = execution.start(workflow, sid, body, foundation_stage=stage)
            check()
            result = workflow.execute_analysis_plan_system_stage(sid, {'batch_id':batch['batch_id'], 'stage':stage,
                'expected_current_run_id':batch['initial_binding']['current'].get(stage)})
            system_pipeline.usable(workflow, check(), result['run_id'])
            return stage + ' 已归档'

    messages, failures = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {stage:pool.submit(branch, stage) for stage in ('A01', 'A02')}
        for stage, job in jobs.items():
            try:
                messages.append(job.result())
            except Exception as error:
                failures.append(stage + ' · ' + str(error))
    require(not failures, '；'.join(messages + failures))
    return '；'.join(messages) + '。请在 A03 一次核对两侧。'


def run(settings, task, manager):
    """使用现有独立科学工作进程、资源预算与取消机制。"""
    from ..core.kernel import full_workflow

    def progress(text):
        print(text, flush=True)
        manager.update(task['task_id'], progress={'step_zh':text,'done':0,'total':1})

    def new_workflow():
        return full_workflow(settings.data_root)

    result = execute(new_workflow(), task['study_id'], json.loads(task['payload']), progress=progress, new_workflow=new_workflow)
    manager.update(task['task_id'], progress={'step_zh':result,'done':1,'total':1})
    return result
