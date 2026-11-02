"""固定STRING稳定编号原件采集与逐查询恢复；成功空响应、失败和未请求严格区分。"""
import json
from pathlib import Path
import urllib.parse
import urllib.request

from contracts import fingerprint, require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
import ppi_identity as original
from . import plan_identity as identity

VERSION = 'A04.plan_identity_probes.1'
LIMIT = 16 * 1024 * 1024


def request(spec, folder, *, opener=None):
    """每次固定官方POST独立归档；错误响应留字节，但不伪造成功列表或改网址。"""
    url = original.BASE + 'get_string_ids'; params = original.params(spec['identifier'])
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / 'request.json', {'url': url, 'params': params, 'query': spec, 'started_at': now()})
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                 headers={'User-Agent': 'ModuleA/' + VERSION})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=40) as response:
            require(getattr(response, 'status', 200) == 200, 'STRING未返回成功状态')
            require(response.geturl() == url, 'STRING补查发生未批准的重定向')
            raw = response.read(LIMIT + 1)
        (folder / 'response.bin').write_bytes(raw)
        require(len(raw) <= LIMIT, 'STRING补查响应超过容量限制')
        text = raw.decode('utf-8'); rows = json.loads(text)
        require(isinstance(rows, list), 'STRING错误对象不能作为成功空结果')
        source = {'url': url, 'params': params, 'response_text': text,
                  'response_sha256': fingerprint(text), 'retrieved_at': now(), 'query_state': 'succeeded'}
        return {'query': spec, 'source': source}
    except Exception as error:
        # HTTPError正文亦保留；404/限流/超时绝不能转换成[]或身份暂不采用。
        if hasattr(error, 'read') and not (folder / 'response.bin').exists():
            try: (folder / 'response.bin').write_bytes(error.read(LIMIT + 1))
            except OSError: pass
        write_json(folder / 'failure.json', {'schema_version': VERSION, 'query': spec, 'state': 'query_failed',
                   'error_type': type(error).__name__, 'error_zh': str(error), 'finished_at': now()})
        raise


def checked_checkpoint(home, ref, spec, binding_hash):
    """恢复只复用完整成功的原字节；损坏或跨范围缓存立即阻断，不静默重下掩盖。"""
    value = read_json(verified_file(home, ref))
    require(value.get('schema_version') == VERSION and value.get('binding_hash') == binding_hash
            and value.get('query') == spec, 'PPI补查断点不属于本范围或编号')
    raw = verified_file(home, value['response_file']).read_bytes()
    require(value['probe']['query'] == spec and raw.decode('utf-8') == value['probe']['source']['response_text'], 'PPI补查缓存原字节不同')
    for item in value['files']: verified_file(home, item)
    return value['probe']


def execute(home, folder, targets, hgnc_raw, approved_scope, binding_hash, *, opener=None, progress=None):
    """同明确请求复用成功查询，失败仅显式再试；缺项不交给身份解析器。"""
    home = Path(home); folder = Path(folder); expected = identity.queries(targets, hgnc_raw, approved_scope)
    index_path = folder / 'checkpoints.json'; folder.mkdir(parents=True, exist_ok=True)
    probes = []; files = []; failures = []; reused = 0
    for index, spec in enumerate(expected):
        key = fingerprint({'binding_hash': binding_hash, 'query': spec, 'position': index})
        with write_lock(folder):
            saved = read_json(index_path) if index_path.exists() else {}
            ref = saved.get(key)
            if ref:
                probe = checked_checkpoint(home, ref, spec, binding_hash)
                require(probe['source']['query_state'] == 'succeeded', '失败查询不能复用为成功断点')
                probes.append(probe); files.append(ref)
                files.extend(read_json(verified_file(home, ref))['files']); reused += 1
        if not ref:
            attempt = folder / 'attempts' / new_id('queryattempt')
            try:
                probe = request(spec, attempt, opener=opener)
                # 此处逐查询核对原件结构，全部编号是否一致由完整身份解析器另行判断。
                require(probe['source']['url'] == original.BASE + 'get_string_ids', 'PPI补查来源错误')
                rows = json.loads(probe['source']['response_text'])
                require(all(isinstance(row, dict) and str(row.get('queryIndex')) == '0'
                            and row.get('queryItem') == spec['identifier']
                            and isinstance(row.get('preferredName'), str) and isinstance(row.get('stringId'), str)
                            and type(row.get('ncbiTaxonId')) is int for row in rows), 'PPI补查响应不属于本精确编号')
                response_ref = file_record(home, attempt / 'response.bin', 'ppi_identity_query_response')
                request_ref = file_record(home, attempt / 'request.json', 'ppi_identity_query_request')
                value = {'schema_version': VERSION, 'binding_hash': binding_hash, 'query': spec, 'probe': probe,
                         'response_file': response_ref, 'files': [request_ref, response_ref]}
                path = attempt / 'success.json'; write_json(path, value); ref = file_record(home, path, 'ppi_identity_query_checkpoint')
                with write_lock(folder):
                    saved = read_json(index_path) if index_path.exists() else {}
                    if key in saved:
                        probe = checked_checkpoint(home, saved[key], spec, binding_hash); ref = saved[key]; reused += 1
                    else: saved[key] = ref; write_json(index_path, saved, replace=True)
                probes.append(probe); files.append(ref)
                files.extend(read_json(verified_file(home, ref))['files'])
            except Exception as error:
                diagnostic = attempt / 'validation_failure.json'
                write_json(diagnostic, {'schema_version': VERSION, 'query': spec, 'state': 'query_failed',
                                       'error_type': type(error).__name__, 'error_zh': str(error)})
                refs = [file_record(home, p, 'ppi_identity_failed_attempt') for p in sorted(attempt.iterdir()) if p.is_file()]
                failures.append({'query': spec, 'state': 'query_failed', 'error_type': type(error).__name__,
                                 'error_zh': str(error), 'files': refs}); files.extend(refs)
        if progress: progress({'step_zh': '核对获准清单的原稳定编号', 'done': index + 1, 'total': len(expected)})
    if not failures: identity.checked_queries(targets, hgnc_raw, approved_scope, probes)
    return {'schema_version': VERSION, 'state': 'partial_failure' if failures else 'complete',
            'expected_queries': len(expected), 'successful_queries': len(probes), 'reused_queries': reused,
            'probes': probes, 'failures': failures, 'files': files}
