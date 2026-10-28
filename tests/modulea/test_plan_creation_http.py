"""真实本机HTTP验证新版建档的令牌/Origin、状态码、不可变方案及参数预览兼容。"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from modulea.api.server import create_server
from modulea.config import Settings
from storage import read_json, write_json
from tests.modulea.test_study_creation import official_fixture


class PlanCreationHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_creation_http_');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.settings=Settings(data_root=root/'data',runtime_dir=root/'runtime')
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.verify=patch('modulea.core.plan_creation.verify_mesh_identity',side_effect=official_fixture).start()
        self.addCleanup(patch.stopall)
        self.body={'intake':{'formula':'合成方','herbs':'合成药','disease':'合成病','mesh_term':'Synthetic Disease',
                            'mesh_id':'D123456','operator':'隔离测试','analysis_purpose':'workflow_test'},
                   'specification':{'mode':'standard'}}

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def call(self,method,path,body=None,token=True,origin=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=20)
        headers={'Content-Type':'application/json'}
        if token:headers['X-ModuleA-Token']=self.app.token
        if origin:headers['Origin']=origin
        connection.request(method,'/api/v1'+path,None if body is None else json.dumps(body),headers)
        response=connection.getresponse();result=response.status,json.loads(response.read());connection.close()
        return result

    def prepare(self):
        status,preview=self.call('POST','/analysis-plans/creation/preflight',self.body)
        self.assertEqual(status,200,preview)
        body={'request_id':'plancreate_'+uuid4().hex,'preflight_id':preview['preflight_id'],
              'expected_input_hash':preview['input_hash'],'confirmed':True}
        return preview,body

    def test_http_create_retry_info_and_export(self):
        preview,body=self.prepare();status,value=self.call('POST','/analysis-plans/creation',body)
        self.assertEqual(status,201,value);sid=value['study_id']
        status,repeated=self.call('POST','/analysis-plans/creation',body)
        self.assertEqual(status,200,repeated);self.assertEqual(repeated['study_id'],sid)
        status,info=self.call('GET',f'/studies/{sid}/analysis-plan/creation')
        self.assertEqual(status,200,info);self.assertEqual(info['initial_plan']['parameter_hash'],preview['plan']['parameter_hash'])
        status,export=self.call('GET',f'/studies/{sid}/analysis-plan/creation/export.json')
        self.assertEqual(status,200,export);self.assertEqual(export['initial_plan_id'],value['plan_id'])
        self.assertEqual(self.app.tasks.list(),[])

    def test_invalid_csrf_origin_unknown_fields_and_expiry(self):
        for token,origin in ((False,None),(True,'https://untrusted.example')):
            status,_=self.call('POST','/analysis-plans/creation/preflight',self.body,token,origin)
            self.assertEqual(status,403)
        self.verify.assert_not_called()
        status,_=self.call('POST','/analysis-plans/creation/preflight',dict(self.body,approved=True))
        self.assertEqual(status,422)
        _,body=self.prepare()
        status,_=self.call('POST','/analysis-plans/creation',dict(body,confirmed=False));self.assertEqual(status,422)
        status,_=self.call('POST','/analysis-plans/creation',body,token=False);self.assertEqual(status,403)
        path=self.app.plan_creation.folder/(body['preflight_id']+'.json');record=read_json(path)
        record['expires_at']='2000-01-01T00:00:00+00:00';write_json(path,record,replace=True)
        status,_=self.call('POST','/analysis-plans/creation',body);self.assertEqual(status,409)
        self.assertFalse(self.settings.studies_dir.exists())

    def test_old_creation_and_unbound_parameter_preview_remain_separate(self):
        with patch('modulea.core.study_creation.verify_mesh_identity',side_effect=official_fixture):
            body=dict(self.body['intake'],request_id='create_'+uuid4().hex)
            status,value=self.call('POST','/studies',body)
            self.assertEqual(status,201,value)
        status,info=self.call('GET',f"/studies/{value['study_id']}/analysis-plan/creation")
        self.assertEqual((status,info),(200,None))
        m=self.app.kernel.workflow().load(value['study_id'])
        self.assertNotIn('initial_analysis_plan',m)
        status,preview=self.call('POST','/analysis-plans/validate',{'specification':{'mode':'personalized','parameters':{'a06.component_count':2}}})
        self.assertEqual(status,200,preview);self.assertFalse(preview['execution_available'])
        self.assertEqual(len(list(self.settings.studies_dir.iterdir())),1)
