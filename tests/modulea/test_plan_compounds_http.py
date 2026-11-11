"""实际HTTP和独立科学任务验证新方案成分名单；只用合成研究。"""
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core import plan_compounds as flow
from modulea.core.kernel import full_workflow
from tests.modulea import test_plan_creation_http as creation_http
from tests.modulea.test_plan_stages import fixture, body


class PlanCompoundsHttpTests(unittest.TestCase):
    call=creation_http.PlanCreationHttpTests.call
    close=creation_http.PlanCreationHttpTests.close

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_compounds_http_');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.settings=Settings(data_root=root/'data',runtime_dir=root/'runtime')
        self.w,self.sid,_=fixture(self.settings.data_root)
        result=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'))
        self.w.review(self.sid,result['run_id'],'approved','隔离测试','核对合成上游')
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/a03-selection'

    def request(self):
        value=flow.info(self.w,self.sid)
        return dict({k:v for k,v in value.items() if k.startswith('expected_')},operator='隔离测试',reason='明确生成合成名单',confirmed=True)

    def test_get_uses_read_workflow_with_original_values_and_no_writes(self):
        before=self.w.load(self.sid);expected=flow.info(self.w,self.sid)
        with patch.object(self.app.kernel,'workflow',side_effect=AssertionError('GET不能新建写入工作流')):
            status,value=self.call('GET',self.path)
            self.assertEqual(status,200,value)
            self.assertEqual(value,expected)
            status,view=self.call('GET',f'/studies/{self.sid}/modules/A03_SELECT')
            self.assertEqual(status,200,view)
            self.assertEqual(view['plan_compounds'],expected)
        self.assertEqual(self.w.load(self.sid),before)
        self.assertEqual(self.app.tasks.list(),[])

    def test_real_task_count_review_and_trace(self):
        before=self.w.load(self.sid);request=self.request()
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertEqual(value['target_count'],15)
        status,queued=self.call('POST',self.path+'/execute',request);self.assertEqual(status,202,queued)
        task_id=queued['task']['task_id'];deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            task=self.app.tasks.get(task_id)
            if task['state'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(task['state'],'succeeded',task)
        m=self.w.load(self.sid);self.assertEqual(m['reviews'],before['reviews'])
        w=full_workflow(self.settings.data_root);result=w.result(m,m['current']['A03_SELECT'])
        run=w.run(m,result['run_id']);w.validators['A03_SELECT'](run,result['summary'],result['tables'],result['anomalies'],result['outcome'])
        self.assertEqual([r['compound_id'] for r in result['tables']['selected']],['C1'])
        self.assertEqual(result['summary']['目标成分数'],15);self.assertTrue(result['summary']['候选不足'])
        self.assertFalse(w.approved(m,result['run_id']))
        status,view=self.call('GET',f'/studies/{self.sid}/modules/A03_SELECT');self.assertEqual(status,200,view)
        self.assertTrue(view['plan_compounds']['current']);self.assertIsNone(view['compound_selection'])
        self.assertFalse(view['review']['continue']['available'])
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertTrue(any(f['role']=='compound_selection_request' for f in trace['files']))
        selection=next(r for r in trace['modules'] if r['module_id']=='A03_SELECT')
        self.assertEqual(selection['execution_request']['request'],request)
        self.assertEqual(self.call('POST',self.path+'/execute',request)[0],409)
        self.assertEqual(len(self.app.tasks.list(self.sid)),1)

    def test_invalid_requests_do_not_start_tasks(self):
        request=self.request()
        for token,origin in ((False,None),(True,'https://untrusted.example')):
            self.assertEqual(self.call('POST',self.path+'/execute',request,token,origin)[0],403)
        for change in ({'confirmed':False},{'selected':['C1']},{'target_count':1}):
            self.assertEqual(self.call('POST',self.path+'/execute',dict(request,**change))[0],422)
        self.assertEqual(self.call('POST',self.path+'/execute',dict(request,expected_input_hash='old'))[0],409)
        self.w.set_trashed(self.sid,True,'隔离测试','只读合成研究')
        self.assertEqual(self.call('POST',self.path+'/execute',request)[0],423)
        self.assertEqual(self.app.tasks.list(),[])
