"""显式同批目录技术修订调度；不替换历史准备或启动评分。"""
from copy import deepcopy

from contracts import fingerprint, require, safe_id
from storage import file_record, read_json, verified_file, within, write_json, write_lock
from . import system_execution as execution

VERSION = 'A06.system_qualification_paths.1'
FIELDS = {'batch_id', 'expected_preparation_run_id', 'expected_result_sha256', 'request_id'}


# 只接受同批原资格和精确结果指纹；合法重复请求返回原发表。
def execute(workflow, sid, body, *, tools, progress=None):
    require(isinstance(body, dict) and set(body) == FIELDS, '受体路径修订请求字段错误')
    safe_id(body['batch_id'], 'systembatch')
    safe_id(body['expected_preparation_run_id'], 'run')
    safe_id(body['request_id'], 'receptorpathrepair')
    from science_modules.a06 import receptor_path_repair as repair, system_qualification_paths as science

    notify = progress or (lambda _: None)
    m = workflow.load(sid)
    home = workflow.location(sid)
    current = m['current'].get('A06_PREP')
    require(current, '原系统资格尚未归档')
    original = workflow.run(m, current)
    if original['config'].get('version') == VERSION:
        request = read_json(verified_file(home, original['inputs']['path_repair_request']))
        require(request['request'] == body and workflow.active(m, current),
                '已有不同或失效的路径修订，不能重复提交')
        return workflow.result(m, current)
    require(current == body['expected_preparation_run_id']
            and original['config'].get('version') == 'A06.system_qualification.2'
            and workflow.active(m, current), '原系统资格已改变或尚未完成')
    batch_ref = original['batch_file']
    batch, plan = execution.require_batch(workflow, m, batch_ref)
    require(batch['batch_id'] == body['batch_id'], '路径修订批次不同')
    review = workflow.latest_review(m, original['artifact_id'])
    require(not review or review['decision'] == 'approved', '原资格已明确暂存或退回')
    source_ref = m['runs'][current]['run_file']
    result_ref = m['runs'][current]['result_file']
    require(result_ref and result_ref['sha256'] == body['expected_result_sha256'], '原资格结果字节已改变')
    parents = deepcopy(original['parent_runs'])
    parent_records = execution.parent_records(workflow, m, parents)
    inputs = {key: deepcopy(original['inputs'][key]) for key in (
        'study_id', 'bound_a00', 'analysis_plan_id', 'analysis_plan_file', 'analysis_parameter_hash',
        'system_input_ref', 'source_preparation_fact', 'source_preparation_run')}
    inputs.update(source_qualification_run=source_ref, source_qualification_result=result_ref)
    _, original_result = science.source(workflow.root, sid, inputs)
    request = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body),
               'request_hash': fingerprint(body), 'batch_file': batch_ref, 'source_qualification_run': source_ref,
               'source_qualification_result': result_ref, 'parent_validation_records': parent_records,
               'source_review': deepcopy(review), 'human_review_written': False}
    folder = within(home, f'decisions/analysis_plans/system_batches/{body["batch_id"]}/receptor_path_repairs/{body["request_id"]}')
    request_path = folder / 'qualification_request.json'
    with write_lock(workflow.root):
        _check_source(workflow, sid, current, original, result_ref, batch_ref, review, parents, parent_records)
        _immutable(request_path, request)
    inputs['path_repair_request'] = file_record(home, request_path, 'receptor_path_qualification_request')
    packet_ref, _ = repair.compute(home, inputs['source_preparation_fact'], body['request_id'], tools, notify)
    require(verified_file(home, packet_ref).parent == folder, '受体补执行档案不属于本次明确请求')
    inputs['path_repair_packet'] = packet_ref
    _, fact, summary, tables, refs = science.facts(home, original, inputs)
    fact_path = folder / 'qualification_fact.json'
    _immutable(fact_path, fact)
    inputs['qualification_fact'] = file_record(home, fact_path, 'system_qualified_preparation')
    tables['preparation_packet'] = [inputs['qualification_fact']]
    with write_lock(workflow.root):
        m = _check_source(workflow, sid, current, original, result_ref, batch_ref, review, parents, parent_records)
        run = execution.begin(workflow, m, 'A06_PREP', inputs, science.configuration(original),
                              '原同批目录技术修订；' + batch['request']['note'], batch_ref, parents)
        checker = execution.validation.canonical_validator(workflow.root, 'A06_PREP')
        checker(run, summary, tables, [], 'success')
        result = workflow._finish(m, run['run_id'], summary, tables, [], 'success',
                                sources=[batch_ref, *parent_records.values(), source_ref, result_ref,
                                         inputs['path_repair_request'], inputs['qualification_fact'],
                                         *original_result['files'], *refs])
        workflow.save(m)
        return result


# 计算开始和发表分别读取当前指针、回执和人工意见；阻止期间变化被覆盖。
def _check_source(workflow, sid, current, original, result_ref, batch_ref, review, parents, parent_records):
    m = workflow.load(sid)
    execution.require_batch(workflow, m, batch_ref)
    require(m['current'].get('A06_PREP') == current and workflow.active(m, current)
            and m['runs'][current]['result_file'] == result_ref
            and workflow.latest_review(m, original['artifact_id']) == review
            and execution.parent_records(workflow, m, parents) == parent_records,
            '受体补执行期间原资格、人工决定或上游已改变')
    return m


# 同一请求复用原字节，任何变动另由明确请求处理。
def _immutable(path, value):
    if path.exists():
        require(read_json(path) == value, '路径修订已有不同的请求或资格事实')
    else:
        write_json(path, value)
