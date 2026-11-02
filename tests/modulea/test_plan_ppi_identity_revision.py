"""合成官方响应下真实新PPI规范发布、同批选择、旧运行保留和报告限制。"""
import json
import os
from pathlib import Path
import shutil
import threading
import time
import urllib.error
import urllib.parse
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from storage import verified_file
from modulea.core import ppi_identity_revision as revisions, system_execution as execution
from modulea.core.trace_export import build_trace
from modulea.config import Settings
from modulea.tasks.manager import TaskManager
from modulea.presenters.network import present_a04
from science_modules.a07.plan_payload import build as report_payload
from science_modules.a04 import plan_flow as network
from tests.modulea.test_plan_ppi_identity_workflow import PpiIdentityFixture, Response


class NetworkResponse(Response):
    def geturl(self):
        return super().geturl().removesuffix('get_string_ids') + 'network'


class PlanPpiIdentityRevisionTests(PpiIdentityFixture):
    def revision_body(self, *, empty=False, omit=True):
        """原登记决定、成功查询与新运行各有独立明确请求，均经公开入口。"""
        if not omit: self.body['omit_ids'] = []
        probe_body = self.probe_body()
        probe = self.w.probe_analysis_plan_ppi_identities(self.sid, probe_body,
            opener=(lambda request, timeout: Response(b'[]')) if empty else self.opener)
        return {'request_id': 'ppirevisionreq_' + uuid4().hex, 'scope_request_id': self.body['request_id'],
                'probe_id': probe['probe_id'], 'expected_a04': self.rid, 'expected_input_hash': self.body['expected_input_hash'],
                'author': '明确合成测试', 'note': '原五基因交集的独立PPI规范发布测试，未改参数或签复核', 'confirmed': True}

    def network_opener(self, request, timeout=40):
        """新请求按实际全部核实后节点生成完整星形边；不是复制旧部分网络。"""
        self.assertTrue(request.full_url.endswith('/network')); self.assertEqual(timeout, 40)
        params = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(params['required_score'], ['900']); self.assertEqual(params['add_nodes'], ['0'])
        self.assertEqual(params['network_type'], ['functional']); ids = params['identifiers'][0].split('\r')
        rows = [{'stringId_A': ids[0], 'stringId_B': sid, 'ncbiTaxonId': 9606, 'score': .95} for sid in ids[1:]]
        return NetworkResponse(json.dumps(rows).encode())

    def test_unique_stable_evidence_publishes_new_network_and_replay_is_read_only(self):
        body = self.revision_body(); old_files = {ref['path']: verified_file(self.home, ref).read_bytes() for ref in self.binding['run_files']['A04'].values()}
        result = self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        m = self.w.load(self.sid); run = self.w.run(m, result['run_id']); actual = self.w.result(m, result['run_id'])
        self.assertEqual(run['config']['version'], 'A04.plan_network.2'); self.assertTrue(self.w.active(m, result['run_id']))
        self.assertEqual(actual['summary']['交集输入数'], 5); self.assertEqual(actual['summary']['已识别数'], 5)
        self.assertEqual(actual['summary']['稳定编号核实数'], 1); self.assertEqual(actual['summary']['本次PPI暂不采用数'], 0)
        self.assertFalse(actual['summary']['handoff_blocked']); self.assertEqual(actual['summary']['合格边数'], 4)
        self.assertEqual(m['reviews'], self.before['reviews']); self.assertEqual(m['current']['A03'], self.before['current']['A03'])
        self.assertEqual(run['batch_file'], self.binding['batch_file']); self.assertEqual(run['parent_review_ids'], {})
        for path, raw in old_files.items(): self.assertEqual((self.home / path).read_bytes(), raw)
        with patch('urllib.request.urlopen', side_effect=AssertionError('已发布修订重放不得联网')):
            replay = self.w.revise_analysis_plan_ppi_identities(self.sid, body)
        self.assertFalse(replay['created']); self.assertEqual(replay['run_id'], result['run_id'])
        trace = build_trace(self.w, self.sid, include_data=True)
        self.assertEqual(len(trace['plan_decisions']['ppi_identity_revision_receipts']), 1)
        event = trace['plan_decisions']['system_batch_events'][-1]; self.assertEqual(event['run_id'], result['run_id'])
        self.assertEqual(trace['plan_decisions']['ppi_identity_scopes'][0]['binding']['current']['A04'], self.rid)

    def test_explicit_omission_keeps_unresolved_identity_and_allows_same_batch_selection(self):
        body = self.revision_body(empty=True); result = self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        m = self.w.load(self.sid); actual = self.w.result(m, result['run_id']); summary = actual['summary']; tables = actual['tables']
        self.assertEqual(summary['交集输入数'], 5); self.assertEqual(summary['已识别数'], 4)
        self.assertEqual(summary['身份待核验数'], 1); self.assertEqual(summary['本次PPI暂不采用数'], 1)
        self.assertFalse(summary['handoff_blocked']); self.assertEqual(len(tables['identity_issues']), 1)
        self.assertFalse(any(row['target_id'] == 'HGNC:5' for row in tables['metrics'] + tables['isolates']))
        parts = present_a04(actual, {}); self.assertTrue(parts.special['ppi_identity']['rows'])
        self.assertTrue(all(item['tier'] == 'should_know' for item in parts.focus)); self.assertIn('暂不采用', str(parts.focus))
        selection = self.w.execute_analysis_plan_system_decision(self.sid, {'batch_id': self.batch_id, 'stage': 'A04_SELECTION', 'expected_decision_id': None})
        fixed = self.w.execute_analysis_plan_system_decision(self.sid, {'batch_id': self.batch_id, 'stage': 'A06_INPUT', 'expected_decision_id': None})
        self.assertEqual(selection['binding']['parent_runs']['A04'], result['run_id'])
        self.assertEqual(fixed['payload']['receptors'], selection['payload']['selected']); self.assertEqual(self.w.load(self.sid)['reviews'], self.before['reviews'])
        payload = report_payload(self.w, self.sid)
        notice = next(row['description'] for row in payload['sources'] if row['label'] == '本批PPI身份清单限制')
        self.assertIn('暂不采用1项', notice); self.assertIn('HGNC:5', notice); self.assertIn('稳定编号', notice)

    def test_without_omit_permission_result_stays_blocked_and_selection_is_rejected(self):
        body = self.revision_body(empty=True, omit=False); result = self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        actual = self.w.result(self.w.load(self.sid), result['run_id']); self.assertTrue(actual['summary']['handoff_blocked'])
        self.assertEqual(actual['summary']['未获准身份阻断数'], 1); self.assertEqual(actual['summary']['本次PPI暂不采用数'], 0)
        with self.assertRaises(ContractError): self.w.execute_analysis_plan_system_decision(
            self.sid, {'batch_id': self.batch_id, 'stage': 'A04_SELECTION', 'expected_decision_id': None})
        parts = present_a04(actual, {}); self.assertTrue(any(item['blocks'] == ['A06_PREP'] for item in parts.focus))

    def test_extra_network_node_rejected_and_failure_keeps_original_current(self):
        body = self.revision_body(empty=True)
        bad = lambda request, timeout: NetworkResponse(b'[{"stringId_A":"9606.1","stringId_B":"9606.5","ncbiTaxonId":9606,"score":0.95}]')
        with self.assertRaises(ContractError): self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=bad)
        self.assert_science_unchanged(); trace = build_trace(self.w, self.sid)
        self.assertEqual(len(trace['plan_decisions']['ppi_identity_revision_failures']), 1)
        self.assertFalse(trace['plan_decisions']['ppi_identity_revision_receipts'])
        self.assertTrue(trace['plan_decisions']['ppi_identity_revision_failures'][0]['files'])
        # 明确重试原修订，新尝试不覆盖第一份错误网络或失败回执。
        prior = self.w.load(self.sid)[revisions.FAILURES][0]; raw = verified_file(self.home, prior).read_bytes()
        result = self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        self.assertTrue(result['created']); self.assertEqual(verified_file(self.home, prior).read_bytes(), raw)

    def test_http_failure_keeps_raw_body_without_fallback_to_old_network(self):
        body = self.revision_body()
        def failed(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 503, '明确合成服务失败', {}, __import__('io').BytesIO(b'{"error":"busy"}'))
        with self.assertRaises(urllib.error.HTTPError): self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=failed)
        self.assert_science_unchanged(); trace = build_trace(self.w, self.sid)
        failure = trace['plan_decisions']['ppi_identity_revision_failures'][-1]
        ref = next(ref for ref in failure['files'] if ref['path'].endswith('/network.json'))
        metadata = json.loads(verified_file(self.home, ref).read_bytes())
        self.assertEqual(metadata['query_state'], 'query_failed'); self.assertEqual(bytes.fromhex(metadata['response_bytes_hex']), b'{"error":"busy"}')

    def test_human_hold_during_new_network_blocks_publication_and_keeps_raw(self):
        body = self.revision_body()
        def hold(request, timeout):
            self.w.review(self.sid, self.rid, 'pending', '明确合成测试', '新网络请求期间暂存'); return self.network_opener(request, timeout)
        with self.assertRaises(ContractError): self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=hold)
        m = self.w.load(self.sid); self.assertEqual(m['current'], self.before['current']); self.assertNotIn(revisions.RECEIPTS, m)
        self.assertEqual(len(m[revisions.FAILURES]), 1)

    def test_partial_probe_and_client_parameter_overrides_never_start_network(self):
        body = self.revision_body()
        for change in ({'required_score': 400}, {'source_file': {}}, {'confirmed': False}, {'probe_id': 'ppiprobe_' + uuid4().hex}):
            with self.subTest(change=change), patch('urllib.request.urlopen', side_effect=AssertionError('错误确认不得联网')), self.assertRaises(ContractError):
                self.w.revise_analysis_plan_ppi_identities(self.sid, body | change)
        self.assert_science_unchanged()

    def test_actual_budgeted_workers_reject_unconfirmed_requests_before_any_query(self):
        """真实独立worker及预算关口执行拒绝路径；没有确认时不得触发联网。"""
        body = self.revision_body()
        probe_body = {'request_id': 'ppiprobereq_' + uuid4().hex, 'scope_request_id': self.body['request_id'],
                      'expected_input_hash': self.body['expected_input_hash'], 'author': '明确合成测试', 'note': '未确认必须拒绝', 'confirmed': False}
        settings = Settings(data_root=self.root, runtime_dir=Path(self.temp.name) / 'worker_runtime')
        manager = TaskManager(settings)
        for kind, payload in (('plan_ppi_identity_probe', probe_body), ('plan_ppi_identity_revision', body | {'confirmed': False})):
            task, created = manager.submit(self.sid, kind, '明确合成真实worker', payload); self.assertTrue(created)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                value = manager.get(task['task_id'])
                if value['state'] not in ('queued', 'running'): break
                time.sleep(.1)
            else: self.fail('本测试worker未终止：' + manager.log(task['task_id']))
            for thread in threading.enumerate():
                if thread.name == 'modulea-reap-' + task['task_id']:
                    thread.join(30); self.assertFalse(thread.is_alive())
            self.assertEqual(value['state'], 'failed', manager.log(task['task_id']))
            self.assertIn('明确确认', manager.log(task['task_id'])['text'])
        self.assertNotIn(revisions.REQUESTS, self.w.load(self.sid)); self.assert_science_unchanged()

    def test_partial_probe_record_cannot_be_used_for_revision(self):
        probe_body = self.probe_body()
        def failed(request, timeout): raise urllib.error.URLError('明确合成失败，不是空结果')
        probe = self.w.probe_analysis_plan_ppi_identities(self.sid, probe_body, opener=failed)
        body = {'request_id': 'ppirevisionreq_' + uuid4().hex, 'scope_request_id': self.body['request_id'], 'probe_id': probe['probe_id'],
                'expected_a04': self.rid, 'expected_input_hash': self.body['expected_input_hash'], 'author': '明确合成测试', 'note': '缺失证据不得新取网络', 'confirmed': True}
        with patch('urllib.request.urlopen', side_effect=AssertionError('缺补查不得联网')), self.assertRaises(ContractError):
            self.w.revise_analysis_plan_ppi_identities(self.sid, body)
        self.assertNotIn(revisions.REQUESTS, self.w.load(self.sid)); self.assert_science_unchanged()

    def api_view(self, run_id=None):
        """真实只读视图层，不用伪造状态；独立runtime没有后台任务。"""
        from modulea.api.views import Views
        from modulea.core.kernel import Kernel
        settings = Settings(data_root=self.root, runtime_dir=Path(self.temp.name) / 'view_runtime')
        return Views(Kernel(settings), TaskManager(settings)).module(self.sid, 'A04', run_id)

    def test_current_api_preserves_scoped_identity_and_hides_legacy_forms_and_history_is_read_only(self):
        body = self.revision_body(empty=True); result = self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        manifest = (self.home / 'manifest.json').read_bytes()
        # 当前系统版已隐藏旧人工表单，不应先执行其昂贵读取再丢弃结果。
        with patch('modulea.api.views.candidate_context', side_effect=AssertionError('当前系统A04不读取旧候选表单')), \
             patch('modulea.api.views.plan_view', side_effect=AssertionError('当前系统A04不读取旧补查表单')), \
             patch('modulea.api.plan_selection_ui.info', side_effect=AssertionError('当前系统A04不读取旧名单表单')):
            value = self.api_view()
        self.assertEqual(value['run']['run_id'], result['run_id'])
        for field in ('ppi_run', 'identity_plan', 'plan_selection_ui', 'docking_candidates'): self.assertIsNone(value[field])
        identity = value['special']['ppi_identity']; self.assertEqual(identity['scope_kind'], 'explicit_bound_test_decision')
        self.assertFalse(identity['handoff_blocked']); self.assertEqual(identity['rows'][0]['target_id'], 'HGNC:5')
        self.assertIn('approved', value['review']['allowed_decisions']); self.assertIsNone(value['review']['blocked_reason_zh'])
        focus = [row for row in value['focus'] if row.get('source_table') == 'identity_issues']
        self.assertEqual(len(focus), 1); self.assertEqual(focus[0]['tier'], 'should_know')
        historical = self.api_view(self.rid); self.assertTrue(historical['historical']); self.assertFalse(historical['review']['can_review'])
        self.assertEqual(historical['run']['run_id'], self.rid); self.assertNotIn('scope_kind', historical['special']['ppi_identity'])
        self.assertEqual((self.home / 'manifest.json').read_bytes(), manifest)

    def test_unapproved_unresolved_api_keeps_real_block_and_does_not_offer_approval(self):
        body = self.revision_body(empty=True, omit=False); self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        manifest = (self.home / 'manifest.json').read_bytes(); value = self.api_view()
        self.assertTrue(value['special']['ppi_identity']['handoff_blocked'])
        self.assertNotIn('approved', value['review']['allowed_decisions']); self.assertTrue(value['review']['blocked_reason_zh'])
        self.assertTrue(any(row['tier'] == 'must_handle' and row.get('source_table') == 'identity_issues' for row in value['focus']))
        self.assertEqual((self.home / 'manifest.json').read_bytes(), manifest)

    def test_revised_ppi_and_unicode_a05_reach_same_batch_real_synthetic_double_reports(self):
        """完整生产编排复用PPI2/A05文字修订2；外部结构明确合成NA，真实R/Word不替身。"""
        from tests.modulea import test_plan_a05 as annotation
        from tests.modulea.plan_report_nonempty_fixture import unavailable_sources
        from science_modules.a06 import plan_preparation_v2 as preparation
        from science_modules.a04 import plan_identity_network as new_network
        from modulea.core import plan_a05_text
        from storage import file_record, write_json
        import xml.etree.ElementTree as xml
        import zipfile
        body = self.revision_body(empty=True)
        ppi = self.w.revise_analysis_plan_ppi_identities(self.sid, body, opener=self.network_opener)
        m = self.w.load(self.sid); draft = self.w.analysis_plan_info(self.sid)['draft']; annotation.install_source(self.root, draft['plan'])
        with patch.dict(os.environ, {'MODULEA_RSCRIPT': str(annotation.RSCRIPT)}):
            original_a05 = self.w.execute_analysis_plan_system_stage(self.sid, {'batch_id': self.batch_id, 'stage': 'A05', 'expected_current_run_id': None})
            info = plan_a05_text.info(self.w, self.sid)
            a05 = self.w.revise_analysis_plan_a05_text(self.sid, {key: info[key] for key in ('expected_a05', 'expected_input_hash')} |
                {'request_id': 'a05textreq_' + uuid4().hex, 'author': '明确合成测试', 'note': '保留原统计修订中文', 'confirmed': True})
            # 原批次两个最新完成事件都必须复用；不能再次联网获取PPI或替换其范围。
            with patch.object(new_network, 'request_network', side_effect=AssertionError('同批接续不得重取新网络')), \
                 patch.object(network, 'request', side_effect=AssertionError('同批接续不得重跑旧PPI')), \
                 patch.object(preparation, 'connect', side_effect=unavailable_sources):
                result = self.w.execute_analysis_plan_system_pipeline(self.sid, {'batch_id': self.batch_id},
                    tools=Path('D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))
        m = self.w.load(self.sid); self.assertEqual(result['state'], 'awaiting_report_review')
        self.assertEqual(m['current']['A04'], ppi['run_id']); self.assertEqual(m['current']['A05'], a05['run_id'])
        self.assertIn(original_a05['run_id'], m['runs']); self.assertEqual(m['reviews'], self.before['reviews'])
        self.assertEqual(m['current']['A03'], self.before['current']['A03'])
        report = self.w.result(m, m['current']['A07']); files = report['tables']['report_files']; self.assertEqual(len(files), 2)
        for ref in files:
            with zipfile.ZipFile(verified_file(self.home, ref)) as document:
                text = ' '.join(node.text or '' for node in xml.fromstring(document.read('word/document.xml')).iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
            self.assertIn('HGNC:5', text); self.assertIn('暂不采用1项', text); self.assertIn('仅限本研究本批流程测试', text)
        trace = build_trace(self.w, self.sid, include_data=True)
        self.assertEqual(trace['plan_decisions']['ppi_identity_revision_receipts'][0]['run_id'], ppi['run_id'])
        # 仅独立核查显式设置此环境变量时留副本，供渲染检查；正常测试仍自动清理自己的临时目录。
        if os.environ.get('MODULEA_PPI_QA_ROOT'):
            dest = Path(os.environ['MODULEA_PPI_QA_ROOT']) / ('case_' + uuid4().hex)
            shutil.copytree(self.root, dest / 'data')
            copied_home = dest / 'data/studies' / self.sid
            write_json(dest / 'case.json', {'synthetic': True, 'real_official_requests_performed': False,
                'study_id': self.sid, 'data_root': str(dest / 'data'), 'ppi_run_id': ppi['run_id'], 'a05_run_id': a05['run_id'],
                'report_run_id': m['current']['A07'], 'report_files': [file_record(copied_home, copied_home / ref['path'], ref['role']) for ref in files]})
