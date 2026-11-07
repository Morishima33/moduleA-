"""只用本批已指纹核实的官方请求重放来源身份；发布校验不联网。"""
import json
from urllib.error import HTTPError, URLError
from contracts import require, fingerprint
from storage import read_json, verified_file
from .compound_sources_v2 import resolve


class ReplayFetcher:
    def __init__(self, root, refs, files):
        self.root = root
        self.files = files
        require(all(ref in files for ref in refs), '来源重放请求未登记在本对象文件中')
        self.events = [read_json(verified_file(root, ref)) for ref in refs]

    def take(self, expected):
        require(self.events, '来源核验缺少原官方请求')
        value = self.events.pop(0)
        require(all(value.get(k) == v for k, v in expected.items()), '来源请求次序、编号或地址不同')
        error = value.get('error')
        if error:
            if error['kind'] == 'HTTPError':
                raise HTTPError(expected['url'], error['status'], error['reason'], {}, None)
            if error['kind'] == 'URLError':
                raise URLError(error['reason'])
            raise ValueError(error['message'])
        ref = value['file']
        require(ref in self.files, '来源请求响应未登记在本对象文件中')
        path = verified_file(self.root, ref)
        return path, ref

    def get(self, url, suffix='json'):
        path, ref = self.take({'operation': 'get', 'url': url, 'suffix': suffix})
        return (json.loads(path.read_text('utf8')) if suffix == 'json' else {}), ref

    def herb_detail(self, identifier):
        path, ref = self.take({'operation': 'herb_detail', 'identifier': identifier})
        return read_json(path), ref


def validate(home, packet, connection, identities):
    """来源成功项须从同批原来源和原始响应独立重建，不能只相信摘要。"""
    for fixed, row in zip(packet['compounds'], connection['compounds']):
        if row['state'] != 'connected':
            continue
        require('source_requests' in row, '来源成功项缺少可重放的请求证据')
        replay = ReplayFetcher(home, row['source_requests'], connection['files'])
        actual = resolve(fixed, replay, identities.get(fixed['compound_id'], []))
        saved = {k: v for k, v in row.items() if k not in ('source_requests','original_sources')}
        require(not replay.events and fingerprint(actual) == fingerprint(saved),
                '来源身份、CID、官方三维或原始来源关系与归档响应不同')
