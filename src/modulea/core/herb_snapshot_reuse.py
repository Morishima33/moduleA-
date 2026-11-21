"""经明确选择的 HERB 归档，仅复用与当前药味清单一致的官方详情原响应。"""
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import json
import re
from zipfile import ZipFile

from contracts import require, safe_id
from storage import read_json, verified_file, within, write_json
from science_modules.a01 import acquisition as original


class Snapshot:
    def __init__(self, archive, provenance):
        self.archive = archive
        self.names = set(archive.namelist())
        require(len(self.names) == len(archive.namelist()), 'HERB 历史包有重名成员')
        self.provenance = provenance

    def detail(self, token, payload, ingredient_name):
        index = 'original_requests/' + token + '.json'
        binary = 'original_requests/' + token + '.bin'
        if index not in self.names and binary not in self.names:
            return None
        require(index in self.names and binary in self.names, 'HERB 历史详情原件与清单不完整')
        require(self.archive.getinfo(index).file_size <= 64 * 1024
                and self.archive.getinfo(binary).file_size <= 64 * 1024 * 1024, 'HERB 历史详情超过校验容量')
        record = json.loads(self.archive.read(index))
        raw = self.archive.read(binary)
        require(record['url'] == original.HERB_API and record['payload'] == payload
                and record['bytes'] == len(raw) and record['sha256'] == sha256(raw).hexdigest(),
                'HERB 历史详情与原请求或指纹不同')
        detail = original._herb_json(raw)
        summary = detail.get('summary', [])
        if len(summary) != 2 or dict(zip(*summary)).get('Ingredient name') != ingredient_name:
            return None  # 现行清单变化时重新联网；现有解析器重核身份与关系表。
        return raw, dict(record, reused_archive=self.provenance)


class SnapshotFetcher(original.Fetcher):
    """本批原件优先；只有新读到的药味清单中存在的详情才可命中历史快照。"""
    def __init__(self, *args, snapshot, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshot = snapshot
        self.ingredient_names = {}

    def herb(self, func, **values):
        if func == 'detail_api' and values.get('label') == 'Ingredient':
            name = self.ingredient_names.get(values.get('key_id'))
            if name is not None:
                payload = dict(func_name=func, **values)
                token = sha256(original.HERB_API.encode() + json.dumps(payload, sort_keys=True).encode()).hexdigest()
                index = self.folder / (token + '.json')
                binary = self.folder / (token + '.bin')
                if not index.exists() and not binary.exists():
                    match = self.snapshot.detail(token, payload, name)
                    if match is not None:
                        raw, record = match
                        with binary.open('xb') as file:
                            file.write(raw)
                        write_json(index, record)
        response = super().herb(func, **values)
        if func == 'detail_api' and values.get('label') == 'Herb':
            for row in response.get('herb_ingredient', [])[1:]:
                self.ingredient_names[original._value(row[0])] = row[1]
        return response


@contextmanager
def open_snapshot(workflow, manifest, request, herbs):
    """匹配本地授权、登记、方案及指定归档回执，源文件只读。"""
    sid = safe_id(manifest['study_id'], 'study')
    selection = within(workflow.root, 'references/herb_snapshot_reuse/' + sid + '.json')
    if not selection.is_file():
        yield None
        return
    entry = read_json(selection)
    require(set(entry) == {'study_id', 'a00_run_id', 'plan_id', 'source_study_id', 'source_receipt_sha256'},
            'HERB 快照授权记录字段不一致')
    if (entry['study_id'], entry['a00_run_id'], entry['plan_id']) != (
            sid, request['binding']['a00'], request['request']['expected_plan_id']):
        yield None
        return
    source_id = safe_id(entry['source_study_id'], 'study')
    require(source_id != sid and re.fullmatch(r'[0-9a-f]{64}', entry['source_receipt_sha256']),
            'HERB 快照来源或回执指纹无效')
    from . import system_acquisition
    source_manifest = workflow.load(source_id)
    matches = [ref for ref in source_manifest.get(system_acquisition.SOURCES, [])
               if ref['sha256'] == entry['source_receipt_sha256']]
    require(len(matches) == 1, '找不到授权的唯一 HERB 原件回执')
    receipt = system_acquisition.read_record(workflow, source_manifest, matches[0], kind='source')
    source = receipt['source']['source']
    require(source['database'] == 'HERB' and source['source_url'] == original.HERB_API
            and set(source['coverage']) == set(herbs)
            and all(row['status'] == 'complete' for row in source['coverage'].values()),
            'HERB 历史归档的药味、官方来源或覆盖不同')
    ref = receipt['source']['archive']
    require(0 < ref['bytes'] <= 64 * 1024 * 1024, 'HERB 历史归档超过原件容量')
    data = verified_file(workflow.location(source_id), ref).read_bytes()
    require(len(data) == ref['bytes'] and sha256(data).hexdigest() == ref['sha256'], 'HERB 快照读取期间发生变化')
    provenance = dict(entry, source_archive_sha256=ref['sha256'], source_retrieved_at=source['retrieved_at'])
    with ZipFile(BytesIO(data)) as archive:
        yield Snapshot(archive, provenance)
