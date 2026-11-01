"""真实HTTP读取实际生产发布的合成A01，下载绑定/旧版/损坏保护；不联网。"""
import http.client,json,shutil,tempfile,threading,unittest
from pathlib import Path
from urllib.parse import urlsplit
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from storage import write_lock
from tests.modulea import test_system_component_sources as fixture


class ComponentIdentityEvidenceHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SystemComponentSourceTests.setUpClass.__func__(cls)
        cls.source=fixture.SystemComponentSourceTests();cls.source.mapping_root=cls.mapping_root;cls.source.setUp();cls.addClassCleanup(cls.source.doCleanups)
        w=cls.source.w;sid=cls.source.sid;w.bind_analysis_plan_system_a01_sources(sid,cls.source.body)
        batch=cls.source.start();w.execute_analysis_plan_system_stage(sid,{'batch_id':batch['batch_id'],'stage':'A01','expected_current_run_id':None})

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'data'
        shutil.copytree(self.source.root,self.root);self.sid=self.source.sid;self.w=full_workflow(self.root)
        self.server,self.app=create_server(Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'runtime'),0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/api/v1/studies/{self.sid}/analysis-plan/component-identity-evidence'

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(5)

    def call(self,path,method='GET'):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
        try:
            conn.request(method,path);response=conn.getresponse();raw=response.read()
            return response.status,raw
        finally:conn.close()

    def test_read_export_and_registered_attachment_keep_manifest_and_reviews(self):
        manifest=self.w.location(self.sid)/'manifest.json';before=manifest.read_bytes()
        status,raw=self.call(self.path);self.assertEqual(status,200,raw);value=json.loads(raw)
        self.assertTrue(value['supported']);self.assertTrue(value['read_only']);self.assertEqual(value['stats']['source_rows'],0)
        self.assertEqual(self.call(value['export_json_url'])[0],200);self.assertEqual(self.call(value['export_csv_url'])[0],200)
        status,attachment=self.call(value['files'][0]['url']);self.assertEqual(status,200)
        self.assertEqual(attachment,(self.w.location(self.sid)/value['files'][0]['file']['path']).read_bytes())
        self.assertEqual(manifest.read_bytes(),before);self.assertEqual(self.w.load(self.sid)['reviews'],[])
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def test_stale_download_link_and_unknown_path_parameters_rejected(self):
        _,raw=self.call(self.path);value=json.loads(raw)
        with write_lock(self.w.root):
            m=self.w.load(self.sid);m['trashed']=True;self.w.save(m)
        self.assertEqual(self.call(value['export_json_url'])[0],409)
        self.assertEqual(self.call(value['files'][0]['url'])[0],409)
        self.assertEqual(self.call(self.path+'?path=outside')[0],422)
        self.assertEqual(self.call(self.path,method='POST')[0],403)

    def test_corrupt_original_is_reported_as_failure(self):
        _,raw=self.call(self.path);value=json.loads(raw);ref=value['files'][0]['file']
        (self.w.location(self.sid)/ref['path']).write_bytes(b'changed')
        status,body=self.call(self.path);self.assertEqual(status,503)
        self.assertEqual(json.loads(body)['error']['code'],'ARCHIVE_UNAVAILABLE')

    def test_no_current_a01_is_unsupported_and_never_runs_science(self):
        with write_lock(self.w.root):
            m=self.w.load(self.sid);m['current'].pop('A01');self.w.save(m)
        status,raw=self.call(self.path);self.assertEqual(status,200,raw)
        self.assertFalse(json.loads(raw)['supported']);self.assertEqual(self.app.tasks.list(self.sid),[])


if __name__=='__main__':unittest.main()
