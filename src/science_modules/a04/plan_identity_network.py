"""PPI精确身份例外的新网络协议；全部原交集、原映射和既定中心性规则保留。"""
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

from contracts import fingerprint, require
from storage import now, read_json, verified_file
from science_modules.analysis_protocol import checked_plan
from . import plan_flow as original, plan_identity as identity

VERSION = 'A04.plan_network.2'
SOURCE_VERSION = 'A04.plan_source.2'


def request_network(params, *, opener=None, evidence=None):
    """新网络的原HTTP成功及失败都保留；404/超时不回退旧网络或占位空列表。"""
    url = original.BASE + 'network'; raw = None
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers={'User-Agent': 'ModuleA/' + VERSION})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=40) as response:
            require(getattr(response, 'status', 200) == 200 and response.geturl() == url, 'STRING新网络状态或实际网址错误')
            raw = response.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024, 'STRING新网络响应超过容量限制')
        text = raw.decode('utf-8'); rows = json.loads(text)
        require(isinstance(rows, list), 'STRING新网络未返回完整列表')
        value = {'url': url, 'params': params, 'response_text': text, 'response_sha256': fingerprint(text),
                 'method': 'network', 'retrieved_at': now(), 'query_state': 'succeeded'}
        if evidence: evidence(value)
        return value
    except Exception as error:
        if raw is None and hasattr(error, 'read'):
            try: raw = error.read(16 * 1024 * 1024 + 1)
            except OSError: pass
        value = {'url': url, 'params': params, 'method': 'network', 'query_state': 'query_failed',
                 'retrieved_at': now(), 'error_type': type(error).__name__, 'error_zh': str(error)}
        if raw is not None:
            # 失败原字节以十六进制保留，不能用替换解码掩盖原始内容。
            value.update(response_bytes_hex=raw.hex(), response_bytes_sha256=hashlib.sha256(raw).hexdigest())
        if evidence: evidence(value)
        raise


def corrected_mapping(targets, old_source, probes, hgnc_raw, scope, plan):
    """只派生原名称映射；完整稳定编号、反证和碰撞规则委托既定独立解析器。"""
    plan = checked_plan(plan)
    require(old_source.get('schema_version') == 'A04.plan_source.1'
            and old_source.get('string_version') == '12.0'
            and old_source.get('analysis_parameter_hash') == plan['parameter_hash'], 'PPI原来源包版本或方案不同')
    require(old_source['mapping']['url'] == original.BASE + 'get_string_ids'
            and old_source['mapping']['params'] == {'identifiers': '\r'.join(x['symbol'] for x in targets),
                'species': 9606, 'echo_query': 1, 'caller_identity': 'ModuleA'}, 'PPI原名称请求不属于原完整交集')
    mapping = json.loads(old_source['mapping']['response_text'])
    return identity.resolve(targets, mapping, probes, hgnc_raw, scope)


def mapped_ids(targets, mapping):
    """完全沿用原唯一人类名称判定；网络请求不含未决、额外或替代节点。"""
    ids = []
    for index, target in enumerate(targets):
        matches = [row for row in mapping if row['queryIndex'] == index]
        if len(matches) == 1 and matches[0]['ncbiTaxonId'] == 9606 and matches[0]['preferredName'] == target['symbol'] and matches[0]['stringId'].startswith('9606.'):
            ids.append(matches[0]['stringId'])
    require(len(ids) == len(set(ids)), '多个原交集基因映射同一STRING身份，不允许合并')
    return sorted(ids)


def network_params(ids, plan):
    """新请求逐项复用原方案，不扩展节点、不改变置信度或网络类型。"""
    return {'identifiers': '\r'.join(ids), 'species': 9606,
            'required_score': int(round(checked_plan(plan)['parameters']['a04.required_score'] * 1000)),
            'network_type': 'functional', 'add_nodes': 0, 'caller_identity': 'ModuleA'}


def fetch_network(targets, old_source, probes, hgnc_raw, scope, plan, *, opener=None, evidence=None):
    """对全部核实后身份重新获取完整网络；不在旧边上拼接缺失节点。"""
    mapping, _, _ = corrected_mapping(targets, old_source, probes, hgnc_raw, scope, plan)
    ids = mapped_ids(targets, mapping); params = network_params(ids, plan)
    network = request_network(params, opener=opener, evidence=evidence) if len(ids) > 1 else {
        'url': original.BASE + 'network', 'params': params, 'response_text': '[]',
        'response_sha256': fingerprint('[]'), 'method': 'network', 'skipped': '少于两个已核验节点'}
    require(network['url'] == original.BASE + 'network' and network['params'] == params, 'PPI新网络请求不属于本批完整核实范围')
    # 原生产request已核验完整列表；独立来源2仍保存原文指纹，不能生成替代空结果。
    if evidence and len(ids) <= 1: evidence(network)
    require(network.get('response_sha256') == fingerprint(network['response_text']), 'PPI新网络原文缺少一致指纹')
    return {'schema_version': SOURCE_VERSION, 'string_version': '12.0', 'analysis_parameter_hash': plan['parameter_hash'],
            'mapped_string_ids': ids, 'network': network}


def evaluate(targets, old_source, probes, hgnc_raw, scope, new_source, plan):
    """复算派生映射及全网络；原未决保留，只有明确范围内的暂不采用可解除交接阻断。"""
    plan = checked_plan(plan)
    corrected, adjustments, decisions = corrected_mapping(targets, old_source, probes, hgnc_raw, scope, plan)
    require(new_source.get('schema_version') == SOURCE_VERSION and new_source.get('string_version') == '12.0'
            and new_source.get('analysis_parameter_hash') == plan['parameter_hash'], 'PPI新来源版本或参数指纹不同')
    ids = mapped_ids(targets, corrected); network = new_source['network']
    require(new_source['mapped_string_ids'] == ids and network['url'] == original.BASE + 'network'
            and network['params'] == network_params(ids, plan)
            and network['response_sha256'] == fingerprint(network['response_text']), 'PPI新网络范围、参数或原文不同')
    rows = json.loads(network['response_text']); require(isinstance(rows, list), 'PPI网络错误对象不能作为空网络')
    summary, tables = original.calculate(targets, corrected, rows, plan)
    omitted = [row for row in decisions if row['action'] == 'temporarily_omitted']
    unresolved = [row for row in decisions if row['action'] == 'unresolved']
    # 仍保留原完整身份问题表；暂不采用不改称“身份已解决”，也不填零度数。
    require({row['target_id'] for row in tables['identity_issues']} == {row['target_id'] for row in omitted + unresolved},
            'PPI派生后的未决身份不等于完整明确清单')
    tables.update(identity_decisions=decisions, identity_adjustments=adjustments,
                  identity_temporarily_omitted=omitted, identity_unresolved=unresolved,
                  original_identity_scope=[{'target_id': gid} for gid in scope['check_ids']])
    summary.update(analysis_plan_id=plan['parameter_hash'], analysis_parameter_hash=plan['parameter_hash'],
                   STRING版本='12.0', 计算库版本=original.NETWORKX_VERSION, analysis_purpose='workflow_test',
                   identity_protocol=identity.VERSION, identity_notice_zh=identity.NOTICE,
                   原身份问题数=len(decisions), 稳定编号核实数=len(adjustments), 本次PPI暂不采用数=len(omitted),
                   未获准身份阻断数=len(unresolved), handoff_blocked=bool(unresolved))
    return summary, tables


def implementation_files():
    """新版本复算同时固定原网络算法、身份规则及发布桥接字节。"""
    import ppi_identity
    from modulea.core import ppi_identity_revision
    return [Path(__file__), Path(original.__file__), Path(identity.__file__), Path(ppi_identity.__file__), Path(ppi_identity_revision.__file__)]


def configuration(plan, plan_id):
    """同方案显式新版本；旧第一版配置不原地追加字段。"""
    plan = checked_plan(plan)
    return {'version': VERSION, 'identity_protocol': identity.VERSION, 'identity_scope_protocol': 'A04.plan_identity_scope.1',
            'string_version': '12.0', 'required_score': int(round(plan['parameters']['a04.required_score'] * 1000)),
            'network_type': 'functional', 'add_nodes': 0, 'analysis_plan_id': plan_id,
            'analysis_parameter_hash': plan['parameter_hash'],
            'implementation_sha256': {str(path.relative_to(Path(__file__).parents[2])).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in implementation_files()}}


def facts(w, m, inputs):
    """发布和规范校验共用原批准、完整补查回执及新原始网络，不接受自行组合证据。"""
    from modulea.core import ppi_identity_scope as scopes, ppi_identity_probes as registry, ppi_identity_revision as revisions
    home = w.location(m['study_id']); approved = scopes.read_record(w, m, inputs['ppi_identity_scope'])
    probe = registry.read_record(w, m, inputs['ppi_identity_probes']); binding = approved['binding']
    request = registry.read_request(w, m, probe['request_file'])
    revision = revisions.read_request(w, m, inputs['identity_revision_request'])
    require(probe['state'] == 'complete' and request['scope_file'] == inputs['ppi_identity_scope']
            and revision['scope_file'] == inputs['ppi_identity_scope'] and revision['probe_file'] == inputs['ppi_identity_probes']
            and inputs['study_id'] == m['study_id'] == binding['study_id']
            and inputs['bound_a00'] == binding['current']['A00']
            and inputs['parent_result'] == binding['run_files']['A03']['result_file']
            and inputs['analysis_plan_file'] == binding['plan_file']
            and inputs['analysis_plan_id'] == binding['plan_id']
            and inputs['analysis_parameter_hash'] == binding['parameter_hash']
            and inputs['original_ppi_run'] == binding['run_files']['A04']['run_file']
            and inputs['original_ppi_source'] == binding['source_file'], 'PPI发布原批准、补查或上游不同')
    plan = read_json(verified_file(home, binding['plan_file']))['plan']
    targets = w.result(m, binding['current']['A03'])['tables']['intersection_targets']
    summary, tables = evaluate(targets, read_json(verified_file(home, binding['source_file'])), probe['probes'],
                               verified_file(home, binding['mapping_file']).read_bytes(), approved['scope'],
                               read_json(verified_file(home, inputs['source_file'])), plan)
    summary['analysis_plan_id'] = inputs['analysis_plan_id']
    return summary, tables


def validator(root, fallback):
    """只接新第二版，旧PPI验证器继续冻结；实际系统父回执和原精确批准均必需。"""
    def check(run, summary, tables, anomalies, outcome):
        if run['config'].get('version') != VERSION: return fallback(run, summary, tables, anomalies, outcome)
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from modulea.core import ppi_identity_scope as scopes
        w = AnalysisPlanWorkflow(root); m = w.load(run['study_id']); inputs = run['inputs']; home = w.location(m['study_id'])
        approved = scopes.read_record(w, m, inputs['ppi_identity_scope']); binding = approved['binding']
        plan = read_json(verified_file(home, binding['plan_file']))['plan']
        require(run.get('execution_protocol') == 'ModuleA.system_execution.1'
                and run.get('execution_authority') == 'system_validation' and run['parent_review_ids'] == {}
                and run['batch_file'] == binding['batch_file'] and run['parent_runs'] == {'A03': binding['current']['A03']}
                and run['config'] == configuration(plan, binding['plan_id']), 'PPI新协议配置、原批准或系统依赖不同')
        expected, rows = facts(w, m, inputs)
        require((summary, tables) == (expected, rows) and outcome == ('success' if summary['参与节点数'] else 'empty'),
                'PPI新结果与原件复算或实际状态不同')
    return check
