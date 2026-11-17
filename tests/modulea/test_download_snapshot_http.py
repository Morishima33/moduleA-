"""真实临时HTTP发送同一私有快照，退出SHA失败与客户端断开均释放句柄。"""
from hashlib import sha256
from http.client import HTTPConnection
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from modulea.api.download_snapshot import capture_verified,VerifiedSnapshot
from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.bounded_evidence import file_record
from modulea.core.http_read_evidence import HttpReadEvidence


class DownloadSnapshotHttpTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='完整包HTTP ');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.sid='study_'+'b'*32
        self.home=self.root/'studies'/self.sid;self.home.mkdir(parents=True)
        (self.home/'manifest.json').write_text(json.dumps({'revision':1}),encoding='utf8')
        self.source=self.home/'complete.zip';self.raw=bytes(range(256))*4096;self.source.write_bytes(self.raw)
        self.ref=file_record(self.home,self.source,'archive');self.snapdir=self.root/'runtime/downloads'
        self.issued=[]
        settings=Settings(data_root=self.root,runtime_dir=self.root/'runtime')
        self.server,self.app=create_server(settings,0)
        self.app.dispatch=lambda *_:self.app._json_read(self.sid,self.reply)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def reply(self):
        value=capture_verified(self.home,self.ref,self.snapdir,min_free_bytes=0);self.issued.append(value)
        self.addCleanup(value.close)
        return ('verified_snapshot',value,'合成完整包.zip','application/zip',False)

    def closed(self):
        deadline=time.monotonic()+5
        while self.issued and not self.issued[-1].closed and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(self.issued and self.issued[-1].closed)
        self.assertEqual(list(self.snapdir.rglob('*')),[])

    def test_actual_download_bytes_sha_and_original_security_headers(self):
        before=(self.home/'manifest.json').read_bytes()
        with urlopen(self.base+'/api/v1/test-snapshot') as response:
            self.assertEqual(response.read(),self.raw)
            self.assertEqual(response.headers['X-Content-SHA256'],sha256(self.raw).hexdigest())
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertIn('attachment',response.headers['Content-Disposition'])
        self.closed();self.assertEqual((self.home/'manifest.json').read_bytes(),before)

    def test_origin_path_changed_after_exit_proof_still_sends_exact_verified_snapshot(self):
        finish=HttpReadEvidence.finish
        def change(reader):
            value=finish(reader);self.source.write_bytes(b'x'*len(self.raw));return value
        with patch.object(HttpReadEvidence,'finish',change),urlopen(self.base+'/api/v1/test-snapshot') as response:
            self.assertEqual(response.read(),self.raw)
        self.closed()

    def test_exit_sha_failure_closes_snapshot_before_error_response(self):
        finish=HttpReadEvidence.finish;stamp=self.source.stat()
        def change(reader):
            self.source.write_bytes(b'x'*len(self.raw));os.utime(self.source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return finish(reader)
        with patch.object(HttpReadEvidence,'finish',change),self.assertRaises(HTTPError) as caught:
            urlopen(self.base+'/api/v1/test-snapshot')
        self.assertEqual(caught.exception.code,503);self.closed()

    def test_actual_client_disconnect_releases_snapshot_before_full_transfer(self):
        with self.source.open('wb') as stream:
            for _ in range(32):stream.write(self.raw)
        self.ref=file_record(self.home,self.source,'archive')
        original=VerifiedSnapshot.read;sent=[]
        def counted(value,size):
            raw=original(value,size);sent.append(len(raw));return raw
        with patch.object(VerifiedSnapshot,'read',counted):
            conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
            conn.request('GET','/api/v1/test-snapshot');response=conn.getresponse()
            self.assertEqual(response.status,200);response.close();conn.close();self.closed()
        self.assertLess(sum(sent),self.ref['bytes'])
