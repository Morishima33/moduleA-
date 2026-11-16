"""原生真实生产编排的合成矩阵、构象下载与跨批保护；不写任何实际研究。"""
from hashlib import sha256
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
from unittest import TestCase

from modulea.api.errors import ApiError
from contracts import ContractError
from storage import read_json,verified_file
from tests.modulea import test_native_execution as fixture


class NativeResultsTests(TestCase):
    def test_full_matrix_top1_download_and_binding_are_readonly(self):
        seed=fixture.NativeExecutionTests('test_scoring_keeps_full_matrix_actual_model1_and_reuses_after_publication_stop')
        seed.setUp();self.addCleanup(seed.doCleanups)
        seed.test_scoring_keeps_full_matrix_actual_model1_and_reuses_after_publication_stop()
        w=seed.w;sid=seed.sid;manifest=w.load(sid);rid=manifest['current']['A06']
        before={p:p.read_bytes() for p in w.location(sid).rglob('*') if p.is_file()}
        page=seed.base.app.views.module(sid,'A06')
        self.assertIn('native_scores',page['special'],'本机新协议评分须显示同批矩阵和构象证据')
        self.assertIsNone(page.get('docking_candidates'),'新评分不能显示旧候选阶段或尚未启动提示')
        view=page['special']['native_scores']
        self.assertEqual(len(view['table']['rows']),2);self.assertEqual(len(view['table']['columns']),2)
        cells=[cell for line in view['table']['cells'] for cell in line]
        self.assertEqual(sum(c['score'] is None for c in cells),3)
        cell=next(c for c in cells if c['score'] is not None)
        self.assertEqual(cell['score'],-1.25)
        self.assertTrue(all(c['reason_zh'] for c in cells if c['score'] is None))
        link=next(link for link in cell['downloads'] if link['label_zh']=='Top-1构象')
        query=parse_qs(urlsplit(link['url']).query)
        req=SimpleNamespace(query=query,query1=lambda key:query[key][0])
        from modulea.api.native_results import top1
        downloaded=top1(seed.base.app,req,sid,rid,'1','top1.pdbqt')
        self.assertEqual(downloaded[0],'download');raw=downloaded[1]
        self.assertEqual(raw.splitlines()[0],b'MODEL 1');self.assertEqual(raw.splitlines()[-1],b'ENDMDL')
        self.assertNotIn(b'MODEL 2',raw)
        result=w.result(manifest,rid);fact=read_json(verified_file(w.location(sid),result['tables']['scoring_packet'][0]))
        execution=read_json(verified_file(w.location(sid),fact['pairs'][0]['execution']))
        original=verified_file(w.location(sid),execution['pose']).read_bytes()
        self.assertIn(b'MODEL 2',original);self.assertTrue(original.startswith(raw))
        context=top1(seed.base.app,req,sid,rid,'1','context.json')
        import json
        value=json.loads(context[1]);self.assertEqual(value['top1_sha256'],sha256(raw).hexdigest())
        self.assertEqual(value['source_pose_sha256'],sha256(original).hexdigest())
        self.assertEqual(w.load(sid),manifest)
        self.assertEqual(before,{p:p.read_bytes() for p in w.location(sid).rglob('*') if p.is_file()})
        for key in query:
            actual=query[key];query[key]=['0'*64]
            with self.subTest(changed=key),self.assertRaises(ApiError):top1(seed.base.app,req,sid,rid,'1','top1.pdbqt')
            query[key]=actual
        with self.assertRaises(ApiError):top1(seed.base.app,req,sid,rid,'2','top1.pdbqt')
        pose=verified_file(w.location(sid),execution['pose']);pose.write_bytes(original.replace(b'-1.25',b'-9.99',1))
        with self.assertRaises((ApiError,ContractError)):top1(seed.base.app,req,sid,rid,'1','top1.pdbqt')
