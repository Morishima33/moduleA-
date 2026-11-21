"""精确请求快照复用与实时清单变化回退，全部使用隔离原件。"""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from contracts import ContractError
from modulea.core.herb_snapshot_reuse import Snapshot, SnapshotFetcher
from science_modules.a01 import acquisition


class HerbSnapshotTests(TestCase):
    def archives(self, index_sha=None):
        payload = {'func_name':'detail_api','label':'Ingredient','v':'HBIN00001','key_id':'HBIN00001'}
        token = sha256(acquisition.HERB_API.encode() + json.dumps(payload, sort_keys=True).encode()).hexdigest()
        value = {'summary':[['Ingredient id','Ingredient name'],['HBIN00001','Archived compound']],
                 'ingredient_target':[['Target id','Target name','Database sources']]}
        raw = json.dumps(value).encode()
        stream = BytesIO()
        with ZipFile(stream,'w') as archive:
            archive.writestr(f'original_requests/{token}.bin',raw)
            archive.writestr(f'original_requests/{token}.json',json.dumps({
                'url':acquisition.HERB_API,'payload':payload,'sha256':index_sha or sha256(raw).hexdigest(),
                'bytes':len(raw),'retrieved_at':'2026-10-31'}))
        return stream, payload, token, value

    def test_exact_fresh_name_reuses_bytes_once_and_keeps_original_date(self):
        stream,payload,token,value = self.archives()
        with ZipFile(stream) as archive, TemporaryDirectory() as root:
            def offline(*args,**kwargs):
                raise AssertionError('命中的同名成分详情不联网')
            fetcher = SnapshotFetcher(root,offline,lambda _:None,snapshot=Snapshot(archive,{'source':'fixture'}))
            fetcher.ingredient_names['HBIN00001']='Archived compound'
            self.assertEqual(fetcher.herb('detail_api',label='Ingredient',v='HBIN00001',key_id='HBIN00001'),value)
            self.assertEqual(fetcher.reused_requests,1)
            record=json.loads((Path(root)/(token+'.json')).read_bytes())
            self.assertEqual(record['payload'],payload)
            self.assertEqual(record['retrieved_at'],'2026-10-31')
            self.assertEqual(record['reused_archive'],{'source':'fixture'})

    def test_name_change_falls_back_and_digest_mismatch_blocks(self):
        stream,payload,token,value=self.archives()
        with ZipFile(stream) as archive:
            snapshot=Snapshot(archive,{})
            self.assertIsNone(snapshot.detail(token,payload,'Renamed compound'))
            self.assertIsNone(snapshot.detail('0'*64,payload,'Archived compound'))
            with TemporaryDirectory() as root, patch.object(acquisition.Fetcher,'herb',return_value=value) as fresh:
                fetcher=SnapshotFetcher(root,None,None,snapshot=snapshot)
                fetcher.ingredient_names['HBIN00001']='Renamed compound'
                fetcher.herb('detail_api',label='Ingredient',v='HBIN00001',key_id='HBIN00001')
                fresh.assert_called_once()
                self.assertEqual(list(Path(root).iterdir()),[])
        stream,payload,token,_=self.archives(index_sha='0'*64)
        with ZipFile(stream) as archive, self.assertRaisesRegex(ContractError,'指纹'):
            Snapshot(archive,{}).detail(token,payload,'Archived compound')
