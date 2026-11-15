"""验收包只整理同批既有图件与构象；缺译、损坏或跨批附件明确阻断。"""
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import zipfile

from modulea.api import acceptance_bundle
from modulea.api.errors import ApiError
from tests.modulea.test_rescue_evidence_http import RescueEvidenceHttpTests


class AcceptanceBundleTests(unittest.TestCase):
    def setUp(self):
        self.seed=RescueEvidenceHttpTests('test_actual_http_download_sha_and_read_only_manifest')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        font=os.environ.get('MODULEA_TEST_FONT')
        if not font:
            candidates=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc',
                        Path('/System/Library/Fonts/Supplemental/Songti.ttc')]
            font=next((str(path) for path in candidates if path.is_file()),None)
        if not font:raise unittest.SkipTest('实际PNG/SVG核验需要明确可用的中文字体')
        from science_modules.a06.system_rescue_display_v2 import export
        s=self.seed
        s.packet['summary']['message_zh']='合成同批验收包测试'
        folder=s.case.home/f'runs/A06/{s.rid}/rescue/display'/('display_'+'f'*32)
        figures,attachments=export(s.case.home,s.packet,folder,font_path=font)
        s.files.extend(figures+attachments);s.save()
        self.empty=SimpleNamespace(query={},query1=lambda _:None)
        self.req=SimpleNamespace(query={'expected_input_key':['original']},query1=lambda _:'original')

    def test_zip_member_fingerprints_and_original_top1_without_new_study_files(self):
        s=self.seed
        before={p.relative_to(s.case.home).as_posix():p.read_bytes() for p in s.case.home.rglob('*') if p.is_file()}
        value=acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertTrue(value['enabled'],value)
        answer=acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        with zipfile.ZipFile(io.BytesIO(answer[1])) as archive:
            manifest=json.loads(archive.read('验收目录与指纹.json'))
            self.assertEqual(manifest['run_id'],s.rid)
            for row in manifest['files']:
                raw=archive.read(row['path'])
                self.assertEqual(len(raw),row['bytes'])
                self.assertEqual(sha256(raw).hexdigest(),row['sha256'])
            top=archive.read('poses/pair_000001/top1.pdbqt')
            self.assertIn(b'MODEL 1',top);self.assertNotIn(b'MODEL 2',top)
            self.assertFalse(any(name.endswith('.docx') for name in archive.namelist()))
        after={p.relative_to(s.case.home).as_posix():p.read_bytes() for p in s.case.home.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_missing_translation_blocks_final_delivery(self):
        s=self.seed
        # 只测试门控函数，原科学包和已登记展示不改写；缺译必须独立列明。
        bundle=list(acceptance_bundle.load_bundle(s.app,s.sid,s.rid))
        bundle[5]=deepcopy(bundle[5]);bundle[5]['source_fixed']['compounds'][0]['name']='Untranslated identity'
        bundle[4]=deepcopy(bundle[4]);bundle[4]['files']=[ref for ref in bundle[4]['files'] if not
            ref.get('role','').startswith('plot_a06_rescue_') and ref.get('role') not in
            ('a06_rescue_matrix_csv','a06_rescue_display_view')]
        value=acceptance_bundle.assess(bundle)
        self.assertFalse(value['enabled'])
        self.assertEqual(value['translation_missing_ids'],['C1'])
        self.assertTrue(any('核译' in note for note in value['blockers_zh']))

    def test_missing_current_figure_is_blocked_without_generating_it(self):
        s=self.seed
        s.files=[r for r in s.files if r.get('role')!='plot_a06_rescue_focus_png'];s.save()
        value=acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertFalse(value['enabled'])
        with self.assertRaises(ApiError) as caught:acceptance_bundle.download(s.app,self.req,s.sid,s.rid)
        self.assertEqual(caught.exception.status,409)

    def test_corrupt_registered_csv_is_not_regenerated(self):
        s=self.seed
        ref=next(r for r in s.files if r.get('role')=='a06_rescue_matrix_csv')
        path=s.case.home/ref['path'];path.write_bytes(b'wrong')
        with self.assertRaises(ApiError) as caught:acceptance_bundle.info(s.app,self.empty,s.sid,s.rid)
        self.assertEqual(caught.exception.status,503)
        self.assertEqual(path.read_bytes(),b'wrong')


if __name__=='__main__':unittest.main()
