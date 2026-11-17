"""原名称来源必须从固定父链和归档HERB回读，不借用后来current或目录猜测。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from contracts import ContractError, fingerprint
from storage import file_record, write_json
from modulea.core import rescue_presentation_names


class RescueNameBasisTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.sid='study_'+'a'*32
        self.home=self.root/'studies'/self.sid;self.home.mkdir(parents=True)
        self.ids={key:'run_'+value*32 for key,value in [('A01','1'),('A03','3'),('A06_PREP','6'),('A06','7')]}
        self.batch=self.save('batch.json',{'kind':'synthetic'})
        self.raw={'summary':[['Ingredient id','Ingredient name'],['HBIN000001','Source beta']]}
        self.raw_ref=self.save('raw/HERB/HERB_existing_details/HBIN000001.json',self.raw)
        self.binding={'schema_version':'A01.system_source_binding.1','study_id':self.sid,
                      'datasets':[{'file':self.raw_ref}]}
        self.binding_ref=self.save('raw/binding.json',self.binding)
        self.fixed={'study_id':self.sid,'stage':'A06_INPUT','binding':{'batch_file':self.batch,
                    'parent_runs':{'A03':self.ids['A03']},'parent_files':{}},
                    'payload':{'study_id':self.sid,'input_key':'original',
                       'compounds':[{'compound_id':'C1','name':'Alpha'},{'compound_id':'C2','name':'Source beta'}],
                       'receptors':[{'target_id':'HGNC:1','symbol':'GENE'}]}}
        self.prepared={'study_id':self.sid,'schema_version':'A06.system_qualification_paths.1','input_key':'original',
                       'compounds':[{'compound_id':'C1','state':'ready','cid':1},{'compound_id':'C2','state':'NA'}],
                       'receptors':[{'target_id':'HGNC:1','state':'ready'}]}
        self.prepared_ref=self.save('prep/packet.json',self.prepared)
        self.runs={};self.results={};self.m={'study_id':self.sid,'runs':{},'current':{},'reviews':[],
             'analysis_plan_system_component_source_records':[self.binding_ref]}
        for module,rid in self.ids.items():
            self.runs[module]={'study_id':self.sid,'run_id':rid,'module_id':module,'artifact_id':'artifact_'+rid[4:],
                'inputs':{},'parent_runs':{},'config':{}}
            self.results[module]={'study_id':self.sid,'run_id':rid,'module_id':module,
                                 'artifact_id':self.runs[module]['artifact_id'],'files':[],'tables':{}}
        self.runs['A01']['inputs']['system_source_binding']=self.binding_ref
        self.runs['A03']['parent_runs']={'A01':self.ids['A01']}
        self.results['A03']['tables']['formula_evidence']=[{'compound_id':'C2',
             'source_ref':'raw/HERB_existing_details/HBIN000001.json:ingredient_target:1'}]
        self.runs['A06_PREP'].update(batch_file=self.batch,parent_runs={'A03':self.ids['A03']},
                                    config={'version':self.prepared['schema_version']})
        self.results['A06_PREP'].update(files=[self.prepared_ref],tables={'preparation_packet':[self.prepared_ref]})
        self.runs['A06'].update(config={'version':'A06.system_rescue.2'},parent_runs={'A06_PREP':self.ids['A06_PREP']})
        self.refresh()
        self.workflow=SimpleNamespace(root=self.root,location=lambda sid:self.home)

    def save(self,path,value):
        target=self.home/path;write_json(target,value,replace=True)
        return file_record(self.home,target,'synthetic')

    def refresh(self):
        """重新登记明确修改的合成来源，反例不只测坏SHA。"""
        for module in ('A01','A03'):
            rid=self.ids[module];self.m['runs'][rid]={
                'run_file':self.save('runs/'+rid+'/run.json',self.runs[module]),
                'result_file':self.save('runs/'+rid+'/result.json',self.results[module])}
        self.fixed['binding']['parent_files']['A03']=deepcopy(self.m['runs'][self.ids['A03']])
        self.fixed_ref=self.save('fixed.json',self.fixed)
        for module in ('A06_PREP','A06'):
            self.runs[module]['inputs']['system_input_ref']=self.fixed_ref
            if module=='A06':
                entry=self.m['runs'][self.ids['A06_PREP']]
                self.runs[module]['inputs'].update(source_preparation_run=entry['run_file'],
                    source_preparation_result=entry['result_file'])
            rid=self.ids[module];self.m['runs'][rid]={
                'run_file':self.save('runs/'+rid+'/run.json',self.runs[module]),
                'result_file':self.save('runs/'+rid+'/result.json',self.results[module]) if module!='A06' else None}
        self.m['current']={key:rid for key,rid in self.ids.items()}
        self.save('manifest.json',self.m)

    def read(self):
        from modulea.core.rescue_name_basis import source_basis
        return source_basis(self.workflow,self.m,self.sid,self.ids['A06'])

    def test_pending_score_can_read_only_original_prep_and_herb_names(self):
        before=fingerprint(self.m)
        value=self.read()
        self.assertEqual(value['compounds'],self.fixed['payload']['compounds'])
        self.assertEqual(value['prepared'],self.prepared['compounds'])
        self.assertEqual(value['herb_sources']['C2'][0],{'id':'HBIN000001','name':'Source beta','file':self.raw_ref})
        self.assertIsNone(value['source']['run_files'][self.ids['A06']]['result_file'])
        self.assertEqual(fingerprint(self.m),before)

    def test_later_current_a01_a03_are_not_used_for_historical_names(self):
        before=self.read()
        self.m['current']['A01']='run_'+'e'*32;self.m['current']['A03']='run_'+'f'*32
        self.assertEqual(self.read(),before)

    def test_foreign_study_or_parent_prep_cannot_supply_names(self):
        for kind in ('study','parent'):
            with self.subTest(kind=kind):
                original=deepcopy(self.runs['A06_PREP'])
                if kind=='study':self.runs['A06_PREP']['study_id']='study_'+'f'*32
                else:self.runs['A06_PREP']['parent_runs']['A03']='run_'+'f'*32
                self.refresh()
                with self.assertRaises(ContractError):self.read()
                self.runs['A06_PREP']=original

    def test_prepared_order_cannot_be_changed_with_fresh_hash(self):
        self.prepared['compounds'].reverse()
        ref=self.save(self.prepared_ref['path'],self.prepared)
        self.results['A06_PREP'].update(files=[ref],tables={'preparation_packet':[ref]});self.refresh()
        with self.assertRaises(ContractError):self.read()

    def test_unregistered_preparation_packet_and_a01_binding_are_rejected(self):
        self.results['A06_PREP']['files']=[];self.refresh()
        with self.assertRaises(ContractError):self.read()
        self.results['A06_PREP']['files']=[self.prepared_ref];self.refresh()
        self.m['analysis_plan_system_component_source_records']=[]
        with self.assertRaises(ContractError):self.read()

    def test_bad_herb_raw_id_and_missing_pinned_raw_are_rejected(self):
        self.raw['summary'][1][0]='HBIN999999'
        changed=self.save(self.raw_ref['path'],self.raw)
        self.binding['datasets']=[{'file':changed}]
        b=self.save(self.binding_ref['path'],self.binding)
        self.runs['A01']['inputs']['system_source_binding']=b
        self.m['analysis_plan_system_component_source_records']=[b];self.refresh()
        with self.assertRaises(ContractError):self.read()

    def test_source_name_conflict_is_untranslated_instead_of_guessed(self):
        self.fixed['payload']['compounds'][1]['name']='Different';self.refresh()
        basis=self.read()
        from tests.modulea.test_rescue_presentation_names import RescuePresentationNamesTests
        row=RescuePresentationNamesTests.entry('HERB','HBIN000001',['Different'],'合成术语','source_term_translation_only')
        catalog={'schema_version':rescue_presentation_names.CATALOG_VERSION,'entries':[row]}
        self.assertIn('C2',rescue_presentation_names.derive_names(basis,catalog)['missing_ids'])

    def test_explicit_source_rejection_blocks_new_presentation(self):
        review={'study_id':self.sid,'run_id':self.ids['A06_PREP'],
                'artifact_id':self.runs['A06_PREP']['artifact_id'],'decision':'rejected'}
        self.m['reviews']=[self.save('reviews/rejection.json',review)]
        with self.assertRaises(ContractError):self.read()

    def test_corrupt_raw_file_cannot_be_treated_as_missing_translation(self):
        (self.home/self.raw_ref['path']).write_text('broken')
        with self.assertRaises(ContractError):self.read()

    def test_parent_result_with_same_run_but_foreign_artifact_is_rejected(self):
        for module in ('A03','A06_PREP'):
            with self.subTest(module=module):
                original=self.results[module]['artifact_id']
                self.results[module]['artifact_id']='artifact_'+'f'*32;self.refresh()
                with self.assertRaises(ContractError):self.read()
                self.results[module]['artifact_id']=original

    def test_foreign_run_approval_cannot_override_real_source_rejection(self):
        artifact=self.runs['A06_PREP']['artifact_id']
        rejected={'study_id':self.sid,'run_id':self.ids['A06_PREP'],'artifact_id':artifact,'decision':'rejected'}
        forged=dict(rejected,run_id='run_'+'f'*32,decision='approved')
        self.m['reviews']=[self.save('reviews/rejected.json',rejected),self.save('reviews/foreign_approved.json',forged)]
        with self.assertRaises(ContractError):self.read()

    def test_empty_artifact_identity_cannot_match_another_empty_identity(self):
        self.runs['A06_PREP']['artifact_id']=''
        self.results['A06_PREP']['artifact_id']=''
        self.refresh()
        with self.assertRaises(ContractError):self.read()

    def test_http_scope_tracks_all_name_sources_and_blocks_exit_change(self):
        from modulea.core.http_read_evidence import json_evidence_scope
        import os
        with self.assertRaises(ContractError):
            with json_evidence_scope(self.root,self.sid) as evidence:
                basis=self.read()
                self.assertEqual({ref['path'] for _,ref,_ in evidence.proofs.values()},
                                 {ref['path'] for ref in basis['evidence']})
                target=self.home/self.raw_ref['path'];stamp=target.stat()
                target.write_bytes(target.read_bytes().replace(b'Source beta',b'Source zeta'))
                os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
