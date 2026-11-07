"""根据当前资格选择导出协议，并提供跨协议的只读历史。"""
from . import system_exports_paths as repaired, system_exports_v2 as original
from . import system_exports_sources as sources

PROTOCOLS = (original, repaired, sources)


def _protocol(w, m):
    """修订资格的附件进入独立档案，原请求按原协议处理。"""
    rid = m['current'].get('A06_PREP')
    if rid and w.run(m, rid)['config'].get('version') in sources.PREPARATION:
        return sources
    if rid and w.run(m, rid)['config'].get('version') in repaired.PREPARATION:
        return repaired
    return original


def info(w, sid):
    """列出同一研究的新旧归档，当前下载仍绑定本次输入。"""
    m = w.load(sid)
    protocol = _protocol(w, m)
    value = protocol.info(w, sid)
    value['history'] = sorted(value['history'] + [
        dict(other.read_record(w, m, ref), file=ref) for other in PROTOCOLS if other is not protocol
        for ref in m.get(other.INDEX, [])
    ], key=lambda record: record['created_at'])
    return value


def validate_request(w, sid, body):
    """按当前适用协议预检。"""
    return _protocol(w, w.load(sid)).validate_request(w, sid, body)


def execute(w, sid, body):
    """相同请求编号沿登记协议恢复，独立协议不可重复占用。"""
    m = w.load(sid)
    if isinstance(body, dict):
        for protocol in PROTOCOLS:
            for ref in m.get(protocol.REQUESTS, []):
                if protocol.read_request(w, m, ref)['request']['request_id'] == body.get('request_id'):
                    return protocol.execute(w, sid, body)
    return _protocol(w, m).execute(w, sid, body)


def records(w, m):
    """读取两类已发表下载。"""
    return [protocol.read_record(w, m, ref) for protocol in PROTOCOLS
            for ref in m.get(protocol.INDEX, [])]
