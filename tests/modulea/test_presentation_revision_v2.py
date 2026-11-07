"""展示二版规范序列化回归：真实存储往返与字典重排不改原行、评分、NA或旧版。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import shutil
import unittest

from contracts import ContractError,fingerprint
from storage import read_json,write_json
from science_modules import presentation_revision as legacy,presentation_revision_v2 as presentation
from tests.modulea.test_presentation_revision import fixture


def reordered(value):
    """模拟存储/客户端只改变所有JSON对象键顺序；数组行顺序始终不变。"""
    if isinstance(value,dict):return {key:reordered(child) for key,child in reversed(list(value.items()))}
    if isinstance(value,list):return [reordered(child) for child in value]
    return value


class PresentationRevisionV2Tests(unittest.TestCase):
    """使用明确合成科学事实实际绘制八图，独立临时目录中验证归档可重放。"""

    @classmethod
    def setUpClass(cls):
        cls.seed=TemporaryDirectory(prefix='presentation_v2_seed_');cls.addClassCleanup(cls.seed.cleanup)
        cls.payload,cls.a03,cls.lexicon=fixture();cls.root=Path(cls.seed.name)
        from science_modules.a07.plan_facts_v2 import docking
        old=cls.payload['docking'];pairs=deepcopy(old['pairs'])
        for row in pairs:
            row['source_relations']={'database':'explicit_synthetic','original_source':{'stable_id':row['compound_id'],'coordinates':None},
                                     'records':[{'target_id':row['target_id'],'score':row['score'],'flags':[None,{'verified':False}]}]}
        cls.payload['docking']=docking({'study_id':old['study_id'],'run_id':old['run_id'],
            'compounds':old['compounds'],'receptors':old['receptors'],'pairs':pairs},old['configuration'])
        cls.legacy_sha=sha256(Path(legacy.__file__).read_bytes()).hexdigest()
        cls.before=fingerprint([cls.payload,cls.a03,cls.lexicon]);cls.folder=cls.root/'bundle'
        cls.manifest=presentation.build_bundle(cls.payload,cls.a03,cls.folder,lexicon=cls.lexicon)
        # 使用生产存储函数，而非默认不排序的json.dumps，重现正式归档后才暴露的旧缺陷。
        for key,value in (('payload',cls.payload),('a03',cls.a03),('lexicon',cls.lexicon),('bundle',cls.manifest)):
            write_json(cls.root/(key+'.json'),value)

    def setUp(self):
        self.temp=TemporaryDirectory(prefix='presentation_v2_case_');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'bundle';shutil.copytree(self.__class__.folder,self.folder)
        self.value=read_json(self.__class__.root/'bundle.json')
        self.data=read_json(self.__class__.root/'payload.json')
        self.result=read_json(self.__class__.root/'a03.json')
        self.entries=read_json(self.__class__.root/'lexicon.json')

    def validate(self):
        return presentation.validate_bundle(self.data,self.result,self.folder,self.value,lexicon=self.entries)

    def test_storage_write_json_round_trip_can_fully_validate_real_files(self):
        self.assertTrue(self.validate())
        self.assertEqual(self.value['schema_version'],'ModuleA.presentation_bundle.2')
        self.assertEqual(fingerprint([self.payload,self.a03,self.lexicon]),self.before)
        self.assertEqual(self.value['counts']['translation_terms'],12)
        self.assertEqual(self.value['counts']['translation_rows'],25)
        self.assertFalse(self.value['word_generated']);self.assertEqual(list(self.folder.rglob('*.docx')),[])

    def test_dictionary_order_changes_produce_identical_data_and_image_bytes(self):
        target=Path(self.temp.name)/'reordered'
        value=presentation.build_bundle(reordered(self.payload),reordered(self.a03),target,lexicon=reordered(self.lexicon))
        self.assertEqual({key:child for key,child in value.items() if key!='files'},
                         {key:child for key,child in self.manifest.items() if key!='files'})
        self.assertEqual({row['path']:row for row in value['files']},{row['path']:row for row in self.manifest['files']})
        self.assertEqual({path.relative_to(target):path.read_bytes() for path in target.rglob('*') if path.is_file()},
                         {path.relative_to(self.folder):path.read_bytes() for path in self.folder.rglob('*') if path.is_file()})
        self.data=reordered(self.data);self.result=reordered(self.result)
        self.entries=reordered(self.entries);self.value=reordered(self.value)
        self.assertTrue(self.validate())

    def test_csv_columns_are_stable_while_all_source_rows_scores_and_na_are_preserved(self):
        with (self.folder/'tables/a06_pairs.csv').open(encoding='utf-8-sig',newline='') as handle:
            reader=csv.DictReader(handle);rows=list(reader);keys=reader.fieldnames
        self.assertEqual(keys,sorted(keys))
        self.assertEqual([(row['compound_id'],row['target_id']) for row in rows],
                         [(row['compound_id'],row['target_id']) for row in self.payload['docking']['pairs']])
        self.assertEqual([row['score'] for row in rows],['-8.001','NA','-7.999','NA'])
        self.assertEqual([row['state'] for row in rows],['completed','NA','completed','failed'])
        self.assertEqual(rows[1]['reason_zh'],'固定身份未通过')
        self.assertEqual(json.loads(rows[1]['source_relations']),self.payload['docking']['pairs'][1]['source_relations'])
        nested=json.loads(rows[1]['source_relations'])
        self.assertIsNone(nested['original_source']['coordinates'])
        self.assertIsNone(nested['records'][0]['score'])
        self.assertEqual(nested['records'][0]['flags'],[None,{'verified':False}])
        for name,values in self.value['tables'].items():
            with (self.folder/'tables'/(name+'.csv')).open(encoding='utf-8-sig',newline='') as handle:
                exported=list(csv.DictReader(handle))
            if values and 'ID' in values[0]:self.assertEqual([row['ID'] for row in exported],[row['ID'] for row in values])

    def test_translation_audit_uses_canonical_ids_and_table_names_with_same_evidence(self):
        audit=self.value['translation_audit']
        self.assertEqual([row['ID'] for row in audit],sorted(row['ID'] for row in audit))
        for row in audit:
            self.assertEqual(row['tables'],sorted(row['tables']))
            self.assertEqual(row['english'],self.lexicon[row['ID']]['english'])
            self.assertEqual(row['chinese'],self.lexicon[row['ID']]['zh'])
            self.assertEqual(row['translation_basis'],self.lexicon[row['ID']]['translation_basis'])
        self.assertIn('kegg_deferred',next(row for row in audit if row['ID']=='hsa00003')['tables'])

    def test_build_and_validate_use_one_v2_namespace_and_legacy_remains_frozen(self):
        self.assertIs(presentation.build_bundle.__globals__,presentation.validate_bundle.__globals__)
        self.assertIs(presentation.build_bundle.__globals__['validate_bundle'],presentation.validate_bundle)
        self.assertIs(presentation.validate_bundle.__globals__['_checked_data'],presentation._checked_data)
        self.assertEqual(legacy.VERSION,'ModuleA.presentation_bundle.1')
        self.assertEqual(sha256(Path(legacy.__file__).read_bytes()).hexdigest(),self.legacy_sha)
        with self.assertRaises(ContractError):legacy.validate_bundle(self.data,self.result,self.folder,self.value,lexicon=self.entries)

    def test_corrupted_download_is_rejected(self):
        path=self.folder/'figures/intersection.svg';path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ContractError):self.validate()

    def test_na_zero_with_forged_new_sha_still_cannot_pass(self):
        path=self.folder/'tables/a06_pairs.csv'
        text=path.read_text(encoding='utf-8-sig')
        reader=csv.DictReader(text.splitlines());rows=list(reader)
        rows[1]['score']='0'
        with path.open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=reader.fieldnames,lineterminator='\n')
            writer.writeheader();writer.writerows(rows)
        raw=path.read_bytes();ref=next(row for row in self.value['files'] if row['path']=='tables/a06_pairs.csv')
        ref.update(bytes=len(raw),sha256=sha256(raw).hexdigest())
        with self.assertRaises(ContractError):self.validate()

    def test_changed_row_order_is_rejected_even_after_rehashing_csv(self):
        path=self.folder/'tables/a05_bp_display.csv';lines=path.read_bytes().splitlines(keepends=True)
        path.write_bytes(lines[0]+b''.join(reversed(lines[1:])))
        raw=path.read_bytes();ref=next(row for row in self.value['files'] if row['path']=='tables/a05_bp_display.csv')
        ref.update(bytes=len(raw),sha256=sha256(raw).hexdigest())
        with self.assertRaises(ContractError):self.validate()

    def test_missing_english_mismatch_and_inconsistent_translation_aliases_still_block(self):
        for change in ('missing','english','visible_alias'):
            self.data=read_json(self.__class__.root/'payload.json');self.entries=read_json(self.__class__.root/'lexicon.json')
            if change=='missing':del self.entries['hsa00003']
            elif change=='english':self.entries['hsa00003']['english']='different original'
            else:self.data['enrichment']['tables']['bp_display'][0]['description_zh']='不一致中文'
            with self.subTest(change=change),self.assertRaises(ContractError):self.validate()


if __name__=='__main__':
    unittest.main()
