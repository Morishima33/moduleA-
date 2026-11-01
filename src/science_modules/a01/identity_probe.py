"""按原HERB精确编号获取官方凭据；只记录来源一致性，不采用身份或改写科学结果。"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from contracts import require
from storage import file_record, now, read_json, verified_file, write_json
from .identity_probe_contract import candidate_hgnc_ids

VERSION = 'A01.identity_probe.1'
LIMIT = 4 * 1024 * 1024


def text(value):
    """官方链接单元格只取其显式标题，不从URL猜编号。"""
    return str(value.get('title', '')) if isinstance(value, dict) else str(value or '')


def herb_document(data, target):
    """精确核对Target详情和必要字段，未知物种/编号保留为空。"""
    rows = data.get('summary')
    require(isinstance(rows, list) and len(rows) == 2 and len(rows[0]) == len(rows[1]), 'HERB靶点详情结构改变')
    row = {key: text(value).strip() for key, value in zip(rows[0], rows[1])}
    require(row.get('Target id') == target, 'HERB返回了其他靶点编号')
    require(row.get('Gene name'), 'HERB靶点详情缺少原基因名')
    for field in ('Gene id', 'Taxonomy id', 'HGNC id'):
        require(not row.get(field) or re.fullmatch(r'[0-9]+', row[field]), 'HERB官方编号格式改变：' + field)
    return row


def hgnc_document(data, target):
    """HGNC精确编号必须得到唯一相同编号的原记录。"""
    response = data.get('response', {}); docs = response.get('docs')
    require(response.get('numFound') == 1 and isinstance(docs, list) and len(docs) == 1
            and docs[0].get('hgnc_id') == target, 'HGNC精确编号无唯一对应原记录')
    return docs[0]


def ncbi_document(data, ids):
    """逐个明确Gene编号核对，部分响应或错误不能当作零结果。"""
    result = data.get('result', {})
    require(isinstance(result, dict) and set(result.get('uids', [])) == set(ids), 'NCBI精确编号响应不完整')
    for gid in ids:
        row = result.get(gid, {})
        require(str(row.get('uid')) == gid and not row.get('error') and row.get('name')
                and type(row.get('organism', {}).get('taxid')) is int, 'NCBI基因原记录缺失或编号不同')
    return result


def execute(home, folder, targets, *, opener=None, sleeper=None, progress=None):
    """固定官方端点，逐查询保存原文和失败；同请求仅复用已核验成功响应。"""
    opener = opener or urllib.request.urlopen; sleeper = sleeper or time.sleep
    attempt = folder / 'attempts' / __import__('uuid').uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    cache = folder / 'cache'; cache.mkdir(exist_ok=True)
    files = []; queries = []

    def get(label, url, payload, validate):
        """每次实际尝试独立保存，只有成功HTTP与有效内容才可进入成功缓存。"""
        key = hashlib.sha256(json.dumps([url, payload], sort_keys=True).encode()).hexdigest()
        cached = cache / (key + '.json')
        if cached.exists():
            meta = read_json(cached); raw = verified_file(home, meta['response_file']).read_bytes()
            require(meta['url'] == url and meta['payload'] == payload and meta['state'] == 'ready'
                    and meta['version'] == VERSION and meta['http_status'] == 200
                    and len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256'],
                    '补查成功缓存与原查询或字节不同')
            data = validate(json.loads(raw)); ref = file_record(home, cached, 'identity_probe_query')
            files.extend([ref, meta['response_file']]); queries.append(dict(meta, file=ref, reused=True))
            return data
        if progress: progress('按原精确编号补查：' + label)
        for number in range(1, 4):
            raw = b''; status = None; headers = {}; error = ''; retry = False; parsed = None
            try:
                request = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None,
                    headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'ModuleA/1.0'})
                with opener(request, timeout=25) as response:
                    status = response.status; headers = dict(response.headers)
                    final = response.geturl() if hasattr(response, 'geturl') else url
                    require(urllib.parse.urlsplit(final).hostname == urllib.parse.urlsplit(url).hostname,
                            '官方请求跳转到其他站点，未采用响应')
                    raw = response.read(LIMIT + 1)
                require(status == 200 and len(raw) <= LIMIT, '官方响应状态或大小异常')
                parsed = validate(json.loads(raw))
            except urllib.error.HTTPError as exc:
                status = exc.code; headers = dict(exc.headers or {}); raw = exc.read(LIMIT + 1); exc.close()
                error = '官方请求失败，HTTP ' + str(status); retry = status in (429, 500, 502, 503, 504)
            except (TimeoutError, ConnectionError, urllib.error.URLError) as exc:
                error = '官方连接失败：' + type(exc).__name__
                retry = isinstance(exc, (TimeoutError, ConnectionError)) or isinstance(getattr(exc, 'reason', None), (TimeoutError, ConnectionError))
            except Exception as exc:
                error = '官方响应未通过核验：' + str(exc)
            base = attempt / (key + '_' + str(number)); body = base.with_suffix('.bin')
            body.write_bytes(raw); body_ref = file_record(home, body, 'identity_probe_response')
            meta = {'version': VERSION, 'label_zh': label, 'url': url, 'payload': payload,
                    'http_status': status, 'headers': headers, 'retrieved_at': now(), 'attempt': number,
                    'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'response_file': body_ref,
                    'state': 'failed' if error else 'ready', 'error_zh': error}
            path = base.with_suffix('.json'); write_json(path, meta); ref = file_record(home, path, 'identity_probe_query')
            files.extend([ref, body_ref]); queries.append(dict(meta, file=ref, reused=False))
            if not error:
                write_json(cached, meta); files.append(file_record(home, cached, 'identity_probe_query'))
                return parsed
            if not retry or number == 3: return None
            sleeper(2 ** number)

    herb = {}; hgnc_ids = set()
    for target in targets:
        tid = target['target_id']; require(re.fullmatch(r'HBTAR[0-9]+', tid), '原HERB靶点编号格式错误')
        payload = {'func_name': 'detail_api', 'label': 'Target', 'v': tid, 'key_id': tid}
        herb[tid] = get('HERB ' + tid, 'http://herb.ac.cn/chedi/api/', payload, lambda data, t=tid: herb_document(data, t))
        hgnc_ids.update(cid for row in target['issues'] for cid in candidate_hgnc_ids(row))
        if herb[tid] and herb[tid].get('HGNC id'): hgnc_ids.add('HGNC:' + herb[tid]['HGNC id'])
    hgnc = {}
    for hid in sorted(hgnc_ids):
        hgnc[hid] = get('HGNC ' + hid, 'https://rest.genenames.org/fetch/hgnc_id/' + hid, None,
                        lambda data, h=hid: hgnc_document(data, h))
    gene_ids = {row['Gene id'] for row in herb.values() if row and row.get('Gene id')}
    gene_ids.update(str(row['entrez_id']) for row in hgnc.values() if row and str(row.get('entrez_id', '')).isdigit())
    ids = sorted(gene_ids, key=int); ncbi = None
    if ids:
        url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?' + urllib.parse.urlencode({'db': 'gene', 'id': ','.join(ids), 'retmode': 'json'})
        ncbi = get('NCBI精确Gene编号', url, None, lambda data: ncbi_document(data, ids))
    rows = []
    for target in targets:
        detail = herb[target['target_id']]; state = 'query_failed'; message = '官方补查失败，未确认来源身份'
        gene = ncbi.get(detail.get('Gene id')) if ncbi and detail else None
        hg = hgnc.get('HGNC:' + detail.get('HGNC id', '')) if detail else None
        if detail and gene:
            taxa_match = str(gene['organism']['taxid']) == detail.get('Taxonomy id')
            if not taxa_match: state, message = 'conflicting', 'HERB与NCBI物种不一致，继续待核'
            elif gene['organism']['taxid'] != 9606: state, message = 'source_nonhuman_confirmed', 'HERB精确Gene编号与NCBI均指向非人类；未自动排除原关系'
            elif hg and hg.get('status') == 'Approved' and str(hg.get('entrez_id')) == detail['Gene id'] and hg.get('symbol') == gene['name']:
                state, message = 'stable_links_agree', '来源稳定编号与人类官方现名一致；原名称歧义仍须按既有规则处理，未采用'
            elif detail.get('HGNC id') and not hg: state, message = 'query_failed', 'HGNC补查未完成，不能确认完整交叉凭据'
            else: state, message = 'missing_or_conflicting_ids', '来源编号不足或未一致，继续待核'
        elif detail and not detail.get('Gene id'): state, message = 'missing_ids', '原详情缺少明确Gene编号，未猜测身份'
        local_candidates = {cid for issue in target['issues'] for cid in candidate_hgnc_ids(issue)}
        if detail and detail.get('HGNC id'): local_candidates.add('HGNC:' + detail['HGNC id'])
        rows.append({'target_id': target['target_id'], 'issues': target['issues'], 'source_files': target['source_files'],
            'herb_detail': detail, 'ncbi_gene': gene, 'hgnc_record': hg,
            'candidate_hgnc_records': {hid: hgnc.get(hid) for hid in sorted(local_candidates) if hid in hgnc},
            'state': state, 'message_zh': message, 'adopted': False})
    return {'rows': rows, 'queries': queries, 'files': list({r['path']: r for r in files}.values()),
            'state': 'partial_failure' if any(q['state'] == 'failed' and not any(x['url'] == q['url'] and x['payload'] == q['payload'] and x['state'] == 'ready' for x in queries) for q in queries) else 'complete'}
