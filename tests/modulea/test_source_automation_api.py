"""三库采集与疾病映射入口的安全、版本绑定及只读分页验证。"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from modulea.api.server import create_server
from modulea.config import load_settings
from modulea.devtools.demo_data import build
from storage import file_record, write_json


class AutomationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.sid=build(self.root/'data')
        self.server,self.app=create_server(load_settings(data_root=self.root/'data',runtime_dir=self.root/'runtime'),0)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()

    def call(self,method,path,body=None,token=True,origin=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-ModuleA-Token']=self.app.token
        if origin:headers['Origin']=origin
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
        con.request(method,path,json.dumps(body) if body else None,headers)
        r=con.getresponse();raw=r.read();con.close();return r.status,json.loads(raw)

    def test_acquisition_and_mapping_require_token_origin_versions_and_valid_scope(self):
        info={'enabled':True,'expected_a00':'run_a00','expected_run':'run_a01','expected_staging':'abc','verification':{'enabled':True}}
        versions={k:info[k] for k in ('expected_a00','expected_run','expected_staging')}
        with patch.object(self.app,'get_sources',return_value=info),patch.object(self.app.tasks,'_spawn'):
            for module,action,databases in [('A01','acquire_sources',['HERB']),('A02','mapping_preview',['TTD'])]:
                url=f'/api/v1/studies/{self.sid}/modules/{module}/actions/{action}'
                body=dict(versions,databases=databases,reason='test')
                self.assertEqual(self.call('POST',url,body,token=False)[0],403)
                self.assertEqual(self.call('POST',url,body,origin='https://external.invalid')[0],403)
                self.assertEqual(self.call('POST',url,dict(body,expected_run='old'))[0],409)
                for ds in [[],['INVALID'],[None],databases*2]:
                    self.assertEqual(self.call('POST',url,dict(body,databases=ds))[0],422)
                status,value=self.call('POST',url,body)
                self.assertEqual(status,202)
                self.assertNotIn('payload',value['task'])
                self.app.tasks.update(value['task']['task_id'],state='succeeded')
            self.assertEqual(len(self.app.tasks.list(self.sid)),2)

    def test_resolution_requires_explicit_confirmation_and_current_result(self):
        info={'enabled':True,'expected_a00':'a00','expected_run':'a01','expected_staging':'abc','verification':{'enabled':False}}
        body={k:info[k] for k in ('expected_a00','expected_run','expected_staging')}
        body.update(reviewer='test',note='test',confirmed=False,confirm_coverage=True,omit_unresolved=False)
        url=f'/api/v1/studies/{self.sid}/modules/A01/actions/resolve_sources'
        with patch.object(self.app,'get_sources',return_value=info),patch.object(self.app.tasks,'_spawn'):
            self.assertEqual(self.call('POST',url,body)[0],409)
            info['verification']['enabled']=True
            self.assertEqual(self.call('POST',url,body)[0],422)
            self.assertEqual(self.call('POST',url,dict(body,confirmed=True))[0],202)

    def test_preview_pagination_does_not_expose_raw_requests_and_detects_tamper(self):
        w=self.app.kernel.workflow();m=w.load(self.sid);before=json.dumps(m,sort_keys=True)
        pid='task_'+'1'*32;folder=w.location(self.sid)/'raw/A02_mapping_previews'/pid;folder.mkdir(parents=True)
        value={'study_id':self.sid,'bound_a00':m['current']['A00'],'bound_a02':m['current'].get('A02',''),'source_files':[],
               'databases':[{'database':'TTD','status_zh':'test','requests':[{'secret_raw':'private'}],'candidates':[{'candidate_id':str(i)} for i in range(30)]}]}
        write_json(folder/'preview.json',value);write_json(folder/'index.json',{'file':file_record(w.location(self.sid),folder/'preview.json','preview')})
        url=f'/api/v1/studies/{self.sid}/source_previews/{pid}'
        status,r=self.call('GET',url+'?database=TTD&page=2&size=25')
        self.assertEqual(status,200);self.assertEqual(len(r['items']),5);self.assertNotIn('requests',r)
        self.assertEqual(self.call('GET',url+'?size=no')[0],422)
        self.assertEqual(json.dumps(w.load(self.sid),sort_keys=True),before)
        (folder/'preview.json').write_text('{}',encoding='utf8')
        self.assertNotEqual(self.call('GET',url)[0],200)


if __name__=='__main__':unittest.main()
