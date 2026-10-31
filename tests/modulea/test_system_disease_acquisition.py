"""新登记疾病五库原件获取与断点恢复，网络响应明确合成，原解析/身份/回执实际执行。"""
import unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import verified_file
from modulea.core import system_disease_acquisition as core
from modulea.core.trace_export import build_trace
from science_modules.a02 import system_acquisition as science
from tests.modulea import test_system_acquisition as fixture
from intake_sources import stage


def synthetic_source(db,summary,*,empty=False):
    """保留明确合成原文，真实通用TSV解析不伪造官方研究结果。"""
    return {'database':db,'format':'tsv','query':summary['mesh_term'],'retrieved_at':'2026-10-31','version':'explicit-synthetic-v1',
        'source_url':'explicit_synthetic_fixture','encoding':'utf-8-sig','name':'synthetic.tsv',
        'data':('raw_symbol\tdisease_term\n'+('' if empty else 'A\t'+summary['mesh_term']+'\n')).encode()}, {'synthetic_fixture':True}


class SystemDiseaseAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.SystemAcquisitionTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.w=self.fixture.w;self.sid=self.fixture.sid;self.root=self.fixture.root
        self.before=self.w.load(self.sid);self.summary=self.w.result(self.before,self.before['current']['A00'])['summary']
        self.body=self.request()

    def request(self):
        value=core.info(self.w,self.sid)
        return {key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成五库原件测试','note':'仅原件获取和恢复，不发布疾病候选或人工复核','confirmed':True}

    def execute(self):return self.w.acquire_analysis_plan_system_disease_sources(self.sid,self.body)

    def stage_manual(self):
        """旧公开预上传入口真实暂存受限库，仍不批准A00或生成A02。"""
        for db in ('GeneCards','OMIM'):stage(self.w,self.sid,self.before['current']['A00'],synthetic_source(db,self.summary)[0])

    def test_unapproved_registration_fetches_three_public_sources_manual_missing_not_zero(self):
        calls=[]
        def fetch(db,summary):calls.append(db);return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=fetch):value=self.execute()
        self.assertEqual(calls,['TTD','PharmGKB','OTP']);self.assertEqual(value['state'],'incomplete')
        self.assertEqual([r['state'] for r in value['sources']],['missing','missing','ready','ready','ready'])
        m=self.w.load(self.sid);self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['runs'],self.before['runs'])
        self.assertEqual(m['reviews'],[]);self.assertNotIn('current_source_staging',m)
        self.assertFalse(self.w.approved(m,m['current']['A00']));self.assertEqual(len(m[core.SOURCES]),3)
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['disease_acquisitions']),1)

    def test_manual_upload_then_new_confirmation_reuses_successful_public_originals(self):
        with patch.object(science,'fetch_source',side_effect=synthetic_source):first=self.execute()
        saved={r['database']:r['archive'] for r in first['sources'] if r['state']=='ready'}
        self.stage_manual()
        with self.assertRaises(ContractError):self.execute()
        self.body=self.request();before=self.w.load(self.sid)
        with patch.object(science,'fetch_source',side_effect=AssertionError('成功来源不重新获取')):second=self.execute()
        self.assertEqual(second['state'],'complete');self.assertEqual(len(second['sources']),5)
        for row in second['sources']:
            if row['database'] in saved:self.assertEqual(row['archive'],saved[row['database']])
        with patch.object(science,'fetch_source',side_effect=AssertionError('完整原件不重新获取')):self.assertEqual(self.execute(),second)
        m=self.w.load(self.sid)
        for key in ('current','runs','reviews','current_source_staging'):self.assertEqual(m[key],before[key])
        build_trace(self.w,self.sid)

    def test_partial_failure_explicit_retry_only_fetches_failed_library_keeps_originals(self):
        self.stage_manual();self.body=self.request()
        def partial(db,summary):
            if db=='TTD':raise ContractError('明确合成TTD网关失败')
            return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=partial):first=self.execute()
        self.assertEqual(first['state'],'incomplete');self.assertEqual(first['sources'][2]['state'],'failed');calls=[]
        def retry(db,summary):calls.append(db);return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=retry):second=self.execute()
        self.assertEqual(calls,['TTD']);self.assertEqual(second['state'],'complete')
        for row in first['sources']:
            if row['state']=='ready':verified_file(self.w.location(self.sid),row['archive'])

    def test_interruption_before_batch_record_reuses_individual_checkpoints(self):
        def interrupt(db,summary):
            if db=='PharmGKB':raise KeyboardInterrupt('明确合成进程中断')
            return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=interrupt),self.assertRaises(KeyboardInterrupt):self.execute()
        m=self.w.load(self.sid);self.assertEqual(len(m[core.SOURCES]),1);self.assertNotIn(core.RECORDS,m);calls=[]
        def retry(db,summary):calls.append(db);return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=retry):value=self.execute()
        self.assertEqual(calls,['PharmGKB','OTP']);self.assertEqual(value['state'],'incomplete');build_trace(self.w,self.sid)

    def test_valid_zero_is_ready_unknown_version_and_malformed_data_failed(self):
        def fetch(db,summary):
            value,detail=synthetic_source(db,summary,empty=True)
            if db=='TTD':value['version']='unknown'
            if db=='PharmGKB':value['data']=b'wrong_header\nvalue\n'
            return value,detail
        with patch.object(science,'fetch_source',side_effect=fetch):value=self.execute()
        self.assertEqual(value['sources'][2]['state'],'failed');self.assertEqual(value['sources'][3]['state'],'failed')
        self.assertEqual(value['sources'][4]['state'],'ready');self.assertEqual(value['sources'][4]['parsed_records'],0)
        self.assertTrue(any(r['path'].endswith('/original.bin') for r in value['files']))

    def test_hold_during_fetch_stops_next_library_and_retains_actual_failure_files(self):
        calls=[]
        def stop(db,summary):
            calls.append(db);self.w.review(self.sid,self.before['current']['A00'],'pending','明确合成测试','获取期间暂停')
            return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=stop),self.assertRaises(ContractError):self.execute()
        self.assertEqual(calls,['TTD']);trace=build_trace(self.w,self.sid)
        self.assertTrue(trace['plan_decisions']['disease_acquisition_failures'][-1]['files'])
        self.assertEqual(self.w.load(self.sid)['current'],self.before['current'])

    def test_new_draft_during_fetch_is_not_adopted_as_original_plan(self):
        changed=[]
        def fetch(db,summary):
            if not changed:
                draft=self.w.analysis_plan_info(self.sid)['draft'];self.w.save_analysis_plan_draft(self.sid,{
                    'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],'expected_draft_id':draft['plan_id'],
                    'specification':{'mode':'personalized','parameters':{'a06.seed':7}},'author':'明确合成测试','note':'后来草稿不改原获取'});changed.append(True)
            return synthetic_source(db,summary)
        with patch.object(science,'fetch_source',side_effect=fetch):value=self.execute()
        request=core.read_record(self.w,self.w.load(self.sid),self.w.load(self.sid)[core.REQUESTS][-1],kind='request')
        self.assertEqual(request['request']['expected_plan_id'],self.body['expected_plan_id'])
        self.assertEqual(self.w.analysis_plan_info(self.sid)['draft']['plan']['parameters']['a06.seed'],7)

    def test_confirm_stale_override_and_corruption_never_trigger_refetch(self):
        for change in ({'confirmed':False},{'passed':True},{'path':'outside'},{'url':'https://example.com'},{'expected_input_hash':'stale'}):
            with self.subTest(change=change),self.assertRaises(ContractError):
                self.w.acquire_analysis_plan_system_disease_sources(self.sid,self.body|change)
        self.assertEqual(self.w.load(self.sid),self.before)
        self.stage_manual();self.body=self.request()
        with patch.object(science,'fetch_source',side_effect=synthetic_source):value=self.execute()
        path=verified_file(self.w.location(self.sid),value['sources'][-1]['archive']);path.write_bytes(path.read_bytes()+b'corrupt')
        with patch.object(science,'fetch_source',side_effect=AssertionError('损坏不重下掩盖')),self.assertRaises(ContractError):self.execute()

    def test_original_public_collector_dispatch_uses_only_archived_official_mesh_terms(self):
        import a02_auto_prepare as original
        def ttd(summary):return synthetic_source('TTD',summary)
        def otp(summary):return synthetic_source('OTP',summary)
        pharm=synthetic_source('PharmGKB',self.summary)[0]
        with patch.object(original,'_ttd_source',side_effect=ttd) as ttd_call,\
                patch.object(original,'_otp_source',side_effect=otp) as otp_call,\
                patch.object(original,'fetch_pharmgkb',return_value=pharm) as pharm_call:
            result=self.execute()
        self.assertEqual(result['state'],'incomplete');ttd_call.assert_called_once_with(self.summary)
        otp_call.assert_called_once_with(self.summary);pharm_call.assert_called_once_with(original._terms(self.summary))


class SystemDiseaseAcquisitionExistingTests(unittest.TestCase):
    def test_current_raw_or_normalized_five_sources_are_reused_without_network_or_state_replacement(self):
        import tempfile
        from pathlib import Path
        from tests.modulea import plan_report_fixture
        for normalized in (False,True):
            with self.subTest(normalized=normalized),tempfile.TemporaryDirectory(prefix='existing_disease_sources_') as temp:
                w,sid,_,_=plan_report_fixture.prepare(Path(temp)/'data',modern=True,stop_before_normalization=True)
                if normalized:
                    from modulea.core import system_execution
                    value=system_execution.info(w,sid);batch=w.start_analysis_plan_system_batch(sid,
                        {key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                        'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成系统标准化测试','note':'建立实际系统A02来源链','confirmed':True})
                    for module in ('A01','A02'):
                        w.execute_analysis_plan_system_stage(sid,{'batch_id':batch['batch_id'],'stage':module,
                            'expected_current_run_id':w.load(sid)['current'].get(module)})
                before=w.load(sid);value=core.info(w,sid)
                body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                    'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成旧五库复用测试','note':'当前真实来源链复用，不重新检索','confirmed':True}
                with patch.object(science,'fetch_source',side_effect=AssertionError('当前已有五库不联网')):
                    result=w.acquire_analysis_plan_system_disease_sources(sid,body)
                self.assertEqual(result['state'],'complete');self.assertTrue(all(r['mode']=='existing' for r in result['sources']))
                after=w.load(sid)
                for key in ('current','runs','reviews'):self.assertEqual(after[key],before[key])
                build_trace(w,sid)
