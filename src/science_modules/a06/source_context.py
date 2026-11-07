"""从本批A01归档追溯内部CHEM编号，不接受客户端身份或路径覆盖。"""
from copy import deepcopy
import csv
import io
from pathlib import Path
import time
import urllib.request
from urllib.error import HTTPError, URLError

from contracts import require
from storage import file_record, new_id, read_json, verified_file, write_json
from .automatic_sources import Fetcher as OriginalFetcher


def bound_sources(workflow, manifest, packet):
    """沿固定A03父运行读取原三库来源，所有身份表必须已登记且指纹完整。"""
    home = workflow.location(manifest['study_id'])
    a03 = workflow.run(manifest, packet['runs']['A03'])
    a01_id = a03['parent_runs']['A01']
    a01 = workflow.run(manifest, a01_id)
    result = workflow.result(manifest, a01_id)
    rows = result['tables'].get('component_sources', [])
    staging = a01['inputs'].get('staging_file')
    datasets = read_json(verified_file(home, staging)).get('datasets', []) if staging else []
    identities = {}
    wanted = {row['compound_id'] for row in packet['compounds']}
    # HERB全量身份表保留了原CID/TCMSP编号，不能只使用下游显示名称。
    herb_tables = [ref for slot in datasets if slot['database'] == 'HERB' for ref in slot['files']
                   if Path(ref['path']).name == 'HERB_ingredient_info_v2.txt']
    require(len(herb_tables) <= 1, '本批HERB完整身份表不唯一')
    herb = {}
    if herb_tables:
        text = verified_file(home, herb_tables[0]).read_text('utf-8-sig')
        values = list(csv.DictReader(io.StringIO(text), delimiter='\t'))
        herb = {r['Ingredient_id']: r for r in values}
        require(len(herb) == len(values), '本批HERB身份编号重复')
    for row in rows:
        if row['compound_id'] not in wanted:
            continue
        identity = deepcopy(row)
        identity['a01_result'] = deepcopy(manifest['runs'][a01_id]['result_file'])
        if identity.get('source') == 'BATMAN':
            # 原BATMAN解析器的source_id来自PubChem_CID列，不是内部CHEM编号。
            from .compound_sources_v2 import _cid
            identity['pubchem_id'] = str(_cid(identity['source_id']) or '')
        if identity.get('source') == 'HERB' and identity['source_id'] in herb:
            original = herb[identity['source_id']]
            identity.update(pubchem_id=original.get('PubChem_id', ''), tcmsp_id=original.get('TCMSP_id', ''),
                            identity_file=deepcopy(herb_tables[0]))
        identities.setdefault(row['compound_id'], []).append(identity)
    require(set(identities) == wanted, '本批内部成分编号缺少A01原始来源关系，不能仅按显示名称补查')
    return identities


class Fetcher(OriginalFetcher):
    """旧GET原件归档直接复用；HERB补查复用原采集器的固定官方POST与退避。"""
    def herb_detail(self, identifier):
        from science_modules.a01.acquisition import Fetcher as HerbFetcher
        folder = self.folder / ('herb_' + identifier)
        fetch = HerbFetcher(folder, urllib.request.urlopen, time.sleep)
        try:
            detail = fetch.herb('detail_api', label='Ingredient', v=identifier, key_id=identifier)
            path = folder / 'normalized_detail.json'; write_json(path, detail)
            ref = file_record(self.root, path, 'official_herb_ingredient_detail')
            # 重放需与返回引用连角色一并登记，不能只留相同字节的泛来源别名。
            self.records.append(ref)
            self.save_event({'operation': 'herb_detail', 'identifier': identifier, 'file': ref})
            return detail, ref
        finally:
            self.records.extend(file_record(self.root, p, 'official_herb_source')
                                for p in sorted(folder.rglob('*')) if p.is_file())
    def __init__(self, root, folder):
        super().__init__(root, folder)
        self.events = []

    def get(self, url, suffix='json'):
        event = {'operation': 'get', 'url': url, 'suffix': suffix}
        try:
            value, ref = super().get(url, suffix)
            event['file'] = ref
            return value, ref
        except (ValueError, KeyError, TypeError, OSError) as error:
            event['error'] = {'message': str(error), 'kind': type(error).__name__}
            if isinstance(error, HTTPError):
                event['error'].update(status=error.code, reason=str(error.reason))
            elif isinstance(error, URLError):
                event['error']['reason'] = str(error.reason)
            raise
        finally:
            self.save_event(event)

    def save_event(self, event):
        path = self.folder / (new_id('boundrequest') + '.json')
        write_json(path, event)
        ref = file_record(self.root, path, 'bound_source_request')
        self.records.append(ref)
        self.events.append(ref)

