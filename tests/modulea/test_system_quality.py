"""系统资格纯规则边界，结构和预测值明确合成；旧人工规则保持。"""
from copy import deepcopy
import unittest
from science_modules.a06.system_quality import assess
from science_modules.a06.plan_preparation_v2 import assess_plan_attempt


def sample():
    spec={'source_type':'experimental','pdb_id':'synthetic','uniprot':'P1','chains':['A'],'pocket':'p2rank'}
    target={'target_id':'HGNC:1'}
    evidence={'structure_id':'synthetic','identity':{'target_id':'HGNC:1','uniprot':'P1','species':9606,'polymer_type':'Protein','sequence_matches':True,'chains':['A']},
        'pocket_complete':True,'environment_resolved':True,'receptor_ready':True,
        'pocket':{'rank':1,'runs':[{'score':'9'},{'score':'9'}],'mapped_indices':[0,1],'confirmation':{}},
        'predicted_pocket':{'files':[{'explicit_synthetic':1},{'explicit_synthetic':2}],'input_pdb':{'explicit_synthetic':True}}}
    config={'strict_rmsd_A':2.0,'requested_rmsd_max_A':2.0}
    return spec,evidence,target,config


class SystemQualityTests(unittest.TestCase):
    def test_new_system_evidence_uses_distinct_authority_and_old_human_rule_stays_closed(self):
        spec,evidence,target,config=sample();old=deepcopy(evidence)
        value=assess(spec,evidence,target,config);self.assertEqual(value['state'],'ready');self.assertEqual(value['quality'],'探索')
        self.assertFalse(value['system_decision']['human_review_written']);self.assertEqual(value['system_decision']['authority_kind'],'system_validation')
        self.assertNotIn('reviewer',value['system_decision']);self.assertEqual(evidence,old)
        self.assertEqual(assess_plan_attempt(spec,evidence,target,2,config)['state'],'failed')

    def test_unknown_identity_environment_and_unequal_or_missing_prediction_block(self):
        for condition in ('species','identity','environment','pocket','prediction','first_rank','structure'):
            spec,evidence,target,config=sample()
            if condition=='species':evidence['identity']['species']=10090
            elif condition=='identity':evidence['identity']['sequence_matches']=False
            elif condition=='environment':evidence['environment_resolved']=False
            elif condition=='pocket':evidence['pocket_complete']=False
            elif condition=='prediction':evidence['pocket']['runs'][1]={'score':'8'}
            elif condition=='first_rank':evidence['pocket']['rank']=2
            else:evidence['structure_id']='other'
            with self.subTest(condition=condition):self.assertEqual(assess(spec,evidence,target,config)['state'],'failed')

    def test_alphafold_uses_local_exact_confidence_and_sequence(self):
        spec,evidence,target,config=sample();spec.update(source_type='alphafold',model_id='synthetic',sequence_start=1,sequence_end=2)
        evidence['identity'].update(sequence_start=1,sequence_end=2)
        evidence['confidence']={'plddt':[80.,80.],'pae':[[0.,10.],[10.,0.]],'pocket_indices':[0,1]}
        self.assertEqual(assess(spec,evidence,target,config)['state'],'ready')
        for confidence in ({'plddt':[89.,69.]},{'plddt':[79.,80.]},{'pae':[[0.,10.1],[10.,0.]]},{'pocket_indices':[1,0]}):
            bad=deepcopy(evidence);bad['confidence'].update(confidence)
            with self.subTest(confidence=confidence):self.assertEqual(assess(spec,bad,target,config)['state'],'failed')

    def test_strict_reference_does_not_borrow_system_prediction_authority(self):
        spec,evidence,target,config=sample();spec.update(pocket='reference',reference_code='LIG',reference_chain='A',reference_sequence='1')
        evidence['reference']={k:spec[k] for k in ('reference_code','reference_chain','reference_sequence')}
        evidence['top1_rmsd']=2.0;value=assess(spec,evidence,target,config);self.assertEqual(value['state'],'ready');self.assertEqual(value['quality'],'严格')
        for value in (2.01,float('nan'),True,None):
            evidence['top1_rmsd']=value
            with self.subTest(value=value):self.assertEqual(assess(spec,evidence,target,config)['state'],'failed')
        evidence['top1_rmsd']=1.8;config['requested_rmsd_max_A']=1.5;self.assertEqual(assess(spec,evidence,target,config)['state'],'failed')
