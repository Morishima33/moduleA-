"""新版正式评分的版本绑定与Workflow状态入口；HTTP进程仅依赖标准库。"""
from copy import deepcopy

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock

VERSION = 'A06.plan_scoring.1'
PREPARATION_VERSION = 'A06.plan_reviewable_preparation.1'
INPUT_FIELDS = {'preparation_run', 'preparation_result', 'preparation_review', 'a06_plan_input', 'authorization'}


def request(payload):
    """客户端只能绑定版本并明确确认，不能提供科学参数、文件路径或评分。"""
    require(isinstance(payload, dict) and set(payload) == {'request_id', 'expected_preparation_run_id',
        'expected_preparation_review_id', 'expected_input_id', 'expected_a06_run_id', 'operator', 'note', 'confirmed'},
        '正式评分字段不完整或含不支持选项')
    for key, prefix in (('request_id', 'scoreq'), ('expected_preparation_run_id', 'run'),
                        ('expected_preparation_review_id', 'review'), ('expected_input_id', 'input')):
        safe_id(payload[key], prefix)
    require(payload['expected_a06_run_id'] is None or safe_id(payload['expected_a06_run_id'], 'run'), '评分版本格式不合法')
    require(payload['confirmed'] is True and all(isinstance(payload[k], str) and
        0 < len(payload[k].strip()) <= 2000 for k in ('operator', 'note')), '请填写评分执行人与依据并明确确认')


def binding(workflow, sid, manifest):
    """完整核对本研究当前准备、明确批准、独立选择及同批真实参数。"""
    from .scoring_preflight import _source
    require(not manifest.get('trashed'), '回收站研究只读，不能执行评分')
    rid = manifest.get('current', {}).get('A06_PREP')
    require(rid, '请先完成可人工整体复核准备')
    run = workflow.run(manifest, rid)
    require(run['config'].get('version') == PREPARATION_VERSION, '仅新版可复核准备支持此评分协议')
    q = workflow.analysis_plan_a06_reference_qualification(sid)
    require(q.get('qualified') and q.get('can_enter_review'), '准备资料或上游已失效，请刷新')
    require(workflow.approved(manifest, rid), 'A06_PREP尚未完成人工整体复核通过')
    review = workflow.latest_review(manifest, run['artifact_id'])
    home = workflow.location(sid)
    review_ref = next(ref for ref in manifest['reviews'] if read_json(verified_file(home, ref))['review_id'] == review['review_id'])
    result = workflow.result(manifest, rid)
    require(result and result['outcome'] == 'success' and result['summary']['ready_pairs'] > 0 and
            result['summary']['scored_pairs'] == 0, '准备没有可用组合或已含评分，不能执行')
    source, record, packet, parameters = _source(workflow, sid, manifest, run)
    require(workflow.analysis_plan_info(sid).get('a06_preparation_input') == record, '准备输入或选择复核已更新，请刷新')
    source_ref_run = read_json(verified_file(home, run['inputs']['reference_preparation_run']))
    return {'run': run, 'result': result, 'review': review, 'review_ref': review_ref,
            'input_record': record, 'input_ref': source_ref_run['inputs']['a06_plan_input'],
            'packet': packet, 'source': source, 'parameters': parameters}


def configuration(data):
    """评分配置固定来源方案参数；CPU是执行资源限制，不能由网页覆盖。"""
    return {'version': VERSION, 'vina_version': '1.2.7', 'vina_parameters': deepcopy(data['parameters']),
            'analysis_parameter_hash': data['packet']['analysis_parameter_hash'],
            'source_config_hash': data['source']['config_hash'], 'cpu_per_pair': 1,
            'parallel_pairs': 1, 'timeout_seconds': 1800, 'automatic_approval': False}


def check(workflow, sid, payload):
    """请求幂等且不能回退历史；失败或中断的原批保留，重试须新请求和当前版本。"""
    request(payload)
    manifest = workflow.load(sid)
    data = binding(workflow, sid, manifest)
    require(data['run']['run_id'] == payload['expected_preparation_run_id'] and
            data['review']['review_id'] == payload['expected_preparation_review_id'] and
            data['input_record']['input_id'] == payload['expected_input_id'], '准备、复核或固定输入已更新，请刷新')
    for entry in manifest.get('analysis_plan_a06_scoring_records', []):
        old = read_json(verified_file(workflow.location(sid), entry['authorization']))
        if old['request']['request_id'] != payload['request_id']:
            continue
        require(old['request_hash'] == fingerprint(payload), '评分请求编号已用于其他内容，请刷新')
        require(entry['run_id'] == manifest['current'].get('A06') and workflow.active(manifest, entry['run_id']),
                '评分已有后续版本或准备已失效，请刷新')
        result = workflow.result(manifest, entry['run_id'])
        require(result and result['outcome'] == 'success', '原评分未成功归档，请刷新后用新请求明确重试；历史保留')
        return {'repeated': True, 'run_id': entry['run_id']}
    require(manifest['current'].get('A06') == payload['expected_a06_run_id'], '评分版本已更新，请刷新')
    return {'repeated': False, 'configuration': configuration(data)}


def guard_begin(workflow, manifest, inputs, config):
    """为A06新版本精确放行，旧执行器或伪造来源均不能使用新准备。"""
    require(set(inputs) == INPUT_FIELDS and config.get('version') == VERSION, '新版准备不能调用旧评分协议')
    sid = manifest['study_id']
    data = binding(workflow, sid, manifest)
    home = workflow.location(sid)
    authorization = read_json(verified_file(home, inputs['authorization']))
    request(authorization['request'])
    require(authorization['schema_version'] == VERSION and authorization['study_id'] == sid and
            authorization['request_hash'] == fingerprint(authorization['request']) and
            authorization['configuration'] == config == configuration(data), '评分授权或同批参数不一致')
    body = authorization['request']
    require(body['expected_preparation_run_id'] == data['run']['run_id'] and
            body['expected_preparation_review_id'] == data['review']['review_id'] and
            body['expected_input_id'] == data['input_record']['input_id'] and
            body['expected_a06_run_id'] == manifest['current'].get('A06'), '评分授权版本已更新，请刷新')
    require(inputs['preparation_run'] == manifest['runs'][data['run']['run_id']]['run_file'] and
            inputs['preparation_result'] == manifest['runs'][data['run']['run_id']]['result_file'] and
            inputs['preparation_review'] == data['review_ref'] and inputs['a06_plan_input'] == data['input_ref'],
            '评分输入不属于当前明确批准的同批准备')


def begin(workflow, sid, payload):
    """锁内归档一次明确执行授权并创建A06运行，不生成结果或代签。"""
    with write_lock(workflow.root):
        checked = check(workflow, sid, payload)
        manifest = workflow.load(sid)
        if checked['repeated']:
            return workflow.run(manifest, checked['run_id']), True
        data = binding(workflow, sid, manifest)
        home = workflow.location(sid)
        authorization = {'schema_version': VERSION, 'study_id': sid, 'authorization_id': new_id('scoreauth'),
                         'request': deepcopy(payload), 'request_hash': fingerprint(payload),
                         'configuration': checked['configuration'], 'created_at': now()}
        target = home / 'decisions/analysis_plans/a06_scoring' / (authorization['authorization_id'] + '.json')
        write_json(target, authorization)
        inputs = {'authorization': file_record(home, target, 'a06_scoring_authorization'),
                  'preparation_run': manifest['runs'][data['run']['run_id']]['run_file'],
                  'preparation_result': manifest['runs'][data['run']['run_id']]['result_file'],
                  'preparation_review': data['review_ref'], 'a06_plan_input': data['input_ref']}
        run = workflow._begin(manifest, 'A06', inputs, checked['configuration'], '按已复核准备与固定方案执行Vina评分；结果待独立复核')
        manifest.setdefault('analysis_plan_a06_scoring_records', []).append(
            {'authorization': inputs['authorization'], 'run_id': run['run_id']})
        workflow.save(manifest)
        return run, False


def finish(workflow, sid, run_id, summary, tables, files):
    """发布前再次核对原批准、输入和当前运行；不能把旧版本计算写为当前结果。"""
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        run = workflow.run(manifest, run_id)
        require(run['config'].get('version') == VERSION and manifest['current'].get('A06') == run_id and
                workflow.active(manifest, run_id), '评分或上游复核已更新，请刷新；原始计算文件已保留')
        data = binding(workflow, sid, manifest)
        require(run['inputs']['preparation_review'] == data['review_ref'] and
                run['inputs']['a06_plan_input'] == data['input_ref'], '评分固定输入已更新，请刷新')
        outcome = 'success' if summary['scored_pairs'] > 0 else 'failed'
        result = workflow._finish(manifest, run_id, summary, tables, [], outcome, attachments=files)
        workflow.save(manifest)
        return result


def info(workflow, sid):
    """只读执行资格与本批状态；不自动评分或重复已有成功计算。"""
    manifest = workflow.load(sid)
    prep = manifest.get('current', {}).get('A06_PREP')
    value = {'supported': False, 'enabled': False, 'execution_available': False, 'protocol_version': VERSION,
             'blockers': [], 'state': 'blocked', 'current_run_id': manifest.get('current', {}).get('A06')}
    if not prep or workflow.run(manifest, prep)['config'].get('version') != PREPARATION_VERSION:
        return dict(value, reason_zh='请先完成新版可复核准备并人工复核通过')
    value['supported'] = True
    try:
        data = binding(workflow, sid, manifest)
    except (ValueError, KeyError) as error:
        return dict(value, blockers=[str(error)], reason_zh=str(error))
    value.update(expected_preparation_run_id=prep, expected_preparation_review_id=data['review']['review_id'],
                 expected_input_id=data['input_record']['input_id'], parameters=data['parameters'],
                 pair_count=data['result']['summary']['pair_count'], ready_pairs=data['result']['summary']['ready_pairs'],
                 na_pairs=data['result']['summary']['na_pairs'])
    current = value['current_run_id']
    if current:
        run = workflow.run(manifest, current)
        result = workflow.result(manifest, current)
        if run['config'].get('version') == VERSION and workflow.active(manifest, current) and result:
            value.update(summary=result['summary'], result_run_id=current,
                         state='completed' if result['outcome'] == 'success' else 'failed')
            if result['outcome'] == 'success':
                return dict(value, reason_zh='同批评分已归档，结果须独立人工复核；不会重复运行')
    return dict(value, enabled=True, execution_available=True,
                reason_zh='准备及人工批准有效；明确确认后按原参数评分，NA保留，结果仍须独立复核')
