"""新平台评分按原生字段展示，不能误走旧评分字段而丢失结果。"""
from unittest import TestCase
from modulea.presenters import present


class NativePresenterTests(TestCase):
    def test_native_scores_use_actual_counts_and_complete_table(self):
        pairs=[{'compound_id':'synthetic_C','target_id':'synthetic_T','score':-1.25,
                'state':'completed','quality':'探索','reason_zh':''},
               {'compound_id':'synthetic_D','target_id':'synthetic_T','score':None,
                'state':'NA','quality':'探索','reason_zh':'合成身份资料不足'}]
        result={'summary':{'science_version':'A06.platform_execution.1','pair_count':2,
            'compound_count':2,'receptor_count':1,'scored_pairs':1,'failed_pairs':0,'na_pairs':1,
            'message_zh':'合成原生评分，待独立复核','input_key':'synthetic_key'},
            'tables':{'native_scores':pairs}}
        value=present('A06',result,{})
        self.assertIsNotNone(value['table'],'不能按旧字段展示而丢失本批原生评分')
        self.assertEqual(value['table']['source_table'],'native_scores')
        self.assertEqual(value['table']['row_count'],2)
        self.assertEqual([r['score'] for r in value['table']['rows']],[-1.25,None])
        self.assertEqual(value['table']['rows'][1]['reason_zh'],'合成身份资料不足')
        self.assertIn('合成原生评分',value['flow_note_zh'])
        self.assertTrue(any(row['label_zh']=='有效评分' and row['value']==1 for row in value['kpis']))
