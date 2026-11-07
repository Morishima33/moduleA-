"""合成官方响应、真实Meeko/Vina贯通第三版评分、第四版导出及第二版报告。"""
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from storage import read_json, verified_file
from tests.modulea import test_system_sources as upstream, plan_report_fixture


class FoundationScoredOutputsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        original = plan_report_fixture.prepare
        def prepare(*args, **kwargs):
            # 本合成用例明确不纳入富集，验证有评分分支，不借缺失A05绕过门禁。
            kwargs['specification'] = {'mode':'personalized','parameters':{
                'a05.include_go':False,'a05.include_kegg':False}}
            return original(*args, **kwargs)
        with patch.object(plan_report_fixture, 'prepare', side_effect=prepare):
            upstream.SystemSourcesTests.setUpClass.__func__(cls)

    setUp = upstream.SystemSourcesTests.setUp
    execute = upstream.SystemSourcesTests.execute

    def test_actual_scored_source_protocol_exports_and_report_keep_exact_same_batch(self):
        upstream.SystemSourcesTests.test_interrupted_ready_ligand_and_real_vina_use_original_fixed_parameters(self)
        from modulea.core import system_execution
        m = self.w.load(self.sid)
        for module in ('A00','A01','A02','A03','A03_SELECT','A04','A06_PREP','A06'):
            system_execution.ensure_parents(self.w, self.sid, {module:self.w.load(self.sid)['current'][module]})
        before = self.w.load(self.sid)
        score = self.w.result(before, before['current']['A06'])
        info = self.w.analysis_plan_system_exports_info(self.sid)
        self.assertTrue(info['enabled'], info['blockers'])
        exported = self.w.export_analysis_plan_system_results(self.sid,
            {k:info[k] for k in ('expected_module','expected_run_id','expected_input_hash')} | {
                'request_id':'sysexportreq_'+uuid4().hex,'author':'明确合成测试',
                'note':'真实工具的合成评分导出，不是研究验收','confirmed':True})
        self.assertEqual(exported['schema_version'], 'A06.system_exports.4')
        self.assertEqual(exported['source_run_id'], score['run_id'])
        view = read_json(verified_file(self.w.location(self.sid), exported['view_file']))
        actual = [c['score'] for row in view['table']['cells'] for c in row]
        self.assertEqual(actual, [r['score'] for r in score['tables']['plan_scoring_pairs']])
        info = self.w.report_revision_info(self.sid)
        self.assertTrue(info['enabled'], info['blockers'])
        report = self.w.publish_analysis_plan_report_revision(self.sid,
            {k:info[k] for k in ('expected_report_run_id','expected_input_hash')} | {
                'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成测试',
                'note':'合成有评分分支生产接续，不替代真实研究验收','confirmed':True})
        after = self.w.load(self.sid); run = self.w.run(after, report['run_id'])
        self.assertEqual(run['config']['version'], 'A07.plan_report.2')
        payload = read_json(verified_file(self.w.location(self.sid), run['inputs']['payload_file']))
        self.assertEqual(payload['run_ids']['A06'], score['run_id'])
        self.assertEqual(payload['docking']['counts']['scored'], 1)
        self.assertEqual(after['reviews'], before['reviews'])
        self.assertEqual(len(report['tables']['report_files']), 2)
