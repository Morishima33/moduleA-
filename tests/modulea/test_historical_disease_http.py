"""真实HTTP的例外确认、安全、旧表单隔离与科学worker；全为临时合成研究。"""
import http.client,json,shutil,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from modulea.tasks.worker import run_historical_disease_sources
from tests.modulea import test_historical_disease_sources as fixture


class HistoricalDiseaseHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=fixture.HistoricalDiseaseSourceTests();cls.source.setUp();cls.addClassCleanup(cls.source.doCleanups)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'data';shutil.copytree(self.source.root,self.root)
        self.sid=self.source.sid;self.body=dict(self.source.body);self.w=full_workflow(self.root)
        self.settings=Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'runtime');self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/historical-disease-sources'
        self.token=json.loads(self.call('GET','/session')[1])['token']
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(5)
    def call(self,method,path,body=None,*,token=True,origin=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
        try:
            headers={'Content-Type':'application/json'}
            if token and hasattr(self,'token'):headers['X-ModuleA-Token']=self.token
            if origin:headers['Origin']=origin if isinstance(origin,str) else f'http://127.0.0.1:{self.server.server_port}'
            conn.request(method,'/api/v1'+path,json.dumps(body) if body is not None else None,headers)
            response=conn.getresponse();return response.status,response.read()
        finally:conn.close()
    def test_get_is_read_only_and_post_only_queues_then_real_worker_publishes(self):
        before=self.w.load(self.sid);status,raw=self.call('GET',self.path);self.assertEqual(status,200,raw)
        self.assertTrue(json.loads(raw)['enabled']);self.assertEqual(self.w.load(self.sid),before)
        with patch.object(self.app.tasks,'_spawn',return_value=None):status,raw=self.call('POST',self.path+'/publish',self.body)
        self.assertEqual(status,202,raw);task=json.loads(raw)['task'];self.assertEqual(task['kind'],'plan_historical_disease_sources')
        self.assertEqual(self.w.load(self.sid),before)
        run_historical_disease_sources(self.settings,{'task_id':task['task_id'],'study_id':self.sid,'payload':json.dumps(self.body)},SimpleNamespace(update=lambda *a,**k:None))
        m=self.w.load(self.sid);self.assertEqual(m['reviews'],[]);self.assertIn('A02',m['current'])
        status,raw=self.call('GET',f'/studies/{self.sid}/modules/A02');self.assertEqual(status,200,raw)
        view=json.loads(raw);self.assertIsNone(view['source_uploads']);self.assertIsNone(view['disease_scope']);self.assertIsNone(view['normalization']);self.assertIsNone(view['disease_workflow'])
        self.assertIn('发布版本未知',raw.decode('utf8'))
        self.assertIn('统一执行与续做',view['state']['reason_zh']);self.assertNotIn('请先保存范围决定',view['state']['reason_zh'])
        self.assertIn('historical_disease_source',view['special'])
        status,raw=self.call('GET',f'/studies/{self.sid}/analysis-plan/disease-acquisition');self.assertEqual(status,200,raw)
        sources=json.loads(raw);self.assertFalse(sources['enabled']);self.assertEqual(sources['historical_candidate']['candidate_records'],5)
        self.assertEqual(sources['requests'][0]['state'],'incomplete')
    def test_security_unknown_fields_stale_busy_and_trash_rejected(self):
        before=self.w.load(self.sid)
        self.assertEqual(self.call('POST',self.path+'/publish',self.body,token=False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/publish',self.body,origin='https://untrusted.invalid')[0],403)
        for change in ({'confirmed':False},{'passed':True},{'version':'fake'},{'path':'outside'},{'user_decision':''}):
            self.assertEqual(self.call('POST',self.path+'/publish',self.body|change)[0],422,change)
        self.assertEqual(self.call('POST',self.path+'/publish',self.body|{'expected_input_hash':'stale'})[0],409)
        self.assertEqual(self.call('GET',self.path+'?path=outside')[0],422)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'fake'}):self.assertEqual(self.call('POST',self.path+'/publish',self.body)[0],409)
        self.assertEqual(self.w.load(self.sid),before);self.assertEqual(self.app.tasks.list(self.sid),[])
        self.w.set_trashed(self.sid,True,'明确合成测试','验证回收站拒绝')
        self.assertEqual(self.call('POST',self.path+'/publish',self.body)[0],423)


if __name__=='__main__':unittest.main()
