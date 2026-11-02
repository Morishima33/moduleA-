"""公开Workflow的实际R文字修订、同批事件、追溯与失败/暂停保护；仅合成研究。"""
from copy import deepcopy
import hashlib,os,shutil,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from storage import verified_file
from modulea.core.kernel import full_workflow
from modulea.core import plan_a05_text as core,system_execution
from modulea.core import plan_a05_display
from modulea.core.trace_export import build_trace
from modulea.config import Settings
from modulea.tasks.manager import TaskManager
from tests.modulea import test_system_decisions as upstream,test_plan_a05 as annotation


class PlanA05TextRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=patch.dict(os.environ,{'MODULEA_RSCRIPT':str(annotation.RSCRIPT)});cls.env.start();cls.addClassCleanup(cls.env.stop)
        upstream.SystemDecisionTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base);m=w.load(cls.sid);draft=w.analysis_plan_info(cls.sid)['draft']
        annotation.install_source(cls.base,draft['plan'])
        w.execute_analysis_plan_system_stage(cls.sid,{'batch_id':cls.batch_id,'stage':'A05','expected_current_run_id':None})
        assert core.info(w,cls.sid)['enabled'],'本机须实际重现旧R中文编码损坏，不能把未发生问题冒作修订验证'

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='a05_text_revision_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root)
        self.before=self.w.load(self.sid);value=core.info(self.w,self.sid)
        self.body={key:value[key] for key in ('expected_a05','expected_input_hash')}|{'request_id':'a05textreq_'+uuid4().hex,
            'author':'明确合成编码修订测试','note':'原统计全部保留，仅校正R中文原因','confirmed':True}

    def publish(self,body=None):return self.w.revise_analysis_plan_a05_text(self.sid,body or self.body)

    def test_actual_r_revision_replay_preserves_old_statistics_and_publishes_new_same_batch_event_without_review(self):
        old=self.w.result(self.before,self.body['expected_a05']);value=self.publish();m=self.w.load(self.sid);new=value['result']
        self.assertTrue(value['created']);self.assertEqual(self.w.run(m,value['run_id'])['config']['version'],'A05.plan_enrichment.2')
        self.assertEqual(core.statistics(old['summary'],old['tables']),core.statistics(new['summary'],new['tables']))
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertTrue(self.w.active(m,value['run_id']))
        for rid,refs in self.before['runs'].items():
            self.assertEqual(m['runs'][rid],refs)
            for ref in refs.values():
                if ref:verified_file(self.w.location(self.sid),ref)
        self.assertFalse(self.publish()['created']);self.assertEqual(self.w.load(self.sid),m)
        trace=build_trace(self.w,self.sid,include_data=True)
        self.assertEqual(len(trace['plan_decisions']['a05_text_requests']),1)
        self.assertEqual(len(trace['plan_decisions']['a05_text_receipts']),1)
        self.assertEqual(trace['plan_decisions']['system_batch_events'][-1]['run_id'],value['run_id'])
        for group in ('bp','cc','mf','kegg'):
            for row in new['tables'][group+'_skipped']:
                self.assertIn(row['reason'],('条目背景基因数不在本方案范围','有效输入无命中'))
        display=plan_a05_display.info(self.w,self.sid);self.assertTrue(display['enabled'])
        rendered=self.w.prepare_analysis_plan_a05_display(self.sid,{key:display[key] for key in
            ('expected_a05','expected_display_id','expected_input_hash')}|{'request_id':'a05displayreq_'+uuid4().hex,
            'author':'明确合成新版展示','note':'第二版统计沿用原分类和完整数据，不签科研复核','confirmed':True})
        self.assertEqual(rendered['schema_version'],'A05.plan_display.2')
        self.assertEqual(self.w.load(self.sid)['current'],m['current'])
        trace=build_trace(self.w,self.sid,include_data=True)
        self.assertEqual(trace['plan_decisions']['a05_display_records'][-1]['schema_version'],'A05.plan_display.2')

    def test_fields_confirmation_stale_or_parameter_override_reject_without_mutation(self):
        for changes in ({'confirmed':False},{'passed':True},{'path':'outside'},{'min_size':1},{'expected_input_hash':'old'}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.publish(self.body|changes)
        self.assertEqual(self.w.load(self.sid),self.before)

    def test_human_hold_blocks_revision_without_new_science_or_request(self):
        self.w.review(self.sid,self.body['expected_a05'],'pending','明确合成暂停','文字修订不能放行人工暂停')
        held=self.w.load(self.sid)
        with self.assertRaises(ContractError):self.publish()
        self.assertEqual(self.w.load(self.sid),held)

    def test_missing_r_keeps_request_and_failure_without_replacing_original_run(self):
        with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(self.root/'missing-rscript')}),self.assertRaises(ContractError):self.publish()
        m=self.w.load(self.sid);self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['reviews'],self.before['reviews'])
        self.assertEqual(len(m[core.REQUESTS]),1);self.assertEqual(len(m[core.FAILURES]),1)
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['a05_text_failures']),1)

    def test_failed_request_retries_without_overwriting_prior_files_or_logs(self):
        with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(self.root/'missing-rscript')}),self.assertRaises(ContractError):self.publish()
        folder=self.w.location(self.sid)/'decisions/analysis_plans/a05_text_revisions'/self.body['request_id']
        original_files={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.rglob('*') if path.is_file()}
        self.assertTrue(self.publish()['created'])
        for path,digest in original_files.items():self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
        m=self.w.load(self.sid);self.assertEqual(len(m[core.REQUESTS]),1);self.assertEqual(len(m[core.FAILURES]),1)
        self.assertEqual(len(list((folder/'attempts').iterdir())),2)

    def test_forged_statistics_never_publish_even_if_injected_calculation_says_complete(self):
        from science_modules.a05 import plan_flow_utf8 as science
        result=self.w.result(self.before,self.body['expected_a05']);summary=dict(result['summary'],protocol_version=science.VERSION)
        summary['BP显著条目数']+=1;plan=self.w.analysis_plan_info(self.sid)['draft']['plan']
        with (patch.object(science,'facts',return_value=(plan,summary,deepcopy(result['tables']),'明确合成伪输出')),
                self.assertRaises(ContractError)):self.publish()
        m=self.w.load(self.sid);self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['runs'],self.before['runs'])
        self.assertEqual(m['reviews'],self.before['reviews'])

    def test_actual_budgeted_worker_uses_configured_r_and_preserves_originals(self):
        settings=Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'runtime',science_rscript=annotation.RSCRIPT)
        manager=TaskManager(settings);task,created=manager.submit(self.sid,'plan_a05_text_revision','明确合成真实worker',self.body)
        self.assertTrue(created);deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            value=manager.get(task['task_id'])
            if value['state'] not in ('queued','running'):break
            time.sleep(.1)
        else:self.fail('本测试真实R修订任务未进入终态：'+manager.log(task['task_id']))
        # 仅等待本测试启动器关闭日志，任务终态本身不代表系统进程已退出。
        for thread in threading.enumerate():
            if thread.name=='modulea-reap-'+task['task_id']:thread.join(30);self.assertFalse(thread.is_alive())
        self.assertEqual(value['state'],'succeeded',manager.log(task['task_id']))
        m=self.w.load(self.sid);self.assertNotEqual(m['current']['A05'],self.before['current']['A05'])
        self.assertEqual(m['reviews'],self.before['reviews']);self.assertEqual(m['runs'][self.body['expected_a05']],self.before['runs'][self.body['expected_a05']])

    def test_explicit_new_recoverable_batch_uses_unicode_script_and_old_batch_is_unchanged(self):
        original_run=self.w.run(self.before,self.body['expected_a05'])
        original_batch,_=system_execution.read_batch(self.w,self.before,original_run['batch_file'])
        self.assertNotIn('enrichment_protocol',original_batch)
        root=Path(self.temp.name)/'new_batch'
        w,sid,draft,_=upstream.fixture.prepare(root,modern=True,multiple_targets=True,stop_before_normalization=True)
        original_reviews=deepcopy(w.load(sid)['reviews'])
        info=system_execution.info(w,sid)
        body={key:info[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成Unicode新批','note':'新批协议独立记录，旧批不升级','confirmed':True}
        batch=w.start_analysis_plan_recoverable_system_batch(sid,body)
        self.assertEqual(batch['enrichment_protocol'],'A05.plan_enrichment.2')
        self.assertFalse(w.start_analysis_plan_system_batch(sid,body)['created'])
        annotation.install_source(root,draft['plan'])
        for stage in ('A01','A02','A03','A05'):
            result=w.execute_analysis_plan_system_stage(sid,{'batch_id':batch['batch_id'],'stage':stage,
                'expected_current_run_id':w.load(sid)['current'].get(stage)})
        m=w.load(sid);self.assertEqual(w.run(m,result['run_id'])['config']['version'],'A05.plan_enrichment.2')
        self.assertEqual(m['reviews'],original_reviews)
        for group in ('bp','cc','mf','kegg'):
            for row in result['tables'][group+'_skipped']:
                self.assertIn(row['reason'],('条目背景基因数不在本方案范围','有效输入无命中'))

    def test_new_unicode_nonempty_pipeline_reaches_real_synthetic_double_reports(self):
        from science_modules.a04 import plan_flow as network
        from science_modules.a06 import plan_preparation_v2 as preparation
        from tests.modulea.plan_report_nonempty_fixture import string_response,unavailable_sources
        import docx
        root=Path(self.temp.name)/'full_unicode_batch'
        w,sid,draft,_=upstream.fixture.prepare(root,modern=True,multiple_targets=True,stop_before_normalization=True)
        original_reviews=deepcopy(w.load(sid)['reviews']);info=system_execution.info(w,sid)
        batch=w.start_analysis_plan_recoverable_system_batch(sid,{key:info[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成Unicode全链','note':'固定R真实计算、合成来源、完整NA和双报告','confirmed':True})
        annotation.install_source(root,draft['plan'])
        with patch.object(network,'request',side_effect=string_response),patch.object(preparation,'connect',side_effect=unavailable_sources):
            result=w.execute_analysis_plan_system_pipeline(sid,{'batch_id':batch['batch_id']},
                tools=Path('D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))
        m=w.load(sid);self.assertEqual(result['state'],'awaiting_report_review');self.assertEqual(m['reviews'],original_reviews)
        self.assertEqual(w.run(m,m['current']['A05'])['config']['version'],'A05.plan_enrichment.2')
        report=w.result(m,m['current']['A07']);self.assertEqual(len(report['tables']['report_files']),2)
        for ref in report['tables']['report_files']:
            document=docx.Document(verified_file(w.location(sid),ref))
            self.assertTrue(document.paragraphs)
        trace=build_trace(w,sid,include_data=True)
        self.assertTrue(any(row['run_id']==m['current']['A05'] for row in trace['modules']))


if __name__=='__main__':unittest.main()
