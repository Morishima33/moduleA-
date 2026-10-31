"""逐对象准备的中断、已完成复用、损坏阻断与新旧资格兼容；仅合成研究。"""
from pathlib import Path
from copy import deepcopy
import os,shutil,tempfile,unittest
from unittest.mock import patch
from contracts import ContractError
from storage import read_json,verified_file
from modulea.core.kernel import full_workflow
from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core import system_preparation_checkpoints as cp,system_decisions
from modulea.core.trace_export import build_trace
from science_modules.a06 import plan_preparation_v2 as legacy,system_preparation_incremental as science
from tests.modulea import test_system_decisions as upstream
from tests.modulea.plan_report_nonempty_fixture import unavailable_sources


class SystemPreparationIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(AnalysisPlanWorkflow,'start_analysis_plan_system_batch',AnalysisPlanWorkflow.start_analysis_plan_recoverable_system_batch):
            upstream.SystemDecisionTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base)
        for stage in ('A04_SELECTION','A06_INPUT'):
            w.execute_analysis_plan_system_decision(cls.sid,{'batch_id':cls.batch_id,'stage':stage,'expected_decision_id':None})
        cls.tools=Path(os.environ.get('MODULEA_A06_TOOLS','D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='preparation_objects_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root)
        self.before=self.w.load(self.sid);self.body={'batch_id':self.batch_id,'stage':'A06_PREP','expected_current_run_id':None}

    def execute(self,**kwargs):return self.w.execute_analysis_plan_system_stage(self.sid,self.body,tools=kwargs.pop('tools',self.tools),**kwargs)

    def fixed(self):return system_decisions.current(self.w,self.w.load(self.sid),self.batch_id,'A06_INPUT')[1]['payload']

    def test_full_na_objects_publish_second_version_then_real_qualification_without_fake_reviews(self):
        with patch.object(legacy,'connect',side_effect=unavailable_sources):result=self.execute()
        m=self.w.load(self.sid);run=self.w.run(m,result['run_id'])
        self.assertEqual(run['config']['version'],science.VERSION);self.assertEqual(result['summary']['na_pairs'],2)
        self.assertEqual(len(m[cp.SESSIONS]),1);self.assertEqual(len(m[cp.OBJECTS]),6);self.assertEqual(len(m[cp.PACKETS]),1)
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertEqual(run['parent_review_ids'],{})
        self.assertTrue(self.w.active(m,result['run_id']));self.assertFalse(self.w.approved(m,result['run_id']))
        qualified=self.w.qualify_analysis_plan_system_preparation(self.sid,{'batch_id':self.batch_id,'expected_preparation_run_id':result['run_id']})
        m=self.w.load(self.sid);self.assertEqual(self.w.run(m,qualified['run_id'])['config']['version'],'A06.system_qualification.2')
        self.assertEqual(qualified['summary']['ready_pairs'],0);self.assertEqual(m['reviews'],self.before['reviews'])
        for ref in build_trace(self.w,self.sid,include_data=True)['files']:verified_file(self.w.location(self.sid),ref)

    def test_interruption_after_first_completed_object_resumes_missing_objects_and_keeps_first_files(self):
        seen=[]
        def progress(message):
            if message.startswith('已保存准备对象：'):
                seen.append(message)
                if len(seen)==1:raise KeyboardInterrupt('明确合成准备中断，不生成完整包')
        with patch.object(legacy,'connect',side_effect=unavailable_sources),self.assertRaises(KeyboardInterrupt):self.execute(progress=progress)
        m=self.w.load(self.sid);self.assertEqual(len(m[cp.OBJECTS]),2);self.assertNotIn(cp.PACKETS,m)
        first=[read_json(verified_file(self.w.location(self.sid),ref)) for ref in m[cp.OBJECTS]]
        # 来源不可用属于未成功连接，可重试；已完成成功来源的复用在后续真实配体用例核查。
        with patch.object(legacy,'connect',side_effect=unavailable_sources):result=self.execute()
        self.assertEqual(result['summary']['pair_count'],2)
        for ref,value in zip(m[cp.OBJECTS],first):self.assertEqual(read_json(verified_file(self.w.location(self.sid),ref)),value)
        self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])

    def test_complete_packet_after_failed_canonical_publish_reuses_all_objects_without_connect_or_prepare(self):
        with patch.object(legacy,'connect',side_effect=unavailable_sources),patch.object(science.original,'validate_evidence',side_effect=ContractError('明确合成规范核查失败')):
            with self.assertRaises(ContractError):self.execute()
        m=self.w.load(self.sid);self.assertEqual(len(m[cp.PACKETS]),1);self.assertNotIn('A06_PREP',m['current'])
        with patch.object(legacy,'connect',side_effect=AssertionError('完整包恢复不能下载')),patch.object(legacy,'prepare',side_effect=AssertionError('完整包恢复不能重做准备')):
            result=self.execute()
        self.assertEqual(result['summary']['na_pairs'],2);self.assertEqual(len(self.w.load(self.sid)[cp.OBJECTS]),len(m[cp.OBJECTS]))

    def test_damaged_checkpoint_evidence_blocks_resume_instead_of_redownloading(self):
        def progress(message):
            if message.startswith('已保存准备对象：'):raise KeyboardInterrupt('明确合成中断')
        with patch.object(legacy,'connect',side_effect=unavailable_sources),self.assertRaises(KeyboardInterrupt):self.execute(progress=progress)
        m=self.w.load(self.sid);value=cp.read_object(self.w,m,m[cp.OBJECTS][0]);ref=value['payload']['files'][0]
        verified_file(self.w.location(self.sid),ref).write_bytes(b'damaged')
        with patch.object(legacy,'connect',side_effect=AssertionError('损坏不能重下掩盖')),self.assertRaises(ContractError):self.execute()
        self.assertNotIn('A06_PREP',self.w.load(self.sid)['current'])

    def test_human_hold_after_saved_object_stops_resume_without_new_object_or_scientific_run(self):
        def progress(message):
            if message.startswith('已保存准备对象：'):raise KeyboardInterrupt('明确合成中断')
        with patch.object(legacy,'connect',side_effect=unavailable_sources),self.assertRaises(KeyboardInterrupt):self.execute(progress=progress)
        m=self.w.load(self.sid);self.w.review(self.sid,m['current']['A04'],'pending','明确合成测试','恢复前暂停')
        before=self.w.load(self.sid)
        with patch.object(legacy,'connect',side_effect=AssertionError('暂停不能继续连接')),self.assertRaises(ContractError):self.execute()
        self.assertEqual(len(self.w.load(self.sid)[cp.OBJECTS]),len(before[cp.OBJECTS]));self.assertEqual(self.w.load(self.sid)['current'],before['current'])

    def test_real_ready_ligand_is_not_downloaded_or_prepared_twice_after_interruption(self):
        from tests.modulea.preparation_object_fixture import ObjectSources
        source=ObjectSources(self.fixed());calls=[];original_prepare=legacy.prepare_compounds
        def count(*args,**kwargs):
            calls.extend(row['compound_id'] for row in args[2]['compounds']);return original_prepare(*args,**kwargs)
        def stop(message):
            if message.startswith('已保存准备对象：'):raise KeyboardInterrupt('真实配体已保存后中断')
        with patch.object(legacy,'connect',side_effect=source.connect),patch.object(legacy,'attempt',side_effect=source.attempt),patch.object(legacy,'prepare_compounds',side_effect=count):
            with self.assertRaises(KeyboardInterrupt):self.execute(progress=stop)
            m=self.w.load(self.sid);saved=cp.read_object(self.w,m,m[cp.OBJECTS][-1]);self.assertEqual(saved['payload']['state'],'ready')
            result=self.execute()
        cid=self.fixed()['compounds'][0]['compound_id'];self.assertEqual(source.calls.count(('compound',cid)),1);self.assertEqual(calls.count(cid),1)
        self.assertEqual(result['summary']['scored_pairs'],0);self.assertEqual(result['summary']['na_pairs'],2)
        self.assertEqual(cp.read_object(self.w,self.w.load(self.sid),m[cp.OBJECTS][-1]),saved)

    def test_new_qualification_and_real_vina_scoring_keep_na_and_original_recovery_records(self):
        from tests.modulea.preparation_object_fixture import ObjectSources
        source=ObjectSources(self.fixed())
        with patch.object(legacy,'connect',side_effect=source.connect),patch.object(legacy,'attempt',side_effect=source.attempt):raw=self.execute()
        qualified=self.w.qualify_analysis_plan_system_preparation(self.sid,{'batch_id':self.batch_id,'expected_preparation_run_id':raw['run_id']})
        self.assertEqual(qualified['summary']['ready_pairs'],1);self.assertEqual(qualified['summary']['exploratory_receptors'],1)
        result=self.w.score_analysis_plan_system_preparation(self.sid,{'batch_id':self.batch_id,'expected_preparation_run_id':qualified['run_id'],
            'expected_scoring_run_id':None},tools=self.tools)
        m=self.w.load(self.sid);self.assertEqual(self.w.run(m,result['run_id'])['config']['version'],'A06.system_scoring.2')
        self.assertEqual(result['summary']['scored_pairs'],1);self.assertEqual(result['summary']['na_pairs'],1)
        self.assertEqual(m['reviews'],self.before['reviews'])
        for ref in build_trace(self.w,self.sid,include_data=True)['files']:verified_file(self.w.location(self.sid),ref)

    def test_changed_actual_tool_bytes_block_resume_without_fetching(self):
        def stop(message):
            if message.startswith('已保存准备对象：'):raise KeyboardInterrupt('准备中断')
        with patch.object(legacy,'connect',side_effect=unavailable_sources),self.assertRaises(KeyboardInterrupt):self.execute(progress=stop)
        tools=Path(self.temp.name)/'changed_tools';path=tools/'environments/vina_1.2.7/vina_1.2.7_win.exe';path.parent.mkdir(parents=True)
        original=self.tools/'environments/vina_1.2.7/vina_1.2.7_win.exe';path.write_bytes(original.read_bytes()+b'\nexplicit-test-changed-bytes')
        with patch.object(legacy,'connect',side_effect=AssertionError('工具改变不重下')),self.assertRaisesRegex(ContractError,'工具或科学实现已改变'):
            self.execute(tools=tools)

    def test_canonical_validator_rejects_forged_preparation_counts_with_fake_caller_validator(self):
        actual=science.compute
        def forged(*args):
            values=list(actual(*args));values[2]=dict(values[2],scored_pairs=1);return tuple(values)
        self.w.validators['A06_PREP']=lambda *args:None
        with patch.object(legacy,'connect',side_effect=unavailable_sources),patch.object(science,'compute',side_effect=forged),self.assertRaises(ContractError):self.execute()
        self.assertNotIn('A06_PREP',self.w.load(self.sid)['current']);self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])

    def test_saved_receptor_attempt_is_reused_when_process_interrupts_before_object_summary(self):
        from tests.modulea.preparation_object_fixture import ObjectSources
        source=ObjectSources(self.fixed())
        def stop(message):
            if message.startswith('已保存受体候选尝试：'):raise KeyboardInterrupt('候选实际证据已存，受体汇总未写')
        with patch.object(legacy,'connect',side_effect=source.connect),patch.object(legacy,'attempt',side_effect=source.attempt):
            with self.assertRaises(KeyboardInterrupt):self.execute(progress=stop)
            before=self.w.load(self.sid);attempts=[ref for ref in before[cp.OBJECTS] if read_json(verified_file(self.w.location(self.sid),ref))['stage']=='attempt']
            self.assertEqual(len(attempts),1);self.assertNotIn(cp.PACKETS,before)
            self.execute()
        self.assertEqual(len(source.attempts),1)
        self.assertEqual(cp.read_object(self.w,self.w.load(self.sid),attempts[0])['payload']['evidence']['structure_id'],'1ABC')

    def test_later_draft_during_object_connection_keeps_original_batch_seed(self):
        from uuid import uuid4
        changed=[]
        def connect(home,packet,folder,progress):
            if not changed:
                draft=self.w.analysis_plan_info(self.sid)['draft']
                self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],
                    'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
                    'author':'明确合成逐对象测试','note':'后存草稿不替换已授权旧批参数'});changed.append(True)
            return unavailable_sources(home,packet,folder,progress)
        with patch.object(legacy,'connect',side_effect=connect):result=self.execute()
        run=self.w.run(self.w.load(self.sid),result['run_id']);self.assertEqual(run['config']['vina_parameters']['seed'],1)
        self.assertEqual(self.w.analysis_plan_info(self.sid)['draft']['plan']['parameters']['a06.seed'],7)
