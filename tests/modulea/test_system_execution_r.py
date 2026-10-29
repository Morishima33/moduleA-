"""未人工批准A03按系统证据执行真实固定R，旧统计不改；全部合成来源。"""
import math,os,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.modulea import test_system_execution as fixture
from tests.modulea import test_plan_a05 as annotation_fixture
from modulea.core.kernel import full_workflow
from modulea.core import system_execution as system
from modulea.core.trace_export import build_trace


class SystemExecutionRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SystemExecutionTests.setUpClass.__func__(cls)

    def test_actual_r_runs_without_new_human_approvals_and_preserves_parameters(self):
        temp=tempfile.TemporaryDirectory(prefix='system_execution_r_');self.addCleanup(temp.cleanup)
        root=Path(temp.name)/'data';shutil.copytree(self.source,root);w=full_workflow(root);before=w.load(self.sid)
        value=system.info(w,self.sid)
        batch=w.start_analysis_plan_system_batch(self.sid,{key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+'b'*32,'author':'明确合成系统R测试','note':'一次批次确认，真实固定R，不写新人工批准','confirmed':True})
        def execute(stage):
            return w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':stage,
                'expected_current_run_id':w.load(self.sid)['current'].get(stage)})
        execute('A01');a03=execute('A03');plan=w.analysis_plan_info(self.sid)['draft']['plan'];annotation_fixture.install_source(root,plan)
        with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(annotation_fixture.RSCRIPT)}):result=execute('A05')
        m=w.load(self.sid);self.assertFalse(w.approved(m,a03['run_id']));self.assertFalse(w.approved(m,result['run_id']))
        self.assertTrue(w.active(m,result['run_id']));self.assertEqual(m['reviews'],before['reviews'])
        row=next(row for row in result['tables']['bp_all'] if row['ID']=='hsa00002')
        self.assertAlmostEqual(row['pvalue'],math.comb(10,5)/math.comb(40,5),places=12)
        self.assertEqual(row['GeneRatio'],'5/5');self.assertEqual(row['BgRatio'],'10/40')
        self.assertEqual(w.run(m,result['run_id'])['parent_review_ids'],{})
        self.assertEqual(w.run(m,result['run_id'])['inputs']['analysis_plan_file'],batch['plan_file'])
        trace=build_trace(w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['system_batch_events']),3)
