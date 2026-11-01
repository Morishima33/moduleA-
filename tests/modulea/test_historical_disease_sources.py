"""未知版本例外绑定原文件和流程测试；生产候选/旧拒绝/标准化与报告均用合成原文核验。"""
import json,shutil,tempfile,unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from contracts import ContractError,fingerprint
from storage import verified_file,write_lock
from modulea.core import historical_disease_sources as core,system_disease_acquisition as acquisition,system_execution,system_pipeline
from modulea.core.kernel import full_workflow
from modulea.core.trace_export import build_trace
from tests.modulea import test_system_disease_manual_sources as fixture
from tests.modulea.test_system_disease_acquisition import synthetic_source
from science_modules.a02 import system_acquisition as old_science


class HistoricalDiseaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.SystemDiseaseManualSourcesTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.w=self.f.w;self.sid=self.f.sid;self.root=self.f.root
        for db in ('GeneCards','OMIM'):
            body=self.f.body(db);body['source']['version']='未知';self.w.stage_analysis_plan_system_disease_source(self.sid,body,self.f.raw)
        value=acquisition.info(self.w,self.sid)
        request={k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{'request_id':'diseaseacqreq_'+uuid4().hex,'author':'合成测试','note':'真实旧关口仍拒绝未知版本','confirmed':True}
        with patch.object(old_science,'fetch_source',side_effect=synthetic_source):self.old=self.w.acquire_analysis_plan_system_disease_sources(self.sid,request)
        self.assertEqual(self.old['state'],'incomplete');value=core.info(self.w,self.sid)
        self.body={k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash','expected_source_hashes')}|{
            'request_id':'historicaldiseaseq_'+uuid4().hex,'author':'明确合成测试登记','note':'只针对本研究这两份原件','user_decision':'明确合成测试：同意，仅限当前流程测试','confirmed':True}

    def publish(self):return self.w.publish_analysis_plan_historical_disease_candidates(self.sid,self.body)

    def test_candidate_keeps_unknown_and_original_files_and_no_reviews(self):
        before=self.w.load(self.sid);home=self.w.location(self.sid);refs={r['database']:r['archive'] for r in core.context(self.w,before)['sources']}
        with patch.object(old_science,'fetch_source',side_effect=AssertionError('不能重下载')):result=self.publish()
        self.assertEqual(result['summary']['候选记录数'],5);self.assertTrue(result['summary']['handoff_blocked'])
        self.assertFalse(result['summary']['database_versions_complete']);self.assertEqual(len(result['tables']['source_version_exceptions']),2)
        self.assertTrue(all(r['version']=='未知' for r in result['tables']['source_version_exceptions']))
        m=self.w.load(self.sid);self.assertEqual(m['reviews'],[]);self.assertEqual(m['current']['A00'],before['current']['A00'])
        self.assertEqual(set(m['current']),{'A00','A02'});self.assertTrue(self.w.active(m,m['current']['A02']))
        self.assertEqual(self.publish()['run_id'],result['run_id']);self.assertEqual(len(self.w.load(self.sid)[core.INDEX]),1)
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['historical_disease_sources']),1)
        for ref in refs.values():verified_file(home,ref)
        system_pipeline.required_inputs(self.w,m)
        from modulea.core import system_disease_sources
        self.w.review(self.sid,m['current']['A00'],'pending','明确合成测试','暂停不妨碍查看原件')
        stopped=self.w.load(self.sid)
        self.assertEqual(system_disease_sources.resolve(self.w,stopped,check_reviews=False)['base_run_id'],result['run_id'])
        with self.assertRaises(ContractError):system_disease_sources.resolve(self.w,stopped)
        build_trace(self.w,self.sid,include_data=True)

    def test_stale_extra_fields_no_confirmation_and_changed_file_hash_refused(self):
        before=self.w.load(self.sid)
        for change in ({'confirmed':False},{'passed':True},{'version':'pretend'},{'url':'https://example.com'},
                {'expected_input_hash':'old'},{'expected_source_hashes':{'GeneCards':'0'*64,'OMIM':'0'*64}},{'user_decision':''}):
            with self.subTest(change=change),self.assertRaises(ContractError):self.w.publish_analysis_plan_historical_disease_candidates(self.sid,self.body|change)
        self.assertEqual(self.w.load(self.sid),before)

    def test_formal_purpose_new_plan_pause_and_trash_block(self):
        self.w.review(self.sid,self.body['expected_a00'],'pending','明确合成测试','暂停')
        with self.assertRaises(ContractError):self.publish()
        with write_lock(self.w.root):
            m=self.w.load(self.sid);m['trashed']=True;self.w.save(m)
        self.assertFalse(core.info(self.w,self.sid)['enabled'])

    def test_corrupt_original_and_cross_study_deny(self):
        value=core.context(self.w,self.w.load(self.sid));ref=value['sources'][0]['archive'];home=self.w.location(self.sid)
        (home/ref['path']).write_bytes(b'corrupt')
        with self.assertRaises(ContractError):self.publish()
        other=fixture.SystemDiseaseManualSourcesTests();other.setUp();self.addCleanup(other.doCleanups)
        with self.assertRaises(ContractError):other.w.publish_analysis_plan_historical_disease_candidates(other.sid,self.body)

    def test_new_plan_or_replaced_valid_original_cannot_inherit_old_decision(self):
        draft=self.w.analysis_plan_info(self.sid)['draft'];m=self.w.load(self.sid)
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},'author':'明确合成测试','note':'新方案须新决定'})
        with self.assertRaises(ContractError):self.publish()
        self.assertNotIn(core.INDEX,self.w.load(self.sid))

    def test_formal_research_is_never_eligible(self):
        from modulea.core.plan_creation import PlanCreation
        from modulea.config import Settings
        from modulea.core.kernel import Kernel
        from tests.modulea.test_study_creation import official_fixture
        service=PlanCreation(Kernel(Settings(data_root=self.root,runtime_dir=self.root/'rt2')))
        data={'intake':{'formula':'正式测试方','herbs':'合成药','disease':'合成病','mesh_term':'Synthetic Disease','mesh_id':'D123456',
            'operator':'明确测试','analysis_purpose':'formal_research'},'specification':{'mode':'standard'}}
        with patch('modulea.core.plan_creation.verify_mesh_identity',side_effect=official_fixture):pre=service.preflight(data)
        result=service.create({'request_id':'plancreate_'+uuid4().hex,'preflight_id':pre['preflight_id'],'expected_input_hash':pre['input_hash'],'confirmed':True})
        value=core.info(self.w,result['study_id']);self.assertFalse(value['enabled']);self.assertTrue(any('正式研究' in s for s in value['blockers']))

    def test_interrupted_exception_save_reuses_exact_orphan_without_overwrite(self):
        save=self.w.save
        def failed(m):
            if m.get(core.INDEX):raise ContractError('明确合成保存失败')
            return save(m)
        with patch.object(self.w,'save',side_effect=failed),self.assertRaises(ContractError):self.publish()
        home=self.w.location(self.sid);path=home/'decisions/analysis_plans/historical_disease_sources'/self.body['request_id']/'exception.json'
        before=path.read_bytes();self.assertNotIn(core.INDEX,self.w.load(self.sid));result=self.publish()
        self.assertEqual(path.read_bytes(),before);self.assertTrue(result['summary']['source_version_exception'])


class HistoricalDiseasePipelineTests(unittest.TestCase):
    def test_original_normalization_and_empty_report_preserve_version_notice(self):
        from tests.modulea import test_system_component_sources as source_fixture
        from tests.modulea import plan_report_fixture as mapping_fixture
        from modulea.core import system_disease_manual_sources as manual
        import docx
        with tempfile.TemporaryDirectory() as temp:
            mapping=Path(temp)/'mapping';mapping_fixture.prepare(mapping,modern=True)
            source=source_fixture.SystemComponentSourceTests();source.mapping_root=mapping;source.setUp();self.addCleanup(source.doCleanups)
            w=source.w;sid=source.sid;w.bind_analysis_plan_system_a01_sources(sid,source.body)
            for db in ('GeneCards','OMIM'):
                info=manual.info(w,sid);body={k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                    'request_id':'manualsourceq_'+uuid4().hex,'author':'明确合成测试','note':'同研究未知版本','confirmed':True,
                    'source':{'database':db,'format':'tsv','query':'Synthetic Disease','retrieved_at':'2026-10-17','version':'未知',
                        'encoding':'utf-8-sig','name':'synthetic.tsv','query_quoted':'unknown','export_completeness':'unknown'}}
                w.stage_analysis_plan_system_disease_source(sid,body,b'raw_symbol\tdisease_term\nB\tSynthetic Disease\n')
            info=acquisition.info(w,sid);body={k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成测试','note':'旧规则继续拒绝','confirmed':True}
            def public(db,summary):
                item,diagnostic=synthetic_source(db,summary);item['data']=item['data'].replace(b'A\t',b'B\t');return item,diagnostic
            with patch.object(old_science,'fetch_source',side_effect=public):w.acquire_analysis_plan_system_disease_sources(sid,body)
            info=core.info(w,sid);body={k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash','expected_source_hashes')}|{
                'request_id':'historicaldiseaseq_'+uuid4().hex,'author':'明确合成测试','note':'独立例外全链','user_decision':'合成测试明确同意，仅当前流程测试','confirmed':True}
            candidate=w.publish_analysis_plan_historical_disease_candidates(sid,body)
            batch=source.start();self.assertEqual(batch['disease_source_protocol'],'A02.system_source_reuse.3')
            result=w.execute_analysis_plan_system_pipeline(sid,{'batch_id':batch['batch_id']})
            m=w.load(sid);a02=w.result(m,m['current']['A02']);self.assertEqual(w.run(m,m['current']['A02'])['config']['version'],'A02.system_normalization.4')
            self.assertFalse(a02['summary']['database_versions_complete']);self.assertEqual(a02['summary']['标准化基因数'],1)
            self.assertEqual(w.result(m,m['current']['A03'])['summary']['交集靶点数'],0);self.assertEqual(m['reviews'],[])
            report=w.result(m,m['current']['A07']);self.assertEqual(len(report['tables']['report_files']),2)
            for ref in report['tables']['report_files']:
                document=docx.Document(verified_file(w.location(sid),ref));self.assertIn(core.NOTICE,'\n'.join(p.text for p in document.paragraphs))
            build_trace(w,sid,include_data=True)
            # 版本例外不能放行A01关键身份待核；用独立损坏输入验证原关口仍拒绝。
            from science_modules.a02.system_normalization_historical import facts
            from storage import file_record,write_json
            run=w.run(m,m['current']['A02']);inputs=dict(run['inputs']);a01=w.result(m,m['current']['A01'])
            a01['summary']['handoff_blocked']=True;path=w.location(sid)/'raw/explicit_blocked_a01_fixture.json';write_json(path,a01)
            inputs['a01_result']=file_record(w.location(sid),path,'explicit_invalid_fixture')
            with self.assertRaises(ContractError):facts(w.location(sid),inputs)


if __name__=='__main__':unittest.main()
