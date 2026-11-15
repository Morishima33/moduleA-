"""三版补救报告合同：只使用明确合成对象，不执行真实研究或生成真实研究Word。"""
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from contracts import ContractError
from tests.modulea.test_plan_report_documents import payload as document_fixture


class RescueReportContractTests(TestCase):
    def model(self):
        """版本缺失应作为功能未实现的失败，不用导入异常冒充红测。"""
        path = Path(__file__).resolve().parents[2]/'src/science_modules/a07/plan_payload_v3.py'
        self.assertTrue(path.is_file(), '缺少明确三版补救事实适配')
        return import_module('science_modules.a07.plan_payload_v3')

    def fixture(self, version='A06.system_rescue.2'):
        """生产validator在本合同测试中以明确合成返回包替身隔离，不声称科学验证。"""
        from tests.modulea.test_plan_report_facts import packet
        value = packet(); value.update(study_id='study_synthetic', run_id='run_synthetic')
        value['source_fixed'] = {'compounds': deepcopy(value['compounds']), 'receptors': deepcopy(value['receptors'])}
        value['summary'] = {'reused_scored_pairs': 1, 'new_scored_pairs': 1, 'human_review_written': False}
        value['pairs'][0]['regions'] = [{'region_id': 'p1', 'state': 'failed', 'score': None,
            'reason_zh': '明确合成工具失败', 'execution': {'path': 'synthetic.json'}}]
        run = {'study_id': value['study_id'], 'run_id': value['run_id'], 'config': {'version': version},
               'inputs': {'rescue_request': {'path': 'request.json'}}}
        result = {'summary': value['summary'], 'tables': {'scoring_packet': [{'path': 'packet.json'}]},
                  'anomalies': [], 'outcome': 'success'}
        return value, run, result

    def test_rescue_reads_production_validated_packet_and_preserves_every_pair(self):
        model = self.model(); value, run, result = self.fixture()
        with patch('science_modules.a06.system_receptor_rescue_v2.validate_packet', return_value=value) as check:
            facts = model.rescue_docking(Mock(), run, result)
        check.assert_called_once_with(check.call_args.args[0], run, result['summary'], result['tables'], [], 'success')
        self.assertEqual(facts['pairs'], value['pairs'])
        self.assertEqual(facts['rescue']['summary'], value['summary'])
        self.assertEqual(facts['rescue']['failed_regions'][0]['reason_zh'], '明确合成工具失败')
        self.assertFalse(facts['human_review_written'])

    def test_both_rescue_versions_keep_their_own_scientific_validator(self):
        model = self.model(); value, run, result = self.fixture('A06.system_rescue.1')
        with patch('science_modules.a06.system_receptor_rescue.validate_packet', return_value=value) as old, \
                patch('science_modules.a06.system_receptor_rescue_v2.validate_packet', side_effect=AssertionError('不能升级')):
            model.rescue_docking(Mock(), run, result)
        old.assert_called_once()

    def test_display_does_not_duplicate_large_preparation_attempts_but_keeps_original_packet(self):
        model = self.model(); value, run, result = self.fixture()
        class Attempts:
            """大型原准备尝试不应被展示矩阵复制；原包引用保留全部原件。"""
            def __deepcopy__(self, memo): raise AssertionError('展示复制了大型准备尝试')
        attempts = Attempts(); value['receptors'][0]['attempts'] = attempts
        with patch('science_modules.a06.system_receptor_rescue_v2.validate_packet', return_value=value):
            facts = model.rescue_docking(Mock(), run, result)
        self.assertNotIn('attempts', facts['receptors'][0])
        self.assertIs(value['receptors'][0]['attempts'], attempts)
        self.assertEqual(facts['rescue']['scoring_packet'], result['tables']['scoring_packet'])

    def test_validation_failure_and_wrong_study_cannot_form_report_facts(self):
        model = self.model(); value, run, result = self.fixture()
        with patch('science_modules.a06.system_receptor_rescue_v2.validate_packet', side_effect=ContractError('原构象变化')):
            with self.assertRaises(ContractError): model.rescue_docking(Mock(), run, result)
        value['study_id'] = 'study_other'
        with patch('science_modules.a06.system_receptor_rescue_v2.validate_packet', return_value=value):
            with self.assertRaises(ContractError): model.rescue_docking(Mock(), run, result)

    def test_report_routing_selects_rescue_v3_and_never_upgrades_old_queued_payloads(self):
        self.model()
        from modulea.core import report_registry
        w = Mock(); w.run.return_value = {'config': {'version': 'A06.system_rescue.2'}}
        self.assertEqual(report_registry.current(w, {'current': {'A06': 'run_synthetic'}}).VERSION, 'A07.plan_report.3')
        w.publish_analysis_plan_report.return_value = 'old'
        self.assertEqual(report_registry.publish_queued(w, 'study_synthetic', {'request_id': 'old'}), 'old')
        report_registry.publish_queued(w, 'study_synthetic', {'report_protocol': 'A07.plan_report.2', 'request': {'v': 2}})
        w.publish_analysis_plan_report_revision.assert_called_once_with('study_synthetic', {'v': 2})
        report_registry.publish_queued(w, 'study_synthetic', {'report_protocol': 'A07.plan_report.3', 'request': {'v': 3}})
        w.publish_analysis_plan_rescue_report.assert_called_once_with('study_synthetic', {'v': 3})

    def test_draft_document_preserves_rescue_notice_and_rejects_removed_provenance(self):
        self.model()
        from science_modules.a07 import plan_documents_v3 as documents
        from docx import Document
        data = document_fixture(); data['schema_version'] = 'A07.plan_payload.3'
        data['completion']['schema_version'] = 'A07.plan_facts.2'
        data['docking']['rescue'] = {'protocol': 'A06.system_rescue.2', 'summary': {'reused_scored_pairs': 1,
            'new_scored_pairs': 1}, 'failed_regions': [], 'notice_zh': '明确合成：沿用1组，新增1组；探索补救不表示严格验证。'}
        with TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic.docx'
            documents.build(data, path, folder, draft=True)
            self.assertEqual(documents.validate_document(path, data, draft=True)['matrix_cells_verified'], 4)
            doc = Document(path)
            notice = next(p for p in doc.paragraphs if p.text == data['docking']['rescue']['notice_zh'])
            notice.text = '已全部严格验证'; doc.save(path)
            with self.assertRaises(ContractError): documents.validate_document(path, data, draft=True)

    def test_nonempty_fact_builder_uses_bound_rescue_packet_without_reclassifying_authority(self):
        """真实合成上游加隔离补救合同替身；不冒充非空科学全链验收。"""
        model = self.model()
        from tests.modulea.plan_report_fixture import prepare
        from storage import file_record, read_json, verified_file, write_json, new_id
        with TemporaryDirectory() as folder:
            w, sid, _, _ = prepare(Path(folder)/'data', empty=False)
            home = w.location(sid); manifest_before = (home/'manifest.json').read_bytes()
            manifest = w.load(sid)
            a03 = w.run(manifest, manifest['current']['A03'])
            reference = a03['inputs']['analysis_plan_file']
            plan = read_json(verified_file(home, reference))['plan']
            value, run, result = self.fixture()
            prep_id, score_id = new_id('run'), new_id('run')
            run.update(study_id=sid, run_id=score_id, parent_runs={'A06_PREP': prep_id})
            value.update(study_id=sid, run_id=score_id)
            fixed = {'study_id': sid, 'packet': {'plan_ref': reference,
                'analysis_parameter_hash': plan['parameter_hash'], 'runs': {'A03': a03['run_id']},
                'compounds': value['compounds'], 'receptors': value['receptors']}}
            path = home/'synthetic_report_input.json'; write_json(path, fixed)
            ref = file_record(home, path, 'synthetic_report_input')
            run['inputs']['system_input_ref'] = ref
            prep = {'study_id': sid, 'run_id': prep_id, 'config': {'version': 'explicit_synthetic'},
                    'inputs': {'a06_plan_input': ref}, 'parent_runs': {'A03': a03['run_id']}}
            manifest['current'].update(A06_PREP=prep_id, A06=score_id)
            manifest['runs'].update({prep_id: {'result_file': {'synthetic': True}}, score_id: {'result_file': {'synthetic': True}}})
            manifest['analysis_plan_a06_input_records'] = [ref]
            class View:
                """只在此合同测试投影合成分支，底层真实合成上游保持原字节。"""
                def __getattr__(self, key): return getattr(w, key)
                def load(self, _): return manifest
                def run(self, m, rid): return run if rid == score_id else prep if rid == prep_id else w.run(m, rid)
                def result(self, m, rid): return result if rid == score_id else {'summary': {}, 'tables': {}} if rid == prep_id else w.result(m, rid)
                def active(self, m, rid): return True if rid in (score_id, prep_id) else w.active(m, rid)
            with patch('science_modules.a06.system_receptor_rescue_v2.validate_packet', return_value=value), \
                    patch.object(model.validation, 'request', return_value={'expected_input_hash': 'synthetic'}):
                payload = model.build(View(), sid)
            self.assertEqual(payload['schema_version'], 'A07.plan_payload.3')
            self.assertEqual(payload['docking']['pairs'], value['pairs'])
            self.assertEqual(payload['run_ids']['A06'], score_id)
            self.assertEqual(payload['docking']['rescue']['protocol'], 'A06.system_rescue.2')
            self.assertNotIn('execution_protocol', run)
            self.assertEqual((home/'manifest.json').read_bytes(), manifest_before)

    def test_region_table_uses_actual_names_and_rejects_cross_pair_reason_swap(self):
        self.model()
        from science_modules.a07 import plan_documents_v3 as documents
        from docx import Document
        data = document_fixture(); data['schema_version'] = 'A07.plan_payload.3'
        data['completion']['schema_version'] = 'A07.plan_facts.2'
        pairs = data['docking']['pairs']
        regions = [dict(compound_id=p['compound_id'], target_id=p['target_id'], region_id='r1',
                        state='failed', reason_zh='明确合成原因'+str(i)) for i, p in enumerate(pairs[:2])]
        data['docking']['rescue'] = {'notice_zh': '明确合成补救限制', 'failed_regions': regions}
        with TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic_regions.docx'; documents.build(data, path, folder, draft=True)
            documents.validate_document(path, data, draft=True)
            doc = Document(path)
            table = next(t for t in doc.tables if [c.text for c in t.rows[0].cells] == ['成分', '受体', '区域', '实际状态', '原因'])
            self.assertIn('One', table.rows[1].cells[0].text)
            a, b = table.rows[1].cells[-1].text, table.rows[2].cells[-1].text
            table.rows[1].cells[-1].text, table.rows[2].cells[-1].text = b, a
            doc.save(path)
            with self.assertRaises(ContractError): documents.validate_document(path, data, draft=True)


class RescueReportWorkflowTests(TestCase):
    """实际生产发布链的合法空研究验收，不能替代真实非空补救计算验收。"""
    @classmethod
    def setUpClass(cls):
        from tests.modulea.test_plan_report_revision import ReportRevisionWorkflowTests
        ReportRevisionWorkflowTests.setUpClass.__func__(cls)

    def setUp(self):
        from tests.modulea.test_plan_report_revision import ReportRevisionWorkflowTests
        ReportRevisionWorkflowTests.setUp(self)

    def body(self):
        from uuid import uuid4
        value = self.w.rescue_report_info(self.sid)
        self.assertTrue(value['enabled'], value['blockers'])
        return {key: value[key] for key in ('expected_report_run_id', 'expected_input_hash')} | {
            'request_id': 'planreportreq_'+uuid4().hex, 'author': '明确合成测试',
            'note': '只在隔离合成研究验证三版，不签科研复核', 'confirmed': True}

    def test_public_v3_publishes_valid_documents_preserves_history_and_exports_provenance(self):
        from hashlib import sha256
        from storage import verified_file, read_json
        from modulea.core import report_registry
        from modulea.core.trace_export import build_trace
        from science_modules.a07.plan_report_flow_v3 import validate_result
        legacy = self.w.publish_analysis_plan_report(self.sid, self.body())
        before = self.w.load(self.sid)
        hashes = {r['path']: sha256(verified_file(self.w.location(self.sid), r).read_bytes()).hexdigest()
                  for r in legacy['tables']['report_files']}
        result = self.w.publish_analysis_plan_rescue_report(self.sid, self.body())
        after = self.w.load(self.sid); run = self.w.run(after, result['run_id'])
        self.assertEqual(run['config']['version'], 'A07.plan_report.3')
        self.assertEqual(before['reviews'], after['reviews'])
        self.assertFalse(self.w.approved(after, result['run_id']))
        validate_result(self.root, run, result['summary'], result['tables'], [], result['outcome'])
        self.assertEqual(len(result['tables']['report_files']), 2)
        self.assertEqual(hashes, {r['path']: sha256(verified_file(self.w.location(self.sid), r).read_bytes()).hexdigest()
                                 for r in legacy['tables']['report_files']})
        info = report_registry.info(self.w, self.sid)
        self.assertEqual(info['schema_version'], 'A07.plan_report.3')
        self.assertEqual({r['run_id'] for r in info['history']}, {legacy['run_id'], result['run_id']})
        trace = build_trace(self.w, self.sid, include_data=True)['plan_decisions']
        self.assertEqual(len(trace['report_rescue_receipts']), 1)
        payload = read_json(verified_file(self.w.location(self.sid), run['inputs']['payload_file']))
        source = read_json(verified_file(self.w.location(self.sid), payload['figure_source']))
        self.assertEqual(source['schema_version'], 'A07.plan_figures.3')

    def test_changed_source_review_blocks_explicit_v3_generation(self):
        body = self.body(); m = self.w.load(self.sid); rid = m['current']['A01']
        previous = self.w.latest_review(m, self.w.run(m, rid)['artifact_id'])
        self.w.review(self.sid, rid, 'pending', '明确合成测试', '退回源复核', previous['review_id'])
        with self.assertRaises(ContractError): self.w.publish_analysis_plan_rescue_report(self.sid, body)

    def test_published_v3_is_readable_without_scientific_or_document_dependencies(self):
        """实际隔离标准库进程读取已生产发布记录；GET不能创建完整科学工厂。"""
        import subprocess, sys, json
        self.w.publish_analysis_plan_rescue_report(self.sid, self.body())
        source = Path(__file__).resolve().parents[2]/'src'
        code = '''
import builtins,sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1]);base=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.split('.')[0] in {'docx','numpy','scipy','networkx','rdkit','meeko','PIL'}:raise AssertionError('读取不应导入科学依赖：'+name)
 return base(name,*args,**kwargs)
builtins.__import__=guarded
from modulea.config import Settings
from modulea.core.kernel import Kernel
from modulea.core.report_registry import info
w=Kernel(Settings(data_root=Path(sys.argv[2]))).read_workflow()
v=info(w,sys.argv[3]);assert v['history'][-1]['active']
print(json.dumps({'version':v['schema_version'],'count':len(v['history'])}))
'''
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-X', 'utf8', '-c', code,
                                 str(source), str(self.root), self.sid], capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(result.stdout)['version'], 'A07.plan_report.3')

    def test_read_archive_rejects_changed_payload_receipt_figure_and_source_review(self):
        """只读状态不重跑科学，但每类原件和人工退回仍实际阻断。"""
        from storage import read_json, verified_file
        self.w.publish_analysis_plan_rescue_report(self.sid, self.body())
        m = self.w.load(self.sid); rid = m['current']['A07']; run = self.w.run(m, rid)
        home = self.w.location(self.sid); payload = read_json(verified_file(home, run['inputs']['payload_file']))
        self.assertTrue(self.w.active(m, rid))
        for reference in (run['inputs']['payload_file'], payload['validation_records'][0]['source'], payload['figures'][0]['record']):
            path = verified_file(home, reference); original = path.read_bytes()
            with self.subTest(path=reference['path']):
                try:
                    path.write_bytes(original+b' ')
                    self.assertFalse(self.w.active(m, rid))
                finally:
                    path.write_bytes(original)
            self.assertTrue(self.w.active(m, rid))
        source = m['current']['A01']; old = self.w.latest_review(m, self.w.run(m, source)['artifact_id'])
        self.w.review(self.sid, source, 'pending', '明确合成复核', '退回源结果', old['review_id'])
        self.assertFalse(self.w.active(self.w.load(self.sid), rid))

    def test_actual_http_v3_history_download_and_submission_keep_explicit_protocol(self):
        """实际合成HTTP入口、下载字节及队列绑定，GET不改变研究索引。"""
        import hashlib, http.client, json
        from threading import Thread
        from storage import verified_file
        from modulea.api.server import create_server
        from modulea.config import Settings
        result = self.w.publish_analysis_plan_rescue_report(self.sid, self.body())
        before = (self.w.location(self.sid)/'manifest.json').read_bytes()
        server, app = create_server(Settings(data_root=self.root, runtime_dir=self.root/'http_runtime'), 0)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def request(path, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=90)
            conn.request('GET' if body is None else 'POST', path,
                         None if body is None else json.dumps(body),
                         {} if body is None else {'Content-Type': 'application/json', 'X-ModuleA-Token': app.token})
            response = conn.getresponse(); raw = response.read(); conn.close()
            return response.status, raw
        base = '/api/v1/studies/'+self.sid+'/analysis-plan/reports'
        status, raw = request(base); self.assertEqual(status, 200, raw[:200])
        value = json.loads(raw); self.assertEqual(value['schema_version'], 'A07.plan_report.3')
        for item, ref in zip(value['history'][-1]['downloads'], result['tables']['report_files']):
            status, raw = request(item['url']); self.assertEqual(status, 200)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['sha256'])
        self.assertEqual((self.w.location(self.sid)/'manifest.json').read_bytes(), before)
        body = self.body()
        with patch.object(app.tasks, '_spawn'):
            status, raw = request(base+'/generate', body)
        self.assertEqual(status, 202, raw[:200])
        queued = json.loads(app.tasks._raw(json.loads(raw)['task']['task_id'])['payload'])
        self.assertEqual(queued, {'report_protocol': 'A07.plan_report.3', 'request': body})
