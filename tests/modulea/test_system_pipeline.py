"""统一系统编排的空交集、完整NA与中断恢复；使用同研究真实科学发布与明确合成来源。"""
from pathlib import Path
from copy import deepcopy
import shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import verified_file,read_json
from modulea.core.kernel import full_workflow
from modulea.core import system_execution,system_pipeline
from modulea.core.trace_export import build_trace
from tests.modulea import plan_report_fixture as fixture
from tests.modulea.plan_report_nonempty_fixture import string_response,unavailable_sources
from science_modules.a04 import plan_flow as network
from science_modules.a06 import plan_preparation_v2 as preparation


class SystemPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=tempfile.TemporaryDirectory(prefix='pipeline_seed_');cls.addClassCleanup(cls.seed.cleanup);cls.cases={}
        for empty in (True,False):
            root=Path(cls.seed.name)/str(empty)
            w,sid,_,_=fixture.prepare(root,empty=empty,modern=True,multiple_targets=not empty,stop_before_normalization=True,
                specification={'mode':'personalized','parameters':{'a05.include_go':False,'a05.include_kegg':False}})
            info=system_execution.info(w,sid)
            batch=w.start_analysis_plan_system_batch(sid,{k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|
                {'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成编排测试','note':'合成资料技术闭环，不构成正式科研批准','confirmed':True})
            cls.cases[empty]=(root,sid,batch['batch_id'])

    def prepare(self,empty):
        self.temp=tempfile.TemporaryDirectory(prefix='pipeline_case_');self.addCleanup(self.temp.cleanup)
        root,sid,batch=self.cases[empty];self.root=Path(self.temp.name)/'data';shutil.copytree(root,self.root)
        self.w=full_workflow(self.root);self.sid=sid;self.body={'batch_id':batch};self.before=self.w.load(sid)
        self.tools=Path('D:/codex-重大专项/moduleA/environment/a06_runtime_v1')

    def execute(self):return self.w.execute_analysis_plan_system_pipeline(self.sid,self.body,tools=self.tools)

    def test_a00_followup_stops_at_a02_and_reuses_both_results(self):
        from modulea.tasks.a00_followup import execute
        self.prepare(True)
        m=self.w.load(self.sid);m['current'].pop('A01');m.pop(system_execution.BATCHES);self.w.save(m)
        rid=m['current']['A00']
        review=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        draft=self.w._analysis_plan_records(m)[-1]
        request={'run_id':rid,'review_id':review['review_id'],'plan_id':draft['plan_id']}
        progress=[]
        execute(self.w,self.sid,request,progress=progress.append)
        actual=self.w.load(self.sid)
        self.assertEqual(set(actual['current']),{'A00','A01','A02'})
        self.assertEqual(actual['reviews'],m['reviews'])
        self.assertEqual(progress,['计算 A01','计算 A02'])
        with patch.object(self.w,'execute_analysis_plan_system_stage',side_effect=AssertionError('不能重跑已完成结果')):
            execute(self.w,self.sid,request,progress=progress.append)
        self.assertEqual(self.w.load(self.sid),actual)
        self.w.review(self.sid,rid,'pending','隔离复核','改为暂存',review['review_id'])
        with self.assertRaisesRegex(ContractError,'A00 复核已改变'):
            execute(self.w,self.sid,request,progress=progress.append)

    def test_empty_pipeline_generates_real_report_without_any_inapplicable_science_then_repeat_keeps_versions(self):
        self.prepare(True)
        with patch.object(network,'request',side_effect=AssertionError('空集不请求PPI')),patch.object(preparation,'connect',side_effect=AssertionError('空集不连接结构')):
            result=self.execute()
        self.assertEqual(result['state'],'awaiting_report_review');m=self.w.load(self.sid)
        self.assertEqual(set(m['current']),{'A00','A01','A02','A03','A07'});self.assertEqual(m['reviews'],self.before['reviews'])
        history=system_pipeline.info(self.w,self.sid)['batches'][0]['history']
        skipped=[r for r in history if r['event']=='stage' and r['state']=='not_applicable'];self.assertEqual(len(skipped),8)
        self.assertTrue(all(r['run_id'] is None for r in skipped));report=self.w.result(m,result['report_run_id'])
        self.assertEqual(len(report['tables']['report_files']),2);self.assertFalse(self.w.approved(m,result['report_run_id']))
        current=dict(m['current']);runs=dict(m['runs'])
        with (patch.object(self.w,'execute_analysis_plan_system_stage',side_effect=AssertionError('续做不得重跑阶段')),
            patch.object(self.w,'publish_analysis_plan_report',side_effect=AssertionError('有效双报告不重复生成'))):
            again=self.execute()
        self.assertEqual(again['report_run_id'],result['report_run_id']);self.assertEqual(self.w.load(self.sid)['current'],current)
        self.assertEqual(self.w.load(self.sid)['runs'],runs);trace=build_trace(self.w,self.sid)
        self.assertTrue(trace['plan_decisions']['system_pipeline']);self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])

    def test_full_na_pipeline_keeps_fixed_objects_and_skips_disabled_r_and_vina(self):
        self.prepare(False)
        from science_modules.a05 import plan_flow
        from science_modules.a06 import system_scoring
        with (patch.object(network,'request',side_effect=string_response),patch.object(preparation,'connect',side_effect=unavailable_sources),
            patch.object(plan_flow,'r_call',side_effect=AssertionError('未纳入富集不运行R')),
            patch.object(system_scoring,'execute_pair',side_effect=AssertionError('全NA不执行Vina'))):
            result=self.execute()
        m=self.w.load(self.sid);self.assertNotIn('A05',m['current']);self.assertNotIn('A06',m['current'])
        prep=self.w.result(m,m['current']['A06_PREP']);self.assertEqual(prep['summary']['na_pairs'],2)
        self.assertEqual(prep['summary']['ready_pairs'],0);self.assertEqual(m['reviews'],self.before['reviews'])
        records=build_trace(self.w,self.sid)['plan_decisions']['system_pipeline']
        self.assertEqual([r['stage'] for r in records if r['event']=='stage' and r['state']=='not_applicable'],['A05','A06'])
        self.assertEqual(result['state'],'awaiting_report_review')

    def test_first_approval_keeps_published_batch_and_report_reviewable(self):
        """首次人工通过同一结果，保留原系统回执和已发表报告。"""
        from modulea.core import plan_reports, system_validation
        self.prepare(True)
        result=self.execute()
        before=self.w.load(self.sid)
        a03=before['current']['A03']
        a07=result['report_run_id']
        self.assertIsNone(self.w.latest_review(before,self.w.run(before,a03)['artifact_id']))
        expected=system_validation.request(self.w,self.sid,a03)
        review=self.w.review(self.sid,a03,'approved','合成测试复核','通过同一交集结果')
        approved=self.w.load(self.sid)
        self.assertEqual(approved['current'],before['current'])
        self.assertEqual(approved['runs'],before['runs'])
        self.assertEqual(system_validation.request(self.w,self.sid,a03),expected)
        self.assertTrue(self.w.active(approved,a07))
        self.assertTrue(plan_reports.info(self.w,self.sid)['history'][-1]['active'])
        withdrawn=self.w.review(self.sid,a03,'pending','合成测试复核','暂存交集',review['review_id'])
        self.assertFalse(self.w.active(self.w.load(self.sid),a07))
        self.w.review(self.sid,a03,'approved','合成测试复核','撤回后再次通过',withdrawn['review_id'])
        self.assertFalse(self.w.active(self.w.load(self.sid),a07))

    def test_explicit_restart_after_actual_source_failure_reuses_all_completed_stages_and_diagnostics(self):
        self.prepare(False)
        with (patch.object(network,'request',side_effect=string_response),patch.object(preparation,'connect',side_effect=ContractError('明确测试：结构来源中断')),
            self.assertRaisesRegex(ContractError,'结构来源中断')):self.execute()
        failed=self.w.load(self.sid);saved={k:v for k,v in failed['current'].items() if k!='A07'}
        from science_modules.a04 import plan_flow
        with (patch.object(plan_flow,'fetch',side_effect=AssertionError('已完成PPI不得重取')),
            patch.object(preparation,'connect',side_effect=unavailable_sources)):result=self.execute()
        m=self.w.load(self.sid)
        for k,v in saved.items():self.assertEqual(m['current'][k],v)
        trace=build_trace(self.w,self.sid)['plan_decisions'];self.assertTrue(any(r['event']=='failed' for r in trace['system_pipeline']))
        self.assertEqual(result['state'],'awaiting_report_review');self.assertEqual(m['reviews'],self.before['reviews'])

    def test_hold_and_client_overrides_block_without_replacing_scientific_results(self):
        self.prepare(True)
        with self.assertRaises(ContractError):self.w.execute_analysis_plan_system_pipeline(self.sid,self.body|{'passed':True},tools=self.tools)
        self.assertEqual(self.w.load(self.sid),self.before)
        rid=self.before['current']['A00'];review=self.w.latest_review(self.before,self.w.run(self.before,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成测试','暂停源登记',expected_review=review['review_id'])
        with self.assertRaises(ContractError):self.execute()
        self.assertEqual(self.w.load(self.sid)['current'],self.before['current'])

    def test_required_originals_reject_missing_or_corrupt_five_database_sources_without_any_write(self):
        self.prepare(True);m=self.w.load(self.sid);ref,batch,_=system_pipeline.batch_for(self.w,m,self.body['batch_id'])
        self.assertTrue(system_pipeline.required_inputs(self.w,m,batch));self.assertEqual(self.w.load(self.sid),m)
        missing=deepcopy(m);missing['current'].pop('A02')
        with self.assertRaises(ContractError):system_pipeline.required_inputs(self.w,missing)
        raw=self.w.result(m,m['current']['A02']);manifest=next(r for r in raw['sources'] if r['role']=='source_manifest')
        home=self.w.location(self.sid);source=read_json(verified_file(home,manifest))['datasets'][0]['source_record']
        p=verified_file(home,source);p.write_bytes(p.read_bytes()+b'CORRUPT')
        with self.assertRaises(ContractError):system_pipeline.required_inputs(self.w,m,batch)
        self.assertEqual(self.w.load(self.sid),m)

    def test_queued_binding_keeps_original_plan_but_actual_review_change_rejects(self):
        self.prepare(True);m=self.w.load(self.sid);ref,batch,_=system_pipeline.batch_for(self.w,m,self.body['batch_id'])
        body={'batch_id':batch['batch_id'],'expected_input_hash':system_pipeline.state_hash(self.w,m,ref)}
        draft=self.w.analysis_plan_info(self.sid)['draft']
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.seed':7}},
            'author':'明确合成测试','note':'后来草稿不能改已确认批次'})
        self.assertEqual(system_pipeline.validate_request(self.w,self.sid,body)['batch_id'],batch['batch_id'])
        review=self.w.latest_review(m,self.w.run(m,m['current']['A00'])['artifact_id'])
        self.w.review(self.sid,m['current']['A00'],'pending','明确合成测试','真实源登记变化',expected_review=review['review_id'])
        with self.assertRaises(ContractError):system_pipeline.validate_request(self.w,self.sid,body)
