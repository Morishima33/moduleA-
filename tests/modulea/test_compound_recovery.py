"""名称检索失败后的来源回查；仅使用虚构化学对象和临时目录。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from science_modules.a06.compound_recovery import compound_source, parse_tcmsp
from storage import file_record


KEY = 'AAAAAAAAAAAAAA-BBBBBBBBBB-C'
ROW = {'compound_id': 'MOL000123', 'name': 'Synthetic beta compound'}


def page(**changes):
    """模拟官方页面里的JSON数据，不运行页面脚本。"""
    row = dict(MOL_ID=ROW['compound_id'], molecule_ID='123', molecule_name=ROW['name'],
               inchikey=KEY, pubchem_cid='456')
    row.update(changes)
    return 'var mol = ' + json.dumps([row]) + ';'


class CompoundRecoveryTests(TestCase):
    def test_parser_requires_exact_id_name_and_complete_stereo_key(self):
        self.assertEqual(parse_tcmsp(page(), ROW)['inchikey'], KEY)
        for changes in ({'MOL_ID': 'MOL000124'}, {'molecule_name': 'other'},
                        {'inchikey': KEY[:14]}, {'pubchem_cid': '456,789'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_tcmsp(page(**changes), ROW)
        with self.assertRaises(ValueError):
            parse_tcmsp('<html>new platform homepage CID 456</html>', ROW)

    def fetcher(self, root, *, cid='456', property_key=KEY, missing_3d=False):
        """记录查询路线，并为实际SDF核验保留临时文件。"""
        class Fetch:
            def __init__(self):
                self.root, self.urls = root, []

            def get(self, url, suffix='json'):
                self.urls.append(url)
                if '/name/' in url:
                    raise HTTPError(url, 404, 'NotFound', None, None)
                if 'old.tcmsp-e.com' in url:
                    return page(pubchem_cid=cid), {'path': 'official.html'}
                if '/inchikey/' in url:
                    return {'IdentifierList': {'CID': [456]}}, {'path': 'key.json'}
                if '/property/' in url:
                    return {'PropertyTable': {'Properties': [dict(CID=456, InChIKey=property_key)]}}, {'path': 'properties.json'}
                if missing_3d:
                    raise HTTPError(url, 404, 'NotFound', None, None)
                path = root / 'source.sdf'
                path.write_text('synthetic SDF', encoding='utf-8')
                return {}, file_record(root, path, 'synthetic_sdf')
        return Fetch()

    def test_exact_source_cid_recovers_name_404_without_loosening_audit(self):
        with TemporaryDirectory() as folder, patch('docking_audit.ligand_identity', return_value={'checked': True}) as audit:
            fetch = self.fetcher(Path(folder))
            result = compound_source(ROW, fetch)
            self.assertEqual(result['cid'], 456)
            self.assertEqual(result['identity_resolution']['method'], 'tcmsp_exact_identity')
            audit.assert_called_once_with('synthetic SDF', 456, KEY)
            self.assertFalse(any('/similarity/' in u for u in fetch.urls))

    def test_missing_cid_uses_exact_full_inchikey(self):
        with TemporaryDirectory() as folder, patch('docking_audit.ligand_identity', return_value={}):
            fetch = self.fetcher(Path(folder), cid='')
            self.assertEqual(compound_source(ROW, fetch)['cid'], 456)
            self.assertTrue(any('/inchikey/' + KEY in u for u in fetch.urls))

    def test_stereo_mismatch_stops_before_sdf_and_404_is_stage_specific(self):
        with TemporaryDirectory() as folder:
            fetch = self.fetcher(Path(folder), property_key='AAAAAAAAAAAAAA-CCCCCCCCCC-C')
            with self.assertRaisesRegex(ValueError, '化学身份'):
                compound_source(ROW, fetch)
            self.assertFalse(any('/SDF' in u for u in fetch.urls))
            with self.assertRaisesRegex(ValueError, '三维下载'):
                compound_source(ROW, self.fetcher(Path(folder), missing_3d=True))

    def test_network_failure_does_not_masquerade_as_not_found(self):
        class Fetch:
            def get(self, *args):
                raise TimeoutError('network timeout')
        with self.assertRaisesRegex(ValueError, '名称检索.*network timeout'):
            compound_source(ROW, Fetch())
