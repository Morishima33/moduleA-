"""明确身份例外的真实生产链与拒绝边界；全部原件为临时目录中的合成材料。"""
import hashlib
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError,fingerprint
from storage import verified_file,write_lock
from modulea.core import identity_exceptions as core,system_execution,system_disease_manual_sources as manual
from modulea.core import system_disease_acquisition as acquisition,historical_disease_sources as historical
from modulea.core.trace_export import build_trace
from science_modules.a01 import identity_exception as science
from science_modules.a02 import system_acquisition as disease_science
from tests.modulea import test_system_component_sources as source_fixture,plan_report_fixture as mapping_fixture
from tests.modulea.test_plan_a01_publication import source_package
from tests.modulea.test_system_disease_acquisition import synthetic_source


class IdentityExceptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='identity_exception_mapping_');cls.addClassCleanup(cls.temp.cleanup)
        cls.mapping_root=Path(cls.temp.name)/'mapping';mapping_fixture.prepare(cls.mapping_root,modern=True)

    def setUp(self):
        self.source=source_fixture.SystemComponentSourceTests();self.source.mapping_root=self.mapping_root
        # 仅原始合成ZIP含未知基因，实际采集/解包/科学发布与生产validator照常执行。
        with patch('tests.modulea.test_system_acquisition.source_package',side_effect=lambda db:source_package(db,unknown=True)):
            self.source.setUp()
        self.addCleanup(self.source.doCleanups);self.w=self.source.w;self.sid=self.source.sid
        self.home=self.w.location(self.sid);self.source.bind();batch=self.source.start()
        self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':'A01','expected_current_run_id':None})
        for db in ('GeneCards','OMIM'):
            value=manual.info(self.w,self.sid);body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
                'request_id':'manualsourceq_'+uuid4().hex,'author':'明确合成测试','note':'完整五库合成原件','confirmed':True,
                'source':{'database':db,'format':'tsv','query':'Synthetic Disease','retrieved_at':'2026-10-17','version':'未知',
                    'encoding':'utf-8-sig','name':'test.tsv','query_quoted':'unknown','export_completeness':'unknown'}}
            self.w.stage_analysis_plan_system_disease_source(self.sid,body,b'raw_symbol\tdisease_term\nB\tSynthetic Disease\nUNKNOWN\tSynthetic Disease\n')
        value=acquisition.info(self.w,self.sid);body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'diseaseacqreq_'+uuid4().hex,'author':'明确合成测试','note':'未知版本仍由原关口阻断','confirmed':True}
        def public(db,summary):
            item,extra=synthetic_source(db,summary);item['data']=item['data'].replace(b'A\t',b'B\t');return item,extra
        with patch.object(disease_science,'fetch_source',side_effect=public):self.w.acquire_analysis_plan_system_disease_sources(self.sid,body)
        value=historical.info(self.w,self.sid);body={key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash','expected_source_hashes')}|{
            'request_id':'historicaldiseaseq_'+uuid4().hex,'author':'明确合成测试','note':'同一两份历史原件','user_decision':'明确合成测试批准版本例外','confirmed':True}
        self.w.publish_analysis_plan_historical_disease_candidates(self.sid,body)
        m=self.w.load(self.sid);binding=core.context(self.w,m);mapping=binding['mapping']
        original=json.loads(verified_file(self.home,mapping['identity_evidence_files'][2]).read_bytes())
        def query(url,payload,data):
            text=json.dumps(data);return {'url':url,'payload':payload,'retrieved_at':'2026-11-01T00:00:00+00:00',
                'status':'ok','http_status':200,'response_text':text,'response_sha256':hashlib.sha256(text.encode()).hexdigest()}
        package=dict(original,queries=original.get('queries',[])+[
            query('https://rest.ensembl.org/info/data',None,{'releases':[116]}),
            query('https://rest.ensembl.org/lookup/id',{'ids':[]},{}),
            query('https://rest.ensembl.org/archive/id',{'id':[]},[])])
        self.raw=json.dumps(package).encode();issues=self.w.result(m,m['current']['A01'])['tables']['identity_decisions']
        self.assertEqual(len(issues),1);self.assertTrue(self.w.result(m,m['current']['A01'])['summary']['handoff_blocked'])
        # UNKNOWN及空稳定编号的分组值按公开指纹契约固定，非取待测结果拼成期望。
        group=fingerprint(['UNKNOWN','',''])[:24]
        self.body={'request_id':'identityexceptreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_a01':m['current']['A01'],'expected_a02':m['current']['A02'],'expected_plan_id':binding['plan_id'],
            'expected_input_hash':fingerprint(binding),'expected_evidence_sha256':hashlib.sha256(self.raw).hexdigest(),
            'expected_a01_issue_hash':fingerprint(issues),'a02_omit_ids':[group],'author':'明确合成登记',
            'note':'只限本次合成流程测试精确问题清单','user_decision':'明确合成测试同意，非实际用户科学批准','confirmed':True}

    def register(self,body=None,raw=None):
        return self.w.register_analysis_plan_identity_exception(self.sid,body or self.body,self.raw if raw is None else raw)

    def test_real_pipeline_preserves_unresolved_states_and_report_notice(self):
        before=self.w.load(self.sid);originals={rid:deepcopy(files) for rid,files in before['runs'].items()}
        value=self.register();m=self.w.load(self.sid)
        self.assertEqual(m['current'],before['current']);self.assertEqual(m['reviews'],[])
        self.assertFalse(self.register()['created']);batch=self.source.start()
        self.assertEqual(batch['identity_exception_file'],value['file']);self.assertEqual(batch['mapping'],value['mapping'])
        result=self.w.execute_analysis_plan_system_pipeline(self.sid,{'batch_id':batch['batch_id']})
        m=self.w.load(self.sid);a01=self.w.result(m,m['current']['A01']);a02=self.w.result(m,m['current']['A02'])
        self.assertEqual(self.w.run(m,m['current']['A01'])['config']['version'],science.VERSION)
        self.assertEqual(self.w.run(m,m['current']['A02'])['config']['version'],'A02.system_normalization.5')
        self.assertEqual(a01['summary']['未决身份组数'],1);self.assertFalse(a01['summary']['handoff_blocked'])
        self.assertEqual(a01['summary']['标准化基因数'],1);self.assertEqual(a02['summary']['标准化基因数'],1)
        self.assertEqual(len(a02['tables']['identity_issues']),1);self.assertEqual(a02['tables']['identity_issues'][0]['status'],'unmapped')
        self.assertEqual(a01['summary']['identity_evidence_snapshot'],a02['summary']['identity_evidence_snapshot'])
        self.assertEqual(self.w.result(m,m['current']['A03'])['summary']['交集靶点数'],0)
        self.assertEqual(m['reviews'],[])
        for rid,files in originals.items():
            self.assertEqual(m['runs'][rid],files)
            for ref in files.values():verified_file(self.home,ref)
        trace=build_trace(self.w,self.sid,include_data=True);self.assertEqual(len(trace['plan_decisions']['identity_exceptions']),1)
        import docx
        report=self.w.result(m,m['current']['A07'])
        for ref in report['tables']['report_files']:
            text='\n'.join(p.text for p in docx.Document(verified_file(self.home,ref)).paragraphs)
            self.assertIn(core.NOTICE,text);self.assertIn(historical.NOTICE,text)
        self.assertEqual(result['state'],'awaiting_report_review')

    def test_confirmation_paths_extra_fields_stale_and_scope_changes_denied(self):
        before=self.w.load(self.sid)
        for changes in ({'confirmed':False},{'passed':True},{'path':'other'},{'user_decision':''},
            {'expected_input_hash':'stale'},{'expected_a01_issue_hash':'old'},{'a02_omit_ids':[]},
            {'a02_omit_ids':['0'*24]},{'a02_omit_ids':self.body['a02_omit_ids']*2}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.register(self.body|changes)
        self.assertEqual(self.w.load(self.sid),before)

    def test_failed_query_tampered_old_prefix_and_extra_url_deny(self):
        for mutate in ('failed','foreign','missing'):
            package=json.loads(self.raw)
            if mutate=='failed':package['queries'][0]['status']='query_failed'
            elif mutate=='foreign':package['queries'][0]['url']='https://example.com/identity'
            else:package['queries'].pop()
            raw=json.dumps(package).encode();body=self.body|{'request_id':'identityexceptreq_'+uuid4().hex,
                'expected_evidence_sha256':hashlib.sha256(raw).hexdigest()}
            with self.subTest(mutate=mutate),self.assertRaises(ContractError):self.register(body,raw)
        self.assertNotIn(core.INDEX,self.w.load(self.sid))

    def test_pause_trash_changed_plan_and_cross_study_refused(self):
        rid=self.body['expected_a01'];self.w.review(self.sid,rid,'pending','明确合成暂停','身份例外不覆盖暂停')
        with self.assertRaises(ContractError):self.register()
        with write_lock(self.w.root):
            m=self.w.load(self.sid);m['trashed']=True;self.w.save(m)
        self.assertFalse(core.info(self.w,self.sid)['enabled'])
        with self.assertRaises(ContractError):self.register()
        other=source_fixture.SystemComponentSourceTests();other.mapping_root=self.mapping_root;other.setUp();self.addCleanup(other.doCleanups)
        with self.assertRaises(ContractError):other.w.register_analysis_plan_identity_exception(other.sid,self.body,self.raw)

    def test_original_policy_remains_blocking_and_forged_result_rejected(self):
        value=self.register();batch=self.source.start()
        old=self.w.result(self.w.load(self.sid),self.body['expected_a01'])
        self.assertTrue(old['summary']['handoff_blocked'])
        from modulea.core import system_execution_science
        original=system_execution_science.a01
        def forged(*args):
            result=list(original(*args));result[2]=dict(result[2],标准化基因数=999);return tuple(result)
        with patch.object(system_execution_science,'a01',side_effect=forged),self.assertRaises(ContractError):
            self.w.execute_analysis_plan_system_stage(self.sid,{'batch_id':batch['batch_id'],'stage':'A01','expected_current_run_id':self.body['expected_a01']})
        self.assertEqual(self.w.load(self.sid)['current']['A01'],self.body['expected_a01'])
        self.assertEqual(self.w.load(self.sid)['reviews'],[])

    def test_new_plan_cannot_inherit_and_original_source_corruption_deny(self):
        self.register();draft=self.w.analysis_plan_info(self.sid)['draft'];m=self.w.load(self.sid)
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},
            'author':'明确合成测试','note':'新方案不得继承旧例外'})
        with self.assertRaises(ContractError):self.source.start()
        value=core.read_record(self.w,self.w.load(self.sid),self.w.load(self.sid)[core.CURRENT])
        target=self.home/value['evidence_file']['path'];target.write_bytes(b'changed')
        with self.assertRaises(ContractError):core.read_record(self.w,self.w.load(self.sid),self.w.load(self.sid)[core.CURRENT])

    def test_formal_purpose_bad_bytes_and_post_registration_pause_deny(self):
        original=self.w.result
        def formal(m,rid):
            value=deepcopy(original(m,rid))
            if rid==self.body['expected_a00']:value['summary']['analysis_purpose']='formal_research'
            return value
        with patch.object(self.w,'result',side_effect=formal),self.assertRaises(ContractError):self.register()
        with self.assertRaises(ContractError):self.register(raw=self.raw+b' ')
        self.register();self.w.review(self.sid,self.body['expected_a02'],'pending','明确合成暂停','新批也必须拒绝')
        with self.assertRaises(ContractError):self.source.start()


class IdentityPresentationTests(unittest.TestCase):
    def test_only_completed_system_scope_is_deferred_without_false_downstream_block(self):
        from modulea.presenters.sources import present_a02
        for version in ('A02.system_normalization.4','A02.system_normalization.5'):
            summary={'protocol_version':version,'scope_authority':'system_validation','handoff_blocked':False,'待定范围组数':380}
            parts=present_a02({'summary':summary,'tables':{}},{})
            deferred=[row for row in parts.focus if row['title_zh']=='本批暂缓的疾病范围']
            self.assertEqual(len(deferred),1);self.assertEqual(deferred[0]['blocks'],[])
            self.assertIn('380',deferred[0]['body_zh']);self.assertEqual(deferred[0]['tier'],'should_know')
        for changes in ({'handoff_blocked':True},{'scope_authority':'manual'},{'protocol_version':'A02.old'}):
            parts=present_a02({'summary':summary|changes,'tables':{}},{})
            self.assertTrue(any(row['title_zh']=='疾病范围尚待复核' and 'A03' in row['blocks'] for row in parts.focus))


class IdentityQueryPrefixTests(unittest.TestCase):
    def test_original_query_prefix_cannot_be_rewritten_or_removed(self):
        old={'queries':[{'url':'https://example.invalid/frozen','status':'query_failed'}],'schema_version':'synthetic'}
        package={'queries':[{'url':'https://example.invalid/replaced','status':'query_failed'}],'schema_version':'synthetic'}
        with self.assertRaisesRegex(ContractError,'原查询证据'):science.validate_queries(old,package,[])


if __name__=='__main__':unittest.main()
