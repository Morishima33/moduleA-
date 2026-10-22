"""虚构文献输入回归：第一行、身份类型、精确蛋白映射及来源隔离。"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from contracts import ContractError
from storage import file_record
from science_modules import literature_input as subject


def workbook(path, sheets):
    """最小合成xlsx含shared/inline字符串及容易误读为A列的AA列。"""
    ns = subject.NS['s']
    with ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', f'<sst xmlns="{ns}"><si><t>FIRST</t></si></sst>')
        items, rels = [], []
        for index, (name, values) in enumerate(sheets.items(), 1):
            items.append(f'<sheet name="{name}" sheetId="{index}" r:id="r{index}"/>')
            rels.append(f'<Relationship Id="r{index}" Target="worksheets/s{index}.xml"/>')
            rows = ''.join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>{v}</t></is></c><c r="AA{i}" t="inlineStr"><is><t>IGNORE</t></is></c></row>' for i, v in enumerate(values, 1))
            z.writestr(f'xl/worksheets/s{index}.xml', f'<worksheet xmlns="{ns}"><sheetData>{rows}</sheetData></worksheet>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="{subject.NS["r"]}"><sheets>{"".join(items)}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships>' + ''.join(rels) + '</Relationships>')


class LiteratureInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'studies/study_synthetic'
        self.home.mkdir(parents=True)
        workbook(self.home/'drug.xlsx', {'PharmMapper':['FIRST','ENSG000001','UNKNOWN'], 'SEA':['PROT']})
        workbook(self.home/'disease.xlsx', {'DB':['FIRST','SECOND']})
        (self.home/'identity.json').write_text(json.dumps({'PropertyTable':{'Properties':[{'CID':42,'InChIKey':'FULL-KEY','MolecularFormula':'C2H6'}]}}))
        (self.home/'uniprot.tsv').write_text('Entry\tEntry Name\tGene Names (primary)\tOrganism (ID)\nU1\tPROT_HUMAN\tFIRST\t9606\nU2\tPROT_MOUSE\tSECOND\t10090\nU3\tPROT_EXTRA_HUMAN\tSECOND\t9606\n')
        (self.home/'hgnc.tsv').write_text('synthetic fixed snapshot')
        self.inputs = {'mapping_file':file_record(self.home,self.home/'hgnc.tsv','mapping')}
        self.source = {'schema_version':subject.VERSION,'study_id':self.home.name,'scope_confirmed':True,'omit_unresolved':True,'reviewer':'Agent explicit delegation','reason':'synthetic same-input comparison','doi':'10.synthetic/test','disease_term':'Synthetic disease','compound':{'cid':42,'inchikey':'FULL-KEY','name':'Test ligand'},'original_files':[], 'uniprot_entry_name_sources':['SEA']}
        for key,name in [('compound_targets_file','drug.xlsx'),('disease_targets_file','disease.xlsx'),('compound_identity_file','identity.json'),('uniprot_file','uniprot.tsv')]:
            self.source[key] = file_record(self.home,self.home/name,key)
        self.mapper = SimpleNamespace(digest=self.inputs['mapping_file']['sha256'],rule='HGNC.resolve.3',supplement=SimpleNamespace(digest='evidence-sha'),resolve=Mock(side_effect=self.resolve))
        self.snapshot = patch.object(subject,'load_snapshot',return_value=(self.mapper,{}))
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)
        self.save_source()

    def resolve(self, symbol, stable_id='', uniprot=''):
        value = stable_id or symbol
        if value == 'UNKNOWN': return {'status':'unmapped','target_id':'','symbol':''}
        return {'status':'matched','target_id':'HGNC:1' if value in ('FIRST','ENSG000001') else 'HGNC:2','symbol':'FIRST' if value in ('FIRST','ENSG000001') else 'SECOND'}

    def save_source(self):
        path=self.home/'source.json'
        path.write_text(json.dumps(self.source))
        self.inputs['source_file']=file_record(self.home,path,'source')

    def test_first_row_source_cells_and_exact_column(self):
        rows=subject.read_sheets(self.home/'drug.xlsx')
        self.assertEqual([r['original_identifier'] for r in rows],['FIRST','ENSG000001','UNKNOWN','PROT'])
        self.assertEqual((rows[0]['source'],rows[0]['cell'],rows[0]['source_line']),('PharmMapper','A1',1))

    def test_shared_string_first_cell(self):
        with ZipFile(self.home/'shared.xlsx','w') as z, ZipFile(self.home/'drug.xlsx') as original:
            for name in original.namelist():
                raw=original.read(name)
                if name.endswith('s1.xml'): raw=raw.replace(b'<c r="A1" t="inlineStr"><is><t>FIRST</t></is></c>',b'<c r="A1" t="s"><v>0</v></c>')
                z.writestr(name,raw)
        self.assertEqual(subject.read_sheets(self.home/'shared.xlsx')[0]['original_identifier'],'FIRST')

    def test_typed_mapping_duplicate_sources_and_exact_uniprot(self):
        summary,tables,_,outcome=subject.evaluate(self.root,self.home,'A01',self.inputs)
        self.assertEqual((summary['原始关系记录数'],summary['标准化基因数'],summary['身份问题组数'],outcome),(4,1,1,'success'))
        self.mapper.resolve.assert_any_call('',stable_id='ENSG000001')
        self.mapper.resolve.assert_any_call('FIRST',uniprot='U1')
        self.assertIn('SEA!A1',tables['normalized_compound_targets'][0]['source_ref'])
        self.assertEqual(tables['identity_issues'][0]['original_identifier'],'UNKNOWN')
        self.assertNotIn('ob',tables['components'][0])

    def test_ambiguous_uniprot_entry_is_not_arbitrarily_selected(self):
        path=self.home/'uniprot.tsv'
        path.write_text(path.read_text()+'U4\tPROT_HUMAN\tSECOND\t9606\n')
        self.source['uniprot_file']=file_record(self.home,path,'uniprot')
        self.save_source()
        _,tables,_,_=subject.evaluate(self.root,self.home,'A01',self.inputs)
        self.assertTrue(any(r['original_identifier']=='PROT' and r['status']=='ambiguous_or_conflicting' for r in tables['identity_issues']))

    def test_scope_chemical_identity_and_file_tamper_are_rejected(self):
        for key,value in [('study_id','study_other'),('scope_confirmed',False),('omit_unresolved',False)]:
            with self.subTest(key=key):
                old=self.source[key];self.source[key]=value;self.save_source()
                with self.assertRaises(ContractError): subject.evaluate(self.root,self.home,'A01',self.inputs)
                self.source[key]=old
        self.source['compound']['inchikey']='WRONG';self.save_source()
        with self.assertRaises(ContractError): subject.evaluate(self.root,self.home,'A01',self.inputs)
        self.source['compound']['inchikey']='FULL-KEY';self.save_source()
        (self.home/'drug.xlsx').write_bytes(b'tampered')
        with self.assertRaises(ContractError): subject.evaluate(self.root,self.home,'A01',self.inputs)

    def test_new_validator_recomputes_but_legacy_dispatch_is_unchanged(self):
        old=Mock();check=subject.validator(self.root,'A02',old)
        run={'module_id':'A02','study_id':self.home.name,'inputs':self.inputs,'config':{'version':'legacy'}}
        check(run,{}, {}, [],'empty');old.assert_called_once()
        run['config']=dict(subject.CONFIGS['A02']);expected=subject.evaluate(self.root,self.home,'A02',self.inputs)
        check(run,*expected)
        changed=dict(expected[0],标准化基因数=99)
        with self.assertRaises(ContractError):check(run,changed,*expected[1:])

    def test_presenter_uses_literature_counts_and_never_claims_ob_dl_filter(self):
        from modulea.presenters.sources import present_a01,present_a02
        for module,presenter in [('A01',present_a01),('A02',present_a02)]:
            s,t,_,_=subject.evaluate(self.root,self.home,module,self.inputs)
            parts=presenter({'summary':s,'tables':t},{})
            self.assertEqual(parts.flow[0]['value'],s['原始关系记录数'])
            self.assertEqual(parts.flow[-1]['value'],s['标准化基因数'])
            self.assertTrue(all('OB/DL' not in r['label_zh'] for r in parts.flow))
            self.assertIn('文献归档名单',parts.flow_note_zh)
            self.assertEqual(parts.table['source_table'],'source_summary')

    def test_literature_report_requires_registration_and_matching_source_identity(self):
        from science_modules.a07.literature_reports import literature_sources
        flow=Mock()
        intake={'study_type':'single_compound_literature_comparison','reference_doi':self.source['doi'],
                'compound':{'pubchem_cid':42,'inchikey':'FULL-KEY'}}
        flow.result.side_effect=lambda manifest,rid: {'summary':intake if rid=='intake' else {'input_profile':subject.VERSION}}
        flow.location.return_value=self.home
        flow.run.return_value={'inputs':self.inputs}
        manifest={'study_id':self.home.name};parents={'A00':'intake','A01':'drug','A02':'disease'}
        records=literature_sources(flow,manifest,parents)
        self.assertEqual(records['A01'],self.inputs['source_file'])
        intake['compound']['pubchem_cid']=99
        with self.assertRaises(ContractError):literature_sources(flow,manifest,parents)

    def test_literature_navigation_avoids_standard_database_collection_steps(self):
        from modulea.api.module_navigation import context
        for mid in ('A01','A02'):
            view={'module':{'module_id':mid},'historical':False,'review':{'already_approved':True},'state':{'code':'approved'}}
            guide=context(view,{'summary':{'input_profile':subject.VERSION}})
            self.assertEqual(guide['steps'][-1]['module_id'],'A03')
            self.assertEqual(guide['current_step'],4)
            self.assertTrue(all('检查五库' not in x['label_zh'] for x in guide['steps']))
        self.assertIsNone(context(dict(view,historical=True),{'summary':{'input_profile':subject.VERSION}}))

    def test_intersection_input_audit_does_not_invent_three_database_gaps(self):
        from modulea.api.input_audit import context
        results={}
        for module in ('A01','A02'):
            summary,tables,_,_=subject.evaluate(self.root,self.home,module,self.inputs)
            results[module]={'run_id':module,'summary':summary,'tables':tables}
        flow=Mock();flow.result.side_effect=lambda m,rid:results[rid]
        manifest={'workflow_profile':'A00.preupload.2','current':{'A01':'A01','A02':'A02'}}
        info=context(flow,manifest,'A03',{'parent_runs':manifest['current']},{'summary':{'方剂靶点数':1,'疾病靶点数':2}})
        self.assertEqual(info['formula']['missing_sources'],[])
        self.assertEqual(info['formula']['component_label_zh'],'文献指定成分')
        self.assertEqual(info['disease']['candidate_count'],2)
        self.assertEqual(info['disease']['scope_counts'],[])


if __name__=='__main__':unittest.main()
