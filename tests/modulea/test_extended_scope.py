"""扩展名单沿用旧选择内核，并验证新连接/执行不会退回默认五项。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from contracts import ContractError
from intersection_flow import build, select_build
from modulea.core.extended_scope import context, require_ready
from modulea.core.automatic_experience import AutomaticExperienceWorkflow
from science_modules.a06.candidates import build as candidates
from science_modules.a06.plan_adapter import source_context


def inputs(n=20):
    genes = [dict(target_id=f'HGNC:{100+i}', symbol=f'SYNTHETIC{i}', species=9606, source_ref='synthetic:1') for i in range(n)]
    payload = dict(namespace='HGNC', mapping_snapshot='a'*64, analysis_purpose='workflow_test', herbs=['A','B'],
        components=[dict(compound_id=f'C{i:02}', name=f'SYNTHETIC_{i}') for i in range(n)],
        memberships=[dict(compound_id=f'C{i:02}', herb='A' if i<10 else 'B') for i in range(n)],
        disease_targets=genes, compound_targets=[dict(g, compound_id=f'C{i:02}') for i in range(n) for g in genes[:n-i]])
    return dict(payload=payload, selected=[f'C{i:02}' for i in range(min(15,n))], reviewer='合成测试', reason='扩展候选核对', identity_confirmed=True,
        selection_policy='explicit_manual_supplements_v2', manual_supplements={f'C{i:02}':'隔离测试明确补充' for i in range(5,min(15,n))})


class Fixture:
    def __init__(self,n=20,selected=5,approved=True):
        self.request=inputs(n)
        _,self.a03summary,self.a03tables=build(self.request['payload'])
        self.selection=deepcopy(self.a03tables['ranking'][:selected])
        self.ok=approved;self.valid=True;self.draft=None;self.parent='a03'
        self.manifest={'study_id':'synthetic','current':{'A00':'a00','A03':'a03','A03_SELECT':'selected','A04':'a04'},
                       'runs':{k:{'result_file':{'path':k+'.json','bytes':1,'sha256':'a'*64}} for k in ('a00','a03','selected','a04')}}
        rows=[dict(target_id=f'HGNC:{i+1}',symbol=f'TEST{i+1}',degree=100-i if i<13 else 20,bc=1.,cc=1.) for i in range(16)]
        self.a04={'degree_round2':rows,'degree_top10':rows[:10],'bc_cc_top15':rows[:15]}
        self.group=candidates(self.a04)
        self.group['group_id']='synthetic_group'
    def result(self,m,rid):
        return {'tables':{'ranking':self.a03tables['ranking'],'suggestions':self.a03tables['suggestions']}} if rid=='a03' else {'tables':{'selected':deepcopy(self.selection)}} if rid=='selected' else {'tables':self.a04} if rid=='a04' else {'summary':{'analysis_purpose':'workflow_test'}}
    def run(self,m,rid):return {'parent_runs':{'A03':self.parent},'artifact_id':'artifact_'+rid}
    def active(self,*a):return self.valid
    def approved(self,*a):return self.ok
    def current_docking_review(self,*a):return self.draft
    def latest_review(self,m,artifact):return {'review_id':'review_'+artifact}
    def candidate_binding(self,m):return {'synthetic':True}
    def candidate_record(self,m,b):return self.group,{'path':'synthetic_group.json'}


class ExtendedScopeTests(unittest.TestCase):
    def test_real_archived_selection_review_then_full_scope_keeps_old_batch(self):
        from workflow import Workflow
        from intersection_flow import CONFIG, validate_intersection, validate_selection, run_selection
        with TemporaryDirectory() as directory:
            w=Workflow(Path(directory),{'A03':validate_intersection,'A03_SELECT':validate_selection})
            sid=w.create({'formula':'合成扩展方','herbs':'A、B','disease':'合成疾病','disease_scope':'隔离代码验收','operator':'test','species':9606,'analysis_purpose':'workflow_test'},kind='contract_test')
            def approve(rid):w.review(sid,rid,'approved','合成测试核验人','仅用于隔离流程测试')
            approve(w.load(sid)['current']['A00'])
            for module in ('A01','A02'):
                run=w.begin(sid,module,{}, {},'合成上游');w.finish(sid,run['run_id'],{'test_only':True});approve(run['run_id'])
            data=inputs();_,summary,tables=build(data['payload'])
            run=w.begin(sid,'A03',{'payload':data['payload']},dict(CONFIG),'合成交集');w.finish(sid,run['run_id'],summary,tables);approve(run['run_id']);a03=run['run_id']
            f=Fixture()
            run=w.begin(sid,'A04',{}, {},'合成PPI');w.finish(sid,run['run_id'],{'test_only':True},f.a04);approve(run['run_id'])
            w.current_docking_review=lambda m:None
            w.candidate_binding=lambda m:{'synthetic':True}
            w.candidate_record=lambda m,b:(f.group,{'path':'synthetic_group.json'})
            first=run_selection(w,sid,a03,'',data['selected'][:5],'合成测试','主候选核对',True);approve(first['run_id'])
            for module in ('A06_PREP','A06'):
                run=w.begin(sid,module,{}, {},'合成旧批次');w.finish(sid,run['run_id'],{'test_only':True});approve(run['run_id'])
            old_a06=w.load(sid)['current']['A06'];old_result=w.result(w.load(sid),old_a06)
            draft=context(w,w.load(sid));self.assertFalse(draft['ready'])
            expanded=run_selection(w,sid,a03,first['run_id'],draft['proposed_ids'],'合成测试','明确扩展名单',True,draft['manual_reasons'])
            self.assertEqual(w.run(w.load(sid),expanded['run_id'])['config']['version'],'A03.select.4')
            with self.assertRaisesRegex(ContractError,'独立复核'):require_ready(w,w.load(sid))
            approve(expanded['run_id']);require_ready(w,w.load(sid))
            from modulea.core.two_pass_workflow import selection_context
            w.selection_binding=lambda study:{'expected_a03':a03,'expected_select':expanded['run_id']}
            reopened=selection_context(w,w.load(sid))
            self.assertEqual(reopened['current_manual_supplements'],draft['manual_reasons'])
            connection=source_context(w,sid,w.load(sid))
            self.assertEqual((len(connection['compounds']),len(connection['receptors'])),(15,16))
            self.assertEqual(w.load(sid)['current']['A06'],old_a06)
            self.assertFalse(w.active(w.load(sid),old_a06))
            self.assertEqual(w.result(w.load(sid),old_a06),old_result)

    def test_default_five_cannot_enter_new_extended_execution(self):
        w=Fixture();before=deepcopy(w.manifest);d=context(w,w.manifest)
        self.assertEqual((d['selected_count'],d['required_count'],d['proposed_count']),(5,15,15))
        self.assertFalse(d['ready'])
        with self.assertRaisesRegex(ContractError,'扩展筛查'):require_ready(w,w.manifest)
        self.assertEqual(w.manifest,before)

    def test_old_manual_selection_core_flows_into_all_fifteen_by_sixteen(self):
        w=Fixture();summary,tables=select_build(w.request)
        self.assertEqual(summary['人工补充纳入数'],10)
        self.assertEqual(len(tables['selected']),15)
        w.selection=tables['selected'];scope=require_ready(w,w.manifest)
        connected=source_context(w,'synthetic',w.manifest)
        self.assertEqual([r['compound_id'] for r in connected['compounds']],w.request['selected'])
        self.assertEqual(len(connected['receptors']),16)
        self.assertEqual(len([(c,t) for c in connected['compounds'] for t in connected['receptors']]),240)
        self.assertEqual(scope['selected_count'],15)
        self.assertEqual(w.a03tables['ranking'][0]['main_rank'],1)

    def test_saved_but_unapproved_stale_or_foreign_parent_cannot_pass(self):
        for change in ('approval','active','parent'):
            w=Fixture(selected=15)
            if change=='approval':w.ok=False
            elif change=='active':w.valid=False
            else:w.parent='foreign_a03'
            with self.subTest(change=change),self.assertRaises(ContractError):require_ready(w,w.manifest)

    def test_boundary_ties_are_proposed_without_silent_truncation(self):
        w=Fixture();w.a03tables['ranking'][15]['intersection_count']=w.a03tables['ranking'][14]['intersection_count']
        d=context(w,w.manifest)
        self.assertEqual(d['proposed_count'],16)
        self.assertFalse(d['ready'])

    def test_blocked_identity_is_not_in_draft_or_accepted_selection(self):
        w=Fixture(selected=15);w.draft={'compounds':[{'compound_id':'C00','identity_prechecked':False}],'excluded':[]}
        d=context(w,w.manifest)
        self.assertNotIn('C00',d['proposed_ids']);self.assertIn('C15',d['proposed_ids'])
        self.assertFalse(d['ready'])

    def test_small_study_retains_real_available_count_no_fake_fifteen(self):
        w=Fixture(n=6,selected=6);d=require_ready(w,w.manifest)
        self.assertEqual(d['required_count'],6)
        self.assertEqual(d['proposed_count'],6)

    def test_no_eligible_rows_does_not_enable_execution(self):
        w=Fixture();w.a03tables['ranking']=[];d=context(w,w.manifest)
        self.assertFalse(d['ready']);self.assertEqual(d['required_count'],0)

    def test_legacy_selection_missing_id_stays_readonly_without_crashing(self):
        w=Fixture(selected=15);w.selection[0].pop('compound_id')
        d=context(w,w.manifest)
        self.assertFalse(d['ready']);self.assertIn('稳定编号',d['reason_zh'])

    def test_gate_is_called_by_authorization_for_new_but_not_existing_request(self):
        # 执行范围检查本身已由上面的真实旧内核和240组合投影验证；此处验证授权接线。
        w=AutomaticExperienceWorkflow.__new__(AutomaticExperienceWorkflow)
        w.location=lambda sid:Path('.')
        manifest={'current':{'A06':'run_current'}}
        request={'reference_choices':[],'request_id':'auto_test'}
        record={'packet':{'path':'connection'}}
        with patch('modulea.core.automatic_experience._versioned',return_value=lambda *a:(manifest,None,record)), \
             patch('modulea.core.automatic_experience.verified_file',return_value=Path('unused')), \
             patch('modulea.core.automatic_experience.read_json',return_value={'receptors':[]}), \
             patch('science_modules.a06.reference_candidates.validate_choices'):
            w.automatic_record=lambda *a:None
            with patch.object(w,'validate_extended_scope',side_effect=ContractError('不足完整扩展范围')):
                with self.assertRaisesRegex(ContractError,'完整扩展'):w.validate_automatic_request('synthetic',request)
            w.automatic_record=lambda *a:{'id':'existing_authorization'}
            with patch.object(w,'validate_extended_scope',side_effect=AssertionError('历史授权不重解释')):
                w.validate_automatic_request('synthetic',request)

    def test_continue_after_expanded_selection_does_not_wait_for_stale_old_a06(self):
        from modulea.tasks.worker import run_continue
        from contextlib import nullcontext
        w=SimpleNamespace(load=lambda sid:{'current':{'A06':'old_a06'}},run=lambda *a:{'config':{'schema_version':'A06.automatic.2'}},
            active=lambda *a:False,validate_extended_scope=lambda *a:{'selected_count':15})
        with patch('modulea.tasks.worker.full_workflow',return_value=w),patch('report_dispatch.run_reports',side_effect=AssertionError('旧批次不能生成报告')):
            text=run_continue(SimpleNamespace(data_root='synthetic'),{'study_id':'synthetic','task_id':'task'},SimpleNamespace(update=lambda *a,**k:None))
        self.assertIn('A06_PREP',text);self.assertIn('15',text);self.assertIn('旧批次保留',text)

    def test_fresh_approved_expanded_scope_stops_at_new_connection_not_old_preparation(self):
        from modulea.tasks.worker import run_continue
        w=SimpleNamespace(load=lambda sid:{'current':{'A03_SELECT':'selection','A04':'ppi'}},approved=lambda *a:True,
            validate_extended_scope=lambda *a:{'selected_count':15})
        with patch('modulea.tasks.worker.full_workflow',return_value=w),patch('auto_continue.continue_after_review',side_effect=AssertionError('不得进入旧准备路线')):
            text=run_continue(SimpleNamespace(data_root='synthetic'),{'study_id':'synthetic','task_id':'task'},SimpleNamespace(update=lambda *a,**k:None))
        self.assertIn('A06_PREP',text);self.assertIn('15',text)

    def test_connection_api_accepts_approved_fifteen_without_hidden_object_list(self):
        from modulea.api.server import App
        w=Fixture(selected=15)
        w.automatic_binding=lambda *a:(w.manifest,{'synthetic':True})
        w.validate_extended_scope=lambda *a:require_ready(w,w.manifest)
        submitted=[]
        app=SimpleNamespace(_automatic_ready=lambda sid:w,tasks=SimpleNamespace(submit=lambda *a:(submitted.append(a) or {'task_id':'synthetic'},True)))
        response,status=App.post_automatic_connect(app,SimpleNamespace(json=lambda:{'expected_binding':'a'*64}),'synthetic')
        self.assertEqual(status,202);self.assertEqual(submitted[0][1],'a06_auto_connect')
        self.assertEqual(submitted[0][3]['policy_version'],'A06.automatic.3')
        self.assertNotIn('selected',submitted[0][3])

    def test_next_action_points_to_scope_without_changing_scientific_states(self):
        from modulea.api.views import Views
        w=Fixture();states={m:{'code':'approved'} for m in ('A03','A03_SELECT','A04')}
        before=deepcopy(states)
        view=SimpleNamespace(tasks=SimpleNamespace(active_for=lambda sid:False),_next_step=lambda _: {'module_id':'A06','code':'review'})
        action=Views._scope_next_step(view,w,w.manifest,states)
        self.assertEqual(action['module_id'],'A03_SELECT');self.assertEqual(states,before)


if __name__=='__main__':unittest.main()
