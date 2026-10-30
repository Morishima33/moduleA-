"""获取原件到真实科学A01的独立来源绑定；不伪造上传批准或新研究复核。"""
from copy import deepcopy
from pathlib import Path
import shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError,fingerprint
from storage import file_record,verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_acquisition as acquisition,system_component_sources as sources,system_execution
from modulea.core.trace_export import build_trace
from tests.modulea import test_system_acquisition as fixture,plan_report_fixture as mapping_fixture
from science_modules.a01 import system_source_binding as science


class SystemComponentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=tempfile.TemporaryDirectory(prefix='system_sources_mapping_');cls.addClassCleanup(cls.base.cleanup)
        cls.mapping_root=Path(cls.base.name)/'source';mapping_fixture.prepare(cls.mapping_root,modern=True)

    def setUp(self):
        self.fixture=fixture.SystemAcquisitionTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;shutil.copytree(self.mapping_root/'references',self.root/'references')
        self.w=full_workflow(self.root);self.sid=self.fixture.sid;self.before=self.w.load(self.sid)
        with patch.object(fixture.collection,'acquire_for_plan',side_effect=fixture.synthetic_source):
            self.result=self.w.acquire_analysis_plan_system_a01_sources(self.sid,self.fixture.body)
        m=self.w.load(self.sid);self.body={'request_id':'systemsourcebindreq_'+uuid4().hex,
            'expected_acquisition_request_id':self.fixture.body['request_id'],'expected_record_sha256':m[acquisition.RECORDS][-1]['sha256'],
            'expected_input_hash':fingerprint(acquisition.snapshot(self.w,m)),'author':'明确合成来源绑定测试',
            'note':'实际原ZIP/原算法接科学A01，不造旧人工批准','confirmed':True}

    def bind(self):return self.w.bind_analysis_plan_system_a01_sources(self.sid,self.body)

    def start(self):
        value=system_execution.info(self.w,self.sid)
        body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成科学批次','note':'原系统来源进入原科学算法','confirmed':True}
        return self.w.start_analysis_plan_system_batch(self.sid,body)

    def test_raw_acquisition_binding_enters_real_unreviewed_a01_without_old_staging(self):
        before=self.w.load(self.sid);binding=self.bind();m=self.w.load(self.sid)
        self.assertEqual(m['current'],before['current']);self.assertEqual(m['runs'],before['runs']);self.assertEqual(m['reviews'],[])
        self.assertNotIn('current_component_uploads',m);self.assertEqual(m[sources.CURRENT],binding['file'])
        self.assertFalse(self.w.approved(m,m['current']['A00']))
        duplicate=self.bind();self.assertFalse(duplicate['created']);self.assertEqual(duplicate['file'],binding['file'])
        batch=self.start();self.assertEqual(batch['component_source_protocol'],sources.VERSION)
        self.assertIsNone(batch['initial_binding']['staging_file']);self.assertEqual(batch['staging_file'],binding['file'])
        result=self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':'A01','expected_current_run_id':None})
        m=self.w.load(self.sid);run=self.w.run(m,result['run_id'])
        self.assertEqual(run['config']['version'],science.PUBLICATION);self.assertEqual(result['summary']['标准化基因数'],1)
        self.assertFalse(result['summary']['handoff_blocked']);self.assertTrue(self.w.active(m,result['run_id']))
        self.assertFalse(self.w.approved(m,result['run_id']));self.assertEqual(m['reviews'],[]);self.assertEqual(run['parent_review_ids'],{})
        self.assertNotIn('current_component_uploads',m)
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['system_component_sources']),1)
        for ref in trace['files']:verified_file(self.w.location(self.sid),ref)
        # 后继读取原来源不得再要求采集当时的A01指针仍是空。
        system_execution.require_batch(self.w,m,batch['file'])

    def test_parameters_hold_stale_and_unknown_fields_do_not_publish_binding(self):
        for change in ({'confirmed':False},{'passed':True},{'path':'outside'},{'expected_input_hash':'stale'},{'expected_record_sha256':'old'}):
            with self.subTest(change=change),self.assertRaises(ContractError):
                self.w.bind_analysis_plan_system_a01_sources(self.sid,self.body|change)
        m=self.w.load(self.sid);self.assertNotIn(sources.INDEX,m);self.assertNotIn(sources.CURRENT,m)
        self.w.review(self.sid,m['current']['A00'],'pending','明确合成测试','来源绑定前暂停')
        with self.assertRaises(ContractError):self.bind()
        self.assertNotIn(sources.INDEX,self.w.load(self.sid))

    def test_new_plan_does_not_silently_adopt_original_plan_binding(self):
        m=self.w.load(self.sid);draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},
            'author':'明确合成测试','note':'新门槛不能偷用旧原件'})
        with self.assertRaises(ContractError):self.bind()

    def test_derived_file_with_recomputed_digest_must_equal_actual_original_zip(self):
        value=self.bind();home=self.w.location(self.sid);m=self.w.load(self.sid)
        record=acquisition.read_record(self.w,m,value['acquisition_record'],kind='record')
        request=acquisition.read_record(self.w,m,record['request_file'],kind='request')
        modified=deepcopy(value);slot=modified['datasets'][0];ref=next(r for r in slot['files'] if r['path'].endswith('.tsv'))
        path=verified_file(home,ref);path.write_bytes(path.read_bytes().replace(b'40',b'90'))
        slot['files'][slot['files'].index(ref)]=file_record(home,path,ref['role'])
        with self.assertRaisesRegex(ContractError,'原ZIP实际重建不同'):science.validate_binding(home,modified,request,record)

    def test_production_validator_rejects_forged_counts_even_if_caller_validator_passes(self):
        self.bind();batch=self.start();before=self.w.load(self.sid)
        from modulea.core import system_execution_science
        original=system_execution_science.a01
        def forged(*args):
            result=list(original(*args));result[2]=dict(result[2],标准化基因数=999);return tuple(result)
        self.w.validators['A01']=lambda *args:None
        with patch.object(system_execution_science,'a01',side_effect=forged),self.assertRaises(ContractError):
            self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':'A01','expected_current_run_id':None})
        self.assertEqual(self.w.load(self.sid)['current'],before['current']);self.assertEqual(self.w.load(self.sid)['reviews'],[])

    def test_extra_unregistered_package_file_is_rejected(self):
        value=self.bind();home=self.w.location(self.sid);m=self.w.load(self.sid)
        record=acquisition.read_record(self.w,m,value['acquisition_record'],kind='record')
        request=acquisition.read_record(self.w,m,record['request_file'],kind='request')
        (home/value['datasets'][0]['folder']/'extra.csv').write_text('unregistered',encoding='utf8')
        with self.assertRaisesRegex(ContractError,'未登记文件'):science.validate_binding(home,value,request,record)


class SystemComponentPipelineTests(unittest.TestCase):
    def test_system_sources_flow_through_real_a02_a03_and_dual_report_keep_old_uploads(self):
        from modulea.core import system_pipeline
        from science_modules.a01 import plan_acquisition
        with tempfile.TemporaryDirectory(prefix='system_sources_pipeline_') as temp:
            root=Path(temp)/'data';w,sid,_,_=mapping_fixture.prepare(root,empty=True,modern=True,stop_before_normalization=True,
                specification={'mode':'personalized','parameters':{'a05.include_go':False,'a05.include_kegg':False}})
            before=w.load(sid);info=acquisition.info(w,sid)
            body={key:info[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                'request_id':'systemacqreq_'+uuid4().hex,'author':'明确合成原件全链测试','note':'已有三库只核验复用','confirmed':True}
            with patch.object(plan_acquisition,'acquire_for_plan',side_effect=AssertionError('已有三库不可联网')):
                w.acquire_analysis_plan_system_a01_sources(sid,body)
            m=w.load(sid);binding=w.bind_analysis_plan_system_a01_sources(sid,{'request_id':'systemsourcebindreq_'+uuid4().hex,
                'expected_acquisition_request_id':body['request_id'],'expected_record_sha256':m[acquisition.RECORDS][-1]['sha256'],
                'expected_input_hash':fingerprint(acquisition.snapshot(w,m)),'author':'明确合成原件全链测试','note':'独立系统来源科学接续','confirmed':True})
            info=system_execution.info(w,sid);batch=w.start_analysis_plan_system_batch(sid,
                {key:info[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成原件全链测试','note':'空交集实际报告闭环','confirmed':True})
            result=w.execute_analysis_plan_system_pipeline(sid,{'batch_id':batch['batch_id']})
            self.assertEqual(result['state'],'awaiting_report_review');after=w.load(sid)
            self.assertEqual(w.run(after,after['current']['A01'])['config']['version'],science.PUBLICATION)
            self.assertEqual(after['reviews'],before['reviews']);self.assertEqual(after['current_component_uploads'],before['current_component_uploads'])
            self.assertEqual(len(w.result(after,after['current']['A07'])['tables']['report_files']),2)
            self.assertEqual(w.result(after,after['current']['A03'])['summary']['交集靶点数'],0)
            current=dict(after['current']);runs=deepcopy(after['runs'])
            with patch.object(w,'execute_analysis_plan_system_stage',side_effect=AssertionError('重复续做不得重算')):
                w.execute_analysis_plan_system_pipeline(sid,{'batch_id':batch['batch_id']})
            self.assertEqual(w.load(sid)['current'],current);self.assertEqual(w.load(sid)['runs'],runs)
            build_trace(w,sid,include_data=True)
