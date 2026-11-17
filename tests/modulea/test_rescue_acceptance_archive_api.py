"""完整包显式目录、原任务POST和快照下载；同图表SHA及原MODEL 1保持。"""
from hashlib import sha256
import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
import zipfile

from modulea.api.errors import ApiError
from tests.modulea.test_rescue_acceptance_archives import RescueAcceptanceArchivesTests


class RescueAcceptanceArchiveApiTests(TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[2]/'src/modulea/api/rescue_acceptance_archives.py'
        self.assertTrue(path.is_file(),'缺少完整包明确HTTP目录/任务/下载接线')
        self.api=importlib.import_module('modulea.api.rescue_acceptance_archives')
        self.seed=RescueAcceptanceArchivesTests('test_info_is_read_only_and_complete_publication_preserves_scientific_records')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        s=self.seed;self.sid,self.rid,self.revision=s.sid,s.rid,s.graph['revision_id']
        self.app=s.seed.app;self.app.settings.compute_min_free_bytes=0

    def req(self,url='',**change):return self.seed.seed.request(url,**change)

    def pinned(self,**change):
        return self.req(expected_revision_sha256=self.seed.graph['file']['sha256'],expected_input_key='original',**change)

    def directory(self):return self.api.directory(self.app,self.pinned(),self.sid,self.rid,self.revision)

    def test_directory_refresh_does_not_write_and_completed_zip_is_explicitly_bound(self):
        before=self.seed.w.load(self.sid);files=self.seed.seed.seed.original_files()
        self.assertTrue(self.directory()['enabled']);self.assertTrue(self.directory()['matches_input'])
        self.assertIsNone(self.directory()['current'])
        self.assertEqual(self.seed.w.load(self.sid),before);self.assertEqual(self.seed.seed.seed.original_files(),files)
        record=self.seed.publish();current=self.directory()['current']
        self.assertEqual(current['archive_id'],record['archive_id'])
        self.assertEqual(current['archive_sha256'],record['archive_file']['sha256'])
        result=self.api.download(self.app,self.req(current['download_url']),self.sid,self.rid,self.revision,record['archive_id'])
        self.assertEqual(result[0],'verified_snapshot');snapshot=result[1];raw=[]
        try:
            while block:=snapshot.read(256*1024):raw.append(block)
            data=b''.join(raw);self.assertEqual(sha256(data).hexdigest(),current['archive_sha256'])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(archive.read('poses/pair_000001/top1.pdbqt'),self.seed.seed.top)
                self.assertEqual(json.loads(archive.read('验收目录与指纹.json'))['presentation_revision']['revision_id'],self.revision)
        finally:snapshot.close()

    def test_strict_post_only_queues_original_archive_stage_without_writing(self):
        before=self.seed.w.load(self.sid);body=self.seed.body()
        result=self.api.submit(self.app,SimpleNamespace(query={},json=lambda:body),self.sid,self.rid,self.revision)
        self.assertEqual(result[1],202)
        args=self.app.tasks.submit.call_args.args
        self.assertEqual(args[:2],(self.sid,'plan_rescue_presentation'))
        self.assertEqual(args[3],{'stage':'archive','request':body})
        self.assertEqual(self.seed.w.load(self.sid),before)
        with self.assertRaises(ApiError) as caught:
            self.api.submit(self.app,SimpleNamespace(query={},json=lambda:dict(body,path='foreign')),self.sid,self.rid,self.revision)
        self.assertEqual(caught.exception.status,422)

    def test_unknown_repeated_or_stale_query_cannot_select_another_archive(self):
        record=self.seed.publish();current=self.directory()['current']
        for query,status in [(self.req(current['download_url'],path='outside'),422),
                             (self.req(current['download_url'],expected_archive_sha256='f'*64),409),
                             (self.req(current['download_url'],expected_input_key=['original','other']),422)]:
            with self.subTest(status=status),self.assertRaises(ApiError) as caught:
                self.api.download(self.app,query,self.sid,self.rid,self.revision,record['archive_id'])
            self.assertEqual(caught.exception.status,status)

    def test_pause_keeps_historical_download_but_blocks_generation(self):
        record=self.seed.publish();self.seed.w.review(self.sid,self.rid,'pending','合成暂停','本批勿新生成')
        value=self.directory();self.assertFalse(value['enabled']);self.assertIsNone(value['current'])
        self.assertFalse(value['history'][0]['matches_input'])
        reply=self.api.download(self.app,self.req(value['history'][0]['download_url']),self.sid,self.rid,self.revision,record['archive_id'])
        reply[1].close()
