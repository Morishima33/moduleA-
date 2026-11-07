"""报告展示二版：集合正确、名称可读、译名完整及旧版原字节保护。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from xml.etree import ElementTree as ET
from uuid import uuid4

from contracts import ContractError
from science_modules.a07 import plan_figures_v2 as figures
from science_modules.a07 import plan_translations_v2 as translations


class ReportRevisionTests(TestCase):
    """使用独立合成对象核对新展示，不改变真实统计或研究。"""

    def test_disconnected_layout_does_not_compress_connected_network(self):
        import networkx as nx
        graph = nx.complete_graph(40); graph.add_node('isolated')
        coordinates = figures.network_positions(graph)
        connected = [coordinates[key] for key in range(40)]
        self.assertGreater(max(x for x, y in connected)-min(x for x, y in connected), 1000)
        self.assertGreater(max(y for x, y in connected)-min(y for x, y in connected), 700)
        self.assertEqual(set(coordinates), set(graph))

    def test_appendix_kegg_translations_have_official_id_and_basis(self):
        lexicon = translations.merged_lexicon()
        for tid, english in (('hsa05110', 'Vibrio cholerae infection'),
                             ('hsa05340', 'Primary immunodeficiency'),
                             ('hsa05414', 'Dilated cardiomyopathy')):
            entry = translations.checked_translation({'ID': tid, 'Description': english}, lexicon)
            self.assertTrue(entry['zh'])
            self.assertEqual(entry['source'], 'https://www.kegg.jp/entry/'+tid)

    def test_ppi_uses_degree_round2_internal_edges_and_keeps_isolate(self):
        result = {'tables': {'mapping': [{'target_id': x, 'symbol': x} for x in 'ABCD'],
                             'edges': [{'source': 'A', 'target': 'B'}, {'source': 'B', 'target': 'C'}]}}
        selection = {'degree_round2': [{'target_id': x, 'symbol': x} for x in 'ABD']}
        scope = figures.network_scope(result, selection)
        self.assertEqual([r['target_id'] for r in scope['nodes']], list('ABD'))
        self.assertEqual(scope['edges'], [{'source': 'A', 'target': 'B'}])
        self.assertEqual(scope['isolates'], ['D'])
        self.assertEqual(scope['kind'], 'degree_round2')
        with self.assertRaises(ContractError):
            figures.network_scope(result, {'degree_round2': [{'target_id': 'unknown'}]})
        with self.assertRaises(ContractError):
            figures.network_scope(result, None)

    def test_venn_restores_confirmed_geometry_and_numbers(self):
        with TemporaryDirectory() as temp:
            paths = figures.venn({'仅方剂靶点数': 727, '交集靶点数': 1824, '仅疾病靶点数': 7418}, temp)
            svg = ET.parse(paths['svg']).getroot()
            text = paths['svg'].read_text(encoding='utf-8')
            self.assertIn('#D9E7EA', text)
            self.assertIn('#F7E9D7', text)
            self.assertIn('#E6A9B5', text)
            self.assertIn('1824', text)
            circles = svg.findall('{http://www.w3.org/2000/svg}circle')
            self.assertAlmostEqual(float(circles[1].get('cx')) / float(circles[0].get('r')), 3.18790, places=4)

    def test_heatmap_labels_actual_compound_and_all_na_cells(self):
        facts = {'compounds': [{'compound_id': 'CHEM_A', 'name': 'quercetin'}],
                 'receptors': [{'target_id': 'HGNC:1', 'symbol': 'GENE_A'}],
                 'pairs': [{'compound_id': 'CHEM_A', 'target_id': 'HGNC:1', 'score': None}]}
        with TemporaryDirectory() as temp:
            paths, _ = figures.heatmaps(facts, temp)[0]
            text = paths['svg'].read_text(encoding='utf-8')
            self.assertIn('quercetin', text)
            self.assertNotIn('成分1<', text)
            self.assertIn('>NA<', text)
            self.assertNotIn('>0.00<', text)

    def test_translation_supplement_preserves_original_and_rejects_english_mismatch(self):
        before = translations.original.LEXICON.read_bytes()
        lexicon = translations.merged_lexicon()
        self.assertEqual(len(translations.SUPPLEMENT.read_text(encoding='utf-8')) > 0, True)
        self.assertTrue(lexicon['GO:0099529']['source_obsolete'])
        self.assertEqual(translations.original.LEXICON.read_bytes(), before)
        row = {'ID': 'GO:0007204', 'Description': 'positive regulation of cytosolic calcium ion concentration'}
        self.assertTrue(translations.checked_translation(row, lexicon)['zh'])
        with self.assertRaises(ContractError):
            translations.checked_translation(dict(row, Description='different term'), lexicon)

    def test_readability_gate_rejects_missing_translation_and_placeholder_anywhere(self):
        payload = {'enrichment': {'pending_translations': ['GO:UNKNOWN'], 'tables': {}}, 'figures': []}
        with self.assertRaises(ContractError):
            translations.check_readability(payload)
        payload = {'enrichment': None, 'figures': [], 'sources': [{'description': '中文待核译'}]}
        with self.assertRaises(ContractError):
            translations.check_readability(payload)

    def test_nonempty_enrichment_keeps_statistics_but_unknown_translation_blocks_delivery(self):
        from tests.modulea.test_plan_a05_display import fixture
        from science_modules.a07.plan_facts_v2 import automatic_enrichment
        from contracts import fingerprint
        base, plan, source = fixture(count=2)
        before = fingerprint(base)
        facts = automatic_enrichment(base, plan, source)
        translations.check_readability({'enrichment': facts})
        self.assertEqual(fingerprint(base), before)
        missing = deepcopy(source); missing['translations'] = {key: {} for key in missing['translations']}
        facts = automatic_enrichment(base, plan, missing)
        self.assertTrue(facts['pending_translations'])
        self.assertNotIn('中文待核译', str(facts))
        with self.assertRaises(ContractError):
            translations.check_readability({'enrichment': facts})

    def test_nonempty_document_uses_names_preserves_na_and_rejects_tampered_score(self):
        from docx import Document
        from tests.modulea.test_plan_report_documents import payload
        from science_modules.a07.plan_documents_v2 import build, validate_document
        data = payload(); data['schema_version'] = 'A07.plan_payload.2'
        data['completion']['schema_version'] = 'A07.plan_facts.2'
        with TemporaryDirectory() as temp:
            path = Path(temp)/'synthetic.docx'
            build(data, path, temp, draft=True)
            self.assertEqual(validate_document(path, data, draft=True)['matrix_cells_verified'], 4)
            document = Document(path)
            table = next(value for value in document.tables if [c.text for c in value.rows[0].cells] == ['成分','受体','实际状态','原因'])
            self.assertIn('One', table.rows[1].cells[0].text)
            self.assertIn('T2', table.rows[1].cells[1].text)
            matrix = next(value for value in document.tables if len(value.columns) == 3 and value.rows[0].cells[0].text == '成分')
            matrix.rows[1].cells[2].text = '0.00'; document.save(path)
            with self.assertRaises(ContractError):
                validate_document(path, data, draft=True)


class ReportRevisionWorkflowTests(TestCase):
    """隔离合成研究通过公开Workflow入口执行真实二版规范与生产版本分派。"""

    @classmethod
    def setUpClass(cls):
        from tests.modulea.plan_report_fixture import prepare
        from modulea.core import system_validation
        cls.temp = TemporaryDirectory(prefix='report_revision_seed_')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.workflow, cls.sid, _, _ = prepare(cls.root, empty=True)
        for module in ('A00', 'A01', 'A02', 'A03'):
            expected = system_validation.request(cls.workflow, cls.sid, cls.workflow.load(cls.sid)['current'][module])
            actual = cls.workflow.validate_analysis_plan_scientific_run(cls.sid,
                {key: expected[key] for key in ('expected_run_id', 'expected_input_hash')}
                | {'request_id': 'syscheckreq_'+uuid4().hex})
            if not actual['passed']:
                raise AssertionError(actual)

    def setUp(self):
        import shutil
        from modulea.core.kernel import full_workflow
        from modulea.core import plan_reports_v2 as report
        from science_modules.a07 import plan_report_flow_v2
        self.temp = TemporaryDirectory(prefix='report_revision_case_'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'data'; shutil.copytree(self.__class__.root, self.root)
        self.w = full_workflow(self.root); self.sid = self.__class__.sid

    def body(self):
        from modulea.core import plan_reports_v2 as report
        info = self.w.report_revision_info(self.sid)
        return {key: info[key] for key in ('expected_report_run_id', 'expected_input_hash')} | {
            'request_id': 'planreportreq_'+uuid4().hex, 'author': '明确合成测试',
            'note': '仅隔离验证报告二版，不是用户或科研复核', 'confirmed': True}

    def test_empty_revision_generates_two_valid_documents_without_new_reviews_or_upstream_runs(self):
        from modulea.core import plan_reports_v2 as report
        from storage import verified_file
        from science_modules.a07.plan_report_flow_v2 import validate_result
        before = self.w.load(self.sid)
        result = self.w.publish_analysis_plan_report_revision(self.sid, self.body())
        after = self.w.load(self.sid)
        self.assertEqual(after['reviews'], before['reviews'])
        self.assertEqual(len(after['runs']), len(before['runs'])+1)
        self.assertEqual(len(result['tables']['report_files']), 2)
        for ref in result['tables']['report_files']:
            verified_file(self.w.location(self.sid), ref)
        run = self.w.run(after, result['run_id'])
        validate_result(self.root, run, result['summary'], result['tables'], [], result['outcome'])
        self.assertEqual(result['summary']['报告修订'], report.VERSION)
        self.assertEqual(len(after[report.RECEIPTS]), 1)
        from modulea.core.trace_export import build_trace
        trace = build_trace(self.w, self.sid, include_data=True)['plan_decisions']
        self.assertEqual(len(trace['report_revision_receipts']), 1)
        self.assertEqual(trace['report_receipts'], [])

    def test_legacy_report_files_stay_unchanged_when_explicit_revision_is_generated(self):
        from modulea.core import plan_reports_v2 as report
        from storage import verified_file
        import hashlib
        old = self.w.publish_analysis_plan_report(self.sid, self.body())
        previous = {ref['path']: hashlib.sha256(verified_file(self.w.location(self.sid), ref).read_bytes()).hexdigest()
                    for ref in old['tables']['report_files']}
        self.w.publish_analysis_plan_report_revision(self.sid, self.body())
        self.assertEqual(previous, {ref['path']: hashlib.sha256(verified_file(self.w.location(self.sid), ref).read_bytes()).hexdigest()
                                    for ref in old['tables']['report_files']})



class FoundationPipelineIntegrationTests(TestCase):
    """原生产编排测试改由公开基础层新批次入口绑定二版报告。"""
    @classmethod
    def setUpClass(cls):
        from tests.modulea.test_system_pipeline import SystemPipelineTests
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        from unittest.mock import patch
        with patch.object(AnalysisPlanWorkflow, 'start_analysis_plan_system_batch',
                          AnalysisPlanWorkflow.start_analysis_plan_foundation_system_batch):
            SystemPipelineTests.setUpClass.__func__(cls)

    def prepare(self, empty):
        from tests.modulea.test_system_pipeline import SystemPipelineTests
        return SystemPipelineTests.prepare(self, empty)

    def execute(self):
        return self.w.execute_analysis_plan_system_pipeline(self.sid, self.body, tools=self.tools)

    def check_revision(self):
        from modulea.core import system_execution
        from storage import read_json, verified_file
        from modulea.core.trace_export import build_trace
        manifest = self.w.load(self.sid)
        batch = system_execution.read_batch(self.w, manifest, manifest[system_execution.BATCHES][0])[0]
        self.assertEqual(batch['report_protocol'], 'A07.plan_report.2')
        self.assertEqual(self.w.run(manifest, manifest['current']['A07'])['config']['version'], 'A07.plan_report.2')
        self.assertEqual(len(build_trace(self.w, self.sid)['plan_decisions']['report_revision_receipts']), 1)
        payload_ref = self.w.run(manifest, manifest['current']['A07'])['inputs']['payload_file']
        return read_json(verified_file(self.w.location(self.sid), payload_ref))

    def test_empty_foundation_pipeline_and_repeat_keep_report_version(self):
        from tests.modulea.test_system_pipeline import SystemPipelineTests
        SystemPipelineTests.test_empty_pipeline_generates_real_report_without_any_inapplicable_science_then_repeat_keeps_versions(self)
        self.check_revision()

    def test_full_na_foundation_pipeline_preserves_fixed_degree_selection(self):
        from tests.modulea.test_system_pipeline import SystemPipelineTests
        from tests.modulea.plan_report_nonempty_fixture import unavailable_sources
        from science_modules.a06 import source_preparation
        from unittest.mock import patch
        with patch.object(source_preparation, 'connect', side_effect=unavailable_sources):
            SystemPipelineTests.test_full_na_pipeline_keeps_fixed_objects_and_skips_disabled_r_and_vina(self)
        payload = self.check_revision()
        self.assertEqual(payload['docking']['counts']['NA'], 2)
        self.assertEqual(payload['network']['main']['kind'], 'degree_round2')
        self.assertTrue(payload['network']['selection_source'])
