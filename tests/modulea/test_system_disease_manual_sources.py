"""未批准新登记预上传的真实Workflow、原解析、原件绑定及人工暂停回归。"""
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import verified_file
from modulea.config import Settings
from modulea.core.kernel import Kernel,full_workflow
from modulea.core.plan_creation import PlanCreation
from modulea.core import system_disease_manual_sources as core
from tests.modulea.test_study_creation import official_fixture


class SystemDiseaseManualSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='manual_disease_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';service=PlanCreation(Kernel(Settings(data_root=self.root,runtime_dir=self.root/'rt')))
        body={'intake':{'formula':'合成方','herbs':'合成药','disease':'合成病','mesh_term':'Synthetic Disease',
            'mesh_id':'D123456','operator':'独立测试','analysis_purpose':'workflow_test'},'specification':{'mode':'standard'}}
        with patch('modulea.core.plan_creation.verify_mesh_identity',side_effect=official_fixture):
            value=service.preflight(body)
        created=service.create({'request_id':'plancreate_'+uuid4().hex,'preflight_id':value['preflight_id'],
            'expected_input_hash':value['input_hash'],'confirmed':True})
        self.sid=created['study_id'];self.w=full_workflow(self.root);self.before=self.w.load(self.sid)
        self.raw=b'raw_symbol\tdisease_term\nA\tSynthetic Disease\n'

    def body(self,database='GeneCards'):
        value=core.info(self.w,self.sid)
        return {k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'manualsourceq_'+uuid4().hex,'author':'明确合成测试','note':'只预上传，不签登记或发布候选','confirmed':True,
            'source':{'database':database,'format':'tsv','query':'Synthetic Disease','retrieved_at':'2026-10-31',
                'version':'explicit_synthetic_fixture','encoding':'utf-8-sig','name':'source.tsv','query_quoted':'unknown',
                'export_completeness':'complete'}}

    def test_actual_original_stage_two_libraries_without_a00_review_or_a02_run(self):
        for database in ('GeneCards','OMIM'):
            body=self.body(database);result=self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)
            m=self.w.load(self.sid);value=core.read_record(self.w,m,result['file'])
            self.assertEqual(verified_file(self.w.location(self.sid),value['source_file']).read_bytes(),self.raw)
            self.assertEqual(value['request'],body);self.assertFalse(value['human_review_written']);self.assertFalse(value['a02_published'])
            self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['runs'],self.before['runs']);self.assertEqual(m['reviews'],[])
        value=core.info(self.w,self.sid);self.assertEqual({r['database'] for r in value['sources']},{'GeneCards','OMIM'})
        self.assertFalse(self.w.approved(m,m['current']['A00']));self.assertEqual(len(m[core.INDEX]),2)

    def test_repeat_returns_same_receipt_and_changed_bytes_or_old_replaced_file_reject(self):
        body=self.body();result=self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw);before=self.w.load(self.sid)
        again=self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)
        self.assertEqual(again['file'],result['file']);self.assertFalse(again['created']);self.assertEqual(self.w.load(self.sid),before)
        with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw+b'B\tSynthetic Disease\n')
        self.w.stage_analysis_plan_system_disease_source(self.sid,self.body(),self.raw+b'B\tSynthetic Disease\n')
        with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)

    def test_stale_unknown_fields_wrong_library_oversize_and_missing_confirmation_reject(self):
        body=self.body()
        for invalid in (dict(body,confirmed=False),dict(body,path='outside'),dict(body,source=dict(body['source'],database='OTP')),
                dict(body,source=dict(body['source'],database=[]))):
            with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,invalid,self.raw)
        with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,body,b'x'*(core.MAX_BYTES+1))
        self.w.stage_analysis_plan_system_disease_source(self.sid,self.body('OMIM'),self.raw)
        with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)

    def test_wrong_embedded_disease_title_keeps_manifest_sources_unchanged(self):
        body=self.body();body['source'].update(format='genecards_csv',name='source.csv')
        raw=b'GeneCards - GeneCards - Search results for Another Disease\nGene Symbol\nA\n'
        with self.assertRaisesRegex(ContractError,'身份不匹配'):self.w.stage_analysis_plan_system_disease_source(self.sid,body,raw)
        after=self.w.load(self.sid);self.assertNotIn('current_source_staging',after);self.assertNotIn(core.INDEX,after)
        self.assertEqual(after['current'],self.before['current']);self.assertEqual(after['reviews'],[])

    def test_queue_time_hold_and_hold_during_identity_check_block_original_stage(self):
        body=self.body();original=__import__('science_modules.a02.manual_staging',fromlist=['stage'])
        def hold(*args):
            self.w.review(self.sid,body['expected_a00'],'pending','明确合成人工暂停','只测试排队后暂停')
        with patch.object(original,'validate_source_identity',side_effect=hold),self.assertRaises(ContractError):
            self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)
        self.assertNotIn('current_source_staging',self.w.load(self.sid))
        with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)

    def test_corrupt_uploaded_original_blocks_replay_and_read_only_info(self):
        body=self.body();result=self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)
        path=verified_file(self.w.location(self.sid),result['source_file']);path.write_bytes(b'corrupt')
        with self.assertRaises(ContractError):core.info(self.w,self.sid)
        with self.assertRaises(ContractError):self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)

    def test_save_failure_cannot_publish_source_without_its_receipt(self):
        body=self.body();save=self.w.save
        def reject(manifest):
            if manifest.get(core.INDEX):raise ContractError('明确测试同次保存失败')
            return save(manifest)
        with patch.object(self.w,'save',side_effect=reject),self.assertRaises(ContractError):
            self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)
        m=self.w.load(self.sid);self.assertNotIn('current_source_staging',m);self.assertNotIn(core.INDEX,m)
        self.assertTrue(list((self.w.location(self.sid)/'raw/A00_staging').rglob('source_staging.json')))
        result=self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw);self.assertTrue(result['created'])

    def test_actual_manual_to_five_libraries_and_candidate_without_any_a00_approval(self):
        from modulea.core import system_disease_acquisition as acquisition,system_disease_publication as publication
        from modulea.core.trace_export import build_trace
        from science_modules.a02 import system_acquisition as science
        from tests.modulea.test_system_disease_acquisition import synthetic_source
        receipts=[self.w.stage_analysis_plan_system_disease_source(self.sid,self.body(db),self.raw) for db in ('GeneCards','OMIM')]
        value=acquisition.info(self.w,self.sid)
        body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成集成测试','note':'原件预上传至实际候选，不签复核','confirmed':True}
        with patch.object(science,'fetch_source',side_effect=synthetic_source):result=self.w.acquire_analysis_plan_system_disease_sources(self.sid,body)
        self.assertEqual(result['state'],'complete')
        self.assertEqual([row['archive'] for row in result['sources'][:2]],[row['source_file'] for row in receipts])
        value=publication.info(self.w,self.w.load(self.sid),body['request_id']);self.assertTrue(value['enabled'])
        candidate=self.w.publish_analysis_plan_system_disease_candidates(self.sid,value['request']|{
            'request_id':'diseasepublishreq_'+uuid4().hex,'author':'明确合成集成测试','note':'只整理候选，不签人工批准','confirmed':True})
        self.assertEqual(candidate['summary']['候选记录数'],5);self.assertTrue(candidate['summary']['handoff_blocked'])
        m=self.w.load(self.sid);self.assertEqual(m['reviews'],[]);self.assertEqual(set(m['current']),{'A00','A02'})
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['disease_manual_sources']),2)

    def test_unknown_version_can_be_archived_but_disease_acquisition_still_blocks_it(self):
        from modulea.core import system_disease_acquisition as acquisition
        from science_modules.a02 import system_acquisition as science
        from tests.modulea.test_system_disease_acquisition import synthetic_source
        for db in ('GeneCards','OMIM'):
            body=self.body(db);body['source']['version']='未知';self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.raw)
        self.assertTrue(all(row['status_zh']=='已预上传；版本待核' for row in core.info(self.w,self.sid)['sources']))
        value=acquisition.info(self.w,self.sid)
        body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成版本阻断测试','note':'未知版本不冒充完整原件','confirmed':True}
        with patch.object(science,'fetch_source',side_effect=synthetic_source):result=self.w.acquire_analysis_plan_system_disease_sources(self.sid,body)
        self.assertEqual(result['state'],'incomplete');self.assertEqual([r['state'] for r in result['sources'][:2]],['failed','failed'])
        self.assertTrue(all('版本待核' in r['reason_zh'] for r in result['sources'][:2]));self.assertNotIn('A02',self.w.load(self.sid)['current'])
