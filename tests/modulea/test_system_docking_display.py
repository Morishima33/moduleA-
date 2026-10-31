"""回归：系统1/2评分及准备不可落入旧未启动提示，NA和实际固定名单完整展示。"""
from copy import deepcopy
import unittest
from unittest.mock import patch
from modulea.presenters.system_docking import present,VERSIONS
from modulea.api.system_docking_view import apply
from contracts import ContractError


class SystemDockingDisplayTests(unittest.TestCase):
    def setUp(self):
        self.packet={'compounds':[{'compound_id':'C1','name':'本批原名称'},{'compound_id':'C2','name':'保留NA'}],
            'receptors':[{'target_id':'T1','symbol':'原靶点','candidate_grade':'B'}]}
        self.result={'summary':{'science_version':'A06.system_scoring.2','pair_count':2,'scored_pairs':1,
            'failed_pairs':0,'na_pairs':1,'strict_scored_pairs':0,'exploratory_scored_pairs':1,
            'message_zh':'实际评分','input_key':'fixed','analysis_parameter_hash':'original'},
            'tables':{'plan_scoring_pairs':[{'compound_id':'C1','target_id':'T1','state':'completed','state_zh':'已评分','score':-7.0},
                {'compound_id':'C2','target_id':'T1','state':'NA','state_zh':'准备NA','score':None,'reason_zh':'本对象缺资料'}]}}

    def test_both_system_scoring_versions_keep_full_na_matrix_without_claiming_approval(self):
        before=deepcopy(self.result)
        for version in VERSIONS[-2:]:
            result=deepcopy(self.result);result['summary']['science_version']=version
            display=present(result,self.packet);matrix=display['special']['heatmap']
            self.assertEqual(len(matrix['rows']),2);self.assertEqual(matrix['rows'][0]['compound_name'],'本批原名称')
            self.assertEqual(matrix['rows'][0]['cells'][0]['value'],-7.0);self.assertIsNone(matrix['rows'][1]['cells'][0]['value'])
            self.assertEqual(matrix['omitted'],[]);self.assertEqual(display['table']['rows'][1]['reason_zh'],'本对象缺资料')
            self.assertIn('NA保留',matrix['color_rule_zh'])
            self.assertNotIn('已批准',str(display));self.assertNotIn('未启动',str(display))
        self.assertEqual(self.result,before)

    def test_all_na_never_builds_empty_heatmap_or_fills_zero(self):
        self.result['summary'].update(scored_pairs=0,na_pairs=2,exploratory_scored_pairs=0)
        self.result['tables']['plan_scoring_pairs'][0].update(state='NA',state_zh='准备NA',score=None)
        display=present(self.result,self.packet);self.assertNotIn('heatmap',display['special'])
        self.assertTrue(all(row['score'] is None for row in display['table']['rows']))

    def test_all_preparation_versions_show_actual_receptor_reason_without_scoring(self):
        for version in VERSIONS[:-2]:
            result=deepcopy(self.result);result['summary'].update(science_version=version,scored_pairs=0,ready_pairs=1)
            result['tables'].update(planned_pairs=result['tables']['plan_scoring_pairs'],
                receptor_preparation=[{'target_id':'T1','symbol':'原靶点','state':'ready','quality':'探索','reason_zh':'原证据'}])
            display=present(result,self.packet);self.assertNotIn('heatmap',display['special'])
            self.assertEqual(display['table']['rows'][0]['reason_zh'],'原证据')
            self.assertEqual(display['table']['rows'][0]['state_zh'],'准备可用')

    def test_api_rejects_other_batch_and_clears_legacy_executors_without_changing_review(self):
        class Reader:
            def location(self,sid):return sid
        run={'config':{'version':'A06.system_scoring.2'},'study_id':'study','inputs':{'system_input_ref':{}},'batch_file':{'actual':'batch'}}
        fixed={'study_id':'study','stage':'A06_INPUT','binding':{'batch_file':run['batch_file']},'payload':dict(self.packet,input_key='fixed')}
        response={'review':{'can_review':False,'continue':{'available':True}}}
        with patch('modulea.api.system_docking_view.verified_file',return_value='actual'),patch('modulea.api.system_docking_view.read_json',return_value=fixed):
            apply(Reader(),{'study_id':'study'},run,self.result,response)
            self.assertFalse(response['review']['can_review']);self.assertFalse(response['review']['continue']['available'])
            self.assertIsNone(response['automatic_docking']);self.assertIsNone(response['plan_scoring'])
            fixed['binding']['batch_file']={'other':'batch'}
            with self.assertRaises(ContractError):apply(Reader(),{'study_id':'study'},run,self.result,response)
