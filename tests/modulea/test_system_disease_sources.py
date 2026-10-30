"""只读疾病原件复用：循本研究实际来源链，不扫描借用或改变旧批次。"""
from copy import deepcopy
from pathlib import Path
import shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import read_json,verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_execution,system_disease_sources as sources
from tests.modulea import plan_report_fixture as fixture


class SystemDiseaseSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=tempfile.TemporaryDirectory(prefix='disease_reuse_seed_');cls.addClassCleanup(cls.seed.cleanup)
        cls.base=Path(cls.seed.name)/'data';w,cls.sid,_,_=fixture.prepare(cls.base,modern=True,stop_before_normalization=True)
        info=system_execution.info(w,cls.sid);batch=w.start_analysis_plan_system_batch(cls.sid,{k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|
            {'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成原件复用测试','note':'同研究真实规范标准化，不是科研复核','confirmed':True})
        cls.batch_id=batch['batch_id'];cls.original=w.load(cls.sid)['current']['A02']
        for stage in ('A01','A02'):
            w.execute_analysis_plan_system_stage(cls.sid,{'batch_id':cls.batch_id,'stage':stage,'expected_current_run_id':w.load(cls.sid)['current'].get(stage)})

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='disease_reuse_case_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root);self.before=self.w.load(self.sid)

    def test_actual_normalized_lineage_resolves_original_without_any_write_or_fake_review(self):
        value=sources.resolve(self.w,self.before)
        self.assertTrue(value['reused_from_normalized']);self.assertEqual(value['base_run_id'],self.original)
        self.assertEqual(value['base_run'],self.before['runs'][self.original]['run_file'])
        self.assertEqual(value['source_current_run'],self.before['runs'][self.before['current']['A02']]['run_file'])
        self.assertFalse(value['human_review_written']);self.assertEqual(self.w.load(self.sid),self.before)

    def test_explicit_hold_of_source_normalization_blocks_original_reuse(self):
        rid=self.before['current']['A02'];self.w.review(self.sid,rid,'pending','明确合成测试','当前范围需核对')
        with self.assertRaises(ContractError):sources.resolve(self.w,self.w.load(self.sid))
        self.assertEqual(self.w.load(self.sid)['current'],self.before['current'])

    def test_modified_original_evidence_cannot_be_replaced_with_another_historical_candidate(self):
        home=self.w.location(self.sid);ref=self.before['runs'][self.original]['result_file'];path=verified_file(home,ref)
        path.write_bytes(path.read_bytes()+b'CORRUPT')
        with self.assertRaises(ContractError):sources.resolve(self.w,self.before)
        self.assertEqual(self.w.load(self.sid),self.before)
