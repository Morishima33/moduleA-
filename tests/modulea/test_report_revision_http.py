"""报告二版经真实HTTP读取/下载和后台任务协议绑定；原一版文件保持。"""
from io import BytesIO
import http.client
import json
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from docx import Document
from tests.modulea import test_plan_report_revision as seed


class ReportRevisionHttpTests(TestCase):
    @classmethod
    def setUpClass(cls):
        seed.ReportRevisionWorkflowTests.setUpClass.__func__(cls)

    setUp = seed.ReportRevisionWorkflowTests.setUp
    body = seed.ReportRevisionWorkflowTests.body

    def test_two_versions_http_history_download_and_queued_worker_keep_original_protocol(self):
        from modulea.api.server import create_server
        from modulea.config import Settings
        from modulea.core import report_registry
        from modulea.tasks.worker import run_plan_report
        old = self.w.publish_analysis_plan_report(self.sid, self.body())
        revised = self.w.publish_analysis_plan_report_revision(self.sid, self.body())
        before = self.w.load(self.sid)
        server, app = create_server(Settings(data_root=self.root, runtime_dir=self.root/'http_runtime'), 0)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def get(url):
            connection = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=60)
            connection.request('GET',url); response=connection.getresponse(); raw=response.read(); connection.close()
            self.assertEqual(response.status,200,raw[:200]); return raw
        base = '/api/v1/studies/'+self.sid+'/analysis-plan/reports'
        info = json.loads(get(base))
        self.assertEqual(info['schema_version'],'A07.plan_report.2')
        self.assertEqual({r['run_id'] for r in info['history']},{old['run_id'],revised['run_id']})
        for row in info['history']:
            self.assertEqual(len(row['downloads']),2)
            for file in row['downloads']:
                Document(BytesIO(get(file['url'])))
        self.assertEqual(self.w.load(self.sid),before)
        body = self.body()
        with patch.object(app.tasks,'_spawn') as spawn:
            connection = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=60)
            connection.request('POST',base+'/generate',json.dumps(body),
                {'Content-Type':'application/json','X-ModuleA-Token':app.token})
            response=connection.getresponse(); submitted=json.loads(response.read()); connection.close()
            self.assertEqual(response.status,202,submitted)
        spawn.assert_called_once()
        queued = json.loads(app.tasks._raw(submitted['task']['task_id'])['payload'])
        self.assertEqual(queued['request'],body)
        self.assertEqual(queued['report_protocol'],'A07.plan_report.2')
        class Manager:
            def update(self,*args,**kwargs): pass
        with patch('modulea.tasks.worker.full_workflow',return_value=self.w):
            run_plan_report(Settings(data_root=self.root),{'study_id':self.sid,'task_id':'synthetic',
                'payload':json.dumps(queued)},Manager())
        self.assertEqual(self.w.load(self.sid)['reviews'],before['reviews'])
        self.assertEqual(self.w.run(self.w.load(self.sid),self.w.load(self.sid)['current']['A07'])['config']['version'],'A07.plan_report.2')

    def test_old_worker_payload_is_not_silently_upgraded(self):
        from modulea.core.report_registry import publish_queued
        body={'request_id':'synthetic'}
        with patch.object(self.w,'publish_analysis_plan_report',return_value='old') as old, \
             patch.object(self.w,'publish_analysis_plan_report_revision',side_effect=AssertionError('旧任务不能升级')):
            self.assertEqual(publish_queued(self.w,self.sid,body),'old')
        old.assert_called_once_with(self.sid,body)

    def test_empty_branch_uses_actual_a03_batch_protocol(self):
        from modulea.core import report_registry, system_execution
        manifest={'current':{'A03':'synthetic'},system_execution.BATCHES:[{'fixed':'batch'}]}
        with patch.object(self.w,'run',return_value={'batch_file':{'fixed':'batch'}}), \
             patch.object(system_execution,'read_batch',return_value=({'report_protocol':'A07.plan_report.2'},{})):
            self.assertEqual(report_registry.current(self.w,manifest).VERSION,'A07.plan_report.2')
