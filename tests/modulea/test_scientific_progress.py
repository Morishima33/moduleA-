"""区域、组合与准备进度分离；完整原组、失败和复用分别计数。"""
from copy import deepcopy
import unittest
from contracts import ContractError
from modulea.api.scientific_progress import summarize


class ScientificProgressTests(unittest.TestCase):
    def setUp(self):
        self.fixed={'compounds':[{'compound_id':'C1'},{'compound_id':'C2'}],
                    'receptors':[{'target_id':'T1'},{'target_id':'T2'}]}
        self.baseline={'pairs':[{'compound_id':c['compound_id'],'target_id':t['target_id'],
                        'state':'completed' if t['target_id']=='T1' else 'NA'}
                        for c in self.fixed['compounds'] for t in self.fixed['receptors']]}
        self.prepared=[{'target_id':'T1','state':'ready'},{'target_id':'T2','state':'NA'}]
        self.receptor={'target_id':'T2','state':'ready','mode':'partitioned_blind','regions':[{'region_id':'R1'},{'region_id':'R2'}]}

    def fact(self,region,state='completed',score=-7):
        return {'region_id':region,'state':state,'score':score if state=='completed' else None,'retryable':False}

    def test_two_successful_regions_count_one_completed_combination(self):
        current={'receptor_T2':self.receptor,'pair_000002_region_0001':self.fact('R1'),
                 'pair_000002_region_0002':self.fact('R2')}
        value=summarize(self.fixed,self.baseline,self.prepared,{},current)
        self.assertEqual(value['pairs']['succeeded'],3)
        self.assertEqual(value['pairs']['new'],1)
        self.assertEqual(value['regions']['succeeded'],2)
        self.assertEqual(value['preparation']['reused'],1)
        self.assertEqual(value['preparation']['new'],1)

    def test_partial_region_failure_keeps_completed_combination_and_incomplete_group_is_pending(self):
        current={'receptor_T2':self.receptor,'pair_000002_region_0001':self.fact('R1'),
                 'pair_000002_region_0002':self.fact('R2','failed'),
                 'pair_000004_region_0001':self.fact('R1')}
        value=summarize(self.fixed,self.baseline,self.prepared,{},current)
        self.assertEqual(value['pairs']['completed'],3)
        self.assertEqual(value['pairs']['failed'],0)
        self.assertEqual(value['regions']['failed'],1)
        self.assertEqual(value['pairs']['pending'],1)

    def test_baseline_na_receptors_are_pending_until_actual_attempt_is_registered(self):
        value=summarize(self.fixed,self.baseline,self.prepared,{}, {})
        self.assertEqual(value['preparation']['completed'],1)
        self.assertEqual(value['preparation']['pending'],1)
        self.assertIsNone(value['regions']['total'])

    def test_registered_inherited_group_counts_reuse_not_new(self):
        inherited={'receptor_T2':self.receptor,'pair_000002_region_0001':self.fact('R1'),
                   'pair_000002_region_0002':self.fact('R2')}
        value=summarize(self.fixed,self.baseline,self.prepared,inherited,{})
        self.assertEqual(value['pairs']['reused'],3)
        self.assertEqual(value['pairs']['new'],0)
        self.assertEqual(value['regions']['reused'],2)

    def test_unknown_region_set_stays_unknown_and_wrong_region_id_fails(self):
        value=summarize(self.fixed,self.baseline,[{'target_id':'T2','state':'ready'}],{}, {})
        self.assertIsNone(value['regions']['total'])
        with self.assertRaises(ContractError):
            summarize(self.fixed,self.baseline,self.prepared,{}, {'receptor_T2':self.receptor,
                      'pair_000002_region_0001':self.fact('foreign')})


if __name__=='__main__':unittest.main()
