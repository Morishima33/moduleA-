"""新报告事实模型的范围、缺译、动态矩阵和终态；纯合成输入，不生成科研结果。"""
from copy import deepcopy
import unittest
from contracts import ContractError,fingerprint
from science_modules.a07.plan_facts import automatic_enrichment,docking,completion
from science_modules.a05 import screening
from tests.modulea.test_plan_a05_display import fixture


def packet():
    """2×2明确合成评分；科学来源验证由实际发布流程负责，本测试只验证呈现。"""
    return {'compounds':[{'compound_id':'c1','name':'One'},{'compound_id':'c2','name':'Two'}],
            'receptors':[{'target_id':'t1','symbol':'T1'},{'target_id':'t2','symbol':'T2'}],
            'pairs':[{'compound_id':cid,'target_id':tid,'state':state,'score':score,'quality':quality,'reason_zh':reason}
              for cid,tid,state,score,quality,reason in (
                  ('c1','t1','completed',-8.001,'严格',''),('c1','t2','NA',None,'NA','固定身份未通过'),
                  ('c2','t1','completed',-7.999,'探索',''),('c2','t2','failed',None,'探索','工具输出不完整'))]}


class PlanReportFactsTests(unittest.TestCase):
    def test_system_scope_retains_mechanism_excludes_other_disease_and_defers_unknown(self):
        base,plan,source=fixture(count=4)
        source['catalog']['pathways']['00001']=[{'category':'Human Diseases','subcategory':'Synthetic','name':'Other disease'}]
        source['catalog']['pathways']['00002']=[{'category':'Human Diseases','subcategory':'Synthetic','name':'Synthetic KEGG term 2'}]
        del source['catalog']['pathways']['00003']
        source['identity']={'verified':True,'mesh_id':'D123456','names':['synthetic kegg term 2']}
        source['assessments']=screening.assess(base['tables']['kegg_significant'],source['catalog'],source['identity'])
        before=fingerprint(base);result=automatic_enrichment(base,plan,source)
        self.assertEqual(result['authority_kind'],'system_scope_rule');self.assertFalse(result['human_review_written'])
        self.assertFalse(result['scientific_validation_performed']);self.assertNotIn('confirmed',result)
        self.assertEqual([r['ID'] for r in result['tables']['kegg_excluded']],['hsa00001'])
        self.assertEqual([r['ID'] for r in result['tables']['kegg_deferred']],['hsa00003'])
        self.assertEqual({r['ID'] for r in result['tables']['kegg_display']},{'hsa00002','hsa00004'})
        self.assertEqual(fingerprint(base),before);self.assertEqual(result['groups'][-1]['significant_count'],4)

    def test_missing_translation_keeps_original_and_does_not_block_report_model(self):
        base,plan,source=fixture(count=2);source['translations']={key:{} for key in source['translations']}
        result=automatic_enrichment(base,plan,source)
        row=result['tables']['bp_display'][0]
        self.assertEqual(row['english'],'Synthetic BP term 1');self.assertEqual(row['chinese'],'')
        self.assertEqual(row['translation_status'],'pending');self.assertIn('中文待核译',row['label'])
        self.assertTrue(result['pending_translations']);self.assertNotIn('handoff_blocked',result)

    def test_bound_plan_counts_and_omitted_kegg_are_not_zero_tests(self):
        base,plan,source=fixture({'a05.go_plot_top':10,'a05.go_table_top':25,'a05.include_kegg':False},count=30)
        result=automatic_enrichment(base,plan,source)
        self.assertEqual(len(result['tables']['bp_display']),10);self.assertEqual(len(result['tables']['bp_plan_top']),25)
        self.assertEqual(result['tables']['kegg_display'],[]);self.assertIsNone(result['groups'][-1]['significant_count'])
        self.assertIsNone(result['groups'][-1]['retained_count'])
        wrong=deepcopy(source);wrong['parameter_hash']='old'
        with self.assertRaises(ContractError):automatic_enrichment(base,plan,wrong)

    def test_unknown_disease_identity_defers_without_invented_exact_match(self):
        base,plan,source=fixture(count=1)
        source['catalog']['pathways']['00001']=[{'category':'Human Diseases','subcategory':'Synthetic','name':'Synthetic disease'}]
        source['assessments']=screening.assess(base['tables']['kegg_significant'],source['catalog'],source['identity'])
        result=automatic_enrichment(base,plan,source)
        self.assertEqual(len(result['tables']['kegg_deferred']),1);self.assertEqual(result['tables']['kegg_excluded'],[])
        self.assertEqual(result['tables']['kegg_display'],[])

    def test_dynamic_complete_matrix_raw_scores_na_and_failures_are_preserved(self):
        original=packet();before=fingerprint(original);value=docking(original,{'version':'actual_test_config'})
        self.assertEqual(value['state'],'partial');self.assertEqual(value['counts'],{
            'compounds':2,'receptors':2,'pairs':4,'scored':2,'failed':1,'NA':1,'ready':0,'strict_scored':1,'exploratory_scored':1})
        self.assertEqual(value['matrix'][0]['cells'][0]['score'],-8.001)
        self.assertEqual(value['matrix'][1]['cells'][0]['score'],-7.999)
        self.assertIsNone(value['matrix'][0]['cells'][1]['score']);self.assertEqual(fingerprint(original),before)
        self.assertFalse(value['scientific_validation_performed']);self.assertFalse(value['human_review_written'])

    def test_incomplete_or_duplicate_range_and_filled_na_are_rejected(self):
        for change in ('missing','duplicate','zero_na','nan_score','boolean_score','unknown_quality'):
            raw=packet()
            if change=='missing':raw['pairs'].pop()
            elif change=='duplicate':raw['pairs'][-1]=deepcopy(raw['pairs'][0])
            elif change=='zero_na':raw['pairs'][1]['score']=0
            elif change=='nan_score':raw['pairs'][0]['score']=float('nan')
            elif change=='boolean_score':raw['pairs'][0]['score']=True
            else:raw['pairs'][0]['quality']='unknown'
            with self.subTest(change=change),self.assertRaises(ContractError):docking(raw,{})

    def test_all_na_preparation_is_inapplicable_ready_input_waits_failed_scores_block(self):
        raw=packet();rows=raw.pop('pairs')
        raw['planned_pairs']=[dict(row,state='NA',score=None,reason_zh='固定原对象准备失败') for row in rows]
        value=docking(raw,{},preparation_only=True);self.assertEqual(value['state'],'not_applicable');self.assertEqual(value['counts']['scored'],0)
        raw['planned_pairs'][0].update(state='ready',reason_zh='等待评分')
        self.assertEqual(docking(raw,{},preparation_only=True)['state'],'waiting')
        failed=packet()
        for row in failed['pairs']:
            if row['state']=='completed':row.update(state='failed',score=None,reason_zh='实际工具失败')
        self.assertEqual(docking(failed,{})['state'],'technical_blocked')

    def test_completion_distinguishes_waiting_empty_partial_and_blocked(self):
        def branches(*states):return [{'branch':str(i),'state':state,'reason_zh':'合成实际分支事实'} for i,state in enumerate(states)]
        for states,expected,finished in ((('completed','waiting'),'waiting',False),
            (('valid_empty','not_applicable'),'valid_empty',True),(('completed','partial'),'partial',True),
            (('completed','technical_blocked'),'technical_blocked',True),(('waiting','technical_blocked'),'technical_blocked',False),
            (('completed','completed'),'completed',True),(('not_applicable',),'valid_empty',True)):
            with self.subTest(states=states):
                value=completion(branches(*states));self.assertEqual(value['state'],expected);self.assertEqual(value['all_applicable_finished'],finished)
                self.assertEqual(value['complete_analysis'],expected=='completed');self.assertFalse(value['human_review_written'])
        with self.assertRaises(ContractError):completion([])
        with self.assertRaises(ContractError):completion([{'branch':'x','state':'completed','reason_zh':''}])
