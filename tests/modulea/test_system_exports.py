"""系统导出读回实际Excel/CSV精度、NA、原序与文字；不用Vina或伪造科学状态。"""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as xml
import zipfile

from contracts import ContractError
from science_modules.a06 import system_exports as exports, automatic_exports as original


class SystemExportsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='system_exports_'); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.run = {'run_id': 'run_explicit_synthetic', 'study_id': 'study_explicit_synthetic', 'module_id': 'A06',
                    'config': {'version': 'A06.system_scoring.2'}}
        self.packet = {'input_key': 'synthetic_input',
            'compounds': [{'compound_id': 'C1', 'name': 'Original name', 'name_zh': '本批原名称'}, {'compound_id': 'C2', 'name': 'Second'}],
            'receptors': [{'target_id': 'HGNC:1', 'symbol': 'FIRST', 'candidate_grade': 'A'}, {'target_id': 'HGNC:2', 'symbol': 'SECOND', 'candidate_grade': 'B'}]}
        self.pairs = [{'compound_id': c['compound_id'], 'target_id': r['target_id'], 'state': state, 'score': score,
                       'quality': '探索', 'reason_zh': reason} for (c,r),(state,score,reason) in zip(
            [(c,r) for c in self.packet['compounds'] for r in self.packet['receptors']],
            [('completed',-8.123456789,''),('NA',None,'缺少原结构'),('failed',None,'实际执行失败'),('completed',-0.264,'')])]
        self.result = {'study_id': self.run['study_id'], 'run_id': self.run['run_id'], 'summary': {'input_key': 'synthetic_input'},
                       'tables': {'plan_scoring_pairs': self.pairs}}

    def view(self):
        return exports.build_view(self.run, self.result, self.packet)

    def test_actual_excel_csv_keep_full_original_precision_na_order_and_source(self):
        old = original.VERSION; before = deepcopy((self.run,self.result,self.packet)); view = self.view(); files = exports.export(view,self.home/'output')
        self.assertEqual(original.VERSION, old); self.assertEqual((self.run,self.result,self.packet), before)
        self.assertEqual(view['science_version'],'A06.system_scoring.2'); self.assertEqual(view['score_range'],[-8.123456789,-0.264])
        with Path(files['csv']).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual([row['score'] for row in rows],['-8.123456789','','','-0.264'])
        self.assertEqual([row['state'] for row in rows],['completed','NA','failed','completed'])
        with zipfile.ZipFile(files['xlsx']) as archive:
            root=xml.fromstring(archive.read('xl/worksheets/sheet1.xml'));ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            values={node.attrib['r']:node for node in root.findall('.//s:sheetData/s:row/s:c',ns)}
            self.assertEqual(float(values['C2'].find('s:v',ns).text),-8.123456789)
            self.assertEqual(float(values['D3'].find('s:v',ns).text),-0.264)
            self.assertEqual(''.join(values['D2'].itertext()),'NA');self.assertEqual(''.join(values['C3'].itertext()),'NA')
            self.assertTrue(root.findall('.//s:pane',ns));self.assertEqual(len(root.findall('.//s:f',ns)),0)
        self.assertEqual(len(files),6);self.assertTrue(all(Path(path).is_file() for path in files.values()))
        self.assertIn(self.run['run_id'],view['scope_note_zh']);self.assertTrue(exports.validate_files(view,files))

    def test_complete_all_na_preparation_is_not_a_zero_score_or_fake_color_range(self):
        self.run.update(module_id='A06_PREP',config={'version':'A06.system_qualification.2'})
        rows=[dict(row,state='NA',score=None,reason_zh='原准备不可用') for row in self.pairs]
        self.result['tables']={'planned_pairs':rows};view=self.view();files=exports.export(view,self.home/'all_na')
        self.assertEqual(view['score_range'],[None,None]);self.assertTrue(all(cell['color']=='#FFFFFF' for line in view['table']['cells'] for cell in line))
        self.assertTrue(exports.validate_files(view,files));self.assertEqual(view['science_version'],'A06.system_qualification.2')

    def test_failed_scores_nan_boolean_missing_and_reordered_pairs_are_rejected(self):
        changes=[]
        for score in (float('nan'),float('inf'),True):
            value=deepcopy(self.result);value['tables']['plan_scoring_pairs'][0]['score']=score;changes.append(value)
        value=deepcopy(self.result);value['tables']['plan_scoring_pairs'][1]['score']=0;changes.append(value)
        value=deepcopy(self.result);value['tables']['plan_scoring_pairs'].pop();changes.append(value)
        value=deepcopy(self.result);value['tables']['plan_scoring_pairs'].reverse();changes.append(value)
        value=deepcopy(self.result);value['summary']['input_key']='foreign';changes.append(value)
        for value in changes:
            with self.subTest(value=value),self.assertRaises(ContractError):exports.build_view(self.run,value,self.packet)

    def test_ready_unscored_preparation_cannot_be_exported_as_na(self):
        self.run.update(module_id='A06_PREP',config={'version':'A06.system_preparation.2'})
        self.result['tables']={'planned_pairs':[dict(row,state='ready',score=None) for row in self.pairs]}
        with self.assertRaises(ContractError):self.view()

    def test_original_names_are_literal_text_and_never_excel_formulas(self):
        self.packet['compounds'][0]['name']='=1+2';self.packet['compounds'][0]['name_zh']='=SUM(1,2)'
        self.pairs[1]['reason_zh']='=HYPERLINK("https://example.invalid","raw reason")'
        files=exports.export(self.view(),self.home/'literal_names')
        with zipfile.ZipFile(files['xlsx']) as archive:
            for name in ('xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'):
                root=xml.fromstring(archive.read(name));self.assertFalse(root.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f'))
            self.assertIn('=SUM(1,2)',archive.read('xl/worksheets/sheet1.xml').decode())
            self.assertIn('=HYPERLINK',archive.read('xl/worksheets/sheet2.xml').decode())


if __name__=='__main__':unittest.main()
