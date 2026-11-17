"""同修订矩阵/焦点/下载/ZIP及旧链接隔离；原Workflow状态、合成评分和原MODEL 1字节。"""
from copy import deepcopy
from hashlib import sha256
import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import zipfile

from contracts import fingerprint
from modulea.api.errors import ApiError
from modulea.config import Settings
from tests.modulea.test_rescue_presentation_records import RescuePresentationRecordTests


class RescuePresentationApiTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[2]/'src/modulea/api/rescue_presentations.py'
        self.assertTrue(path.is_file(),'缺少名称修订HTTP读取与显式下载')
        self.api=importlib.import_module('modulea.api.rescue_presentations')
        self.seed=RescuePresentationRecordTests('test_explicit_one_name_consent_and_public_publish_preserve_all_science')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        s=self.seed;self.sid,self.rid,self.w,self.home=s.sid,s.rid,s.w,s.home
        self.settings=Settings(data_root=s.root,runtime_dir=s.root/'runtime',font_regular=s.font)
        self.tasks=SimpleNamespace(active_for=Mock(return_value=None),submit=Mock(return_value=({'task_id':'task_'+'e'*32},True)))
        self.app=SimpleNamespace(settings=self.settings,tasks=self.tasks,
                                 kernel=SimpleNamespace(read_workflow=lambda:self.w,workflow=lambda:self.w))
        self.top=b'MODEL 1\nREMARK VINA RESULT: -7.125 0 0\nATOM synthetic one\nENDMDL\n'
        source=self.top+b'MODEL 2\nREMARK VINA RESULT: -20.0 1 1\nATOM synthetic two\nENDMDL\n'
        folder='runs/A06/'+self.rid+'/scores/pair_000001/'
        self.pose=s.seed.save(folder+'poses.pdbqt',{'unused':True})
        target=self.home/self.pose['path'];target.write_bytes(source)
        from storage import file_record
        self.pose=file_record(self.home,target,'scoring_pose')
        execution={'state':'completed','score':-7.125,'returncode':0,'top_mode':1,'mode_count':2,
                   'pose':self.pose,'files':[self.pose]}
        self.execution=s.seed.save(folder+'execution.json',execution)
        s.packet['pairs'][0]['execution']=self.execution
        self.save_score()

    def save_score(self):
        s=self.seed;ref=s.seed.save('runs/A06/'+self.rid+'/packet.json',s.packet)
        result=s.seed.results['A06'];result.update(files=[self.pose,self.execution,ref],
                tables={'scoring_packet':[ref],'plan_scoring_pairs':deepcopy(s.packet['pairs'])})
        m=self.w.load(self.sid)
        m['runs'][self.rid]['result_file']=s.seed.save('runs/'+self.rid+'/result.json',result);self.w.save(m)

    @staticmethod
    def request(url='',**values):
        query=parse_qs(urlsplit(url).query)
        query.update({key:[value] if isinstance(value,str) else value for key,value in values.items()})
        return SimpleNamespace(query=query,query1=lambda key:query.get(key,[None])[0])

    def publish(self):
        if not self.w.load(self.sid).get(self.seed.model.NAMES):self.seed.approve_name()
        return self.seed.publish()

    def directory(self):return self.api.directory(self.app,self.request(),self.sid,self.rid)

    def query(self,record,**changes):
        return self.request(expected_revision_sha256=record['file']['sha256'],expected_input_key='original',**changes)

    def view(self,record):
        return self.api.view(self.app,self.query(record),self.sid,self.rid,record['revision_id'])

    def test_read_directory_does_not_register_or_generate_and_missing_consent_blocks(self):
        before=self.w.load(self.sid);files=self.seed.original_files();value=self.directory()
        self.assertFalse(value['enabled']);self.assertIsNone(value['current']);self.assertEqual(value['history'],[])
        self.assertEqual(value['translation_missing_ids'],['C2'])
        self.assertEqual(before,self.w.load(self.sid));self.assertEqual(files,self.seed.original_files())

    def test_current_view_and_focus_use_same_explicit_revision_and_keep_na(self):
        record=self.publish();value=self.directory();current=value['current']
        self.assertEqual(current['revision_id'],record['revision_id']);self.assertTrue(current['matches_input'])
        display=self.view(record)
        self.assertEqual(display['schema_version'],'A06.system_rescue.display.3')
        self.assertEqual(display['presentation_revision']['receipt_sha256'],record['file']['sha256'])
        self.assertEqual(display['table']['rows'][0]['name_zh'],'甲成分')
        self.assertEqual(display['table']['rows'][1]['name_scope'],'original_proper_name')
        self.assertEqual(display['table']['cells'][0][0]['score'],-7.125)
        query=self.query(record,compounds=json.dumps(['C2']),targets=json.dumps(['HGNC:1']))
        focused=self.api.focus(self.app,query,self.sid,self.rid,record['revision_id'])
        self.assertEqual(focused['revision_id'],record['revision_id'])
        self.assertEqual(focused['heatmap']['cells'][0][0]['state'],'NA')

    def test_revision_projects_preparation_states_without_mutating_original_rows(self):
        rows=[{'target_id':'HGNC:1','symbol':'GENE','state':'ready'},
              {'target_id':'HGNC:2','symbol':'OTHER','state':'NA','reason_zh':'原准备缺失'}]
        m=self.w.load(self.sid);result=self.w.result(m,self.rid)
        result['tables']['receptor_preparation']=deepcopy(rows)
        m['runs'][self.rid]['result_file']=self.seed.seed.save(m['runs'][self.rid]['result_file']['path'],result)
        self.w.save(m);record=self.publish()
        shown=self.view(record)['receptor_preparation']
        self.assertEqual([row.get('state_zh') for row in shown],['准备可用','准备NA'])
        self.assertEqual(self.w.result(self.w.load(self.sid),self.rid)['tables']['receptor_preparation'],rows)

    def test_old_revision_url_stays_pinned_after_another_revision_is_published(self):
        first=self.publish();second=self.publish()
        self.assertNotEqual(first['revision_id'],second['revision_id'])
        self.assertEqual(self.directory()['current']['revision_id'],second['revision_id'])
        self.assertEqual(self.view(first)['presentation_revision']['revision_id'],first['revision_id'])
        bad=self.request(expected_revision_sha256=second['file']['sha256'],expected_input_key='original')
        with self.assertRaises(ApiError) as error:self.api.view(self.app,bad,self.sid,self.rid,first['revision_id'])
        self.assertEqual(error.exception.status,409)

    def test_download_byte_sha_and_original_na_reasons_are_same_as_view(self):
        record=self.publish();display=self.view(record)
        for index,ref in enumerate(record['files']):
            req=self.query(record,expected_sha256=ref['sha256'])
            reply=self.api.download(self.app,req,self.sid,self.rid,record['revision_id'],str(index))
            self.assertEqual(reply[0],'verified_download')
            self.assertEqual(sha256(reply[1]).hexdigest(),ref['sha256'])
        self.assertEqual(display['table']['cells'][1][0]['reason_zh'],'原服务404；未评分')

    def test_query_overrides_duplicates_stale_bytes_and_foreign_revision_are_rejected(self):
        record=self.publish()
        for req,status in [(self.query(record,path='other'),422),
                           (self.request(expected_revision_sha256=['x','y'],expected_input_key='original'),422),
                           (self.request(expected_revision_sha256=record['file']['sha256'],expected_input_key='changed'),409)]:
            with self.subTest(status=status),self.assertRaises(ApiError) as error:
                self.api.view(self.app,req,self.sid,self.rid,record['revision_id'])
            self.assertEqual(error.exception.status,status)
        with self.assertRaises(ApiError) as error:
            self.api.download(self.app,self.query(record,expected_sha256='f'*64),self.sid,self.rid,record['revision_id'],'0')
        self.assertEqual(error.exception.status,409)
        with self.assertRaises(ApiError) as error:
            self.api.view(self.app,self.query(record),self.sid,self.rid,'rescueview_'+'f'*32)
        self.assertEqual(error.exception.status,404)

    def test_revision_acceptance_zip_keeps_science_and_exact_model_one(self):
        from modulea.api import acceptance_bundle
        record=self.publish();before=self.w.load(self.sid);files=self.seed.original_files()
        req=self.request(revision_id=record['revision_id'],expected_revision_sha256=record['file']['sha256'],expected_input_key='original')
        info=acceptance_bundle.info(self.app,req,self.sid,self.rid)
        self.assertTrue(info['enabled'],info['blockers_zh'])
        self.assertEqual(info['presentation_revision']['revision_id'],record['revision_id'])
        reply=acceptance_bundle.download(self.app,req,self.sid,self.rid)
        with zipfile.ZipFile(io.BytesIO(reply[1])) as archive:
            meta=json.loads(archive.read('验收目录与指纹.json'))
            self.assertEqual(meta['presentation_revision']['receipt_sha256'],record['file']['sha256'])
            self.assertEqual(meta['presentation_revision']['name_counts']['original_proper_name'],1)
            self.assertEqual(archive.read('poses/pair_000001/top1.pdbqt'),self.top)
            self.assertTrue(any(name.startswith('presentation/') and name.endswith('.csv') for name in archive.namelist()))
            for member in meta['files']:
                self.assertEqual(sha256(archive.read(member['path'])).hexdigest(),member['sha256'])
            packet=next(ref for ref in self.seed.seed.results['A06']['files'] if ref['path'].endswith('packet.json'))
            self.assertEqual(json.loads(archive.read('registered/'+packet['path']))['source_fixed']['compounds'][0]['name'],'Alpha')
        self.assertEqual(before,self.w.load(self.sid));self.assertEqual(files,self.seed.original_files())

    def test_no_revision_acceptance_does_not_silently_adopt_new_translation(self):
        from modulea.api import acceptance_bundle
        self.publish()
        original=acceptance_bundle.info(self.app,self.request(),self.sid,self.rid)
        self.assertFalse(original['enabled']);self.assertNotIn('presentation_revision',original)
        self.assertEqual(set(original['translation_missing_ids']),{'C1','C2'})

    def test_large_revision_info_does_not_offer_a_download_that_exceeds_memory_budget(self):
        from modulea.api import acceptance_bundle
        record=self.publish();query=self.request(revision_id=record['revision_id'],
            expected_revision_sha256=record['file']['sha256'],expected_input_key='original')
        with patch.object(acceptance_bundle,'MAX_REGISTERED_BYTES',1):
            value=acceptance_bundle.info(self.app,query,self.sid,self.rid)
        self.assertFalse(value['enabled']);self.assertTrue(value['archive_required'])
        self.assertIn(record['revision_id'],value['archive_url'])
        self.assertIn('完整包','；'.join(value['blockers_zh']))

    def test_scored_pair_missing_execution_cannot_pass_revision_acceptance(self):
        from modulea.api import acceptance_bundle
        self.seed.packet['pairs'][0].pop('execution');self.save_score();record=self.publish()
        req=self.request(revision_id=record['revision_id'],expected_revision_sha256=record['file']['sha256'],expected_input_key='original')
        with self.assertRaises(ApiError) as error:acceptance_bundle.info(self.app,req,self.sid,self.rid)
        self.assertEqual(error.exception.status,503)

    def test_retired_or_paused_revision_remains_historical_and_cannot_submit(self):
        record=self.publish();self.w.review(self.sid,self.rid,'pending','合成科研复核人','明确暂停，仅测试')
        value=self.directory();self.assertFalse(value['enabled']);self.assertIsNone(value['current'])
        display=self.view(record)
        self.assertFalse(display['presentation_revision']['matches_input'])

    def test_strict_publish_request_only_queues_existing_heavy_kind(self):
        self.seed.approve_name();body=self.seed.body();before=self.w.load(self.sid)
        result=self.api.submit(self.app,SimpleNamespace(json=lambda:body),self.sid,self.rid)
        self.assertEqual(result[1],202)
        args=self.tasks.submit.call_args.args
        self.assertEqual(args[:2],(self.sid,'plan_rescue_presentation'))
        self.assertEqual(args[3],{'stage':'publish','request':body})
        self.assertEqual(before,self.w.load(self.sid))
        with self.assertRaises(ApiError) as error:
            self.api.submit(self.app,SimpleNamespace(json=lambda:dict(body,entries=[])),self.sid,self.rid)
        self.assertEqual(error.exception.status,422)

    def test_busy_or_changed_source_never_submits_another_task(self):
        self.seed.approve_name();body=self.seed.body();self.tasks.active_for.return_value={'task_id':'other'}
        with self.assertRaises(ApiError):self.api.submit(self.app,SimpleNamespace(json=lambda:body),self.sid,self.rid)
        self.tasks.submit.assert_not_called()

    def test_reading_existing_revision_does_not_require_local_render_font(self):
        record=self.publish()
        self.app.settings.font_regular=self.seed.root/'not-installed.ttf'
        value=self.directory()
        self.assertIsNotNone(value['current'],'缺本机字体不能隐藏已归档图表')
        self.assertFalse(value['enabled'])
        self.assertEqual(value['current']['revision_id'],record['revision_id'])
        self.assertTrue(self.view(record)['presentation_revision']['matches_input'])

    def test_zip_budget_rejects_before_extracting_or_caching_all_pose_buffers(self):
        from modulea.api import acceptance_bundle
        record=self.publish()
        req=self.request(revision_id=record['revision_id'],expected_revision_sha256=record['file']['sha256'],expected_input_key='original')
        with patch.object(acceptance_bundle,'MAX_REGISTERED_BYTES',1),patch.object(acceptance_bundle,'_artifacts',
                side_effect=AssertionError('超预算前不应提取姿势')):
            with self.assertRaises(ApiError) as caught:acceptance_bundle.download(self.app,req,self.sid,self.rid)
        self.assertEqual(caught.exception.status,503)
        self.assertIn('512MiB',str(caught.exception))
