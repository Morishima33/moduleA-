"""虚构精确编号验证真实A01、HTTP、失败恢复及归档绑定；不访问真实网络或研究。"""
import http.client
import io
import json
import shutil
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from contracts import ContractError, fingerprint
from storage import verified_file, write_lock
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core import component_identity_probes as core, component_identity_evidence as evidence
from modulea.core.kernel import full_workflow
from modulea.core.trace_export import build_trace
from science_modules.a01 import identity_probe as science
from tests.modulea import test_system_component_sources as fixture


class Response:
    """模拟HTTP原字节，科学解析、指纹、缓存和归档真实执行。"""
    status = 200
    headers = {'Content-Type': 'application/json'}
    def __init__(self, value): self.raw = json.dumps(value).encode()
    def read(self, size): return self.raw[:size]
    def __enter__(self): return self
    def __exit__(self, *_): pass


class Official:
    """只响应明确虚构HERB编号及其精确Gene编号。"""
    def __init__(self): self.calls = []; self.offline = False; self.partial = False; self.wrong_target = False
    def __call__(self, request, timeout):
        self.calls.append((request.full_url, request.data))
        if request.data:
            tid = json.loads(request.data)['v']
            if self.offline or self.partial and tid == 'HBTAR000002': raise HTTPError(request.full_url, 503, '虚构网关失败', {}, None)
            return Response({'summary': [['Target id', 'Taxonomy id', 'Gene id', 'Gene name', 'HGNC id'],
                ['HBTAR999' if self.wrong_target else tid, '10090', '42', 'UnknownSource', '']]})
        return Response({'result': {'uids': ['42'], '42': {'uid': '42', 'name': 'UnknownSource', 'organism': {'taxid': 10090}}}})


class IdentityProbeScienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.home = Path(self.temp.name)
        self.folder = self.home / 'probe'; self.folder.mkdir(); self.official = Official()
        self.targets = [{'target_id': 'HBTAR000001', 'issues': [{'issue_key': 'fixture'}], 'source_files': []}]
    def execute(self): return science.execute(self.home, self.folder, self.targets, opener=self.official, sleeper=lambda _: None)
    def test_nonhuman_proof_never_adopts_or_excludes_and_cache_has_original_time(self):
        value = self.execute(); self.assertEqual(value['state'], 'complete'); self.assertFalse(value['rows'][0]['adopted'])
        self.assertEqual(value['rows'][0]['state'], 'source_nonhuman_confirmed'); before = len(self.official.calls)
        self.assertEqual(value['rows'][0]['candidate_hgnc_records'], {})
        again = self.execute(); self.assertEqual(len(self.official.calls), before)
        self.assertTrue(all(q['reused'] for q in again['queries']))
        self.assertEqual(again['queries'][0]['retrieved_at'], value['queries'][0]['retrieved_at'])
        for ref in value['files']: verified_file(self.home, ref)
    def test_shared_endpoint_partial_failure_cannot_be_hidden_by_other_target_success(self):
        self.targets.append(dict(self.targets[0], target_id='HBTAR000002')); self.official.partial = True
        first = self.execute(); self.assertEqual(first['state'], 'partial_failure')
        self.assertEqual(sum(q['state'] == 'failed' for q in first['queries']), 3)
        preserved = {r['path']: (self.home / r['path']).read_bytes() for r in first['files']}
        self.official.partial = False; self.official.calls.clear(); second = self.execute()
        self.assertEqual(second['state'], 'complete'); self.assertEqual(len(self.official.calls), 1)
        for name, raw in preserved.items(): self.assertEqual((self.home / name).read_bytes(), raw)
    def test_wrong_target_is_failure_without_retry_or_success_cache(self):
        self.official.wrong_target = True; result = self.execute()
        self.assertEqual(result['state'], 'partial_failure'); self.assertEqual(len(self.official.calls), 1)
        self.assertEqual(list((self.folder / 'cache').glob('*')), [])
    def test_corrupt_success_cache_blocks_instead_of_redownload(self):
        first = self.execute(); ref = first['queries'][0]['response_file']; (self.home / ref['path']).write_bytes(b'corrupt')
        with self.assertRaises(ContractError): self.execute()
        self.assertEqual(len(self.official.calls), 2)
    def test_partial_ncbi_and_wrong_hgnc_are_not_zero_or_unique(self):
        with self.assertRaises(ContractError): science.ncbi_document({'result': {'uids': ['42']}}, ['42', '43'])
        with self.assertRaises(ContractError): science.hgnc_document({'response': {'numFound': 1, 'docs': [{'hgnc_id': 'HGNC:2'}]}}, 'HGNC:1')

    def test_candidate_hgnc_belongs_to_original_target_not_neighboring_target(self):
        from urllib.parse import parse_qs, urlsplit
        self.targets[0]['issues'][0]['candidate_ids'] = 'HGNC:1|HGNC:2'
        self.targets.append({'target_id': 'HBTAR000002', 'issues': [{'issue_key': 'mouse'}], 'source_files': []})
        def official(request, timeout):
            if request.data:
                tid = json.loads(request.data)['v']; human = tid == 'HBTAR000001'
                return Response({'summary': [['Target id', 'Taxonomy id', 'Gene id', 'Gene name', 'HGNC id'],
                    [tid, '9606' if human else '10090', '101' if human else '42', 'OldGene', '1' if human else '']]})
            if 'genenames.org' in request.full_url:
                hid = request.full_url.rsplit('/', 1)[-1]; gid = '101' if hid == 'HGNC:1' else '102'
                return Response({'response': {'numFound': 1, 'docs': [{'hgnc_id': hid, 'status': 'Approved', 'entrez_id': gid, 'symbol': 'Human' + gid}]}})
            ids = parse_qs(urlsplit(request.full_url).query)['id'][0].split(',')
            return Response({'result': {'uids': ids, **{gid: {'uid': gid, 'name': 'Human' + gid, 'organism': {'taxid': 10090 if gid == '42' else 9606}} for gid in ids}}})
        value = science.execute(self.home, self.folder, self.targets, opener=official, sleeper=lambda _: None)
        self.assertEqual(value['state'], 'complete'); self.assertEqual(value['rows'][0]['state'], 'stable_links_agree')
        self.assertEqual(set(value['rows'][0]['candidate_hgnc_records']), {'HGNC:1', 'HGNC:2'})
        self.assertEqual(value['rows'][1]['candidate_hgnc_records'], {})
        self.assertTrue(core.candidate_coverage(value)['candidate_coverage_complete'])
        incomplete = dict(value, queries=[q for q in value['queries'] if not q['url'].endswith('HGNC:2')])
        self.assertEqual(core.candidate_coverage(incomplete)['missing_candidate_hgnc_ids'], ['HGNC:2'])


class ComponentIdentityProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SystemComponentSourceTests.setUpClass.__func__(cls)
        cls.source = fixture.SystemComponentSourceTests(); cls.source.mapping_root = cls.mapping_root
        original = fixture.fixture.synthetic_source
        def unknown(database, *args, **kwargs):
            value = original(database, *args, **kwargs)
            if database == 'HERB':
                with zipfile.ZipFile(io.BytesIO(value['data'])) as archive: files = {n: archive.read(n) for n in archive.namelist()}
                for name in ('HERB_target_browse_page001.json', 'HERB_existing_details/HBIN000001.json'):
                    data = json.loads(files[name]); data['browse_data' if 'browse' in name else 'ingredient_target'][1][1] = 'UNKNOWN'
                    files[name] = json.dumps(data).encode()
                out = io.BytesIO()
                with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for name, raw in files.items(): archive.writestr(name, raw)
                value['data'] = out.getvalue()
            return value
        with patch.object(fixture.fixture, 'synthetic_source', side_effect=unknown): cls.source.setUp()
        cls.addClassCleanup(cls.source.doCleanups); w = cls.source.w; sid = cls.source.sid
        w.bind_analysis_plan_system_a01_sources(sid, cls.source.body); batch = cls.source.start()
        w.execute_analysis_plan_system_stage(sid, {'batch_id': batch['batch_id'], 'stage': 'A01', 'expected_current_run_id': None})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name) / 'data'
        shutil.copytree(self.source.root, self.root); self.sid = self.source.sid; self.w = full_workflow(self.root); self.official = Official()
        m = self.w.load(self.sid); self.before = m
        self.body = {'request_id': 'componentprobereq_' + uuid4().hex, 'expected_a01': m['current']['A01'],
            'expected_input_hash': fingerprint(evidence.snapshot(m)), 'author': '明确虚构补查测试', 'note': '仅归档精确编号凭据，不采用', 'confirmed': True}

    def execute(self): return self.w.probe_analysis_plan_component_identities(self.sid, self.body, opener=self.official, sleeper=lambda _: None)

    def test_public_workflow_archive_trace_idempotence_keep_scientific_files(self):
        home = self.w.location(self.sid); preserved = {r['path']: (home / r['path']).read_bytes() for row in self.before['runs'].values() for r in row.values() if isinstance(r, dict) and 'path' in r}
        result = self.execute(); self.assertTrue(result['created']); self.assertFalse(self.execute()['created'])
        m = self.w.load(self.sid); self.assertEqual(m['current'], self.before['current']); self.assertEqual(m['runs'], self.before['runs']); self.assertEqual(m['reviews'], [])
        self.assertEqual(len(m[core.INDEX]), 1); self.assertEqual(core.read_record(self.w, m, m[core.INDEX][0])['probe_id'], result['probe_id'])
        self.assertTrue(self.w.result(m, m['current']['A01'])['summary']['handoff_blocked'])
        trace = build_trace(self.w, self.sid, include_data=True); self.assertEqual(len(trace['plan_decisions']['component_identity_probes']), 1)
        for ref in trace['files']: verified_file(home, ref)
        for name, raw in preserved.items(): self.assertEqual((home / name).read_bytes(), raw)

    def test_unknown_fields_stale_or_missing_confirmation_do_not_query_or_write(self):
        for change in ({'confirmed': False}, {'url': 'https://example.com'}, {'path': 'outside'}, {'passed': True}, {'expected_input_hash': 'stale'}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.w.probe_analysis_plan_component_identities(self.sid, self.body | change, opener=self.official)
        self.assertFalse(self.official.calls); self.assertEqual(self.w.load(self.sid), self.before)

    def test_partial_failure_receipt_then_explicit_retry_preserves_all_attempts(self):
        self.official.offline = True; first = self.execute(); self.assertEqual(first['state'], 'partial_failure')
        paths = {r['path']: (self.w.location(self.sid) / r['path']).read_bytes() for r in first['files']}
        self.official.offline = False; second = self.execute(); self.assertEqual(second['state'], 'complete')
        self.assertEqual(len(self.w.load(self.sid)[core.INDEX]), 2)
        for name, raw in paths.items(): self.assertEqual((self.w.location(self.sid) / name).read_bytes(), raw)

    def test_changed_input_during_fetch_retains_raw_without_publishing_receipt(self):
        official = self.official
        def changed(request, timeout):
            with write_lock(self.w.root):
                m = self.w.load(self.sid); m['trashed'] = True; self.w.save(m)
            return official(request, timeout)
        with self.assertRaises(ContractError): self.w.probe_analysis_plan_component_identities(self.sid, self.body, opener=changed)
        self.assertNotIn(core.INDEX, self.w.load(self.sid))
        self.assertTrue(list((self.w.location(self.sid) / 'raw/A01_identity_probes').rglob('*.bin')))

    def test_manual_hold_blocks_new_request_and_trash_keeps_history_readable(self):
        self.execute(); m = self.w.load(self.sid)
        self.w.review(self.sid, m['current']['A00'], 'pending', '明确合成测试', '补查暂停')
        with self.assertRaises(ContractError): self.execute()
        with write_lock(self.w.root):
            m = self.w.load(self.sid); m['trashed'] = True; self.w.save(m)
        value = core.info(self.w, self.sid); self.assertFalse(value['enabled']); self.assertEqual(len(value['records']), 1)

    def test_changed_request_and_corrupt_registered_response_rejected(self):
        first = self.execute()
        with self.assertRaises(ContractError): core.validate_request(self.w, self.sid, self.body | {'note': '不同内容'})
        (self.w.location(self.sid) / first['queries'][0]['response_file']['path']).write_bytes(b'changed')
        with self.assertRaises(ContractError): core.info(self.w, self.sid)

    def test_real_http_read_download_strict_post_and_worker_handler(self):
        from modulea.tasks.worker import run_component_identity_probe
        from types import SimpleNamespace
        settings = Settings(data_root=self.root, runtime_dir=Path(self.temp.name) / 'runtime')
        server, app = create_server(settings, 0); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def call(method, suffix='', body=None, token=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
            try:
                headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{server.server_port}'}
                if token: headers['X-ModuleA-Token'] = token
                conn.request(method, '/api/v1' + suffix, json.dumps(body) if body else None, headers)
                response = conn.getresponse(); return response.status, response.read()
            finally: conn.close()
        try:
            path = f'/studies/{self.sid}/analysis-plan/component-identity-probes'
            module_path = f'/studies/{self.sid}/modules/A01'
            status, raw = call('GET', module_path)
            self.assertEqual(status, 200, raw)
            self.assertTrue(json.loads(raw)['special']['system_component_publication']['identity_tools_available'])
            status, raw = call('GET', path.replace('probes', 'evidence'))
            self.assertEqual(status, 200, raw)
            self.assertTrue(json.loads(raw)['supported'])
            status, raw = call('GET', path); self.assertEqual(status, 200, raw); self.assertEqual(json.loads(raw)['records'], [])
            self.assertEqual(self.w.load(self.sid), self.before); self.assertFalse(self.official.calls)
            status, raw = call('GET', '/session'); token = json.loads(raw)['token']
            self.assertEqual(call('POST', path + '/execute', self.body)[0], 403)
            self.assertEqual(call('POST', path + '/execute', self.body | {'url': 'outside'}, token)[0], 422)
            with patch.object(app.tasks, '_spawn', return_value=None):
                status, raw = call('POST', path + '/execute', self.body, token); self.assertEqual(status, 202, raw)
            task = json.loads(raw)['task']; self.assertEqual(task['kind'], 'plan_component_identity_probe')
            with patch('science_modules.a01.identity_probe.urllib.request.urlopen', side_effect=self.official):
                message = run_component_identity_probe(settings, {'task_id': task['task_id'], 'study_id': self.sid, 'payload': json.dumps(self.body)}, SimpleNamespace(update=lambda *a, **k: None))
            self.assertIn('已归档', message)
            status, raw = call('GET', path); value = json.loads(raw); self.assertEqual(status, 200, raw)
            url = value['records'][0]['downloads'][0]['url'].removeprefix('/api/v1')
            self.assertEqual(call('GET', url)[0], 200); self.assertEqual(call('GET', url + '&path=outside')[0], 422)
            self.assertEqual(call('GET', path + '/componentprobe_' + '0' * 32 + '/files/0?expected_record_sha256=x')[0], 404)
        finally: server.shutdown(); server.server_close(); thread.join(5)


if __name__ == '__main__': unittest.main()
