"""新批复用原五库的真实版本化标准化：旧快照保持、新方案独立、不重取原件。"""
from copy import deepcopy
from pathlib import Path
import hashlib,shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError,fingerprint
from storage import read_json,verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_execution as execution,system_disease_sources as sources,system_validation,system_pipeline
from modulea.core.trace_export import build_trace
from tests.modulea import test_system_disease_sources as fixture


class SystemDiseaseReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.SystemDiseaseSourcesTests.setUpClass.__func__(cls)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='disease_reuse_integration_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root);self.before=self.w.load(self.sid)
        self.old=self.w.result(self.before,self.before['current']['A02']);home=self.w.location(self.sid)
        self.original_files={p.relative_to(home).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in home.rglob('*') if p.is_file() and p.name!='manifest.json'}
        draft=self.w.analysis_plan_info(self.sid)['draft']
        self.plan=self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
            'author':'明确合成原件复用测试','note':'只改变新方案，原批/原件/旧意见保持'})['draft']
        info=execution.info(self.w,self.sid);self.body=({k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|
            {'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成测试','note':'原件复用不是沿用旧科研批准','confirmed':True})

    def start(self):
        self.batch=self.w.start_analysis_plan_system_batch(self.sid,self.body)
        return self.batch

    def stage(self,stage):
        return self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':self.batch['batch_id'],'stage':stage,
            'expected_current_run_id':self.w.load(self.sid)['current'].get(stage)})

    def test_real_second_batch_binds_old_normalization_to_original_five_and_new_plan_without_snapshot_rewrite(self):
        self.start();m=self.w.load(self.sid);source=sources.read(self.w,m,self.batch)
        self.assertEqual(self.batch['initial_binding']['current']['A02'],self.before['current']['A02'])
        self.assertEqual(source['base_run_id'],self.original);self.assertNotEqual(source['base_run_id'],self.batch['initial_binding']['current']['A02'])
        self.assertTrue(system_pipeline.required_inputs(self.w,m,self.batch))
        self.stage('A01')
        with patch('disease.run_disease',side_effect=AssertionError('复用原件不能重新取得候选')):result=self.stage('A02')
        m=self.w.load(self.sid);run=self.w.run(m,result['run_id'])
        self.assertEqual(run['config']['version'],'A02.system_normalization.2')
        self.assertEqual(run['inputs']['analysis_parameter_hash'],self.plan['plan']['parameter_hash'])
        self.assertEqual(fingerprint(result['tables']),fingerprint(self.old['tables']))
        self.assertEqual(result['summary']['标准化基因数'],self.old['summary']['标准化基因数'])
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertEqual(run['parent_review_ids'],{})
        self.assertTrue(self.w.active(m,result['run_id']));self.assertFalse(self.w.approved(m,result['run_id']))
        expected=system_validation.request(self.w,self.sid,result['run_id'])
        checked=self.w.validate_analysis_plan_scientific_run(self.sid,{k:expected[k] for k in ('expected_run_id','expected_input_hash')}|
            {'request_id':'syscheckreq_'+uuid4().hex})
        self.assertTrue(checked['passed'],checked['error_zh']);self.assertTrue(checked['scientific_status']['ready_for_successor'])
        a03=self.stage('A03');self.assertEqual(a03['summary']['交集靶点数'],self.old['summary']['标准化基因数'])
        for path,sha in self.original_files.items():self.assertEqual(hashlib.sha256((self.w.location(self.sid)/path).read_bytes()).hexdigest(),sha)
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['system_batches']),2)

    def test_pending_source_blocks_new_batch_without_new_current_or_reviews(self):
        rid=self.before['current']['A02'];self.w.review(self.sid,rid,'pending','明确合成测试','原范围需重新核对')
        m=self.w.load(self.sid);value=execution.info(self.w,self.sid)
        body=dict(self.body,expected_input_hash=value['expected_input_hash'])
        with self.assertRaises(ContractError):self.w.start_analysis_plan_system_batch(self.sid,body)
        after=self.w.load(self.sid);self.assertEqual(after,m)

    def test_production_validator_still_rejects_forged_new_scientific_counts(self):
        self.start();self.stage('A01');from science_modules.a02 import system_normalization_reuse as science
        original=science.compute
        def forged(*args):
            values=list(original(*args));values[2]=dict(values[2],标准化基因数=999);return values
        self.w.validators['A02']=lambda *args:None
        with patch.object(science,'compute',side_effect=forged),self.assertRaises(ContractError):self.stage('A02')
        m=self.w.load(self.sid);self.assertEqual(m['current']['A02'],self.before['current']['A02']);self.assertEqual(m['reviews'],self.before['reviews'])

    def test_third_batch_reuses_same_original_after_v2_without_recursive_or_replaced_source(self):
        self.start();self.stage('A01');first=self.stage('A02');m=self.w.load(self.sid)
        info=execution.info(self.w,self.sid)
        self.batch=self.w.start_analysis_plan_system_batch(self.sid,{k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|
            {'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成第三批测试','note':'明确新批，直接复用同一原始五库，不递归造新原候选','confirmed':True})
        binding=sources.read(self.w,self.w.load(self.sid),self.batch)
        self.assertEqual(binding['base_run_id'],self.original)
        self.assertEqual(binding['source_current_run'],m['runs'][first['run_id']]['run_file'])
        self.stage('A01');second=self.stage('A02');self.assertNotEqual(second['run_id'],first['run_id'])
        self.assertEqual(first['tables'],second['tables']);self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])
