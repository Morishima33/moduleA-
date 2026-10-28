"""隔离验证新方案A01网页契约、任务分派、版本保护与真实科学子进程发布。"""
import http.client
import json
import subprocess
import sys
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

from contracts import ContractError
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core import plan_a01
from modulea.tasks.worker import run_a01_plan
from tests.modulea import test_plan_a01_publication as fixtures
from tests import test_plan_tcmsp as tcmsp_fixture


class FixtureSetup:
    """复用隔离三库资料，但不将原测试类重复注册到本模块。"""
    def setUp(self):
        self.fixture = fixtures.PlanA01PublicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.w = self.fixture.workflow
        self.sid = self.fixture.sid
        self.settings = Settings(data_root=self.fixture.root, runtime_dir=self.fixture.root/'runtime')


class PlanA01TaskTests(FixtureSetup, unittest.TestCase):
    """使用既有三库虚构字段形状，不使用生产研究或真实联网采集。"""
    def test_read_only_info_uses_plan_and_does_not_write_or_execute(self):
        before = {str(p): p.read_bytes() for p in self.fixture.root.rglob('*') if p.is_file()}
        value = plan_a01.info(self.w, self.sid)
        self.assertTrue(value['acquire_enabled']); self.assertTrue(value['publish_enabled'])
        self.assertEqual(value['parameters'], {'ob_min':30, 'dl_min':.18})
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.fixture.root.rglob('*') if p.is_file()})

    def test_stale_plan_staging_and_hidden_options_rejected(self):
        body = self.fixture.payload()
        for key,value in [('expected_a00','run_old'), ('expected_a01','run_old'),
                          ('expected_plan_id','plan_old'), ('expected_staging','old')]:
            with self.subTest(key=key), self.assertRaises(ContractError):
                plan_a01.validate(self.w, self.sid, dict(body, **{key:value}), 'publish')
        with self.assertRaises(ContractError):
            plan_a01.validate(self.w,self.sid,dict(body,ob_min=0),'publish')
        for databases in ([], ['HERB','HERB'], ['unknown'], [True], 'HERB'):
            with self.subTest(databases=databases),self.assertRaises(ContractError):
                plan_a01.validate(self.w,self.sid,dict(body,databases=databases),'acquire')

    def test_legacy_and_unapproved_and_trash_remain_blocked(self):
        sid,_ = self.fixture.study(modern=False)
        self.assertFalse(plan_a01.info(self.w,sid)['supported'])
        m=self.w.load(self.sid)
        review=self.w.latest_review(m,self.w.run(m,self.fixture.a00)['artifact_id'])
        self.w.review(self.sid,self.fixture.a00,'pending','隔离测试','暂存登记',review['review_id'])
        self.assertFalse(plan_a01.info(self.w,self.sid)['acquire_enabled'])
        self.assertFalse(plan_a01.info(self.w,self.sid)['publish_enabled'])
        m=self.w.load(self.sid)
        review=self.w.latest_review(m,self.w.run(m,self.fixture.a00)['artifact_id'])
        self.w.review(self.sid,self.fixture.a00,'approved','隔离测试','仅测试',review['review_id'])
        self.w.set_trashed(self.sid,True,'隔离测试','只读保护')
        with self.assertRaisesRegex(ContractError,'回收站'):
            plan_a01.validate(self.w,self.sid,self.fixture.payload(),'publish')

    def test_parameter_change_allows_new_publication_without_reupload(self):
        first = self.fixture.publish()
        self.assertTrue(plan_a01.info(self.w,self.sid)['processed'])
        self.assertFalse(plan_a01.info(self.w,self.sid)['publish_enabled'])
        self.fixture.draft = self.fixture.save_plan(**{'a01.ob_min':15, 'a01.dl_min':.08})
        self.assertTrue(plan_a01.info(self.w,self.sid)['publish_enabled'])
        self.assertEqual(plan_a01.info(self.w,self.sid)['parameters'],{'ob_min':15,'dl_min':.08})
        second = self.fixture.publish()
        self.assertEqual((first['summary']['标准化基因数'],second['summary']['标准化基因数']),(1,3))

    def test_missing_sources_and_mapping_do_not_publish(self):
        self.fixture.sid,self.fixture.a00 = self.fixture.study()
        self.sid = self.fixture.sid
        self.fixture.draft = self.fixture.save_plan()
        value = plan_a01.info(self.w,self.sid)
        self.assertTrue(value['acquire_enabled']);self.assertFalse(value['publish_enabled'])
        self.assertEqual(value['missing_databases'],list(plan_a01.DATABASES))
        sid = self.w.create({'formula':'合成方','herbs':'合成药','disease':'合成病','disease_scope':'仅本病',
                             'species':9606,'operator':'隔离测试','analysis_purpose':'workflow_test',
                             'analysis_plan_profile':'ModuleA.analysis_plan.1'},kind='contract_test')
        self.assertTrue(any('HGNC' in v for v in plan_a01.info(self.w,sid)['publish_blockers']))

    def test_partial_acquisition_fails_task_preserves_success_without_publishing(self):
        manager = Mock()
        before = self.w.load(self.sid)
        body = dict(self.fixture.payload(),databases=['TCMSP','HERB'])
        real = self.fixture.stage
        def acquire(sid,payload,progress):
            real('TCMSP')
            return [{'database':'TCMSP','status':'success'}, {'database':'HERB','status':'failed','message_zh':'模拟网关故障'}]
        with patch('modulea.tasks.worker.full_workflow',return_value=self.w),patch.object(self.w,'acquire_analysis_plan_a01_sources',side_effect=acquire):
            with self.assertRaisesRegex(ValueError,'成功库原件已保留'):
                run_a01_plan(self.settings,{'task_id':'task_fixture','study_id':self.sid,
                    'kind':'a01_plan_acquire','payload':json.dumps(body)},manager)
        after = self.w.load(self.sid)
        self.assertEqual(before['current'],after['current']);self.assertEqual(before['reviews'],after['reviews'])
        self.assertNotEqual(before['current_component_uploads']['sha256'],after['current_component_uploads']['sha256'])

    def test_worker_revalidates_changed_draft_before_science(self):
        body = self.fixture.payload()
        self.fixture.save_plan(**{'a01.ob_min':15})
        with patch('modulea.tasks.worker.full_workflow',return_value=self.w),patch.object(self.w,'publish_analysis_plan_a01') as publish:
            with self.assertRaises(ContractError):
                run_a01_plan(self.settings,{'task_id':'task_fixture','study_id':self.sid,
                    'kind':'a01_plan_publish','payload':json.dumps(body)},Mock())
            publish.assert_not_called()

    def test_acquisition_worker_uses_original_plan_during_new_draft(self):
        fake=tcmsp_fixture.PlanTcmspTests();fake.calls=[]
        changed=[]
        original=self.fixture.draft
        def opener(request,timeout):
            if not changed:
                changed.append(self.fixture.save_plan(**{'a01.ob_min':15,'a01.dl_min':.08}))
            return fake.opener(request,timeout)
        task={'task_id':'task_fixture','study_id':self.sid,'kind':'a01_plan_acquire',
              'payload':json.dumps(dict(self.fixture.payload(),databases=['TCMSP']))}
        before=self.w.load(self.sid)
        with patch('modulea.tasks.worker.full_workflow',return_value=self.w),patch('science_modules.a01.acquisition.urllib.request.urlopen',side_effect=opener):
            message=run_a01_plan(self.settings,task,Mock())
        self.assertIn('请明确整理',message)
        after=self.w.load(self.sid)
        from science_modules.a01.uploads import current
        slot=next(row for row in current(self.w,after)['datasets'] if row['database']=='TCMSP')
        self.assertEqual(slot['analysis_plan_source']['screening_parameters'],{'ob_min':30,'dl_min':.18})
        self.assertEqual(before['current'],after['current']);self.assertEqual(before['reviews'],after['reviews'])
        self.assertNotEqual(original['plan_id'],changed[0]['plan_id'])

    def test_http_info_imports_with_standard_library_only(self):
        source=Path(__file__).resolve().parents[2]/'src'
        program=('import sys,json;sys.path.insert(0,sys.argv[1]);'
                 'from modulea.api.server import App;from modulea.config import Settings;from pathlib import Path;'
                 'from modulea.core.plan_a01 import info;'
                 'app=App(Settings(data_root=Path(sys.argv[2]),runtime_dir=Path(sys.argv[2])/"stdlib_runtime"));'
                 'print(json.dumps(info(app.kernel.workflow(),sys.argv[3])))')
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',program,str(source),str(self.fixture.root),self.sid],
                              capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['publish_enabled'])


class PlanA01HttpTests(FixtureSetup, unittest.TestCase):
    """真实HTTP及配置解释器的任务进程；只用临时合成研究。"""
    def setUp(self):
        super().setUp()
        self.server,self.app = create_server(self.settings,0)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.close)

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def call(self,method,suffix='',body=None,token=True,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
        headers={'Content-Type':'application/json'}
        if token:headers['X-ModuleA-Token']=self.app.token
        if origin:headers['Origin']=origin
        try:
            c.request(method,f'/api/v1/studies/{self.sid}/analysis-plan/a01'+suffix,
                      json.dumps(body) if body is not None else None,headers)
            r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()

    def test_http_guards_and_busy_never_start_science(self):
        body=self.fixture.payload()
        self.assertEqual(self.call('POST','/publish',body,token=False)[0],403)
        self.assertEqual(self.call('POST','/publish',body,origin='https://invalid.example')[0],403)
        self.assertEqual(self.call('POST','/publish',dict(body,ob_min=0))[0],422)
        self.assertEqual(self.call('POST','/publish',dict(body,expected_plan_id='plan_'+'0'*32))[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'task_busy'}):
            status,value=self.call('GET')
            self.assertEqual(status,200);self.assertFalse(value['acquire_enabled']);self.assertFalse(value['publish_enabled'])
        with patch.object(self.app.tasks,'submit',return_value=({'task_id':'task_busy'},False)):
            self.assertEqual(self.call('POST','/publish',body)[0],409)

    def test_http_real_subprocess_publishes_both_thresholds_and_preserves_history(self):
        before=self.w.load(self.sid)
        original_reviews=before['reviews']
        runs=[]
        for expected in (1,3):
            if expected==3:self.fixture.draft=self.fixture.save_plan(**{'a01.ob_min':15,'a01.dl_min':.08})
            status,value=self.call('POST','/publish',self.fixture.payload())
            self.assertEqual(status,202,value)
            task_id=value['task']['task_id']
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                task=self.app.tasks.get(task_id)
                if task['state'] not in ('queued','running'):break
                time.sleep(.1)
            self.assertEqual(task['state'],'succeeded',task)
            after=self.w.load(self.sid)
            result=self.w.result(after,after['current']['A01'])
            self.assertEqual(result['summary']['标准化基因数'],expected)
            self.assertEqual(after['reviews'],original_reviews)
            self.assertEqual(after['current']['A02'],before['current']['A02'])
            self.assertNotIn('A03',after['current'])
            runs.append((result['run_id'],self.w.location(self.sid)/'runs/A01'/result['run_id']/'result.json'))
            if expected==1:original=runs[0][1].read_bytes()
            self.assertEqual(self.call('POST','/publish',self.fixture.payload())[0],409)
        self.assertNotEqual(runs[0][0],runs[1][0]);self.assertEqual(original,runs[0][1].read_bytes())

    def test_http_acquisition_submits_exact_plan_binding_without_overrides(self):
        body=dict(self.fixture.payload(),databases=['HERB'])
        before=self.w.load(self.sid)
        with patch.object(self.app.tasks,'submit',return_value=({'task_id':'task_fixture','state':'queued'},True)) as submit:
            status,_=self.call('POST','/acquire',body)
            self.assertEqual(status,202)
            self.assertEqual(submit.call_args.args,(self.sid,'a01_plan_acquire','新方案A01',body))
        self.assertEqual(before,self.w.load(self.sid))


if __name__=='__main__':unittest.main()
