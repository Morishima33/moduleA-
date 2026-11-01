"""系统A01精确编号补查的版本绑定和不可变归档；不替换身份或科研复核。"""
import json
import re
from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from science_modules.a01.identity_probe_contract import candidate_hgnc_ids
from . import component_identity_evidence as evidence, system_component_sources as sources

VERSION = 'A01.identity_probe.1'
INDEX = 'analysis_plan_component_identity_probes'
FIELDS = {'request_id', 'expected_a01', 'expected_input_hash', 'author', 'note', 'confirmed'}
STATES = {'query_failed', 'conflicting', 'source_nonhuman_confirmed', 'stable_links_agree', 'missing_ids', 'missing_or_conflicting_ids'}


def candidate_coverage(value):
    """核对原候选明确编号是否均有成功查询，不把早期遗漏隐藏为完整补查。"""
    expected = {cid for row in value['rows'] for issue in row['issues'] for cid in candidate_hgnc_ids(issue)}
    ready = {q['url'].removeprefix('https://rest.genenames.org/fetch/hgnc_id/') for q in value['queries']
             if q['state'] == 'ready' and q['url'].startswith('https://rest.genenames.org/fetch/hgnc_id/')}
    missing = sorted(expected - ready)
    return {'candidate_coverage_complete': not missing, 'missing_candidate_hgnc_ids': missing,
            'coverage_message_zh': '原候选HGNC编号已逐项补查，均未采用' if not missing else '历史回执尚缺原候选编号补查：' + '、'.join(missing) + '；保留原文，请查看后续完整回执'}


def context(workflow, m, rid):
    """由实际A01及原关系行提取服务端精确编号；历史读取不依赖当前指针。"""
    run = workflow.run(m, rid); result = workflow.result(m, rid); home = workflow.location(m['study_id'])
    require(run['study_id'] == m['study_id'] and run['module_id'] == 'A01'
            and run['config'].get('version') == 'A01.system_publication.1', '仅支持系统三库A01原身份待核记录')
    ref = run['inputs']['system_source_binding']; binding = sources.read_record(workflow, m, ref)
    require(run['inputs']['staging_file'] == ref and binding['plan_file'] == run['inputs']['analysis_plan_file']
            and binding['a00_run_id'] == run['parent_runs']['A00'], '原A01来源绑定不同')
    slot = next(s for s in binding['datasets'] if s['database'] == 'HERB'); refs = {r['path']: r for r in slot['files']}
    browse_ref = refs.get(slot['folder'] + '/HERB_target_browse_page001.json'); require(browse_ref, '原HERB命名表未登记')
    browse = json.loads(evidence.read_bytes(home, browse_ref))
    require(len(browse['browse_data']) - 1 == browse['total_num'], '原HERB命名表不完整')
    names = {row[0]['title']: row[1] for row in browse['browse_data'][1:]}; groups = {}
    for issue in result['tables'].get('identity_decisions', []):
        if issue.get('database') != 'HERB': continue
        match = re.fullmatch(r'raw/(HERB_existing_details/(HBIN[0-9]+)\.json):ingredient_target:([0-9]+)', issue.get('source_ref', ''))
        require(match and re.fullmatch(r'HBTAR[0-9]+', issue.get('raw_target_id', '')), '原HERB待核记录缺少可验证精确编号')
        name, cid, line = match.groups(); tid = issue['raw_target_id']; ref = refs.get(slot['folder'] + '/' + name)
        require(ref and issue['raw_compound_id'] == cid and names.get(tid) == issue['raw_symbol'], '原HERB待核编号或命名表不一致')
        detail = json.loads(evidence.read_bytes(home, ref)); rows = detail.get('ingredient_target', [])
        require(detail['summary'][1][0] == cid and 2 <= int(line) <= len(rows)
                and rows[int(line) - 1][0]['title'] == tid, '原HERB关系行与待核问题不一致')
        group = groups.setdefault(tid, {'target_id': tid, 'issues': [], 'source_files': [browse_ref]})
        require(issue.get('issue_key') and issue.get('decision') == '待核验', '原问题缺少待核状态或指纹')
        group['issues'].append(deepcopy(issue))
        if ref not in group['source_files']: group['source_files'].append(deepcopy(ref))
    return {'a01_run_id': rid, 'a01_files': deepcopy(m['runs'][rid]), 'source_binding': deepcopy(run['inputs']['system_source_binding']),
            'plan_file': deepcopy(binding['plan_file']), 'targets': list(groups.values())}


def check_current(workflow, m):
    """补查属于当前明确版本；回收站及人工暂存/退回不能执行。"""
    require(not m.get('trashed'), '回收站研究只读')
    for rid in m['current'].values():
        review = workflow.latest_review(m, workflow.run(m, rid)['artifact_id'])
        require(not review or review['decision'] == 'approved', '研究已有明确人工暂存或退回，不能补查')


def validate_request(workflow, sid, body):
    """HTTP及worker共用预检，不接收URL、编号、路径或采用标记。"""
    require(isinstance(body, dict) and set(body) == FIELDS, '补查请求字段错误，不接受编号、路径、URL或通过标记')
    safe_id(body['request_id'], 'componentprobereq'); safe_id(body['expected_a01'], 'run')
    require(body['confirmed'] is True and all(isinstance(body[k], str) and 0 < len(body[k].strip()) <= 2000 for k in ('author', 'note')),
            '请填写补查登记人和说明并明确确认')
    m = workflow.load(sid); check_current(workflow, m)
    require(body['expected_a01'] == m['current'].get('A01') and body['expected_input_hash'] == fingerprint(evidence.snapshot(m)),
            '补查输入或科研意见已改变，请刷新')
    value = context(workflow, m, body['expected_a01']); require(value['targets'], '本版没有可按精确编号补查的HERB待核记录')
    for ref in m.get(INDEX, []):
        old = read_record(workflow, m, ref)
        if old['request']['request_id'] == body['request_id']: require(old['request'] == body, '补查请求号已用于其他内容')
    return deepcopy(body)


def read_record(workflow, m, ref):
    """仅标准库核验原版本、请求、逐查询字节及全部原待核问题，供历史和追溯读取。"""
    home = workflow.location(m['study_id']); value = read_json(verified_file(home, ref))
    require(ref in m.get(INDEX, []) and value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False,
            '补查记录归属或协议错误')
    request = value['request']; require(request['confirmed'] is True and value['request_hash'] == fingerprint(request)
            and request['expected_input_hash'] == fingerprint(value['binding']), '补查请求与原输入不同')
    original = context(workflow, m, request['expected_a01'])
    require(value['context'] == original and original['a01_run_id'] == value['binding']['current']['A01'], '补查来源不是本版原A01')
    require(len(value['rows']) == len(original['targets']), '补查不能丢失原待核组')
    for row, target in zip(value['rows'], original['targets']):
        require(all(row[k] == target[k] for k in ('target_id', 'issues', 'source_files')) and row['adopted'] is False
                and row['state'] in STATES, '补查不能替换原身份、丢问题或自动采用')
    for item in value['files']: verified_file(home, item)
    for item in value['implementation_files']: verified_file(home, item)
    for q in value['queries']:
        meta = read_json(verified_file(home, q['file'])); raw = evidence.read_bytes(home, meta['response_file'])
        require(all(q[k] == meta[k] for k in meta) and meta['bytes'] == len(raw)
                and meta['sha256'] == __import__('hashlib').sha256(raw).hexdigest(), '补查查询摘要与原字节不同')
    require(value['state'] in ('complete', 'partial_failure'), '补查整体状态错误')
    return value


def execute(workflow, sid, body, *, opener=None, sleeper=None, progress=None):
    """锁外联网，锁内发布不可变补查回执；成功请求幂等，部分失败显式重试复用成功原文。"""
    validate_request(workflow, sid, body); m = workflow.load(sid); home = workflow.location(sid)
    original = context(workflow, m, body['expected_a01']); binding = evidence.snapshot(m)
    old = [read_record(workflow, m, ref) for ref in m.get(INDEX, [])]
    same = [row for row in old if row['request'] == body]
    if same and same[-1]['state'] == 'complete' and candidate_coverage(same[-1])['candidate_coverage_complete']: return dict(same[-1], created=False)
    folder = home / 'raw/A01_identity_probes' / body['request_id']
    with write_lock(workflow.root):
        current = workflow.load(sid); check_current(workflow, current)
        require(fingerprint(evidence.snapshot(current)) == body['expected_input_hash'], '补查输入已改变，请刷新')
        folder.mkdir(parents=True, exist_ok=True); path = folder / 'request.json'
        request = {'request': deepcopy(body), 'binding': binding, 'context': original, 'schema_version': VERSION}
        if path.exists(): require(read_json(path) == request, '补查请求号已用于其他内容或原来源变化')
        else: write_json(path, request)
    from science_modules.a01.identity_probe import execute as fetch
    implementation_files = []
    for source in (Path(__file__), Path(__import__('inspect').getfile(fetch)), Path(__import__('inspect').getfile(candidate_hgnc_ids))):
        saved = folder / 'implementation' / source.name
        if saved.exists(): require(saved.read_bytes() == source.read_bytes(), '补查实现已改变，旧请求不能换实现重试')
        else:
            saved.parent.mkdir(exist_ok=True); saved.write_bytes(source.read_bytes())
        implementation_files.append(file_record(home, saved, 'identity_probe_implementation'))
    result = fetch(home, folder, original['targets'], opener=opener, sleeper=sleeper, progress=progress)
    result['files'].append(file_record(home, path, 'identity_probe_request'))
    value = dict(result, schema_version=VERSION, study_id=sid, probe_id=new_id('componentprobe'),
        request=deepcopy(body), request_hash=fingerprint(body), binding=binding, context=original, created_at=now(),
        human_review_written=False, scientific_results_changed=False, implementation_files=implementation_files,
        message_zh='官方精确编号凭据已归档；来源一致性说明不等于原身份已解决，未采用、排除或签署科研复核。')
    with write_lock(workflow.root):
        current = workflow.load(sid); check_current(workflow, current)
        require(fingerprint(evidence.snapshot(current)) == body['expected_input_hash'] and context(workflow, current, body['expected_a01']) == original,
                '补查期间输入或科研意见已改变，原文保留，未发布成功回执')
        target = folder / (value['probe_id'] + '.json'); write_json(target, value)
        ref = file_record(home, target, 'component_identity_probe'); current.setdefault(INDEX, []).append(ref)
        workflow.save(current)
    return dict(value, created=True)


def info(workflow, sid):
    """只读资格与所有不可变历史回执；不会联网或重试。"""
    m = workflow.load(sid); rid = m['current'].get('A01'); blockers = []; supported = False; targets = []
    if rid and workflow.run(m, rid)['config'].get('version') == 'A01.system_publication.1':
        supported = True; targets = context(workflow, m, rid)['targets']
    else: blockers.append('仅支持本版系统三库A01')
    if not targets: blockers.append('本版没有可按原精确编号补查的HERB待核记录')
    from contracts import ContractError
    try: check_current(workflow, m)
    except ContractError as error: blockers.append(str(error))
    records = []
    for ref in m.get(INDEX, []):
        row = read_record(workflow, m, ref); records.append(dict(row, file=deepcopy(ref), **candidate_coverage(row)))
    require(fingerprint(evidence.snapshot(workflow.load(sid))) == fingerprint(evidence.snapshot(m)), '读取期间补查输入已改变，请刷新')
    return {'schema_version': VERSION, 'supported': supported, 'enabled': not blockers, 'blockers': blockers,
            'expected_a01': rid, 'expected_input_hash': fingerprint(evidence.snapshot(m)), 'targets': targets, 'records': records,
            'message_zh': '只补查原记录的精确官方编号并归档；不猜身份、不自动采用或排除，不替代科研复核。'}
