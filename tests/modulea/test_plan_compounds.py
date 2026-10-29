"""新成分选择目标1—25、排序改变、全并列、零交集与不足的独立科学测试。"""
import unittest
from copy import deepcopy
from pathlib import Path
import tempfile
from uuid import uuid4
from unittest.mock import patch
from contracts import ContractError
from science_modules.analysis_protocol import compile_plan
from science_modules.plan_compounds import select
from science_modules import plan_compounds
from modulea.core import plan_compounds as flow
from tests.modulea.test_plan_stages import fixture, body
from intersection_flow import validate_selection
from storage import verified_file


class PlanCompoundScienceTests(unittest.TestCase):
    def choose(self,rows,count=15,metric='intersection_count'):
        plan=compile_plan({'mode':'personalized','parameters':{'a06.component_count':count,'a06.component_sort':metric}})
        ranking=[{'compound_id':f'C{i:02}','name':f'合成{i}', 'intersection_count':a,'mixed_degree':b,
                  'in_network':a>0,'herbs':'合成药'} for i,(a,b) in enumerate(rows)]
        return select({'analysis_purpose':'workflow_test'},{'ranking':ranking},plan)

    def test_one_keeps_complete_boundary_and_excludes_zero(self):
        summary,tables=self.choose([(3,4),(3,5),(1,2),(0,0)],count=1)
        self.assertEqual([r['compound_id'] for r in tables['selected']],['C00','C01'])
        self.assertEqual(summary['主候选数'],2);self.assertEqual(summary['边界并列额外纳入数'],1)
        self.assertTrue(all(r['selection_role']=='边界并列纳入' for r in tables['selected']))
        self.assertEqual(tables['excluded'][-1]['reason_zh'],'无交集关系，不进入对接名单')

    def test_two_uses_actual_metric_and_stable_order_only_for_display(self):
        rows=[(4,5),(3,4),(2,8),(1,7)]
        self.assertEqual([r['compound_id'] for r in self.choose(rows,2)[1]['selected']],['C00','C01'])
        self.assertEqual([r['compound_id'] for r in self.choose(rows,2,'mixed_degree')[1]['selected']],['C02','C03'])

    def test_default_fifteen_and_max_twentyfive_are_not_fixed_five(self):
        rows=[(i,i+1) for i in range(30,0,-1)]
        self.assertEqual(self.choose(rows)[0]['主候选数'],15)
        self.assertEqual(self.choose(rows,25)[0]['主候选数'],25)

    def test_shortfall_all_ties_and_empty_are_explicit(self):
        summary,tables=self.choose([(2,3),(1,2)],25)
        self.assertEqual(summary['主候选数'],2);self.assertTrue(summary['候选不足'])
        self.assertEqual(self.choose([(3,4)]*30,25)[0]['主候选数'],30)
        summary,tables=self.choose([(0,0)])
        self.assertEqual(summary['主候选数'],0);self.assertIsNone(summary['截断值']);self.assertEqual(tables['selected'],[])

    def test_malformed_or_duplicate_input_is_not_silently_selected(self):
        with self.assertRaises(ContractError):self.choose([(True,2)])
        with self.assertRaises(ContractError):self.choose([(-1,2)])

    def test_explicit_five_matches_frozen_original_cutoff_candidates(self):
        from intersection import calculate
        counts=[8,7,6,5,4,4,4,2,1,0]
        components=[{'compound_id':f'C{i:02}','name':f'合成{i}'} for i in range(len(counts))]
        memberships=[{'compound_id':r['compound_id'],'herb':'合成药'} for r in components]
        targets=[{'compound_id':f'C{i:02}','target_id':str(j),'species':9606,'source_ref':'合成关系'}
                 for i,count in enumerate(counts) for j in range(count)]
        disease=[{'target_id':str(j),'species':9606,'source_ref':'合成疾病'} for j in range(8)]
        old=calculate(components,memberships,targets,disease,['合成药'],'HGNC')
        plan=compile_plan({'mode':'personalized','parameters':{'a06.component_count':5}})
        _,tables=select({'analysis_purpose':'workflow_test'},{'ranking':old['ranking']},plan)
        self.assertEqual({r['compound_id'] for r in tables['selected']},set(old['above_cutoff'])|set(old['boundary']))


class PlanCompoundPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_compound_publication_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.w,self.sid,self.plan=fixture(self.root)
        self.w.validators['A03_SELECT']=plan_compounds.validator(self.root,validate_selection)
        a03=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'))
        self.w.review(self.sid,a03['run_id'],'approved','隔离测试','合成上游已检查')

    def request(self):
        value=flow.info(self.w,self.sid)
        return dict({k:v for k,v in value.items() if k.startswith('expected_')},operator='隔离测试',
                    reason='合成成分方案选择测试',confirmed=True)

    def test_actual_publication_keeps_parents_reviews_and_exact_scope(self):
        before=self.w.load(self.sid);request=self.request()
        result=flow.publish(self.w,self.sid,request)
        after=self.w.load(self.sid)
        self.assertEqual(after['reviews'],before['reviews'])
        self.assertEqual(after['current']['A03'],before['current']['A03'])
        self.assertEqual(result['summary']['目标成分数'],15)
        self.assertEqual(result['summary']['主候选数'],1)
        self.assertTrue(result['summary']['候选不足'])
        self.assertFalse(flow.info(self.w,self.sid)['enabled'])
        run=self.w.run(after,result['run_id']);bad=deepcopy(result['tables']);bad['selected']=[]
        with self.assertRaises(ContractError):self.w.validators['A03_SELECT'](run,result['summary'],bad,result['anomalies'],result['outcome'])
        self.assertFalse(self.w.approved(after,result['run_id']))

    def test_hidden_fields_stale_draft_and_confirmation_are_rejected(self):
        request=self.request()
        for changes in ({'selected':['C1']},{'confirmed':False},{'expected_input_hash':'old'}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):flow.validate(self.w,self.sid,dict(request,**changes))
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,
            'expected_a00':request['expected_a00'],'expected_draft_id':self.plan['plan_id'],
            'specification':{'mode':'personalized','parameters':{'a06.component_count':2}},'author':'隔离测试','note':'只改变方案'})
        with self.assertRaises(ContractError):flow.publish(self.w,self.sid,request)

    def test_archived_confirmation_tamper_blocks_revalidation(self):
        result=flow.publish(self.w,self.sid,self.request());run=self.w.run(self.w.load(self.sid),result['run_id'])
        path=verified_file(self.w.location(self.sid),run['inputs']['execution_request_file'])
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ContractError):self.w.validators['A03_SELECT'](run,result['summary'],result['tables'],result['anomalies'],result['outcome'])

    def test_read_only_info_does_not_choose_or_write(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(plan_compounds,'select',side_effect=AssertionError('HTTP不应科学计算')):
            value=flow.info(self.w,self.sid)
        self.assertEqual(value['target_count'],15);self.assertTrue(value['enabled'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_only_selected_pending_identity_blocks_without_replacement(self):
        for cid,blocked in [('C1',True),('C999',False)]:
            review={'compounds':[{'compound_id':cid,'identity_prechecked':False}],'excluded':[]}
            with self.subTest(cid=cid),patch.object(self.w,'current_docking_review',return_value=review):
                request=self.request()
                if blocked:
                    with self.assertRaises(ContractError):flow.publish(self.w,self.sid,request)
                    self.assertNotIn('A03_SELECT',self.w.load(self.sid)['current'])
                else:
                    result=flow.publish(self.w,self.sid,request)
                    self.assertEqual([r['compound_id'] for r in result['tables']['selected']],['C1'])
