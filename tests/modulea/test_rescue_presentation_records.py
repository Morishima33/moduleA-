"""独立名称许可与修订账本：真实Workflow存储/状态和合成评分，不运行对接、不生成Word。"""
from copy import deepcopy
from hashlib import sha256
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

from contracts import ContractError, fingerprint
from storage import new_id, read_json, write_json
from workflow import Workflow
from tests.modulea.test_rescue_name_basis import RescueNameBasisTests
from tests.modulea.test_rescue_presentation_names import RescuePresentationNamesTests


class RescuePresentationRecordTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[2]/'src/modulea/core/rescue_presentations.py'
        self.assertTrue(path.is_file(),'缺少公开名称许可和独立展示账本')
        self.model=importlib.import_module('modulea.core.rescue_presentations')
        self.seed=RescueNameBasisTests('test_pending_score_can_read_only_original_prep_and_herb_names')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        s=self.seed;self.root,self.home,self.sid=s.root,s.home,s.sid
        self.rid=s.ids['A06']
        # 测试复用原Workflow.active/approved规则，不伪造active函数；不声称覆盖科学validator。
        class LedgerWorkflow(self.model.RescuePresentationMixin,Workflow):pass
        self.w=LedgerWorkflow(self.root)
        for module,run in s.runs.items():
            run['config_hash']=fingerprint(run['config'])
            run['parent_review_ids']={parent:'review_'+s.ids[parent][4:] for parent in run['parent_runs']}
            s.results[module].update(outcome='success',summary={},config_hash=run['config_hash'])
        s.refresh();s.m['schema_version']='1.0'
        s.m['reviews']=[]
        for module in ('A01','A03','A06_PREP'):
            s.m['reviews'].append(s.save('reviews/'+module+'.json',{'study_id':self.sid,'run_id':s.ids[module],
               'artifact_id':s.runs[module]['artifact_id'],'review_id':'review_'+s.ids[module][4:],'decision':'approved'}))
        self.packet={'schema_version':'A06.system_rescue.2','study_id':self.sid,'run_id':self.rid,
            'inputs':deepcopy(s.runs['A06']['inputs']),'source_fixed':deepcopy(s.fixed['payload']),
            'compounds':deepcopy(s.prepared['compounds']),'receptors':deepcopy(s.fixed['payload']['receptors']),
            'summary':{'input_key':'original'},'reused_pair_keys':[['C1','HGNC:1']],'new_pair_keys':[],
            'pairs':[{'compound_id':cid,'target_id':'HGNC:1','state':'completed' if cid=='C1' else 'NA',
                'score':-7.125 if cid=='C1' else None,'quality':'探索','reason_zh':'' if cid=='C1' else '原服务404；未评分'}
                for cid in ('C1','C2')]}
        ref=s.save('runs/A06/'+self.rid+'/packet.json',self.packet)
        result=s.results['A06'];result.update(summary=self.packet['summary'],files=[ref],
            tables={'scoring_packet':[ref],'plan_scoring_pairs':deepcopy(self.packet['pairs'])})
        s.m['runs'][self.rid]['result_file']=s.save('runs/'+self.rid+'/result.json',result)
        self.w.save(s.m)
        self.font=Path('C:/Windows/Fonts/msyh.ttc')
        if not self.font.is_file():
            self.font=Path('/System/Library/Fonts/Supplemental/Songti.ttc')
        if not self.font.is_file():self.skipTest('实际PNG验证需要已配置中文字体')
        entry=RescuePresentationNamesTests.entry
        self.catalog={'schema_version':'ModuleA.rescue_display_name_catalog.1','entries':[
            entry('PubChem','1',['Alpha'],'甲成分','prepared_identity_translation'),
            entry('HERB','HBIN000001',['Source beta'],'','original_name_requires_user_decision')]}
        self.catalog_path=self.root/'catalog.json';write_json(self.catalog_path,self.catalog)
        p=patch.object(self.model,'CATALOG',self.catalog_path);p.start();self.addCleanup(p.stop)

    def info(self):
        return self.w.rescue_presentation_info(self.sid,self.rid,font_path=self.font)

    def approve_name(self):
        value=self.info()
        body={'decision_id':new_id('rescuename'),'expected_run_id':self.rid,
            'expected_source_hash':value['expected_source_hash'],'author':'合成用户明确决定',
            'note':'仅本测试一条原专名，保留身份未核且不评分','confirmed':True,
            'entries':[{'compound_id':'C2','source_identifier':{'scheme':'HERB','id':'HBIN000001'},
                        'source_name':'Source beta','name_scope':'original_proper_name'}],
            'user_evidence':{'source_id':'synthetic_question_1','question':'仅这条保留原专名？','answer':'明确同意仅此条'}}
        return self.w.register_rescue_original_name_decision(self.sid,body)

    def body(self):
        value=self.info()
        return {'request_id':new_id('rescuereq'),'expected_run_id':self.rid,
                'expected_input_hash':value['expected_input_hash'],'author':'合成技术修订',
                'note':'名称和附件独立归档，原评分保持','confirmed':True}

    def publish(self,body=None):
        return self.w.publish_rescue_presentation(self.sid,body or self.body(),font_path=self.font)

    def original_files(self):
        return {path.relative_to(self.home).as_posix():sha256(path.read_bytes()).hexdigest()
                for path in self.home.rglob('*') if path.is_file() and path.name!='manifest.json'}

    def test_missing_consent_blocks_without_registering_or_mutating_science(self):
        before=self.w.load(self.sid);files=self.original_files();info=self.info()
        self.assertFalse(info['enabled']);self.assertEqual(info['translation_missing_ids'],['C2'])
        with self.assertRaises(ContractError):self.publish()
        self.assertEqual(before,self.w.load(self.sid));self.assertEqual(files,self.original_files())

    def test_explicit_one_name_consent_and_public_publish_preserve_all_science(self):
        before=self.w.load(self.sid);old=self.original_files()
        consent=self.approve_name();self.assertEqual(consent['allowed_original_name_ids'],['C2'])
        self.assertTrue(self.info()['enabled'])
        record=self.publish();after=self.w.load(self.sid)
        for key in ('current','runs','reviews'):self.assertEqual(before[key],after[key])
        for name,digest in old.items():self.assertEqual(sha256((self.home/name).read_bytes()).hexdigest(),digest)
        self.assertFalse(list(self.home.rglob('*.docx')))
        self.assertFalse(record['human_review_written']);self.assertFalse(record['scientific_results_changed'])
        self.assertEqual(len(record['files']),7)
        view=read_json(self.home/next(ref['path'] for ref in record['files'] if ref['role']=='a06_rescue_display_view'))
        self.assertEqual(view['table']['cells'][0][0]['score'],-7.125)
        self.assertEqual(view['table']['cells'][1][0]['state'],'NA')
        self.assertEqual(view['allowed_original_name_ids'],['C2'])

    def test_completed_request_reuses_same_revision_without_rendering_again(self):
        self.approve_name();body=self.body();first=self.publish(body);files=self.original_files()
        with patch('science_modules.a06.system_rescue_presentation.export',side_effect=AssertionError('不应重画')):
            again=self.publish(body)
        self.assertEqual(first['revision_id'],again['revision_id']);self.assertFalse(again['created'])
        self.assertEqual(files,self.original_files())

    def test_same_request_changed_fields_and_foreign_allowlist_are_rejected(self):
        self.approve_name();body=self.body();self.publish(body)
        with self.assertRaises(ContractError):self.publish(dict(body,note='篡改同请求'))
        value=self.info()
        body={'decision_id':new_id('rescuename'),'expected_run_id':self.rid,
            'expected_source_hash':value['expected_source_hash'],'author':'测试','note':'不合法范围','confirmed':True,
            'entries':[{'compound_id':'C1','source_identifier':{'scheme':'HERB','id':'HBIN000001'},
                        'source_name':'Alpha','name_scope':'original_proper_name'}],
            'user_evidence':{'source_id':'test','question':'test','answer':'test'}}
        with self.assertRaises(ContractError):self.w.register_rescue_original_name_decision(self.sid,body)

    def test_source_change_during_render_blocks_publication(self):
        self.approve_name();body=self.body()
        from science_modules.a06 import system_rescue_presentation as render
        original=render.export
        def mutate(*args,**kwargs):
            output=original(*args,**kwargs)
            m=self.w.load(self.sid);m['current']['A06']='run_'+'f'*32;self.w.save(m)
            return output
        with patch.object(render,'export',mutate),self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(self.model.INDEX))

    def test_candidate_recovery_does_not_regenerate_successful_files(self):
        self.approve_name();body=self.body();write=self.model.write_json
        def fail_receipt(path,value,*args,**kwargs):
            if Path(path).name=='receipt.json':raise OSError('合成发表中断')
            return write(path,value,*args,**kwargs)
        with patch.object(self.model,'write_json',fail_receipt),self.assertRaises(OSError):self.publish(body)
        self.assertEqual(len(self.w.load(self.sid).get(self.model.CANDIDATES,[])),1)
        with patch('science_modules.a06.system_rescue_presentation.export',side_effect=AssertionError('不重画完整候选')):
            value=self.publish(body)
        self.assertTrue(value['created']);self.assertEqual(len(self.w.load(self.sid)[self.model.INDEX]),1)

    def test_changed_font_or_implementation_blocks_resume(self):
        self.approve_name();body=self.body()
        with patch.object(self.model,'implementation',return_value={'changed.py':'f'*64}),self.assertRaises(ContractError):
            self.publish(body)
        alternate=self.root/'font.ttc';alternate.write_bytes(self.font.read_bytes()+b'changed')
        with self.assertRaises(ContractError):self.w.publish_rescue_presentation(self.sid,body,font_path=alternate)

    def test_damaged_published_file_blocks_replay_instead_of_regeneration(self):
        self.approve_name();body=self.body();record=self.publish(body)
        (self.home/record['files'][0]['path']).write_bytes(b'broken')
        with self.assertRaises(ContractError):self.publish(body)

    def test_pending_science_blocks_name_registration(self):
        m=self.w.load(self.sid);m['runs'][self.rid]['result_file']=None;self.w.save(m)
        before=self.original_files()
        with self.assertRaises(ContractError):self.approve_name()
        self.assertEqual(before,self.original_files())

    def test_retired_source_keeps_history_but_disables_new_publication(self):
        self.approve_name();record=self.publish();m=self.w.load(self.sid)
        m['current']['A06']='run_'+'f'*32;self.w.save(m)
        historical=self.w.read_rescue_presentation(self.sid,record['file'])
        self.assertEqual(historical['revision_id'],record['revision_id'])
        self.assertFalse(self.info()['enabled'])

    def test_scientific_rejection_after_request_blocks_publication(self):
        self.approve_name();body=self.body();m=self.w.load(self.sid)
        prep=self.seed.runs['A06_PREP']
        ref=self.seed.save('reviews/retirement.json',{'study_id':self.sid,'run_id':prep['run_id'],
            'artifact_id':prep['artifact_id'],'review_id':new_id('review'),'decision':'rejected'})
        m['reviews'].append(ref);self.w.save(m)
        with self.assertRaises(ContractError):self.publish(body)

    def test_kernel_exposes_same_public_workflow_methods_without_state_replacement(self):
        from modulea.core.kernel import Kernel
        from modulea.config import Settings
        w=Kernel(Settings(data_root=self.root,runtime_dir=self.root/'runtime')).workflow()
        for name in ('rescue_presentation_info','register_rescue_original_name_decision',
                     'publish_rescue_presentation','read_rescue_presentation'):
            self.assertTrue(callable(getattr(w,name,None)),name)
        self.assertIs(w.save.__func__,Workflow.save)

    def test_incomplete_export_cannot_publish_success_receipt(self):
        self.approve_name();body=self.body()
        from science_modules.a06 import system_rescue_presentation as render
        original=render.export
        def omit(*args,**kwargs):
            figures,tables=original(*args,**kwargs)
            return figures[1:],tables
        with patch.object(render,'export',omit),self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(self.model.INDEX))

    def test_exported_csv_wrong_score_with_new_fingerprint_is_rejected(self):
        self.approve_name();body=self.body()
        from science_modules.a06 import system_rescue_presentation as render
        from storage import file_record
        original=render.export
        def change(*args,**kwargs):
            figures,tables=original(*args,**kwargs)
            for i,ref in enumerate(tables):
                if ref['role']=='a06_rescue_matrix_csv':
                    path=self.home/ref['path'];raw=path.read_bytes();changed=raw.replace(b'-7.125',b'-9.000')
                    self.assertNotEqual(raw,changed);path.write_bytes(changed)
                    tables[i]=file_record(self.home,path,ref['role'])
            return figures,tables
        with patch.object(render,'export',change),self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(self.model.INDEX))

    def test_cancellation_after_render_prevents_candidate_and_receipt(self):
        self.approve_name();body=self.body();calls=[]
        def check():
            calls.append(1)
            if len(calls)>1:raise ContractError('任务已取消')
        with self.assertRaisesRegex(ContractError,'任务已取消'):
            self.w.publish_rescue_presentation(self.sid,body,font_path=self.font,check_task=check)
        m=self.w.load(self.sid)
        self.assertFalse(m.get(self.model.INDEX));self.assertFalse(m.get(self.model.CANDIDATES))

    def test_first_real_approval_keeps_original_name_consent_and_same_revision(self):
        self.approve_name();body=self.body();record=self.publish(body)
        m=self.w.load(self.sid);original=m[self.model.NAMES]
        self.w.review(self.sid,self.rid,'approved','合成独立科研复核人','首次明确通过，仅测试')
        self.assertTrue(self.info()['enabled'],self.info()['blockers_zh'])
        self.assertEqual(self.w.load(self.sid)[self.model.NAMES],original)
        with patch('science_modules.a06.system_rescue_presentation.export',side_effect=AssertionError('首次通过不重画')):
            again=self.publish(body)
        self.assertEqual(again['revision_id'],record['revision_id']);self.assertFalse(again['created'])

    def test_pause_does_not_consume_name_consent_but_old_display_does_not_auto_revive(self):
        self.approve_name();body=self.body();self.publish(body)
        old=self.w.load(self.sid)[self.model.NAMES]
        review=self.w.review(self.sid,self.rid,'pending','合成科研复核人','明确暂停，仅测试')
        self.assertFalse(self.info()['enabled'])
        with self.assertRaises(ContractError):self.publish(body)
        self.w.review(self.sid,self.rid,'approved','合成科研复核人','新明确通过，仅测试',expected_review=review['review_id'])
        self.assertTrue(self.info()['enabled'])
        self.assertEqual(self.w.load(self.sid)[self.model.NAMES],old)
        with self.assertRaises(ContractError):self.publish(body)

    def test_public_http_read_collects_archived_font_code_and_original_files(self):
        from modulea.api.server import App
        from modulea.core.read_evidence import current_evidence
        from types import SimpleNamespace
        self.approve_name();record=self.publish()
        request=read_json(self.home/record['request_file']['path'])
        expected={ref['path'] for ref in request['implementation_files']}
        expected.update(ref['path'] for ref in (request['font_file'],request['catalog_file']))
        expected.update(ref['path'] for ref in request['binding']['source']['scoring_files'])
        def read():
            value=self.w.read_rescue_presentation(self.sid,record['file'])
            seen={ref['path'] for _,ref,_ in current_evidence(self.root).proofs.values()}
            self.assertTrue(expected<=seen,sorted(expected-seen))
            return value
        App._json_read(SimpleNamespace(settings=SimpleNamespace(data_root=self.root)),self.sid,read)

    def test_public_http_response_rejects_archived_font_changed_at_finish(self):
        from modulea.api.server import App
        from modulea.core.http_read_evidence import HttpReadEvidence
        from types import SimpleNamespace
        import os
        self.approve_name();record=self.publish()
        request=read_json(self.home/record['request_file']['path']);target=self.home/request['font_file']['path']
        raw=target.read_bytes();stamp=target.stat();finish=HttpReadEvidence.finish
        def mutate(reader):
            target.write_bytes(bytes([raw[0]^1])+raw[1:])
            os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return finish(reader)
        try:
            with patch.object(HttpReadEvidence,'finish',mutate),self.assertRaises(ContractError):
                App._json_read(SimpleNamespace(settings=SimpleNamespace(data_root=self.root)),self.sid,
                    self.w.read_rescue_presentation,self.sid,record['file'])
        finally:target.write_bytes(raw)

    def test_unknown_optional_quality_stays_empty_in_csv_without_invented_classification(self):
        self.packet['pairs'][1]['quality']=None
        ref=self.seed.save('runs/A06/'+self.rid+'/packet.json',self.packet)
        m=self.w.load(self.sid);result=self.seed.results['A06']
        result.update(files=[ref],tables={'scoring_packet':[ref],'plan_scoring_pairs':deepcopy(self.packet['pairs'])})
        m['runs'][self.rid]['result_file']=self.seed.save('runs/'+self.rid+'/result.json',result);self.w.save(m)
        self.approve_name();record=self.publish()
        import csv,io
        data=next(ref for ref in record['files'] if ref['role']=='a06_rescue_matrix_csv')
        rows=list(csv.DictReader(io.StringIO((self.home/data['path']).read_text('utf-8-sig'))))
        self.assertEqual(rows[1]['quality'],'');self.assertEqual(rows[1]['score'],'NA')

    def test_interrupted_unregistered_request_preserves_partial_archive_and_retries(self):
        self.approve_name();body=self.body();original=self.model.write_json
        def fail(path,value,*args,**kwargs):
            if Path(path).name=='request.json':raise OSError('合成请求归档中断')
            return original(path,value,*args,**kwargs)
        with patch.object(self.model,'write_json',fail),self.assertRaises(OSError):self.publish(body)
        partial=self.original_files()
        self.assertFalse(self.w.load(self.sid).get(self.model.REQUESTS))
        record=self.publish(body)
        self.assertTrue(record['created'])
        for path,digest in partial.items():self.assertEqual(sha256((self.home/path).read_bytes()).hexdigest(),digest)

    def test_archived_font_filename_cannot_overwrite_catalog_or_request(self):
        self.approve_name()
        font=self.root/'fonts/catalog.json';font.parent.mkdir();font.write_bytes(self.font.read_bytes())
        info=self.w.rescue_presentation_info(self.sid,self.rid,font_path=font)
        body=self.body();body['expected_input_hash']=info['expected_input_hash']
        record=self.w.publish_rescue_presentation(self.sid,body,font_path=font)
        request=read_json(self.home/record['request_file']['path'])
        self.assertNotEqual(request['font_file']['path'],request['catalog_file']['path'])
        self.assertEqual(read_json(self.home/request['catalog_file']['path']),self.catalog)

    def test_name_decision_manifest_save_failure_retries_same_body_and_preserves_orphan(self):
        captured=[]
        def fail(manifest):
            ref=manifest[self.model.NAMES][-1]
            captured.append(read_json(self.home/ref['path'])['decision'])
            raise OSError('合成名称许可索引保存中断')
        with patch.object(self.w,'save',fail),self.assertRaises(OSError):self.approve_name()
        self.assertFalse(self.w.load(self.sid).get(self.model.NAMES))
        partial=self.original_files()
        value=self.w.register_rescue_original_name_decision(self.sid,captured[0])
        self.assertTrue(value['created']);self.assertTrue(self.info()['enabled'])
        self.assertEqual(len(self.w.load(self.sid)[self.model.NAMES]),1)
        for name,digest in partial.items():self.assertEqual(sha256((self.home/name).read_bytes()).hexdigest(),digest)
