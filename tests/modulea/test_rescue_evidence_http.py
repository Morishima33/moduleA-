"""继承评分、稳定对象、区域失败及实际HTTP字节下载回归；全部使用合成归档。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from storage import read_json, verified_file, write_json
from modulea.api import rescue_evidence
from modulea.api.errors import ApiError
from modulea.api.server import create_server
from modulea.config import Settings
from tests.modulea.test_foundation_evidence import EvidenceFixture


class RescueEvidenceHttpTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='构象 证据 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sid = 'study_' + 'a' * 32
        self.case = EvidenceFixture(self.root / 'studies' / self.sid)
        c = self.case
        self.rid = 'run_' + 'd' * 32
        self.run = deepcopy(c.run)
        self.run.update(run_id=self.rid, config=dict(c.config, version='A06.system_rescue.2'))
        self.run['inputs']['source_scoring_run'] = c.run_ref
        self.packet = {'schema_version': 'A06.system_rescue.2', 'study_id': self.sid, 'run_id': self.rid,
                       'inputs': self.run['inputs'], 'configuration': self.run['config'],
                       'source_fixed': c.fixed, 'compounds': deepcopy(c.fixed['compounds']),
                       'receptors': deepcopy(c.fixed['receptors']), 'pairs': [deepcopy(c.pair)],
                       'summary': {'input_key': c.fixed['input_key'], 'science_version': 'A06.system_rescue.2'},
                       'reused_pair_keys': [['C1', 'HGNC:1']], 'new_pair_keys': []}
        self.files = deepcopy(c.files)
        self.manifest = deepcopy(c.manifest)
        # 原fixture结果只有表索引，补上真实附件登记，以便实际原执行追溯校验。
        c.result['files'] = [*c.files, c.score_ref]
        self.manifest['runs'][c.score_id]['result_file'] = c.json('score_result.json', c.result)
        self.save()
        reader = SimpleNamespace(root=self.root, location=lambda sid: c.location(sid),
            load=lambda sid: read_json(c.home / 'manifest.json'),
            run=lambda m, rid: read_json(verified_file(c.home, m['runs'][rid]['run_file'])),
            result=lambda m, rid: read_json(verified_file(c.home, m['runs'][rid]['result_file'])))
        self.app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: reader))

    def save(self):
        """显式建立本次测试的完整登记，篡改用例也必须更新到真实文件字节。"""
        c = self.case
        self.packet['files'] = deepcopy(self.files)
        ref = c.json(f'runs/A06/{self.rid}/rescue/packets/packet.json', self.packet)
        result = {'study_id': self.sid, 'run_id': self.rid, 'summary': self.packet['summary'],
                  'files': self.files + [ref], 'tables': {'scoring_packet': [ref],
                  'plan_scoring_pairs': deepcopy(self.packet['pairs'])}}
        self.manifest['runs'][self.rid] = {
            'run_file': c.json(f'runs/A06/{self.rid}/run.json', self.run),
            'result_file': c.json(f'runs/A06/{self.rid}/result.json', result)}
        write_json(c.home / 'manifest.json', self.manifest, replace=True)

    def request(self, **changes):
        query = {'compound_id': ['C1'], 'target_id': ['HGNC:1'], 'expected_input_key': ['original']}
        query.update({k: [v] for k, v in changes.items()})
        return SimpleNamespace(query=query, query1=lambda key: query.get(key, [None])[0])

    def details(self):
        return rescue_evidence.read(self.app, self.request(), self.sid, self.rid, 'details')

    def test_inherited_score_has_exact_model_one_source_context_and_no_invented_regions(self):
        value = self.details()
        self.assertEqual(value['regions'], [])
        self.assertIn('未登记', value['region_note_zh'])
        self.assertEqual(value['context']['execution_run_id'], self.case.score_id)
        self.assertEqual(value['context']['score'], -7.125)
        links = {row['name']: row for row in value['downloads']}
        top = links['top1.pdbqt']
        source = links['original_poses.pdbqt']
        self.assertNotEqual(top['sha256'], source['sha256'])
        for link in value['downloads']:
            parts = urlsplit(link['url'])
            query = parse_qs(parts.query)
            req = SimpleNamespace(query=query, query1=lambda key: query.get(key, [None])[0])
            raw = rescue_evidence.read(self.app, req, self.sid, self.rid, parts.path.rsplit('/', 1)[-1])[1]
            self.assertEqual(sha256(raw).hexdigest(), link['sha256'])
            self.assertEqual(len(raw), link['bytes'])
            if link is top:
                self.assertIn(b'MODEL 1', raw)
                self.assertNotIn(b'MODEL 2', raw)

    def test_production_rescue_without_duplicate_batch_field_reads_pinned_preparation(self):
        # 真实producer的_begin不复制batch_file；原批次只能沿明确父准备和固定输入追溯。
        self.run.pop('batch_file')
        self.run['inputs']['source_preparation_run']=self.case.prep_run_ref
        self.run['inputs']['source_preparation_result']=self.case.prep_result_ref
        self.save()
        self.assertEqual(self.details()['score'],-7.125)

    def test_rescue_without_batch_field_rejects_re_registered_foreign_preparation(self):
        self.run.pop('batch_file')
        self.run['inputs']['source_preparation_run']=self.case.prep_run_ref
        self.run['inputs']['source_preparation_result']=self.case.prep_result_ref
        self.case.prep_run['batch_file']=dict(self.case.batch,sha256='f'*64)
        changed=self.case.json(self.case.prep_run_ref['path'],self.case.prep_run)
        self.run['inputs']['source_preparation_run']=changed
        self.manifest['runs'][self.case.prep_id]['run_file']=changed
        self.save()
        with self.assertRaises(ApiError):self.details()

    def test_failed_region_keeps_combination_score_and_selected_success(self):
        c = self.case
        failed = dict(c.execution, state='failed', score=None, top_mode=None, mode_count=0,
                      returncode=2, failure_kind='tool_error', reason_zh='合成区域工具返回2', files=[])
        failed.pop('pose')
        ref = c.json(c.folder + '/failed_execution.json', failed)
        self.files.append(ref)
        pair = self.packet['pairs'][0]
        pair.update(region_id='region_one', partial_regions=True, regions=[
            {'region_id': 'region_one', 'state': 'completed', 'score': pair['score'],
             'reason_zh': '', 'execution': c.execution_ref},
            {'region_id': 'region_two', 'state': 'failed', 'score': None,
             'reason_zh': failed['reason_zh'], 'execution': ref}])
        c.score_packet['pairs'] = [deepcopy(pair)]
        c.score_ref = c.json(f'runs/A06/{c.score_id}/system_scoring/packets/packet_test.json', c.score_packet)
        c.result['tables']['scoring_packet'] = [c.score_ref]
        c.result['files'].append(c.score_ref)
        self.manifest['runs'][c.score_id]['result_file'] = c.json('score_result.json', c.result)
        self.save()
        value = self.details()
        self.assertEqual(value['state'], 'completed')
        self.assertEqual(value['score'], -7.125)
        self.assertEqual([row['selected'] for row in value['regions']], [True, False])
        self.assertEqual(value['regions'][1]['reason_zh'], failed['reason_zh'])
        self.assertTrue(value['regions'][1]['downloads'])

    def make_current_score(self):
        """构造本轮真实登记的合成执行，不借用旧运行的成功归属。"""
        c = self.case
        pose = c.save(f'runs/A06/{self.rid}/rescue/poses.pdbqt',
                      (c.home / c.pose['path']).read_text('utf-8'), 'scoring_pose')
        execution = dict(c.execution, pose=pose, files=[c.command_ref, pose])
        ref = c.json(f'runs/A06/{self.rid}/rescue/execution.json', execution)
        self.files.extend([pose, ref])
        self.packet['pairs'][0]['execution'] = ref
        self.packet.update(reused_pair_keys=[], new_pair_keys=[['C1', 'HGNC:1']])
        self.save()

    def test_current_score_context_uses_registered_generation_and_exact_model_one(self):
        self.make_current_score()
        before = (self.case.home / 'manifest.json').read_bytes()
        value = self.details()
        self.assertEqual(value['context']['execution_run_id'], self.rid)
        self.assertIn('本轮新增评分', value['source_zh'])
        self.assertNotIn('沿用', value['source_zh'])
        link = next(row for row in value['downloads'] if row['name'] == 'context.json')
        query = parse_qs(urlsplit(link['url']).query)
        req = SimpleNamespace(query=query, query1=lambda key: query.get(key, [None])[0])
        raw = rescue_evidence.read(self.app, req, self.sid, self.rid, 'context')[1]
        self.assertEqual(json.loads(raw)['source_zh'], value['source_zh'])
        self.assertEqual(sha256(raw).hexdigest(), link['sha256'])
        self.assertEqual(value['context']['top1_sha256'],
                         sha256(rescue_evidence._top1((self.case.home / self.case.pose['path']).read_bytes(), -7.125)).hexdigest())
        old_context = dict(value['context'], source_zh='来自已登记实际执行的MODEL 1原字节；沿用评分不计为本轮新增。')
        old_raw = json.dumps(old_context, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
        query['expected_download_sha256'] = [sha256(old_raw).hexdigest()]
        with self.assertRaises(ApiError) as caught:
            rescue_evidence.read(self.app, req, self.sid, self.rid, 'context')
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual((self.case.home / 'manifest.json').read_bytes(), before)

    def test_checkpoint_recovered_score_is_reused_even_when_source_kind_is_rescue(self):
        c = self.case
        self.manifest['runs'][c.score_id]['result_file'] = None
        checkpoint = c.json(f'runs/A06/{c.score_id}/checkpoint.json',
                            {'run_id': c.score_id, 'key': 'pair_000001_region_000001',
                             'payload': {'execution': c.execution_ref}})
        self.run['inputs']['source_binding'] = {
            'partial_recovery': {'run_id': c.score_id, 'checkpoint_refs': [checkpoint]}}
        self.packet['pairs'][0]['source_kind'] = 'rescue'
        self.save()
        value = self.details()
        self.assertIn('沿用已核验评分', value['source_zh'])
        self.assertNotIn('；本轮新增评分', value['source_zh'])
        self.assertEqual(value['context']['execution_run_id'], c.score_id)

    def test_ambiguous_or_missing_generation_is_rejected(self):
        cases = [([], []), ([['C1', 'HGNC:1']], [['C1', 'HGNC:1']]),
                 ([['C1', 'HGNC:1'], ['C1', 'HGNC:1']], []),
                 ([['unknown', 'HGNC:1']], []), (None, [])]
        for reused, new in cases:
            with self.subTest(reused=reused, new=new):
                self.packet.update(reused_pair_keys=reused, new_pair_keys=new)
                self.save()
                with self.assertRaises(ApiError) as caught:
                    self.details()
                self.assertEqual(caught.exception.status, 503)

    def test_first_protocol_uses_original_source_category_without_round_sets(self):
        self.run['config']['version'] = self.packet['schema_version'] = 'A06.system_rescue.1'
        self.packet.pop('reused_pair_keys')
        self.packet.pop('new_pair_keys')
        for kind, note in [('original', '沿用已核验评分'), ('rescue', '本轮新增评分')]:
            with self.subTest(kind=kind):
                self.packet['pairs'][0]['source_kind'] = kind
                self.save()
                self.assertIn(note, self.details()['source_zh'])

    def test_stale_input_unknown_object_and_path_override_fail(self):
        for change, status in (({'expected_input_key': 'other'}, 409),
                               ({'compound_id': 'same-name-but-another-ID'}, 404),
                               ({'path': '/tmp/anything'}, 422)):
            with self.subTest(change=change), self.assertRaises(ApiError) as caught:
                rescue_evidence.read(self.app, self.request(**change), self.sid, self.rid, 'details')
            self.assertEqual(caught.exception.status, status)

    def test_pose_change_or_foreign_batch_cannot_keep_evidence(self):
        self.case.save(self.case.pose['path'], 'corrupted original pose')
        with self.assertRaises(ApiError) as caught:
            self.details()
        self.assertEqual(caught.exception.status, 503)

    def test_re_registered_foreign_origin_batch_is_rejected(self):
        origin = deepcopy(self.case.run)
        origin['batch_file'] = {'path': 'another-batch.json', 'bytes': 1, 'sha256': 'f' * 64}
        ref = self.case.json(f'runs/A06/{self.case.score_id}/run.json', origin)
        self.manifest['runs'][self.case.score_id]['run_file'] = ref
        self.run['inputs']['source_scoring_run'] = ref
        self.save()
        with self.assertRaises(ApiError) as caught:
            self.details()
        self.assertEqual(caught.exception.status, 503)

    def test_another_pair_with_equal_score_cannot_replace_original_execution(self):
        other = self.case.json(self.case.folder + '/another_execution.json', self.case.execution)
        self.files.append(other)
        self.packet['pairs'][0]['execution'] = other
        self.save()
        with self.assertRaises(ApiError) as caught:
            self.details()
        self.assertEqual(caught.exception.status, 503)

    def test_standard_attachment_download_binds_actual_bytes_and_page_sha(self):
        index = next(i for i, ref in enumerate(self.files) if ref['path'] == self.case.pose['path'])
        query = {'expected_sha256': [self.case.pose['sha256']]}
        req = SimpleNamespace(query=query, query1=lambda key: query.get(key, [None])[0])
        value = rescue_evidence.file_download(self.app, req, self.sid, f'{self.rid}.{index}')
        self.assertEqual(sha256(value[1]).hexdigest(), self.case.pose['sha256'])
        query['expected_sha256'] = ['0' * 64]
        with self.assertRaises(ApiError) as caught:
            rescue_evidence.file_download(self.app, req, self.sid, f'{self.rid}.{index}')
        self.assertEqual(caught.exception.status, 409)

    def test_actual_http_download_sha_and_read_only_manifest(self):
        server, app = create_server(Settings(data_root=self.root, runtime_dir=self.root / 'runtime'), 0)
        app.kernel = self.app.kernel
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        before = (self.case.home / 'manifest.json').read_bytes()
        base = f'http://127.0.0.1:{server.server_port}'
        url = rescue_evidence.evidence_url(self.sid, self.rid, self.packet['pairs'][0], 'original')
        with urlopen(base + url) as response:
            value = json.load(response)
        for file in value['downloads']:
            with urlopen(base + file['url']) as response:
                raw = response.read()
            self.assertEqual(sha256(raw).hexdigest(), file['sha256'])
        self.assertEqual((self.case.home / 'manifest.json').read_bytes(), before)
        with self.assertRaises(HTTPError) as caught:
            urlopen(base + url + '&path=anything')
        self.assertEqual(caught.exception.code, 422)

    def test_focus_is_backend_ordered_empty_safe_and_same_batch(self):
        query = {'expected_input_key': ['original'], 'compounds': ['["C1"]'], 'targets': ['["HGNC:1"]']}
        req = SimpleNamespace(query=query, query1=lambda key: query.get(key, [None])[0])
        value = rescue_evidence.focus(self.app, req, self.sid, self.rid)
        self.assertEqual(value['heatmap']['cells'][0][0]['score'], -7.125)
        query['compounds'] = ['[]']
        self.assertEqual(rescue_evidence.focus(self.app, req, self.sid, self.rid)['heatmap']['rows'], [])
        query['targets'] = ['["unknown"]']
        with self.assertRaises(ApiError):
            rescue_evidence.focus(self.app, req, self.sid, self.rid)


if __name__ == '__main__':
    unittest.main()
