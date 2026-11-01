"""实际HTTP与科学worker预上传；严守令牌、原件字节、版本和未批准登记边界。"""
import json,threading,time,unittest
from unittest.mock import patch
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core import system_disease_manual_sources as core
from modulea.tasks.system_disease_manual_sources import run
from tests.modulea import test_system_disease_manual_sources as fixture
from tests.modulea import test_source_upload_api as upload_fixture


class SystemDiseaseManualSourcesHttpTests(unittest.TestCase):
    body=fixture.SystemDiseaseManualSourcesTests.body
    call=upload_fixture.SourceUploadApiTests.call
    def setUp(self):
        fixture.SystemDiseaseManualSourcesTests.setUp(self)
        self.server,self.app=create_server(Settings(data_root=self.root,runtime_dir=self.root/'http_runtime'),0)
        self.port=self.server.server_port;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close);self.path=f'/api/v1/studies/{self.sid}/analysis-plan/disease-manual-sources'
    def close(self):
        """任务终态先落库，科学进程稍后退出；等待本测试的真实启动器释放日志再清理。"""
        self.server.shutdown();self.server.server_close();self.thread.join()
        names={'modulea-reap-'+task['task_id'] for task in self.app.tasks.list(self.sid)}
        for thread in threading.enumerate():
            if thread.name in names:
                thread.join(30)
                self.assertFalse(thread.is_alive(),'本测试科学启动器未退出，不能删除仍使用的临时目录')
    def form(self,body=None,raw=None,**changes):
        body=body or self.body();fields={key:value for key,value in body.items() if key not in ('source','confirmed')}
        fields.update({key:value for key,value in body['source'].items() if key!='name'},confirmed='yes');fields.update(changes)
        boundary='manual-source-fixture';parts=[]
        for key,value in fields.items():parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="upload"; filename="{body["source"]["name"]}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        parts.extend([self.raw if raw is None else raw,f'\r\n--{boundary}--\r\n'.encode()])
        return b''.join(parts),'multipart/form-data; boundary='+boundary
    def terminal(self,tid):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            task=self.app.tasks.get(tid)
            if task['state'] not in ('queued','running'):return task
            time.sleep(.1)
        self.fail('实际预上传科学worker未终止')

    def test_get_only_and_real_capability_never_creates_requests_or_approval(self):
        before=self.w.load(self.sid);status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertTrue(value['enabled']);self.assertEqual(value['sources'],[]);self.assertEqual(self.w.load(self.sid),before)
        status,value=self.call('GET','/api/v1/session');self.assertTrue(value['capabilities']['system_disease_manual_sources'])
        self.assertEqual(self.app.tasks.list(),[])

    def test_csrf_origin_extra_fields_format_stale_and_trash_reject_before_queue(self):
        data,mime=self.form()
        for kwargs in ({'token':False},{'origin':'https://outside.invalid'}):
            status,_=self.call('POST',self.path,data,mime,**kwargs);self.assertEqual(status,403)
        for changes in ({'passed':'true'},{'confirmed':'no'},{'database':'OTP'},{'format':'omim_xlsx'},{'source_url':'outside'}):
            data,mime=self.form(**changes);status,value=self.call('POST',self.path,data,mime);self.assertEqual(status,422,value)
        data,mime=self.form(expected_input_hash='changed');status,value=self.call('POST',self.path,data,mime);self.assertEqual(status,409,value)
        self.w.set_trashed(self.sid,True,'明确合成测试','明确测试回收站');data,mime=self.form();status,value=self.call('POST',self.path,data,mime)
        self.assertEqual(status,423,value);self.assertEqual(self.app.tasks.list(),[])

    def test_actual_worker_stage_and_exact_replay_keep_a00_runs_reviews(self):
        body=self.body();data,mime=self.form(body);status,value=self.call('POST',self.path,data,mime);self.assertEqual(status,202,value)
        self.assertNotIn('payload',value['task']);first=self.terminal(value['task']['task_id']);self.assertEqual(first['state'],'succeeded',first)
        m=self.w.load(self.sid);self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['runs'],self.before['runs']);self.assertEqual(m['reviews'],[])
        self.assertEqual(len(m[core.INDEX]),1);core.read_record(self.w,m,m[core.INDEX][0])
        status,value=self.call('POST',self.path,data,mime);self.assertEqual(status,202,value)
        second=self.terminal(value['task']['task_id']);self.assertEqual(second['state'],'succeeded',second)
        self.assertEqual(self.w.load(self.sid),m)

    def test_queued_hold_and_corrupt_queue_fail_actual_handler_without_staging(self):
        body=self.body();data,mime=self.form(body)
        with patch.object(self.app.tasks,'_spawn'):
            status,value=self.call('POST',self.path,data,mime);self.assertEqual(status,202,value)
        task=self.app.tasks._raw(value['task']['task_id']);payload=json.loads(task['payload'])
        self.assertEqual((self.app.settings.runtime_dir/'upload_queue'/payload['blob_name']).read_bytes(),self.raw)
        self.w.review(self.sid,body['expected_a00'],'pending','明确测试暂停','排队后阻断')
        with self.assertRaises(Exception):run(self.app.settings,task,self.app.tasks)
        self.assertNotIn('current_source_staging',self.w.load(self.sid))
        (self.app.settings.runtime_dir/'upload_queue'/payload['blob_name']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(Exception,'队列原件校验失败'):run(self.app.settings,task,self.app.tasks)
