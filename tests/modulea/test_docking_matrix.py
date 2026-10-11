"""隔离资料验证十五成分矩阵裁切、来源绑定与名单保存；不运行对接。"""
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from contracts import ContractError
from storage import file_record
from modulea.core.docking_review import SCHEMA,review_context
from modulea.core.two_pass_workflow import selection_context
from science_modules.a06.matrix_display import VERSION,matrix_view,blue
from science_modules.a06.two_pass import RESULT,VINA,VINA_VERSION
from tests.modulea.test_two_pass import fixture

# 保留实际文件哈希校验，但合成姿势绝不作为研究评分。
class MatrixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.cs=[{'compound_id':f'C{i}','name':f'虚构{i}','name_zh':f'测试{i}'} for i in range(15)]
  self.ts=[{'target_id':f'HGNC:{i+1}','symbol':f'VIRTUAL{i+1}','candidate_grade':'A' if i<9 else 'B'} for i in range(17)]
  self.config={'version':VERSION,'heatmap_compounds':[r['compound_id'] for r in self.cs[:8]],'table_compounds':[r['compound_id'] for r in self.cs],'heatmap_targets':[r['target_id'] for r in self.ts[:8]],'table_targets':[r['target_id'] for r in self.ts[:15]]}
  pose=self.root/'isolated.txt';pose.write_text('isolated synthetic pose; no real calculation',encoding='utf-8');record=file_record(self.root,pose,'isolated_pose')
  pairs=[{'compound_id':c['compound_id'],'target_id':t['target_id'],'state':'ready'} for c in self.cs for t in self.ts]
  self.prep={'source_key':'current-source','input_key':'current-input','analysis_purpose':'workflow_test','compounds':self.cs,'receptors':[{**t,'quality':'严格' if i<5 else '探索'} for i,t in enumerate(self.ts)],'planned_pairs':pairs,'primary_targets':[t['target_id'] for t in self.ts[:5]]}
  self.packet={'schema_version':RESULT,'source_key':'current-source','input_key':'current-input','analysis_purpose':'workflow_test','vina_parameters':VINA,'vina_version':VINA_VERSION,'primary_targets':self.prep['primary_targets'],'pairs':[{**r,'input_key':'current-input','state':'completed','pose_rank':1,'score':-5-i/100,'pose_record':record} for i,r in enumerate(pairs)]}
 def tearDown(self):self.tmp.cleanup()
 def view(self,packet=None,prep=None):return matrix_view(self.config,self.cs,self.ts,packet or self.packet,prep or self.prep,self.root,'current-source')
 def test_full_batch_crop_and_one_result_version(self):
  v=self.view();self.assertEqual(v['full_pair_count'],255);self.assertEqual(sum(map(len,v['heatmap']['cells'])),64);self.assertEqual(sum(map(len,v['table']['cells'])),225)
  pairs={(r['compound_id'],r['target_id']):r for r in self.packet['pairs']}
  for part in ('heatmap','table'):
   for line in v[part]['cells']:
    for cell in line:self.assertEqual(cell['score'],pairs[(cell['compound_id'],cell['target_id'])]['score'])
  self.assertEqual(v['result_version'],'current-input');self.assertEqual(v['heatmap']['columns'][0]['quality_zh'],'严格')
 def test_waiting_has_no_scores_or_mock_cells(self):
  v=matrix_view(self.config,self.cs,self.ts);self.assertFalse(v['ready']);self.assertEqual(v['heatmap']['cells'],[]);self.assertEqual(v['table']['cells'],[])
 def test_NA_retained_and_color_direction(self):
  p=deepcopy(self.packet);p['pairs'][0].update(state='NA',score=None,reason_zh='合成资料无法准备');v=self.view(p);self.assertEqual(v['heatmap']['cells'][0][0]['color'],'#DCE1E5');self.assertIsNone(v['heatmap']['cells'][0][0]['score']);self.assertEqual(blue(-10,-10,-5),'#08519c');self.assertEqual(blue(-5,-10,-5),'#eff6ff')
 def test_scope_duplicate_pose_rank_and_source_block(self):
  for mode in ('missing','duplicate','pose','source','nan'):
   p=deepcopy(self.packet)
   if mode=='missing':p['pairs'].pop()
   elif mode=='duplicate':p['pairs'][-1]=p['pairs'][0]
   elif mode=='pose':p['pairs'][0]['pose_rank']=2
   elif mode=='source':p['source_key']='other-study'
   else:p['pairs'][0]['score']=float('nan')
   with self.assertRaises(ContractError):self.view(p)
  prep=deepcopy(self.prep);prep['source_key']='stale'
  with self.assertRaises(ContractError):self.view(prep=prep)
  (self.root/'isolated.txt').write_text('changed')
  with self.assertRaises(ContractError):self.view()
 def test_legacy_missing_id_is_read_only_not_guessed(self):
  from modulea.devtools.demo_data import build
  from modulea.core.two_pass_workflow import TwoPassWorkflow
  from modulea.core.kernel import VIEW_VALIDATORS
  root=self.root/"legacy-demo";sid=build(root);f=TwoPassWorkflow(root,VIEW_VALIDATORS);view=selection_context(f,f.load(sid))
  self.assertFalse(view["enabled"]);self.assertEqual(view["current_selected"],[]);self.assertIn("缺少成分编号",view["disabled_reason_zh"])
 def test_display_tie_crop_retains_full_batch_and_invalid_ids(self):
  v=self.view();self.assertEqual(len(self.packet['pairs']),255);self.assertNotIn('HGNC:17',[r['target_id'] for r in v['table']['columns']])
  self.config['heatmap_targets'][0]='HGNC:999'
  with self.assertRaises(ContractError):self.view()

# 真正Workflow保存链验证：只在独立虚构研究里保存和批准。
class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.f,self.sid=fixture(self.root,selection=False)
  m=self.f.load(self.sid);group,_=self.f.candidate_record(m,self.f.candidate_binding(m));rows=self.f.result(m,m['current']['A03'])['tables']['ranking']
  self.data={'schema_version':SCHEMA,'study_id':self.sid,'binding':self.f.docking_review_binding(m),'approval':None,'execution_allowed':False,'source_files':[],'compounds':[{**r,'name_zh':r['name'],'identity_prechecked':r['compound_id']=='C1','identity_state_zh':'合成身份状态','source_3d_state_zh':'待补','evidence_zh':'合成证据','manual_reason_zh':'虚构扩展'} for r in rows],'excluded':[],'receptors':[{**r,'candidate_grade':r['evidence_group']} for r in group['group_a']+group['group_b']]}
  self.data['display']={'version':VERSION,'heatmap_compounds':['C1'],'table_compounds':['C1','C2'],'heatmap_targets':[self.data['receptors'][0]['target_id']],'table_targets':[r['target_id'] for r in self.data['receptors']]}
 def tearDown(self):self.tmp.cleanup()
 def request(self,rid,cid='C1'):return {**self.f.selection_binding(self.sid),'expected_docking_review':rid,'selected':[cid],'manual_supplements':{},'reviewer':'隔离测试','reason':'核对虚构身份','confirmed':True}
 def test_save_refresh_no_approval_and_guard_pending(self):
  before=self.f.load(self.sid);draft=self.f.save_docking_review(self.sid,self.data);after=self.f.load(self.sid)
  self.assertEqual(before['current'],after['current']);self.assertEqual(before['reviews'],after['reviews']);self.assertEqual(self.f.current_docking_review(after)['review_id'],draft['review_id']);self.assertFalse(selection_context(self.f,after)['rows'][1]['eligible'])
  with self.assertRaises(ContractError):self.f.save_selection(self.sid,self.request(draft['review_id'],'C2'))
  result=self.f.save_selection(self.sid,self.request(draft['review_id']));self.assertFalse(self.f.approved(self.f.load(self.sid),result['run_id']));self.assertFalse(review_context(self.f,self.f.load(self.sid))['matrix']['ready'])
 def test_new_draft_blocks_old_request_and_cross_study(self):
  old=self.f.save_docking_review(self.sid,self.data);req=self.request(old['review_id']);self.f.save_docking_review(self.sid,self.data)
  with self.assertRaises(ContractError):self.f.save_selection(self.sid,req)
  for mode in ('study','binding','duplicates','execute'):
   d=deepcopy(self.data)
   if mode=='study':d['study_id']='study_other'
   elif mode=='binding':d['binding']['source_reviews']['A03']='old'
   elif mode=='duplicates':d['compounds'].append(d['compounds'][0])
   else:d['execution_allowed']=True
   with self.assertRaises(ContractError):self.f.save_docking_review(self.sid,d)
 def test_resigned_source_and_changed_raw_block_without_older_fallback(self):
  source=self.f.location(self.sid)/'raw'/'identity.txt';source.parent.mkdir(exist_ok=True);source.write_text('virtual identity');self.data['source_files']=[file_record(self.f.location(self.sid),source,'identity')];self.f.save_docking_review(self.sid,self.data);source.write_text('changed')
  self.assertFalse(review_context(self.f,self.f.load(self.sid))['enabled']);self.assertFalse(selection_context(self.f,self.f.load(self.sid))['enabled'])
  source.write_text('virtual identity');m=self.f.load(self.sid);self.f.review(self.sid,m['current']['A03'],'approved','隔离测试','新复核',expected_review=self.f.latest_review(m,self.f.run(m,m['current']['A03'])['artifact_id'])['review_id'])
  self.assertFalse(review_context(self.f,self.f.load(self.sid))['enabled'])

if __name__=='__main__':unittest.main()
