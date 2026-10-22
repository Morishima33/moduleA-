"""官方采集边界：固定来源、原件缓存、格式漂移与known隔离。"""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from contracts import ContractError
from science_modules.a01.acquisition import acquire, Fetcher, BATMAN, _arrays, _human_target


class Response(io.BytesIO):
    status=200
    def __init__(self,raw,url):
        super().__init__(raw);self.url=url;self.headers={'Content-Length':str(len(raw))}
    def geturl(self):return self.url


class AcquisitionTests(unittest.TestCase):
    def test_herb_full_chain_uses_shared_package_validator(self):
        responses={
            'search_api':{'res_data':[['Herb id','Herb pinyin name','Herb Chinese name'],[{'title':'HERB1'},'TEST','测试药']]},
            'browse_api':{'total_num':1,'browse_data':[['Target id','Gene name','Gene alias'],[{'title':'HBTAR1'},'A','']]}}
        def opener(req,timeout):
            p=json.loads(req.data)
            if p['func_name']=='detail_api' and p['label']=='Herb':
                value={'summary':[['Herb id','Herb pinyin name','Herb Chinese name'],['HERB1','TEST','测试药']], 'herb_ingredient':[['Ingredient id','Ingredient name'],[{'title':'HBIN1'},'Compound']]}
            elif p['func_name']=='detail_api':
                value={'summary':[['Ingredient id','Ingredient name','Molecule formula','TCMSP id','PubChem id'],['HBIN1','Compound','C1',{'title':'MOL1'},{'title':'1'}]],'ingredient_target':[['Target id','Target name','Database sources'],[{'title':'HBTAR1'},'A','existing']]}
            else:value=responses[p['func_name']]
            return Response(json.dumps(value).encode(),req.full_url)
        with tempfile.TemporaryDirectory() as d:
            source=acquire('HERB',['测试药'],Path(d)/'fetch',opener=opener,sleeper=lambda _:None)
            from science_modules.a01.uploads import unpack,validate_package
            target=Path(d)/'validate';target.mkdir();unpack(source['data'],target)
            meta=validate_package(target,'HERB',['测试药'])
            self.assertEqual(meta['completeness']['测试药']['records'],1)
            # 无完整结构键则保留待核，不能以PubChem编号自动补写身份。
            text=(target/'HERB_ingredient_info_v2.txt').read_text(encoding='utf-8-sig')
            self.assertIn('HBIN1\tCompound\t\t\tC1',text)

    def test_tcmsp_full_chain_ob_dl_and_original_human_mapping(self):
        from science_modules.a01.acquisition import TCMSP
        def opener(req,timeout):
            url=req.full_url
            if url==TCMSP+'tcmsp.php':raw=b'<input name="token" value="abc">'
            elif 'qr=' in url:raw=b'data:[{"MOL_ID":"MOL1","molecule_name":"Compound","ob":"40","dl":"0.3"}],data:[{"MOL_ID":"MOL1","target_ID":"1","target_name":"Protein A"}]'
            elif 'tcmspsearch.php' in url:raw='data:[{"herb_cn_name":"测试药","herb_en_name":"Test herb"}]'.encode()
            elif 'target.php' in url:raw=b'<td>Protein A</td>'
            else:raw=json.dumps({'results':[{'primaryAccession':'P1','organism':{'taxonId':9606},'genes':[{'geneName':{'value':'A'}}],'proteinDescription':{'recommendedName':{'fullName':{'value':'Protein A'}}}}]}).encode()
            return Response(raw,url)
        with tempfile.TemporaryDirectory() as d:
            source=acquire('TCMSP',['测试药'],Path(d)/'fetch',opener=opener,sleeper=lambda _:None)
            from science_modules.a01.uploads import unpack,validate_package
            target=Path(d)/'validate';target.mkdir();unpack(source['data'],target)
            meta=validate_package(target,'TCMSP',['测试药'])
            self.assertEqual(meta['completeness']['测试药']['records'],1)
            self.assertIn('P1\tA\tHomo sapiens (Human)',(target/'references/tcmsp_snapshot.tsv').read_text(encoding='utf-8-sig'))

    def test_batman_real_shaped_download_known_only_and_cache_integrity(self):
        herbs=b'Pinyin.Name\tChinese.Name\tLatin.Name\tIngredients\nTEST\t'
        herbs+='测试药'.encode()+b'\tTest\tcompound(1)\n'
        known=gzip.compress(b'PubChem_CID\tIUPAC_name\tknown_target_proteins\n1\tcompound\tA\n')
        calls=[]
        def opener(req,timeout):
            calls.append(req.full_url)
            return Response(herbs if req.full_url.endswith('herb_browse.txt') else known,req.full_url)
        with tempfile.TemporaryDirectory() as d:
            source=acquire('BATMAN',['测试药'],Path(d),opener=opener,sleeper=lambda _:None)
            with zipfile.ZipFile(io.BytesIO(source['data'])) as z:
                meta=json.loads(z.read('modulea_source.json'))
                self.assertEqual(meta['completeness']['测试药']['records'],1)
                self.assertTrue(all('predicted' not in n for n in z.namelist()))
            acquire('BATMAN',['测试药'],Path(d),opener=opener,sleeper=lambda _:None)
            self.assertEqual(len(calls),2)
            p=next((Path(d)/'original_requests').glob('*.bin'));p.write_bytes(b'tampered')
            with self.assertRaises(ContractError):acquire('BATMAN',['测试药'],Path(d),opener=opener,sleeper=lambda _:None)

    def test_download_failure_and_missing_herb_are_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(OSError):
                acquire('BATMAN',['测试药'],Path(d),opener=lambda *a,**k:(_ for _ in ()).throw(OSError('offline')),sleeper=lambda _:None)
            self.assertFalse((Path(d)/'source.zip').exists())
            self.assertTrue(list((Path(d)/'original_requests').glob('*failure*')))

    def test_external_url_and_partial_http_download_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fetcher(Path(d),None,lambda _:None)
            with self.assertRaises(ContractError):f.get('https://example.com/file')
            def opener(req,timeout):
                r=Response(b'cut',req.full_url);r.headers['Content-Length']='100';return r
            f.opener=opener
            with self.assertRaises(ContractError):f.get(BATMAN+'herb_browse.txt')

    def test_tcmsp_json_is_parsed_without_script_execution(self):
        self.assertEqual(_arrays(b'var x={data:[{"MOL_ID":"MOL1","ob":30,"dl":0.18}]};'),[[{'MOL_ID':'MOL1','ob':30,'dl':.18}]])
        with self.assertRaises(ValueError):_arrays(b'data:[unsafeJavaScript()]')

    def test_human_protein_mapping_must_be_unique_and_exact(self):
        class Fake:
            def get(self,url):return json.dumps({'results':self.rows}).encode()
        f=Fake();row={'primaryAccession':'P1','organism':{'taxonId':9606},'genes':[{'geneName':{'value':'A'}}],'proteinDescription':{'recommendedName':{'fullName':{'value':'Protein A'}}}}
        f.rows=[row];self.assertEqual(_human_target(f,'Protein A'),('P1','A','Homo sapiens (Human)'))
        f.rows=[row,dict(row,primaryAccession='P2')];self.assertEqual(_human_target(f,'Protein A'),('','',''))
        f.rows=[row];self.assertEqual(_human_target(f,'Protein B'),('','',''))


if __name__=='__main__':unittest.main()
