"""同研究真实三库/五库/PPI/R/Vina的部分评分报告集成；所有外部资料明确合成。"""
import os,re,tempfile,unittest
from pathlib import Path
from storage import read_json,verified_file
from modulea.core.plan_reports import info
from science_modules.a07.plan_report_flow import validate_result
from science_modules.a07.plan_documents import validate_document
from tests.modulea import plan_report_nonempty_fixture as upstream
from tests.modulea import plan_report_scoring_fixture as scoring_fixture


class ScoredReportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """一份完整非空研究只计算一次，先保留NA报告，再追加真实评分修订。"""
        cls.temp=tempfile.TemporaryDirectory(prefix='report_scored_');cls.addClassCleanup(cls.temp.cleanup);cls.root=Path(cls.temp.name)
        tools=Path(os.environ.get('MODULEA_A06_TOOLS','D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))
        rscript=Path(os.environ.get('MODULEA_RSCRIPT','D:/R/R-4.4.1/bin/x64/Rscript.exe'))
        cls.w,cls.sid,_,cls.original_report=upstream.prepare(cls.root,tools,rscript)
        cls.before_scoring,cls.scoring,cls.before_report,cls.report=scoring_fixture.publish_scored_report(cls.w,cls.sid,tools)

    def test_actual_top1_parameters_partial_matrix_and_no_report_approval(self):
        home=self.w.location(self.sid);m=self.w.load(self.sid);score=self.scoring
        self.assertEqual(score['outcome'],'success')
        self.assertEqual((score['summary']['scored_pairs'],score['summary']['na_pairs'],score['summary']['exploratory_scored_pairs']),(1,1,1))
        packet=read_json(verified_file(home,score['tables']['scoring_packet'][0]));row=next(row for row in packet['pairs'] if row['state']=='completed')
        execution=read_json(verified_file(home,row['execution']));raw=verified_file(home,execution['pose']).read_text('ascii')
        energy=float(re.search(r'REMARK\s+VINA RESULT:\s*([-+0-9.eE]+)',raw).group(1))
        self.assertEqual(next(row for row in score['tables']['plan_scoring_pairs'] if row['state']=='completed')['score'],energy)
        command=read_json(verified_file(home,next(ref for ref in execution['files'] if ref['path'].endswith('/command.json'))))
        for flag,value in (('--exhaustiveness','8'),('--num_modes','9'),('--energy_range','3.0'),('--seed','1'),('--cpu','1')):
            self.assertEqual(command['arguments'][command['arguments'].index(flag)+1],value)
        run=self.w.run(m,self.report['run_id']);payload=read_json(verified_file(home,run['inputs']['payload_file']))
        self.assertEqual(payload['completion']['state'],'partial');self.assertFalse(payload['completion']['complete_analysis'])
        self.assertEqual(payload['docking']['counts']['NA'],1);self.assertEqual(payload['docking']['counts']['scored'],1)
        self.assertTrue(all(row['score'] is None for row in payload['docking']['pairs'] if row['state']=='NA'))
        self.assertEqual(len(run['parent_validation_records']),9);self.assertEqual(run['parent_review_ids'],{})
        self.assertEqual(m['reviews'],self.before_report['reviews']);self.assertFalse(self.w.approved(m,self.report['run_id']))
        self.assertEqual(payload['run_ids'],{key:rid for key,rid in m['current'].items() if key!='A07'})
        self.assertEqual(payload['counts'],{'a01_genes':5,'a02_genes':5,'intersection':5})
        self.assertEqual(len(info(self.w,self.sid)['history']),2)
        validate_result(self.root,run,self.report['summary'],self.report['tables'],self.report['anomalies'],self.report['outcome'])
        for index,record in enumerate(self.report['tables']['report_files']):
            value=validate_document(verified_file(home,record),payload,concise=bool(index))
            self.assertEqual(value['matrix_cells_verified'],0 if index else 2)
