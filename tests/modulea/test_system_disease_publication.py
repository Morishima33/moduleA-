"""完整疾病原件的真实候选、第三版标准化及旧协议兼容；仅合成研究。"""
from copy import deepcopy
from pathlib import Path
from threading import Event
import hashlib,shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError,fingerprint
from storage import verified_file
from modulea.core.kernel import full_workflow
from modulea.core import system_disease_acquisition as acquisition,system_disease_publication as publication,system_execution,system_disease_sources
from modulea.core.trace_export import build_trace
from science_modules.a02 import system_collection as science
from tests.modulea import test_system_disease_acquisition as fixture,test_system_acquisition as a01_fixture,plan_report_fixture as mapping_fixture


class SystemDiseasePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=fixture.SystemDiseaseAcquisitionTests();cls.seed.setUp();cls.addClassCleanup(cls.seed.doCleanups)
        cls.seed.stage_manual();cls.seed.body=cls.seed.request()
        with patch.object(fixture.science,'fetch_source',side_effect=fixture.synthetic_source):cls.seed.execute()
        cls.sid=cls.seed.sid;cls.acquisition_id=cls.seed.body['request_id']

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='disease_publication_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.seed.root,self.root)
        self.w=full_workflow(self.root);self.before=self.w.load(self.sid);self.body=self.request()

    def request(self):
        value=publication.info(self.w,self.w.load(self.sid),self.acquisition_id)
        return value['request']|{'request_id':'diseasepublishreq_'+uuid4().hex,'author':'明确合成疾病发布测试',
            'note':'完整原件整理为候选，不是人工批准或正式疾病集合','confirmed':True}

    def publish(self):return self.w.publish_analysis_plan_system_disease_candidates(self.sid,self.body)

    def test_complete_unreviewed_sources_publish_real_candidate_idempotently_without_legacy_approval(self):
        home=self.w.location(self.sid);files={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in home.rglob('*') if p.is_file() and p.name!='manifest.json'}
        result=self.publish();m=self.w.load(self.sid);run=self.w.run(m,result['run_id'])
        self.assertEqual(run['config'],science.configuration());self.assertEqual(run['parent_review_ids'],{})
        self.assertEqual(result['summary']['候选记录数'],5);self.assertTrue(result['summary']['handoff_blocked'])
        self.assertTrue(self.w.active(m,result['run_id']));self.assertFalse(self.w.approved(m,result['run_id']))
        self.assertFalse(self.w.approved(m,m['current']['A00']));self.assertEqual(m['reviews'],[])
        self.assertEqual(self.publish(),result);self.assertEqual(len(self.w.load(self.sid)['runs']),2)
        self.assertEqual(m.get('current_source_staging'),self.before.get('current_source_staging'))
        for name,digest in files.items():self.assertEqual(hashlib.sha256((home/name).read_bytes()).hexdigest(),digest)
        for ref in build_trace(self.w,self.sid,include_data=True)['files']:verified_file(home,ref)

    def test_unknown_fields_stale_hash_unconfirmed_and_wrong_record_never_publish(self):
        for change in ({'confirmed':False},{'passed':True},{'datasets':[]},{'expected_input_hash':'stale'},{'expected_record_sha256':'wrong'}):
            with self.subTest(change=change),self.assertRaises(ContractError):
                self.w.publish_analysis_plan_system_disease_candidates(self.sid,self.body|change)
        self.assertEqual(self.w.load(self.sid),self.before)

    def test_missing_manual_sources_remain_missing_and_cannot_publish(self):
        other=fixture.SystemDiseaseAcquisitionTests();other.setUp();self.addCleanup(other.doCleanups)
        with patch.object(fixture.science,'fetch_source',side_effect=fixture.synthetic_source):other.execute()
        value=publication.info(other.w,other.w.load(other.sid),other.body['request_id'])
        body=self.body|value['request'];self.assertFalse(value['enabled'])
        before=other.w.load(other.sid)
        with self.assertRaises(ContractError):other.w.publish_analysis_plan_system_disease_candidates(other.sid,body)
        self.assertEqual(other.w.load(other.sid),before)

    def test_human_pause_before_or_during_organize_prevents_publication(self):
        original=science.facts
        def paused(*args):
            value=original(*args);self.w.review(self.sid,self.before['current']['A00'],'pending','明确合成测试','整理中暂停');return value
        with patch.object(science,'facts',side_effect=paused),self.assertRaises(ContractError):self.publish()
        self.assertEqual(self.w.load(self.sid)['current'],self.before['current'])
        with self.assertRaises(ContractError):self.publish()

    def test_damaged_original_cannot_publish_or_be_masked_by_success_record(self):
        ref=acquisition.read_record(self.w,self.before,self.before[acquisition.RECORDS][-1],kind='record')['sources'][0]['archive']
        verified_file(self.w.location(self.sid),ref).write_bytes(b'corrupt')
        with self.assertRaises(ContractError):self.publish()
        self.assertEqual(self.w.load(self.sid),self.before)

    def test_new_plan_requires_new_acquisition_confirmation_before_publish(self):
        draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},
            'author':'明确合成测试','note':'新方案不能偷用旧获取确认'})
        before=self.w.load(self.sid)
        with self.assertRaises(ContractError):self.publish()
        self.assertEqual(self.w.load(self.sid),before)

    def test_canonical_production_validator_rejects_forged_candidate_even_if_caller_validator_passes(self):
        original=science.facts;calls=[]
        def forged(*args):
            value=deepcopy(original(*args));calls.append(True)
            if len(calls)==1:value[0]['候选记录数']=999
            return value
        self.w.validators['A02']=lambda *args:None
        with patch.object(science,'facts',side_effect=forged),self.assertRaises(ContractError):self.publish()
        self.assertGreaterEqual(len(calls),2);self.assertEqual(self.w.load(self.sid)['current'],self.before['current'])

    def fresh_disease_sources(self,*,empty=False,symbol='A'):
        """为不同数据场景新建研究，不修改或覆盖已归档成功公共来源。"""
        from intake_sources import stage
        fresh=fixture.SystemDiseaseAcquisitionTests();fresh.setUp();self.addCleanup(fresh.doCleanups)
        self.w=fresh.w;self.root=fresh.root;self.sid=fresh.sid;self.before=self.w.load(self.sid)
        intake=self.w.result(self.before,self.before['current']['A00'])['summary']
        def source(db,summary):
            item,detail=fixture.synthetic_source(db,summary,empty=empty);item['data']=item['data'].replace(b'A\t',(symbol+'\t').encode());return item,detail
        for db in ('GeneCards','OMIM'):stage(self.w,self.sid,self.before['current']['A00'],source(db,intake)[0])
        request=fresh.request()
        with patch.object(fixture.science,'fetch_source',side_effect=source):
            self.w.acquire_analysis_plan_system_disease_sources(self.sid,request)
        self.acquisition_id=request['request_id'];self.body=self.request()

    def test_valid_zero_sources_form_empty_candidate_with_handoff_blocked(self):
        self.fresh_disease_sources(empty=True);result=self.publish()
        self.assertEqual(result['outcome'],'empty');self.assertEqual(result['summary']['候选记录数'],0)
        self.assertEqual(result['summary']['已有来源库数'],5);self.assertTrue(result['summary']['handoff_blocked'])

    def prepare_a01(self):
        """仅复制合成共享身份表，目标研究三库经真实获取/绑定，不移植复核。"""
        from modulea.core import system_acquisition as component_acquisition,system_component_sources
        mapping_root=Path(self.temp.name)/'mapping_seed';mapping_fixture.prepare(mapping_root,modern=True)
        shutil.copytree(mapping_root/'references',self.root/'references')
        value=component_acquisition.info(self.w,self.sid)
        body={k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systemacqreq_'+uuid4().hex,'author':'明确合成三库','note':'不批准研究的真实三库技术链','confirmed':True}
        with patch.object(a01_fixture.collection,'acquire_for_plan',side_effect=a01_fixture.synthetic_source):
            self.w.acquire_analysis_plan_system_a01_sources(self.sid,body)
        m=self.w.load(self.sid);self.w.bind_analysis_plan_system_a01_sources(self.sid,{
            'request_id':'systemsourcebindreq_'+uuid4().hex,'expected_acquisition_request_id':body['request_id'],
            'expected_record_sha256':m[component_acquisition.RECORDS][-1]['sha256'],
            'expected_input_hash':fingerprint(component_acquisition.snapshot(self.w,m)),
            'author':'明确合成三库绑定','note':'原件进入真实科学输入，不签复核','confirmed':True})

    def start_batch(self):
        value=system_execution.info(self.w,self.sid)
        return self.w.start_analysis_plan_system_batch(self.sid,{k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成新五库科学批次','note':'实际原件进入规范验证而非人工批准','confirmed':True})

    def test_new_collection_enters_real_a01_a02_a03_and_new_batch_reuses_originals_without_fake_review(self):
        raw=self.publish();self.prepare_a01();batch=self.start_batch()
        self.assertEqual(batch['disease_source_protocol'],'A02.system_source_reuse.2')
        for iteration in range(2):
            for stage in ('A01','A02','A03'):
                self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':stage,
                    'expected_current_run_id':self.w.load(self.sid)['current'].get(stage)})
            m=self.w.load(self.sid);a02=self.w.result(m,m['current']['A02']);run=self.w.run(m,m['current']['A02'])
            self.assertEqual(run['config']['version'],'A02.system_normalization.3');self.assertEqual(a02['summary']['标准化基因数'],1)
            self.assertEqual(self.w.result(m,m['current']['A03'])['summary']['交集靶点数'],1)
            self.assertEqual(system_disease_sources.resolve(self.w,m)['base_run_id'],raw['run_id'])
            self.assertEqual(m['reviews'],[]);self.assertFalse(self.w.approved(m,m['current']['A02']))
            if not iteration:batch=self.start_batch()
        for ref in build_trace(self.w,self.sid,include_data=True)['files']:verified_file(self.w.location(self.sid),ref)
        current=self.w.load(self.sid);self.assertEqual(self.publish(),raw);self.assertEqual(self.w.load(self.sid),current)
        self.w.review(self.sid,current['current']['A00'],'pending','明确合成测试','科学批次结束后暂停登记')
        with self.assertRaises(ContractError):self.publish()

    def test_personalized_a02_finishes_while_a01_is_still_waiting_for_originals(self):
        from modulea.tasks.a00_followup import execute

        raw = self.publish()
        mapping_root = Path(self.temp.name)/'mapping'
        mapping_fixture.prepare(mapping_root, modern=True)
        shutil.copytree(mapping_root/'references', self.root/'references')
        a00 = self.w.load(self.sid)['current']['A00']
        draft = self.w._analysis_plan_records(self.w.load(self.sid))[-1]
        plan = self.w.save_analysis_plan_draft(self.sid, {
            'request_id':'planreq_'+uuid4().hex, 'expected_a00':a00, 'expected_draft_id':draft['plan_id'],
            'specification':{'mode':'personalized'}, 'author':'隔离复核', 'note':'并行计算验证'})['draft']
        review = self.w.review(self.sid, a00, 'approved', '隔离复核', '接续两条原件链')
        approval = {'run_id':a00, 'review_id':review['review_id'], 'plan_id':plan['plan_id']}
        published = Event()
        a01_waited = Event()
        workflow_class = type(self.w)
        original = workflow_class.execute_analysis_plan_system_stage

        def calculator(workflow, sid, request, **kwargs):
            result = original(workflow, sid, request, **kwargs)
            if request['stage'] == 'A02':
                self.assertNotIn('A01', workflow.load(sid)['current'])
                published.set()
            return result

        def formula(*args, **kwargs):
            a01_waited.set()
            if not published.wait(15):
                raise AssertionError('方剂等待期间应完成疾病标准化')
            return a01_fixture.synthetic_source(*args, **kwargs)

        with (patch.object(a01_fixture.collection,'acquire_for_plan', side_effect=formula),
              patch.object(workflow_class, 'execute_analysis_plan_system_stage', autospec=True, side_effect=calculator)):
            execute(self.w, self.sid, approval, progress=lambda _:None, new_workflow=lambda:full_workflow(self.root))
        self.assertTrue(a01_waited.is_set())
        manifest = self.w.load(self.sid)
        normalized = self.w.run(manifest, manifest['current']['A02'])
        self.assertEqual(normalized['config']['version'], 'A02.system_normalization.6')
        self.assertEqual(normalized['parent_runs'], {'A00':a00})
        self.assertEqual(system_disease_sources.resolve(self.w, manifest)['base_run_id'], raw['run_id'])
        self.assertEqual(len(manifest['reviews']), 1)
        self.assertEqual(self.w.result(manifest, normalized['run_id'])['summary']['标准化基因数'], 1)
        with patch.object(workflow_class, 'execute_analysis_plan_system_stage', side_effect=AssertionError('已完成不重算')):
            execute(self.w, self.sid, approval, progress=lambda _:None, new_workflow=lambda:full_workflow(self.root))

    def test_personalized_a01_publishes_despite_missing_disease_originals(self):
        from modulea.tasks.a00_followup import execute

        raw = fixture.SystemDiseaseAcquisitionTests()
        raw.setUp()
        self.addCleanup(raw.doCleanups)
        self.w, self.root, self.sid = raw.w, raw.root, raw.sid
        a00 = self.w.load(self.sid)['current']['A00']
        draft = self.w._analysis_plan_records(self.w.load(self.sid))[-1]
        plan = self.w.save_analysis_plan_draft(self.sid, {
            'request_id':'planreq_'+uuid4().hex, 'expected_a00':a00, 'expected_draft_id':draft['plan_id'],
            'specification':{'mode':'personalized'}, 'author':'隔离复核', 'note':'疾病侧缺资料'})['draft']
        self.prepare_a01()
        review = self.w.review(self.sid, a00, 'approved', '隔离复核', '验证缺原件只卡对应支路')
        approval = {'run_id':a00, 'review_id':review['review_id'], 'plan_id':plan['plan_id']}
        with self.assertRaisesRegex(ContractError, 'A01 已归档.*A02.*GeneCards.*OMIM'):
            execute(self.w, self.sid, approval, progress=lambda _:None, new_workflow=lambda:full_workflow(self.root))
        manifest = self.w.load(self.sid)
        self.assertNotIn('A02', manifest['current'])
        self.assertTrue(self.w.result(manifest, manifest['current']['A01']))
        self.assertEqual(len(manifest['reviews']), 1)

    def test_new_collection_full_empty_pipeline_preserves_zero_and_generates_two_real_reports(self):
        from modulea.core import system_pipeline
        from science_modules.a04 import plan_flow as network
        from science_modules.a06 import plan_preparation_v2 as preparation
        self.fresh_disease_sources(symbol='B');self.publish();self.prepare_a01();batch=self.start_batch()
        with patch.object(network,'request',side_effect=AssertionError('空交集不请求STRING')),patch.object(preparation,'connect',side_effect=AssertionError('空交集不连接结构')):
            result=self.w.execute_analysis_plan_system_pipeline(self.sid,{'batch_id':batch['batch_id']})
        m=self.w.load(self.sid);self.assertEqual(result['state'],'awaiting_report_review');self.assertEqual(m['reviews'],[])
        report=self.w.result(m,result['report_run_id']);self.assertEqual(len(report['tables']['report_files']),2)
        self.assertEqual(self.w.result(m,m['current']['A03'])['summary']['交集靶点数'],0)
        history=system_pipeline.info(self.w,self.sid)['batches'][0]['history']
        self.assertEqual(len([r for r in history if r['event']=='stage' and r['state']=='not_applicable']),8)
        self.assertFalse(self.w.approved(m,result['report_run_id']))

    def test_existing_explicit_scope_decisions_survive_new_candidate_publication(self):
        from disease import run_disease
        from storage import read_json
        self.root=Path(self.temp.name)/'scope_seed';self.w,self.sid,_,_=mapping_fixture.prepare(self.root,modern=True,stop_before_normalization=True)
        m=self.w.load(self.sid);old=m['current']['A02'];rows=self.w.result(m,old)['tables']['scope_groups']
        run_disease(self.w,self.sid,m['current']['A00'],old,[],'明确合成范围保留',scope_change=[{
            'scope_id':row['scope_id'],'scope':'outside','reviewer':'明确合成范围测试','note':'用于验证已有决定不被自动改为direct'} for row in rows])
        value=acquisition.info(self.w,self.sid);body={k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成范围测试','note':'复用当前来源及已存范围，不修改决定','confirmed':True}
        with patch.object(fixture.science,'fetch_source',side_effect=AssertionError('当前完整原件不下载')):
            self.w.acquire_analysis_plan_system_disease_sources(self.sid,body)
        before=self.w.load(self.sid);prior=self.w.result(before,before['current']['A02'])
        manifest=read_json(verified_file(self.w.location(self.sid),next(r for r in prior['sources'] if r['role']=='source_manifest')))
        self.acquisition_id=body['request_id'];self.body=self.request();result=self.publish()
        source=read_json(verified_file(self.w.location(self.sid),next(r for r in result['sources'] if r['role']=='source_manifest')))
        self.assertEqual(source['scope_decisions'],manifest['scope_decisions'])
        self.assertTrue(all(row['scope']=='outside' for row in result['tables']['scope_groups']))
        self.assertEqual(self.w.load(self.sid)['reviews'],before['reviews'])

    def test_third_normalization_canonical_validator_blocks_forged_count_with_fake_caller_validator(self):
        from modulea.core import system_execution_science
        self.publish();self.prepare_a01();batch=self.start_batch()
        self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':'A01','expected_current_run_id':None})
        before=self.w.load(self.sid);original=system_execution_science.a02
        def forged(*args):
            value=list(original(*args));value[2]=dict(value[2],标准化基因数=999);return tuple(value)
        self.w.validators['A02']=lambda *args:None
        with patch.object(system_execution_science,'a02',side_effect=forged),self.assertRaises(ContractError):
            self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':'A02',
                'expected_current_run_id':before['current']['A02']})
        self.assertEqual(self.w.load(self.sid)['current'],before['current'])
        self.assertEqual(self.w.load(self.sid)['reviews'],[])

    def test_new_candidate_originals_are_read_back_by_acquisition_without_fetch_or_replacing_science(self):
        self.publish();before=self.w.load(self.sid);value=acquisition.info(self.w,self.sid)
        body={k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成新候选来源回读','note':'复用新候选原件，不生成替代运行','confirmed':True}
        with patch.object(fixture.science,'fetch_source',side_effect=AssertionError('新候选完整原件不再下载')):
            result=self.w.acquire_analysis_plan_system_disease_sources(self.sid,body)
        self.assertEqual(result['state'],'complete');self.assertTrue(all(r['mode']=='existing' for r in result['sources']))
        after=self.w.load(self.sid)
        for key in ('current','runs','reviews'):self.assertEqual(after[key],before[key])
