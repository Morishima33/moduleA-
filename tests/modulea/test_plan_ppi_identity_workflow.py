"""PPI精确批准和成功原件恢复：合成外部响应，实际公开Workflow/网络规范/追溯。"""
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError, fingerprint
from storage import read_json, verified_file
from modulea.core.kernel import full_workflow
from modulea.core import ppi_identity_scope as scopes, ppi_identity_probes as probes, system_execution as execution
from modulea.core.trace_export import build_trace
from science_modules.a04 import plan_flow as network
import ppi_identity as original
from tests.modulea import plan_report_fixture as fixture
from tests.modulea.plan_report_nonempty_fixture import string_response


class Response(io.BytesIO):
    """明确合成的官方响应形状；不会真实联网。"""
    status = 200

    def geturl(self):
        return original.BASE + 'get_string_ids'


class PpiIdentityFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_temp = tempfile.TemporaryDirectory(prefix='ppi_scope_base_'); cls.addClassCleanup(cls.base_temp.cleanup)
        cls.base = Path(cls.base_temp.name) / 'data'
        w, cls.sid, _, _ = fixture.prepare(cls.base, modern=True, multiple_targets=True, stop_before_normalization=True)
        value = execution.info(w, cls.sid)
        batch = w.start_analysis_plan_system_batch(cls.sid, {k: value[k] for k in ('expected_a00', 'expected_plan_id', 'expected_input_hash')} |
            {'request_id': 'systembatchreq_' + uuid4().hex, 'author': '明确合成测试', 'note': 'PPI精确清单测试，不是实际研究批准', 'confirmed': True})
        cls.batch_id = batch['batch_id']
        for stage in ('A01', 'A02', 'A03', 'A03_SELECT', 'A04'):
            body = {'batch_id': cls.batch_id, 'stage': stage, 'expected_current_run_id': w.load(cls.sid)['current'].get(stage)}
            if stage == 'A04':
                with patch.object(network, 'request', side_effect=cls.original_string_response): w.execute_analysis_plan_system_stage(cls.sid, body)
            else: w.execute_analysis_plan_system_stage(cls.sid, body)

    @staticmethod
    def original_string_response(method, params, opener=None):
        """原第五基因没有名称匹配；其余四个仍通过实际旧协议规范计算。"""
        value = string_response(method, params, opener)
        rows = json.loads(value['response_text'])
        rows = [row for row in rows if row['queryIndex'] != 4] if method == 'get_string_ids' else [row for row in rows if row['stringId_B'] != '9606.5']
        value['response_text'] = json.dumps(rows); return value

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ppi_scope_'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'; shutil.copytree(self.base, self.root)
        self.w = full_workflow(self.root); self.before = self.w.load(self.sid); self.home = self.w.location(self.sid)
        self.rid = self.before['current']['A04']; self.binding = scopes.current_context(self.w, self.before)
        self.hgnc_raw = verified_file(self.home, self.binding['mapping_file']).read_bytes()
        self.snapshot = patch.object(original, 'SNAPSHOT', hashlib.sha256(self.hgnc_raw).hexdigest()); self.snapshot.start(); self.addCleanup(self.snapshot.stop)
        self.raw = self.proposal()
        self.body = {'request_id': 'ppiscopereq_' + uuid4().hex, 'expected_a04': self.rid, 'expected_input_hash': fingerprint(self.binding),
                     'expected_proposal_sha256': hashlib.sha256(self.raw).hexdigest(), 'check_ids': ['HGNC:5'], 'omit_ids': ['HGNC:5'],
                     'author': '明确合成测试', 'note': '本合成研究精确清单', 'user_decision': '明确合成决定，仅本批清单，不是实际用户科学批准', 'confirmed': True}

    def proposal(self):
        """仅从实际生成的合成原件构造提案，不直接修改manifest或绕过发布。"""
        m = self.before; targets = self.w.result(m, m['current']['A03'])['tables']['intersection_targets']
        source = read_json(verified_file(self.home, self.binding['source_file']))
        mapping = json.loads(source['mapping']['response_text'])
        hgnc = {row['hgnc_id']: row for row in csv.DictReader(io.StringIO(self.hgnc_raw.decode()), delimiter='\t')}
        items = []
        for issue in self.binding['issues']:
            gid = issue['target_id']; index = next(i for i, row in enumerate(targets) if row['target_id'] == gid)
            items.append({'issue': issue, 'original_query_index': index, 'string_responses': [row for row in mapping if row['queryIndex'] == index],
                          'frozen_hgnc_fields': hgnc[gid]})
        return json.dumps({'protocol': 'ModuleA.ppi_identity_scope_proposal.1', 'study_id': self.sid, 'analysis_purpose': 'workflow_test',
                          'a04_run_id': self.rid, 'a03_run_id': m['current']['A03'], 'batch_file': self.binding['batch_file'],
                          'a04_run_files': self.binding['run_files']['A04'], 'mapping_file_sha256': self.binding['mapping_file']['sha256'],
                          'issue_ids': sorted(row['target_id'] for row in self.binding['issues']), 'original_issues': items}, ensure_ascii=False).encode()

    def register(self):
        return self.w.register_analysis_plan_ppi_identity_scope(self.sid, self.body, self.raw)

    def probe_body(self):
        self.register()
        return {'request_id': 'ppiprobereq_' + uuid4().hex, 'scope_request_id': self.body['request_id'],
                'expected_input_hash': self.body['expected_input_hash'], 'author': '明确合成测试', 'note': '明确合成响应，无实际官方请求', 'confirmed': True}

    def opener(self, request, timeout=40):
        """按原查询编号返回唯一响应，但测试不会自动采用该映射。"""
        self.assertEqual(request.full_url, original.BASE + 'get_string_ids'); self.assertEqual(timeout, 40)
        params = urllib.parse.parse_qs(request.data.decode()); identifier = params['identifiers'][0]
        return Response(json.dumps([{'queryIndex': 0, 'queryItem': identifier, 'ncbiTaxonId': 9606,
                                     'preferredName': 'E', 'stringId': '9606.5'}]).encode())

    def assert_science_unchanged(self):
        m = self.w.load(self.sid)
        for key in ('current', 'runs', 'reviews'): self.assertEqual(m[key], self.before[key])


class PlanPpiIdentityWorkflowTests(PpiIdentityFixture):
    """批准登记和原件恢复只改变明确的决定/查询档案。"""

    def test_scope_is_read_only_idempotent_and_does_not_sign_or_publish(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('范围登记不得联网')):
            first = self.register(); second = self.register(); value = scopes.info(self.w, self.sid)
        self.assertTrue(first['created']); self.assertFalse(second['created']); self.assertEqual(first['file'], second['file'])
        self.assertEqual(len(first['query_plan']), 2); self.assertEqual(len(value['history']), 1)
        self.assertFalse(value['queries_started_by_this_read']); self.assertFalse(value['network_published_by_this_read']); self.assert_science_unchanged()

    def test_scope_overrides_wrong_lists_and_changed_proposal_are_rejected(self):
        variants = [{'approved': True}, {'url': 'https://example.invalid'}, {'check_ids': ['HGNC:1', 'HGNC:5']},
                    {'omit_ids': ['HGNC:1']}, {'check_ids': ['HGNC:5', 'HGNC:5']}, {'confirmed': False}]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.w.register_analysis_plan_ppi_identity_scope(self.sid, self.body | change, self.raw)
        value = json.loads(self.raw); value['original_issues'][0]['frozen_hgnc_fields']['uniprot_ids'] = 'FORGED'
        raw = json.dumps(value).encode()
        with self.assertRaises(ContractError): self.w.register_analysis_plan_ppi_identity_scope(
            self.sid, self.body | {'expected_proposal_sha256': hashlib.sha256(raw).hexdigest()}, raw)
        self.assert_science_unchanged(); self.assertNotIn(scopes.INDEX, self.w.load(self.sid))

    def test_different_request_same_original_scope_and_reused_id_conflict_rejected(self):
        self.register()
        for body in (self.body | {'note': '不同内容'}, self.body | {'request_id': 'ppiscopereq_' + uuid4().hex}):
            with self.assertRaises(ContractError): self.w.register_analysis_plan_ppi_identity_scope(self.sid, body, self.raw)
        self.assertEqual(len(self.w.load(self.sid)[scopes.INDEX]), 1)

    def test_new_draft_does_not_rebind_original_batch_or_include_a05(self):
        record = self.register(); draft = self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid, {'request_id': 'planreq_' + uuid4().hex, 'expected_a00': self.before['current']['A00'],
            'expected_draft_id': draft['plan_id'], 'specification': {'mode': 'personalized', 'parameters': {'a06.receptor_count': 2}},
            'author': '明确合成测试', 'note': '原批及PPI决定保持'})
        self.assertEqual(scopes.current_context(self.w, self.w.load(self.sid)), self.binding)
        self.assertNotIn('A05', record['binding']['current']); self.assertEqual(self.register()['file'], record['file'])

    def test_complete_raw_trace_and_same_request_replay_make_no_new_queries(self):
        body = self.probe_body(); result = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=self.opener)
        self.assertEqual(result['state'], 'complete'); self.assertEqual(result['successful_queries'], 2)
        with patch('urllib.request.urlopen', side_effect=AssertionError('完整请求重放不得联网')):
            replay = self.w.probe_analysis_plan_ppi_identities(self.sid, body)
        self.assertFalse(replay['created']); self.assertEqual(replay['file'], result['file']); self.assert_science_unchanged()
        trace = build_trace(self.w, self.sid, include_data=True)
        self.assertEqual(len(trace['plan_decisions']['ppi_identity_scopes']), 1)
        self.assertEqual(len(trace['plan_decisions']['ppi_identity_probes']), 1)
        raw_refs = [ref for ref in result['files'] if ref['role'] == 'ppi_identity_query_response']
        self.assertEqual(len(raw_refs), 2)
        # 完整追溯必须包含原响应字节，不能只导出元数据JSON。
        text = json.dumps(trace)
        for ref in raw_refs: self.assertIn(ref['sha256'], text)

    def test_partial_failure_retry_reuses_only_success_and_keeps_old_failure(self):
        body = self.probe_body(); calls = []
        def fail_once(request, timeout):
            key = urllib.parse.parse_qs(request.data.decode())['identifiers'][0]; calls.append(key)
            if key == 'P5': raise urllib.error.URLError('明确合成连接失败')
            return self.opener(request, timeout)
        first = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=fail_once)
        self.assertEqual(first['state'], 'partial_failure'); self.assertEqual(first['successful_queries'], 1)
        prior = {ref['path']: verified_file(self.home, ref).read_bytes() for ref in first['files']}
        calls.clear()
        def finish(request, timeout):
            calls.append(urllib.parse.parse_qs(request.data.decode())['identifiers'][0]); return self.opener(request, timeout)
        final = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=finish)
        self.assertEqual(calls, ['P5']); self.assertEqual(final['reused_queries'], 1); self.assertEqual(final['state'], 'complete')
        self.assertEqual(probes.read_record(self.w, self.w.load(self.sid), first['file'])['state'], 'partial_failure')
        for path, raw in prior.items(): self.assertEqual((self.home / path).read_bytes(), raw)
        self.assertEqual(len(build_trace(self.w, self.sid)['plan_decisions']['ppi_identity_probes']), 2); self.assert_science_unchanged()

    def test_http_404_error_object_and_foreign_query_never_become_empty_success(self):
        body = self.probe_body()
        def invalid(request, timeout):
            key = urllib.parse.parse_qs(request.data.decode())['identifiers'][0]
            if key == 'P5': raise urllib.error.HTTPError(request.full_url, 404, '明确合成404', {}, io.BytesIO(b'{"error":"missing"}'))
            return Response(b'{"error":"rate limited"}')
        first = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=invalid)
        self.assertEqual(first['state'], 'partial_failure'); self.assertEqual(first['successful_queries'], 0)
        self.assertEqual(len(first['failures']), 2)
        foreign = lambda request, timeout: Response(b'[{"queryIndex":0,"queryItem":"FOREIGN","ncbiTaxonId":9606,"preferredName":"E","stringId":"9606.5"}]')
        second = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=foreign)
        self.assertEqual(second['state'], 'partial_failure'); self.assertEqual(second['successful_queries'], 0); self.assert_science_unchanged()

    def test_success_empty_response_is_complete_evidence_without_omitting_identity(self):
        body = self.probe_body(); result = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=lambda request, timeout: Response(b'[]'))
        self.assertEqual(result['state'], 'complete'); self.assertEqual(len(result['probes']), 2)
        self.assertTrue(all(row['source']['response_text'] == '[]' for row in result['probes'])); self.assert_science_unchanged()
        self.assertTrue(self.w.result(self.w.load(self.sid), self.rid)['summary']['handoff_blocked'])

    def test_tampered_success_cache_blocks_retry_without_redownload(self):
        body = self.probe_body()
        def fail_once(request, timeout):
            if urllib.parse.parse_qs(request.data.decode())['identifiers'][0] == 'ENSG5': raise urllib.error.URLError('明确合成失败')
            return self.opener(request, timeout)
        first = self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=fail_once)
        raw_ref = next(ref for ref in first['files'] if ref['role'] == 'ppi_identity_query_response')
        path = verified_file(self.home, raw_ref); path.write_bytes(b'[]')
        with patch('urllib.request.urlopen', side_effect=AssertionError('坏缓存不能静默重下')), self.assertRaises(ContractError):
            self.w.probe_analysis_plan_ppi_identities(self.sid, body)
        self.assert_science_unchanged()

    def test_human_hold_or_trash_blocks_probe_and_does_not_erase_scope_history(self):
        body = self.probe_body(); record = self.register()
        self.w.review(self.sid, self.rid, 'pending', '明确合成测试', '补查前明确暂存')
        with self.assertRaises(ContractError): self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=self.opener)
        self.assertEqual(scopes.read_record(self.w, self.w.load(self.sid), record['file'])['scope']['check_ids'], ['HGNC:5'])
        self.w.set_trashed(self.sid, True, '明确合成测试', '回收站只读')
        with self.assertRaises(ContractError): self.register()

    def test_hold_during_query_preserves_raw_without_publishing_complete_receipt(self):
        body = self.probe_body(); changed = []
        def hold(request, timeout):
            if not changed:
                self.w.review(self.sid, self.rid, 'pending', '明确合成测试', '补查期间明确暂存'); changed.append(True)
            return self.opener(request, timeout)
        with self.assertRaises(ContractError): self.w.probe_analysis_plan_ppi_identities(self.sid, body, opener=hold)
        m = self.w.load(self.sid); self.assertNotIn(probes.INDEX, m); self.assertEqual(m['current'], self.before['current'])
        folder = self.home / 'decisions/analysis_plans/ppi_identity_probes' / body['request_id']
        self.assertEqual(len(list(folder.glob('attempts/*/response.bin'))), 2)
        self.assertEqual(len(m[probes.REQUESTS]), 1)


if __name__ == '__main__': unittest.main()
