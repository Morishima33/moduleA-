"""真实隔离HTTP入口：同版本图CSV/ZIP、token/Origin与返回前原件复核，不运行科学计算。"""
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
import threading
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import zipfile

from modulea.api.server import create_server
from modulea.core.http_read_evidence import HttpReadEvidence
from tests.modulea.test_rescue_presentation_api import RescuePresentationApiTests


class RescuePresentationHttpTests(TestCase):
    def setUp(self):
        self.seed=RescuePresentationApiTests('test_current_view_and_focus_use_same_explicit_revision_and_keep_na')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        self.server,self.app=create_server(self.seed.settings,0)
        self.app.kernel=self.seed.app.kernel;self.app.tasks=self.seed.tasks
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.url=f'/api/v1/studies/{self.seed.sid}/runs/{self.seed.rid}/rescue-presentations'

    def get(self,url):
        with urlopen(self.base+url) as response:return json.load(response)

    def test_directory_view_files_zip_and_refresh_share_one_revision_without_writes(self):
        record=self.seed.publish();before=self.seed.w.load(self.seed.sid);files=self.seed.seed.original_files()
        info=self.get(self.url)
        self.assertEqual(info['current']['revision_id'],record['revision_id'])
        view=self.get(info['current']['view_url'])
        self.assertNotIn('current_view',info)
        inline=self.get(self.url+'?include_current=1')
        self.assertEqual(inline,{**info,'current_view':view})
        with self.assertRaises(HTTPError) as caught:
            self.get(self.url+'?include_current=1&include_current=1')
        self.assertEqual(caught.exception.code,422)
        for link in view['downloads']:
            with urlopen(self.base+link['url']) as response:raw=response.read()
            self.assertEqual(sha256(raw).hexdigest(),link['sha256'])
        accepted=self.get(view['acceptance_url'])
        self.assertTrue(accepted['enabled'])
        with urlopen(self.base+accepted['download_url']) as response,zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            self.assertEqual(archive.read('poses/pair_000001/top1.pdbqt'),self.seed.top)
            metadata=json.loads(archive.read('验收目录与指纹.json'))
            self.assertEqual(metadata['presentation_revision']['receipt_sha256'],record['file']['sha256'])
        self.assertEqual(self.get(self.url)['current'],info['current'])
        self.assertEqual(before,self.seed.w.load(self.seed.sid))
        self.assertEqual(files,self.seed.seed.original_files());self.seed.tasks.submit.assert_not_called()

    def test_publish_keeps_existing_token_origin_and_exact_field_guards(self):
        self.seed.seed.approve_name();body=self.seed.seed.body()
        def post(headers,payload=body):
            return urlopen(Request(self.base+self.url,data=json.dumps(payload).encode('utf8'),
                headers=dict({'Content-Type':'application/json'},**headers),method='POST'))
        for headers in ({'Origin':self.base},{'Origin':'https://example.invalid','X-ModuleA-Token':self.app.token}):
            with self.assertRaises(HTTPError) as caught:post(headers)
            self.assertEqual(caught.exception.code,403)
        self.seed.tasks.submit.assert_not_called()
        headers={'Origin':self.base,'X-ModuleA-Token':self.app.token}
        with self.assertRaises(HTTPError) as caught:post(headers,dict(body,font_path='foreign'))
        self.assertEqual(caught.exception.code,422);self.seed.tasks.submit.assert_not_called()
        with post(headers) as response:
            self.assertEqual(response.status,202);self.assertTrue(json.load(response)['created'])
        self.assertEqual(self.seed.tasks.submit.call_count,1)

    def test_actual_view_response_rejects_archive_font_changed_at_finish(self):
        record=self.seed.publish();directory=self.get(self.url)
        request=json.loads((self.seed.home/record['request_file']['path']).read_text('utf8'))
        target=self.seed.home/request['font_file']['path'];raw=target.read_bytes();stamp=target.stat()
        finish=HttpReadEvidence.finish
        def mutate(reader):
            target.write_bytes(bytes([raw[0]^1])+raw[1:]);os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return finish(reader)
        try:
            for url in (directory['current']['view_url'],self.url+'?include_current=1'):
                with patch.object(HttpReadEvidence,'finish',mutate),self.assertRaises(HTTPError) as caught:
                    self.get(url)
                self.assertEqual(caught.exception.code,503)
                target.write_bytes(raw)
        finally:target.write_bytes(raw)

    def inherited_source(self,partial=False):
        """建立明确旧评分/旧检查点来源；不靠同名或相同分数模拟继承。"""
        seed=self.seed;s=seed.seed;raw=s.seed
        origin_id='run_'+'c'*32
        current=seed.w.run(seed.w.load(seed.sid),seed.rid)
        origin=deepcopy(current);origin.update(run_id=origin_id,artifact_id='artifact_'+'c'*32)
        pose_path=f'runs/A06/{origin_id}/scores/poses.pdbqt'
        target=seed.home/pose_path;target.parent.mkdir(parents=True)
        target.write_bytes((seed.home/seed.pose['path']).read_bytes())
        from storage import file_record
        seed.pose=file_record(seed.home,target,'scoring_pose')
        execution=json.loads((seed.home/seed.execution['path']).read_text('utf8'))
        execution.update(pose=seed.pose,files=[seed.pose])
        seed.execution=raw.save(f'runs/A06/{origin_id}/scores/execution.json',execution)
        s.packet['pairs'][0]['execution']=seed.execution
        origin_ref=raw.save(f'runs/A06/{origin_id}/run.json',origin)
        refs=[origin_ref,seed.pose,seed.execution]
        if partial:
            checkpoint=raw.save(f'runs/A06/{origin_id}/checkpoint.json',{
                'run_id':origin_id,'key':'pair_000001_region_000001','payload':{'execution':seed.execution}})
            current['inputs']['source_binding']={'partial_recovery':{'run_id':origin_id,'checkpoint_refs':[checkpoint]}}
            refs.append(checkpoint);result_ref=None
        else:
            packet=deepcopy(s.packet);packet.update(run_id=origin_id,inputs=origin['inputs'])
            packet_ref=raw.save(f'runs/A06/{origin_id}/packet.json',packet)
            result_ref=raw.save(f'runs/A06/{origin_id}/result.json',{
                'study_id':seed.sid,'run_id':origin_id,'module_id':'A06',
                'files':[seed.pose,seed.execution,packet_ref],'tables':{'scoring_packet':[packet_ref]}})
            refs.extend([result_ref,packet_ref])
        current['inputs']['source_scoring_run']=origin_ref
        s.packet['inputs']=deepcopy(current['inputs'])
        m=seed.w.load(seed.sid)
        m['runs'][origin_id]={'run_file':origin_ref,'result_file':result_ref}
        m['runs'][seed.rid]['run_file']=raw.save(m['runs'][seed.rid]['run_file']['path'],current)
        seed.w.save(m);seed.save_score()
        m=seed.w.load(seed.sid);result=seed.w.result(m,seed.rid)
        result['files'].extend(refs)
        m['runs'][seed.rid]['result_file']=raw.save(m['runs'][seed.rid]['result_file']['path'],result)
        seed.w.save(m)
        return origin_id,(checkpoint if partial else origin_ref)

    def assert_inherited_zip_proof(self,partial):
        """先验证继承Top-1，再在HTTP末尾保长度/mtime篡改原来源，必须503。"""
        origin_id,ref=self.inherited_source(partial)
        record=self.seed.publish();view=self.get(self.get(self.url)['current']['view_url'])
        accepted=self.get(view['acceptance_url'])
        with urlopen(self.base+accepted['download_url']) as response,zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            self.assertEqual(archive.read('poses/pair_000001/top1.pdbqt'),self.seed.top)
            context=json.loads(archive.read('poses/pair_000001/context.json'))
            self.assertEqual(context['execution_run_id'],origin_id)
        target=self.seed.home/ref['path'];raw=target.read_bytes();stamp=target.stat()
        finish=HttpReadEvidence.finish
        def mutate(reader):
            target.write_bytes(bytes([raw[0]^1])+raw[1:])
            os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return finish(reader)
        try:
            with patch.object(HttpReadEvidence,'finish',mutate),self.assertRaises(HTTPError) as caught:
                urlopen(self.base+accepted['download_url'])
            self.assertEqual(caught.exception.code,503)
        finally:target.write_bytes(raw)
        self.assertEqual(self.seed.w.load(self.seed.sid)['analysis_plan_rescue_presentation_records'],[record['file']])

    def test_actual_zip_finish_rechecks_inherited_original_run(self):
        self.assert_inherited_zip_proof(False)

    def test_actual_zip_finish_rechecks_inherited_checkpoint(self):
        self.assert_inherited_zip_proof(True)
