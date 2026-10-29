"""新版A02/A03/A04实际任务接续、明确确认归档及旧流程隔离；只用合成研究。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from contracts import ContractError
from storage import read_json, verified_file
from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core.kernel import full_workflow
from modulea.core.trace_export import build_trace
from science_modules import plan_stages
from science_modules.plan_stages_contract import info, validate
from science_modules.a04 import plan_flow as network
from intersection_flow import validate_intersection
from tests.modulea.test_study_creation import official_fixture


def fixture(root,modern=False,score=.7,purpose='workflow_test'):
    """原始标准化上游为合成字段，实际交集和网络由生产科学入口执行。"""
    w=AnalysisPlanWorkflow(root,{'A03':plan_stages.a03_validator(root,validate_intersection),
                               'A04':network.validator(root,lambda *args:None)})
    intake={'formula':'合成阶段测试方','herbs':'合成药','disease':'合成病','disease_scope':'仅本病',
        'operator':'隔离测试','species':9606,'analysis_purpose':purpose,'analysis_plan_profile':'ModuleA.analysis_plan.1'}
    if modern or purpose=='formal_research':intake.update(mesh_term='Synthetic Disease',mesh_id='D123456',mesh_verification=official_fixture('Synthetic Disease','D123456'))
    sid=w.create(intake,kind='research' if modern else 'contract_test');a00=w.load(sid)['current']['A00'];w.review(sid,a00,'approved','隔离测试','合成登记')
    draft=w.save_analysis_plan_draft(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':a00,'expected_draft_id':'',
        'specification':{'mode':'personalized','parameters':{'a04.required_score':score}},'author':'隔离测试','note':'合成参数'})['draft']
    if not modern:
        components=[{'compound_id':'C1','name':'合成成分'}]
        edges=[{'compound_id':'C1','target_id':f'HGNC:{i}','symbol':f'G{i}','species':9606,'source_ref':'合成来源'} for i in range(1,5)]
        disease=[{key:value for key,value in row.items() if key!='compound_id'} for row in edges]
        summary={'namespace':'HGNC','mapping_snapshot':'a'*64,'analysis_purpose':purpose}
        for module,tables in [('A01',{'components':components,'herb_components':[{'compound_id':'C1','herb':'合成药'}],
            'herb_summary':[{'herb':'合成药'}],'normalized_compound_targets':edges}),('A02',{'normalized_targets':disease,'source_summary':[]})]:
            run=w.begin(sid,module,{}, {},'合成标准化上游');w.finish(sid,run['run_id'],summary,tables)
            w.review(sid,run['run_id'],'approved','隔离测试','合成上游')
    return w,sid,draft


def body(w,sid,stage):
    value=info(w,sid)
    return {'stage':stage,**{k:value[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')},
            'operator':'隔离测试','reason':'明确执行合成阶段','confirmed':True}


def network_request(method,params,opener=None):
    """返回STRING官方字段形状，置信度过滤仍由实际科学代码执行。"""
    if method=='get_string_ids':
        rows=[{'queryIndex':i,'ncbiTaxonId':9606,'preferredName':symbol,'stringId':f'9606.{i+1}'} for i,symbol in enumerate(params['identifiers'].split('\r'))]
    else:
        rows=[{'stringId_A':f'9606.{a}','stringId_B':f'9606.{b}','score':score,'ncbiTaxonId':9606}
              for a,b,score in ((1,2,.75),(2,3,.95),(3,4,.95))]
    return {'url':network.BASE+method,'params':params,'response_text':json.dumps(rows),'method':method}


class PlanStageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_stages_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.w,self.sid,self.draft=fixture(self.root)

    def test_read_only_and_hidden_stale_request_guards(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        value=info(self.w,self.sid)
        self.assertTrue(next(r for r in value['stages'] if r['stage']=='A03')['enabled'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        request=body(self.w,self.sid,'A03')
        for change in ({'confirmed':False},{'required_score':0},{'expected_input_hash':'old'},{'stage':'A07'}):
            with self.subTest(change=change),self.assertRaises(ContractError):validate(self.w,self.sid,dict(request,**change))

    def test_a03_exact_intersection_request_and_receipt_without_approval(self):
        before=self.w.load(self.sid)
        result=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'))
        self.assertEqual(result['summary']['交集靶点数'],4)
        self.assertEqual(len(result['tables']['intersection_targets']),4)
        after=self.w.load(self.sid);self.assertEqual(after['reviews'],before['reviews'])
        self.assertEqual(len(after['analysis_plan_stage_requests']),1);self.assertEqual(len(after['analysis_plan_stage_receipts']),1)
        self.assertFalse(self.w.approved(after,result['run_id']))
        with self.assertRaises(ContractError):self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'))
        run=self.w.run(after,result['run_id']);bad=deepcopy(result['tables']);bad['intersection_targets'].pop()
        with self.assertRaises(ContractError):full_workflow(self.root).validators['A03'](run,result['summary'],bad,result['anomalies'],result['outcome'])

    def test_study_purpose_propagates_from_original_intake(self):
        w,sid,_=fixture(self.root/'purpose',purpose='formal_research')
        result=w.execute_analysis_plan_stage(sid,body(w,sid,'A03'))
        self.assertEqual(result['summary']['analysis_purpose'],'formal_research')
        self.assertEqual(w.load(sid)['kind'],'contract_test')

    def prepare_a03(self):
        result=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'))
        self.w.review(self.sid,result['run_id'],'approved','隔离测试','合成交集')
        return result

    def test_a04_actual_fetch_filter_binding_and_no_downstream(self):
        self.prepare_a03();before=self.w.load(self.sid)
        from storage import write_lock
        def verify_read_locked(workflow,sid):
            with self.assertRaises(ContractError):
                with write_lock(workflow.root):pass
            return original_context(workflow,sid)
        original_context=plan_stages.context
        with patch.object(network,'request',side_effect=network_request) as fetch,patch.object(plan_stages,'context',side_effect=verify_read_locked):
            result=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A04'))
        self.assertEqual(result['summary']['合格边数'],3)
        self.assertEqual(result['summary']['analysis_purpose'],'workflow_test')
        from modulea.presenters.network import present_a04
        self.assertIn('0.7',str(present_a04(result,{}).params))
        self.assertEqual(fetch.call_args_list[1].args[1]['required_score'],700)
        self.assertEqual(result['summary']['analysis_parameter_hash'],self.draft['plan']['parameter_hash'])
        after=self.w.load(self.sid);self.assertEqual(after['reviews'],before['reviews']);self.assertNotIn('A05',after['current'])
        self.assertEqual(len(after['analysis_plan_stage_receipts']),2)

    def test_new_intersection_cannot_fall_back_to_fixed_five_selection(self):
        self.prepare_a03()
        with self.assertRaises(ContractError):self.w.selection_binding(self.sid)
        with self.assertRaises(ContractError):self.w.begin(self.sid,'A03_SELECT',{}, {},'拒绝固定前五')
        for module in ('A03','A04','A05'):
            with self.subTest(module=module),self.assertRaises(ContractError):self.w.begin(self.sid,module,{}, {},'拒绝固定流程')

    def test_failed_network_keeps_mapping_and_diagnosis_without_receipt(self):
        self.prepare_a03()
        def fetch(method,params,opener=None):
            if method=='network':raise ValueError('合成网络中断')
            return network_request(method,params,opener)
        with patch.object(network,'request',side_effect=fetch),self.assertRaises(ValueError):
            self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A04'))
        m=self.w.load(self.sid);self.assertNotIn('A04',m['current'])
        self.assertEqual(len(m['analysis_plan_stage_receipts']),1)
        folder=next((self.w.location(self.sid)/'raw/A04_plan_acquisition').iterdir())
        self.assertTrue((folder/'mapping.json').is_file());self.assertTrue((folder/'error.json').is_file())
        self.assertFalse((folder/'source.json').exists())

    def test_a04_changed_review_during_network_blocks_publish_keeps_source(self):
        a03=self.prepare_a03();count=[]
        def fetch(method,params,opener=None):
            if not count:
                m=self.w.load(self.sid);review=self.w.latest_review(m,self.w.run(m,a03['run_id'])['artifact_id'])
                self.w.review(self.sid,a03['run_id'],'approved','隔离测试','重批合成交集',review['review_id']);count.append(True)
            return network_request(method,params,opener)
        with patch.object(network,'request',side_effect=fetch),self.assertRaises(ContractError):
            self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A04'))
        m=self.w.load(self.sid);self.assertNotIn('A04',m['current']);self.assertEqual(len(m['analysis_plan_stage_receipts']),1)
        self.assertTrue(list((self.w.location(self.sid)/'raw/A04_plan_acquisition').glob('*/source.json')))

    def test_new_draft_during_network_keeps_confirmed_parameters(self):
        self.prepare_a03();request=body(self.w,self.sid,'A04');changed=[]
        def fetch(method,params,opener=None):
            if not changed:
                changed.append(self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':request['expected_a00'],
                    'expected_draft_id':self.draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a04.required_score':.9}},
                    'author':'隔离测试','note':'运行中只追加草稿'})['draft'])
            return network_request(method,params,opener)
        with patch.object(network,'request',side_effect=fetch):result=self.w.execute_analysis_plan_stage(self.sid,request)
        self.assertEqual(result['summary']['required_score'],.7)
        self.assertEqual(result['summary']['合格边数'],3)
        self.assertNotEqual(changed[0]['plan_id'],self.draft['plan_id'])

    def test_tampered_confirmation_cannot_revalidate_a03(self):
        result=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'));m=self.w.load(self.sid)
        run=self.w.run(m,result['run_id']);path=verified_file(self.w.location(self.sid),run['inputs']['execution_request_file'])
        path.write_bytes(path.read_bytes()+b'tampered')
        with self.assertRaises(ContractError):self.w.validators['A03'](run,result['summary'],result['tables'],result['anomalies'],result['outcome'])

    def test_trace_exports_confirmations_receipts_and_checks_fingerprints(self):
        result=self.w.execute_analysis_plan_stage(self.sid,body(self.w,self.sid,'A03'))
        home=self.w.location(self.sid);before=(home/'manifest.json').read_bytes()
        trace=build_trace(self.w,self.sid,include_data=True)
        execution=trace['stage_execution']
        self.assertEqual(execution['receipts'][0]['run_id'],result['run_id'])
        self.assertEqual(execution['requests'][0]['request']['expected_plan_id'],self.draft['plan_id'])
        self.assertEqual((home/'manifest.json').read_bytes(),before)
        self.assertTrue(any(f['role']=='plan_stage_receipt' for f in trace['files']))
        path=verified_file(home,self.w.load(self.sid)['analysis_plan_stage_receipts'][0])
        path.write_bytes(path.read_bytes()+b'tampered')
        with self.assertRaises(ContractError):build_trace(self.w,self.sid)

    def test_a02_initialization_preserves_failures_and_plan_evidence(self):
        w,sid,draft=fixture(self.root/'modern',modern=True)
        # 仅替换联网采集；原五库归档、解析和候选科学校验均实际执行。
        from a02_auto_prepare import _failure
        sources=[_failure(db,ValueError('合成网络失败')) for db in ('OTP','TTD','PharmGKB')]
        w=full_workflow(w.root)
        before=w.load(sid)
        with patch('a02_auto_prepare.new_research_sources',return_value=(sources,{'synthetic_fixture':True})):
            result=w.execute_analysis_plan_stage(sid,body(w,sid,'A02'))
        after=w.load(sid)
        self.assertEqual(after['reviews'],before['reviews']);self.assertTrue(result['summary']['handoff_blocked'])
        self.assertEqual({r['database'] for r in result['tables']['source_summary']},{'GeneCards','OMIM','TTD','PharmGKB','OTP'})
        self.assertEqual(w.run(after,result['run_id'])['inputs']['plan_stage_binding']['analysis_plan_id'],draft['plan_id'])
        self.assertFalse(next(row for row in info(w,sid)['stages'] if row['stage']=='A03')['enabled'])


if __name__=='__main__':unittest.main()
