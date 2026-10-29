"""公开现代建档到非空双报告集成；真实科学计算和原件，不用占位父结果。"""
import math,os,tempfile,unittest
from pathlib import Path
from storage import read_json,verified_file
from modulea.core.plan_reports import info
from science_modules.a07.plan_report_flow import validate_result
from science_modules.a07.plan_documents import validate_document
from tests.modulea import plan_report_nonempty_fixture as fixture


class NonemptyReportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """同一隔离研究只计算一次，后续测试全部只读核对。"""
        cls.temp=tempfile.TemporaryDirectory(prefix='report_nonempty_');cls.addClassCleanup(cls.temp.cleanup)
        cls.root=Path(cls.temp.name)
        cls.w,cls.sid,cls.before,cls.result=fixture.prepare(cls.root,
            Path(os.environ.get('MODULEA_A06_TOOLS','D:/codex-重大专项/moduleA/environment/a06_runtime_v1')),
            Path(os.environ.get('MODULEA_RSCRIPT','D:/R/R-4.4.1/bin/x64/Rscript.exe')))

    def test_all_eight_real_upstreams_and_no_report_review_fabrication(self):
        m=self.w.load(self.sid);run=self.w.run(m,self.result['run_id']);home=self.w.location(self.sid)
        self.assertEqual(m['workflow_profile'],'A00.preupload.2');self.assertEqual(m['reviews'],self.before['reviews'])
        self.assertEqual({key:value for key,value in m['current'].items() if key!='A07'},self.before['current'])
        self.assertEqual(run['parent_review_ids'],{});self.assertEqual(len(run['parent_validation_records']),8)
        self.assertEqual(run['parent_runs'],self.before['current'])
        self.assertFalse(self.w.approved(m,self.result['run_id']));self.assertTrue(info(self.w,self.sid)['history'][0]['active'])
        validate_result(self.root,run,self.result['summary'],self.result['tables'],self.result['anomalies'],self.result['outcome'])
        payload=read_json(verified_file(home,run['inputs']['payload_file']))
        self.assertEqual(payload['counts'],{'a01_genes':5,'a02_genes':5,'intersection':5})

    def test_actual_r_probability_unknown_kegg_and_original_names(self):
        m=self.w.load(self.sid);ora=self.w.result(m,m['current']['A05'])
        first=next(row for row in ora['tables']['bp_all'] if row['ID']=='hsa00002')
        self.assertAlmostEqual(first['pvalue'],math.comb(10,5)/math.comb(40,5),places=12)
        self.assertEqual(first['GeneRatio'],'5/5');self.assertEqual(first['BgRatio'],'10/40')
        run=self.w.run(m,self.result['run_id']);payload=read_json(verified_file(self.w.location(self.sid),run['inputs']['payload_file']))
        self.assertEqual(len(payload['enrichment']['tables']['kegg_deferred']),2)
        self.assertEqual(payload['enrichment']['tables']['kegg_plan_top'],[])
        self.assertTrue(payload['enrichment']['pending_translations'])

    def test_actual_shortage_full_na_matrix_word_and_archived_fact_code(self):
        m=self.w.load(self.sid);run=self.w.run(m,self.result['run_id']);home=self.w.location(self.sid)
        payload=read_json(verified_file(home,run['inputs']['payload_file']));facts=payload['docking']
        self.assertEqual((facts['counts']['compounds'],facts['counts']['receptors'],facts['counts']['pairs']),(2,1,2))
        self.assertEqual(facts['counts']['NA'],2);self.assertEqual(facts['counts']['scored'],0)
        self.assertTrue(all(row['score'] is None and row['state']=='NA' for row in facts['pairs']))
        self.assertNotIn('A06',m['current']);self.assertEqual(facts['state'],'not_applicable')
        source=read_json(verified_file(home,payload['figure_source']))
        self.assertTrue(any(row['path'].endswith('/science_modules/a07/plan_facts.py') for row in source['implementation_files']))
        self.assertEqual({row['module'] for row in payload['figures']},{'A03','A04','A05','A06'})
        for index,ref in enumerate(self.result['tables']['report_files']):
            value=validate_document(verified_file(home,ref),payload,concise=bool(index))
            self.assertEqual(value['matrix_cells_verified'],0 if index else 2)
