"""共晶证据适配的离线故障与参数测试；真实公开样本留在仓库外审计目录。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import file_record, verified_file
from science_modules.analysis_protocol import compile_plan
from science_modules.a06.plan_preparation_v2 import execution_config
from science_modules.a06.reference_candidates import discover
from science_modules.a06.plan_reference_evidence import prepare_selected, validate_ready
from tests.modulea.test_reference_docking import fixture


class PlanReferenceEvidenceTests(unittest.TestCase):
    """采用稳定键不等于通过：序列、CCD、工具和实际参数分别把关。"""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        cif = self.home / 'source.cif'; cif.write_text(fixture(),encoding='utf-8')
        self.origin = {'spec':{'pdb_id':'TEST','source_type':'experimental','chains':['A'],
                              'uniprot':'P00001','pocket':'p2rank','altloc':None},
                       'cif':file_record(self.home,cif,'synthetic_structure'),
                       'identity':[{'uniprot':'P00001','identity_check':'matched'}]}
        self.connection = {'id':'isolated','compounds':[], 'receptors':[{'target_id':'HGNC:1',
            'symbol':'TEST','state':'connected','candidates':[self.origin]}]}
        option = discover(self.home,self.connection)[0]
        self.choice = {k:option[k] for k in ('target_id','candidate_key','reference_key')}
        self.config = execution_config(compile_plan({'mode':'personalized','parameters':{
            'a06.exhaustiveness':12,'a06.seed':9,'a06.box_padding':3.0}}))

    def ccd(self, extra_atom=False):
        """合成CCD与原坐标有相同原子名；多一原子即应拒绝。"""
        text='data_LIG\n_chem_comp.id LIG\nloop_\n_chem_comp_atom.comp_id\n_chem_comp_atom.atom_id\n_chem_comp_atom.type_symbol\n'
        text+=''.join(f'LIG C{i} C\n' for i in range(9 if extra_atom else 8))
        path=self.home/'ccd.cif'; path.write_text(text,encoding='utf-8')
        return path

    def call(self, choice=None):
        return prepare_selected(self.home,self.connection,choice or self.choice,self.home/'attempt',
                                self.home/'tools',self.config,lambda _:None)

    def test_invalid_or_stale_choice_never_starts_preparation(self):
        for choice in (dict(self.choice,path='client-path'),dict(self.choice,reference_key='0'*64)):
            with self.assertRaises(ContractError): self.call(choice)
        self.assertFalse((self.home/'attempt').exists())

    def test_sequence_failure_retains_na_and_does_not_run_tools(self):
        before=deepcopy(self.connection)
        with patch('science_modules.a06.plan_reference_evidence.verify_sequence',side_effect=ValueError('实际序列不符')), \
             patch('science_modules.a06.plan_quality_engine_v2.download_ccd') as download, \
             patch('science_modules.a06.plan_quality_engine_v2.attempt') as prepare:
            value=self.call()
        self.assertEqual(value['state'],'NA')
        self.assertEqual(value['reason_zh'],'实际序列不符')
        self.assertEqual(self.connection,before)
        download.assert_not_called(); prepare.assert_not_called()

    def test_incomplete_ccd_is_na_before_tool_execution(self):
        ccd=self.ccd(extra_atom=True)
        with patch('science_modules.a06.plan_reference_evidence.verify_sequence',return_value={'sequence_scope':{}}), \
             patch('science_modules.a06.plan_quality_engine_v2.download_ccd',return_value=ccd), \
             patch('science_modules.a06.plan_quality_engine_v2.attempt') as prepare:
            value=self.call()
        self.assertEqual(value['state'],'NA')
        self.assertIn('CCD',value['reason_zh'])
        prepare.assert_not_called()

    def test_explicit_choice_and_actual_config_reach_preparation(self):
        ccd=self.ccd()
        evidence={'structure_id':'TEST','identity':{'target_id':'HGNC:1','uniprot':'P00001',
            'species':9606,'polymer_type':'Protein','sequence_matches':True,'chains':['A']},
            'pocket_complete':True,'environment_resolved':True,'receptor_ready':True,
            'reference':{'reference_code':'LIG','reference_chain':'A','reference_sequence':'500'},'top1_rmsd':1.2}
        before=deepcopy(self.connection)
        with patch('science_modules.a06.plan_reference_evidence.verify_sequence',return_value={'sequence_scope':{}}), \
             patch('science_modules.a06.plan_quality_engine_v2.download_ccd',return_value=ccd), \
             patch('science_modules.a06.plan_quality_engine_v2.attempt',return_value=evidence) as prepare:
            value=self.call()
        self.assertEqual(value['state'],'ready')
        self.assertEqual(value['quality'],'严格')
        self.assertEqual(prepare.call_args.kwargs['box_padding'],3.0)
        self.assertEqual(prepare.call_args.kwargs['vina_parameters']['exhaustiveness'],12)
        self.assertEqual(prepare.call_args.kwargs['vina_parameters']['seed'],9)
        self.assertEqual(self.connection,before)
        self.assertTrue(value['candidate']['reference_audit']['reference_count_matches'])

    def test_ready_validation_never_accepts_a_failure_label(self):
        with self.assertRaises(ContractError):
            validate_ready(self.home,self.connection,{'schema_version':'A06.plan_reference_evidence.1','state':'NA'},self.config)

    def test_mutable_checkpoint_does_not_invalidate_immutable_sources(self):
        from tools.check_a06_reference import immutable_evidence_files
        checkpoint=self.home/'source_checkpoint.json'; checkpoint.write_text('{}',encoding='utf-8')
        records=immutable_evidence_files(self.home)
        self.assertNotIn('source_checkpoint.json',[r['path'] for r in records])
        checkpoint.write_text('{"new_request": true}',encoding='utf-8')
        for record in records: verified_file(self.home,record)
        (self.home/'source.cif').write_text('changed source',encoding='utf-8')
        with self.assertRaises(ContractError): verified_file(self.home,records[0])


if __name__=='__main__':
    unittest.main()
