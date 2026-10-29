"""原始现代五库至无人工批准的A01/A02/A03；只使用明确合成原件。"""
from copy import deepcopy
from pathlib import Path
import json,shutil,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError
from storage import read_json,verified_file
from disease import run_disease
from modulea.core.kernel import full_workflow
from modulea.core import system_execution as system
from modulea.core.trace_export import build_trace
from tests.modulea import plan_report_fixture as fixture


class SystemNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempbase=tempfile.TemporaryDirectory(prefix='system_normalization_base_');cls.addClassCleanup(cls.tempbase.cleanup)
        cls.base=Path(cls.tempbase.name)/'data';_,cls.sid,_,_=fixture.prepare(cls.base,modern=True,multiple_targets=True,stop_before_normalization=True)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_normalization_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root)

    def replace(self,database,content=None,**changes):
        m=self.w.load(self.sid);old=self.w.result(m,m['current']['A02']);home=self.w.location(self.sid)
        manifest=read_json(verified_file(home,next(r for r in old['sources'] if r['role']=='source_manifest')))
        item=deepcopy(next(x for x in manifest['datasets'] if x['database']==database))
        item['data']=content if content is not None else verified_file(home,item['source_record']).read_bytes()
        item.pop('source_record',None);item.update(changes)
        return run_disease(self.w,self.sid,m['current']['A00'],m['current']['A02'],[item],'明确合成来源修订')

    def start(self):
        m=self.w.load(self.sid);self.before=deepcopy(m);info=system.info(self.w,self.sid)
        body={k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systembatchreq_'+uuid4().hex,'author':'明确合成测试','note':'同批系统标准化，不是人工复核','confirmed':True}
        self.batch=self.w.start_analysis_plan_system_batch(self.sid,body);self.execute('A01')

    def execute(self,module):
        return self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':self.batch['batch_id'],'stage':module,
            'expected_current_run_id':self.w.load(self.sid)['current'].get(module)})

    def test_raw_five_sources_become_unapproved_system_a02_and_real_intersection(self):
        self.start();a02=self.execute('A02');a03=self.execute('A03');m=self.w.load(self.sid)
        self.assertEqual(a02['summary']['标准化基因数'],5);self.assertEqual(a03['summary']['交集靶点数'],5)
        self.assertEqual(m['reviews'],self.before['reviews'])
        for module in ('A01','A02','A03'):
            run=self.w.run(m,m['current'][module]);self.assertTrue(self.w.active(m,run['run_id']))
            self.assertFalse(self.w.approved(m,run['run_id']));self.assertEqual(run['parent_review_ids'],{})
        self.assertTrue(all(row['authority_kind']=='system_validation' for row in a02['tables']['scope_system_decisions']))
        self.assertEqual(a02['tables']['scope_history'],[])
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['system_batch_events']),3)

    def test_uncertain_range_is_deferred_with_evidence_and_not_called_outside(self):
        self.replace('OMIM',b'raw_symbol\tdisease_term\nA\tSynthetic Disease\nB\tUnresolved subtype\n')
        self.start();a02=self.execute('A02');self.execute('A03')
        self.assertEqual(a02['summary']['暂缓范围组数'],1)
        deferred=[r for r in a02['tables']['scope_system_decisions'] if r['action']=='deferred'];self.assertEqual(len(deferred),1)
        self.assertEqual(deferred[0]['effective_scope'],'pending');self.assertTrue(deferred[0]['reason_zh'])
        self.assertFalse(any(r['symbol']=='B' and r['database']=='OMIM' for r in a02['tables']['normalized_targets']))
        self.assertTrue(any(r['raw_symbol']=='B' for r in a02['tables']['candidate_records']))
        self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])
        from science_modules.a07.plan_payload import build
        payload=build(self.w,self.sid)
        self.assertIn('暂缓1组',payload['sources'][1]['description'])
        self.assertIn('未产生人工范围审核',payload['sources'][1]['description'])

    def test_key_identity_unknown_blocks_without_omitting_or_publishing(self):
        self.replace('GeneCards',b'raw_symbol\tdisease_term\nNOT_A_VERIFIED_GENE\tSynthetic Disease\n')
        self.start();old=self.w.load(self.sid)['current']['A02']
        with self.assertRaisesRegex(ContractError,'关键身份'):self.execute('A02')
        self.assertEqual(self.w.load(self.sid)['current']['A02'],old)
        self.assertEqual(self.w.load(self.sid)['reviews'],self.before['reviews'])

    def test_failed_source_and_unknown_version_do_not_become_empty_success(self):
        self.replace('GeneCards',json.dumps({'database':'GeneCards','status':'query_failed','error':'explicit synthetic outage'}).encode(),
            format='source_failure',source_status='query_failed')
        self.start()
        with self.assertRaisesRegex(ContractError,'缺失或查询失败'):self.execute('A02')
        self.assertEqual(self.w.load(self.sid)['current']['A02'],self.before['current']['A02'])

    def test_source_version_unknown_blocks(self):
        self.replace('GeneCards',version='unknown');self.start()
        with self.assertRaisesRegex(ContractError,'版本待核'):self.execute('A02')

    def test_explicit_hold_during_computation_blocks_publish_and_keeps_failure(self):
        self.start();base=self.before['current']['A02']
        from science_modules.a02 import system_normalization as science
        original=science.facts;called=[]
        def calculate(*args):
            if not called:
                called.append(True);self.w.review(self.sid,base,'pending','明确合成测试','标准化期间暂存')
            return original(*args)
        with patch.object(science,'facts',side_effect=calculate),self.assertRaisesRegex(ContractError,'人工决定已改变'):self.execute('A02')
        m=self.w.load(self.sid);self.assertEqual(m['current']['A02'],base)
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(trace['plan_decisions']['system_batch_events'][-1]['state'],'failed')

    def test_explicit_hold_of_system_result_invalidates_published_system_chain(self):
        self.start();a02=self.execute('A02');a03=self.execute('A03')
        self.w.review(self.sid,a02['run_id'],'rejected','明确合成测试','否决当前疾病结果')
        self.assertFalse(self.w.active(self.w.load(self.sid),a03['run_id']))

    def test_source_replacement_requires_new_explicit_batch(self):
        self.start();self.replace('GeneCards',version='explicit_synthetic_revision')
        with self.assertRaisesRegex(ContractError,'原始五库候选'):self.execute('A02')

    def test_actual_empty_queries_remain_empty_and_do_not_start_downstream_network(self):
        for db in ('GeneCards','OMIM','TTD','PharmGKB','OTP'):
            self.replace(db,b'raw_symbol\tdisease_term\n')
        self.start();a02=self.execute('A02');a03=self.execute('A03')
        self.assertEqual(a02['outcome'],'empty');self.assertEqual(a02['summary']['标准化基因数'],0)
        self.assertEqual(a03['outcome'],'empty');self.assertEqual(a03['summary']['交集靶点数'],0)
        with patch('modulea.core.system_execution_science.a04',side_effect=AssertionError('空交集不能取网络')):
            with self.assertRaisesRegex(ContractError,'交集为空'):self.execute('A04')

    def test_missing_source_blocks_even_workflow_test_without_legacy_exception(self):
        real=fixture.run_disease
        def partial(w,sid,a00,a02,updates,reason,**kwargs):
            return real(w,sid,a00,a02,[row for row in updates if row['database']!='GeneCards'],reason,**kwargs)
        self.root=Path(self.temp.name)/'partial'
        with patch.object(fixture,'run_disease',side_effect=partial):
            self.w,self.sid,_,_=fixture.prepare(self.root,modern=True,multiple_targets=True,stop_before_normalization=True)
        self.start()
        with self.assertRaisesRegex(ContractError,'五库原件不齐'):self.execute('A02')

    def test_caller_validator_cannot_publish_forged_disease_count(self):
        self.start();from modulea.core import system_execution_science as science
        original=science.a02
        def forged(*args):
            value=list(original(*args));value[2]=dict(value[2],标准化基因数=999);return tuple(value)
        self.w.validators['A02']=lambda *args:None
        with patch.object(science,'a02',side_effect=forged),self.assertRaisesRegex(ContractError,'独立复算'):self.execute('A02')
        m=self.w.load(self.sid);self.assertEqual(m['current']['A02'],self.before['current']['A02'])
        self.assertEqual(m['reviews'],self.before['reviews'])
