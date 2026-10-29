"""独立系统回执必须由真实生产校验器产生，不能改人工reviews或批准旧流程。"""
from pathlib import Path
import shutil,tempfile,unittest,os,hashlib
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from modulea.core.kernel import full_workflow
from modulea.core import system_validation as validation
from storage import verified_file
from tests.modulea import test_plan_a05_display_workflow as display_tests
from tests.modulea import test_plan_creation_http as http_fixture


class SystemValidationTests(unittest.TestCase):
    call=http_fixture.PlanCreationHttpTests.call
    close=http_fixture.PlanCreationHttpTests.close
    @classmethod
    def setUpClass(cls):
        """复用真实R基线构建器，数据仅为隔离合成研究。"""
        display_tests.PlanA05DisplayWorkflowTests.setUpClass.__func__(cls)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_validation_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);shutil.copytree(self.seed_root,self.root,dirs_exist_ok=True)
        self.w=full_workflow(self.root);self.rid=self.w.load(self.sid)['current']['A05']

    def body(self,rid=None):
        """读取实际输入指纹，不能由测试编造校验结论。"""
        value=validation.request(self.w,self.sid,rid or self.rid)
        return {key:value[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex}

    def test_actual_registered_r_validator_receipt_without_human_approval(self):
        before=self.w.load(self.sid);body=self.body()
        result=self.w.validate_analysis_plan_scientific_run(self.sid,body);after=self.w.load(self.sid)
        self.assertTrue(result['passed'],result['error_zh']);self.assertEqual(result['authority_kind'],'system_validation')
        self.assertFalse(result['human_review_written']);self.assertFalse(result['grants_legacy_approval'])
        self.assertTrue(result['scientific_status']['ready_for_successor'])
        self.assertEqual(before['current'],after['current']);self.assertEqual(before['reviews'],after['reviews'])
        self.assertFalse(self.w.approved(after,self.rid));self.assertEqual(len(after[validation.INDEX]),1)
        path=verified_file(self.w.location(self.sid),result['validator_code'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),result['validator_sha256'])
        with patch('science_modules.a05.plan_flow.r_call',side_effect=AssertionError('相同请求不得重算')):
            self.assertEqual(self.w.validate_analysis_plan_scientific_run(self.sid,body),result)

    def test_science_tool_failure_is_failed_receipt_not_false_pass(self):
        before=self.w.load(self.sid);body=self.body()
        self.w.validators['A05']=lambda *_:None  # 调用者的假validator不应被生产入口采用。
        with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(self.root/'missing_Rscript.exe')}):
            result=self.w.validate_analysis_plan_scientific_run(self.sid,body)
        self.assertFalse(result['passed']);self.assertIn('Rscript',result['error_zh'])
        after=self.w.load(self.sid);self.assertEqual(after['reviews'],before['reviews']);self.assertEqual(after['current'],before['current'])
        self.assertEqual(len(after[validation.INDEX]),1);self.assertFalse(result['checks'][0]['passed'])

    def test_hidden_pass_flag_and_stale_input_never_pass(self):
        body=self.body()
        with self.assertRaises(ContractError):self.w.validate_analysis_plan_scientific_run(self.sid,body|{'passed':True})
        with self.assertRaises(ContractError):self.w.validate_analysis_plan_scientific_run(self.sid,body|{'expected_input_hash':'old'})
        self.assertFalse(self.w.load(self.sid).get(validation.INDEX))

    def test_replaced_ancestor_cannot_revalidate_stale_descendant(self):
        """A05的直接A03指针虽未换，A00已换时仍必须识别整条依赖失效。"""
        m=self.w.load(self.sid);a00=m['current']['A00'];run=self.w.run(m,a00)
        self.w.revise_intake(self.sid,dict(run['inputs'],operator='新的合成登记人'),'合成祖先变更测试',a00)
        with self.assertRaises(ContractError):validation.request(self.w,self.sid,self.rid)

    def test_intake_canonical_validator_is_real_and_not_human_approval(self):
        m=self.w.load(self.sid);rid=m['current']['A00'];body=self.body(rid)
        receipt=self.w.validate_analysis_plan_scientific_run(self.sid,body)
        self.assertTrue(receipt['passed'],receipt['error_zh'])
        current=self.w.load(self.sid);self.assertEqual(m['reviews'],current['reviews']);self.assertEqual(m['current'],current['current'])
        reference=current[validation.INDEX][-1]
        self.assertEqual(validation.read_receipt(self.w,current,reference),receipt)
        path=verified_file(self.w.location(self.sid),receipt['validator_code']);path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ContractError):validation.read_receipt(self.w,current,reference)

    def test_changed_review_fingerprint_and_trash_block_old_request(self):
        body=self.body();m=self.w.load(self.sid);a03=m['current']['A03'];review=self.w.latest_review(m,self.w.run(m,a03)['artifact_id'])
        self.w.review(self.sid,a03,'pending','系统回执隔离测试','撤回原测试批准',review['review_id'])
        self.assertNotEqual(validation.request(self.w,self.sid,self.rid)['expected_input_hash'],body['expected_input_hash'])
        with self.assertRaises(ContractError):self.w.validate_analysis_plan_scientific_run(self.sid,body)
        self.w.set_trashed(self.sid,True,'系统回执隔离测试','只读保护')
        with self.assertRaises(ContractError):validation.request(self.w,self.sid,self.rid)

    def start_http(self,*,missing_r=False):
        """实际本机HTTP、任务和独立worker；只操作每例临时合成研究。"""
        import threading
        from modulea.api.server import create_server
        from modulea.config import Settings
        self.settings=Settings(data_root=self.root,runtime_dir=self.root/'rt',
            science_rscript=self.root/'missing_Rscript.exe' if missing_r else display_tests.RSCRIPT)
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/system-validations'

    def wait_task(self,tid):
        """限时等独立worker实际终态，不能用任务提交成功代替验证通过。"""
        import time
        deadline=time.monotonic()+80
        while time.monotonic()<deadline:
            task=self.app.tasks.get(tid)
            if task['state'] not in ('queued','running'):return task
            time.sleep(.1)
        self.fail('系统校验worker未在时限内结束：'+self.app.tasks.log(tid))

    def test_actual_http_worker_receipt_trace_and_read_only_get(self):
        """真实A00规范验证走完整HTTP→worker→回执→追溯，不需人工批准。"""
        self.start_http();before=self.w.load(self.sid);body=self.body(before['current']['A00'])
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertTrue(value['supported'])
        expected=next(row for row in value['items'] if row['module_id']=='A00')['request']
        self.assertEqual(set(expected),{'expected_run_id','expected_input_hash'})
        body={'request_id':body['request_id'],**expected}
        self.assertEqual(self.w.load(self.sid),before)
        status,value=self.call('POST',self.path+'/execute',body);self.assertEqual(status,202,value)
        task=self.wait_task(value['task']['task_id']);self.assertEqual(task['state'],'succeeded',self.app.tasks.log(task['task_id']))
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertEqual(len(value['history']),1)
        self.assertTrue(next(row for row in value['items'] if row['module_id']=='A00')['current']['passed'])
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertEqual(len(trace['plan_decisions']['system_validations']),1)
        self.assertEqual(len(trace['plan_decisions']['system_validation_requests']),1)
        self.assertTrue(any(ref.get('role')=='system_validator_source' for ref in trace['files']))
        after=self.w.load(self.sid);self.assertEqual(after['current'],before['current']);self.assertEqual(after['reviews'],before['reviews'])

    def test_actual_worker_r_failure_retains_failed_receipt(self):
        self.start_http(missing_r=True);before=self.w.load(self.sid)
        status,value=self.call('POST',self.path+'/execute',self.body());self.assertEqual(status,202,value)
        task=self.wait_task(value['task']['task_id']);self.assertEqual(task['state'],'failed',self.app.tasks.log(task['task_id']))
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertFalse(value['history'][0]['passed']);self.assertFalse(value['history'][0]['scientific_status']['ready_for_successor'])
        after=self.w.load(self.sid);self.assertEqual(after['current'],before['current']);self.assertEqual(after['reviews'],before['reviews'])

    def test_http_security_fields_stale_busy_trash_without_task(self):
        self.start_http();body=self.body()
        self.assertEqual(self.call('POST',self.path+'/execute',body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/execute',body,True,'https://untrusted.example')[0],403)
        for value in ({'passed':True},{'approved':True},{'path':'outside'}):
            with self.subTest(value=value):self.assertEqual(self.call('POST',self.path+'/execute',body|value)[0],422)
        self.assertEqual(self.call('POST',self.path+'/execute',body|{'expected_input_hash':'old'})[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'synthetic_active'}):
            self.assertEqual(self.call('POST',self.path+'/execute',body)[0],409)
        self.w.set_trashed(self.sid,True,'隔离测试','只读保护')
        self.assertEqual(self.call('POST',self.path+'/execute',body)[0],423)
        self.assertEqual(self.app.tasks.list(self.sid),[])
