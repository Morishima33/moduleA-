"""完整包真实临时HTTP：目录/原重任务/快照ZIP及发送前全部原件SHA，纯合成资料。"""
import io
import json
import os
import threading
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from urllib.parse import urlencode
import zipfile

from modulea.api.server import create_server
from modulea.core.http_read_evidence import HttpReadEvidence
from tests.modulea.test_rescue_acceptance_archive_api import RescueAcceptanceArchiveApiTests


class RescueAcceptanceArchiveHttpTests(TestCase):
    def setUp(self):
        self.seed=RescueAcceptanceArchiveApiTests('test_directory_refresh_does_not_write_and_completed_zip_is_explicitly_bound')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        self.sid,self.rid,self.revision=self.seed.sid,self.seed.rid,self.seed.revision
        self.server,self.app=create_server(self.seed.app.settings,0)
        self.app.kernel=self.seed.app.kernel;self.app.tasks=self.seed.app.tasks
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.path=f'/api/v1/studies/{self.sid}/runs/{self.rid}/rescue-presentations/{self.revision}/acceptance-archives'
        self.url=self.path+'?'+urlencode({'expected_revision_sha256':self.seed.seed.graph['file']['sha256'],'expected_input_key':'original'})

    def get(self,url):
        with urlopen(self.base+url) as response:return json.load(response)

    def test_actual_directory_and_snapshot_download_preserve_same_revision_model_and_no_get_write(self):
        record=self.seed.seed.publish();w=self.seed.seed.w;before=w.load(self.sid)
        files=self.seed.seed.seed.seed.original_files()
        info=self.get(self.url);current=info['current']
        self.assertEqual(current['archive_id'],record['archive_id'])
        with urlopen(self.base+current['download_url']) as response:
            self.assertEqual(response.headers['X-Content-SHA256'],record['archive_file']['sha256'])
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                metadata=json.loads(archive.read('验收目录与指纹.json'))
                self.assertEqual(metadata['presentation_revision']['revision_id'],self.revision)
                self.assertEqual(archive.read('poses/pair_000001/top1.pdbqt'),self.seed.seed.seed.top)
        self.assertEqual(w.load(self.sid),before);self.assertEqual(self.seed.seed.seed.seed.original_files(),files)
        self.app.tasks.submit.assert_not_called()

    def test_actual_post_keeps_origin_token_and_only_returns_202_for_strict_request(self):
        body=self.seed.seed.body()
        def post(headers,payload=body):
            return urlopen(Request(self.base+self.path,data=json.dumps(payload).encode('utf8'),
                headers=dict({'Content-Type':'application/json'},**headers),method='POST'))
        for headers in ({'Origin':self.base},{'Origin':'https://example.invalid','X-ModuleA-Token':self.app.token}):
            with self.assertRaises(HTTPError) as caught:post(headers)
            self.assertEqual(caught.exception.code,403)
        headers={'Origin':self.base,'X-ModuleA-Token':self.app.token}
        with self.assertRaises(HTTPError) as caught:post(headers,dict(body,path='other'))
        self.assertEqual(caught.exception.code,422);self.app.tasks.submit.assert_not_called()
        with post(headers) as response:self.assertEqual(response.status,202)
        self.assertEqual(self.app.tasks.submit.call_args.args[3],{'stage':'archive','request':body})

    def test_actual_finish_rejects_archive_change_and_releases_created_download_snapshot(self):
        record=self.seed.seed.publish();url=self.get(self.url)['current']['download_url']
        target=self.seed.seed.home/record['archive_file']['path'];stamp=target.stat();issued=[]
        original=self.seed.api.capture_verified;finish=HttpReadEvidence.finish
        def capture(*args,**kwargs):
            value=original(*args,**kwargs);issued.append(value);return value
        def corrupt(reader):
            with target.open('r+b') as stream:raw=stream.read(1);stream.seek(0);stream.write(bytes([raw[0]^1]))
            os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns));return finish(reader)
        with patch.object(self.seed.api,'capture_verified',capture),patch.object(HttpReadEvidence,'finish',corrupt),self.assertRaises(HTTPError) as caught:
            urlopen(self.base+url)
        self.assertEqual(caught.exception.code,503)
        self.assertTrue(issued and all(value.closed for value in issued))
