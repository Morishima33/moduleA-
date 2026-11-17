"""完整包公开账本：同修订、恢复、取消和旧原件保护；合成存储，不执行科学计算。"""
import importlib
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError, fingerprint
from storage import new_id
from tests.modulea.test_rescue_presentation_api import RescuePresentationApiTests


class RescueAcceptanceArchivesTests(TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[2]/'src/modulea/core/rescue_acceptance_archives.py'
        self.assertTrue(path.is_file(),'缺少完整包公共Workflow及独立归档账本')
        self.model=importlib.import_module('modulea.core.rescue_acceptance_archives')
        self.seed=RescuePresentationApiTests('test_current_view_and_focus_use_same_explicit_revision_and_keep_na')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        class ArchiveWorkflow(self.model.RescueAcceptanceArchivesMixin,self.seed.w.__class__):pass
        self.w=ArchiveWorkflow(self.seed.seed.root)
        self.seed.w=self.w;self.seed.seed.w=self.w
        self.sid,self.rid,self.home=self.seed.sid,self.seed.rid,self.seed.home
        self.graph=self.seed.publish()

    def info(self):
        return self.w.rescue_acceptance_archive_info(self.sid,self.rid,self.graph['revision_id'],min_free_bytes=0)

    def body(self):
        value=self.info()
        return {'request_id':new_id('rescuezipreq'),'expected_run_id':self.rid,
                'expected_revision_id':self.graph['revision_id'],'expected_revision_sha256':self.graph['file']['sha256'],
                'expected_input_key':'original','expected_input_hash':value['expected_input_hash'],
                'author':'合成完整包任务','note':'仅本同修订完整原件，不重算或签复核','confirmed':True}

    def publish(self,body=None,**options):
        return self.w.publish_rescue_acceptance_archive(self.sid,body or self.body(),min_free_bytes=0,**options)

    def test_info_is_read_only_and_complete_publication_preserves_scientific_records(self):
        before=self.w.load(self.sid);files=self.seed.seed.original_files()
        self.assertTrue(self.info()['enabled']);self.assertEqual(self.w.load(self.sid),before)
        self.assertEqual(self.seed.seed.original_files(),files)
        record=self.publish()
        self.assertFalse(record['human_review_written']);self.assertFalse(record['scientific_results_changed'])
        after=self.w.load(self.sid)
        for key in ('current','runs','reviews'):self.assertEqual(after[key],before[key])
        value=self.w.read_rescue_acceptance_archive(self.sid,record['file'])
        self.assertEqual(value['archive_file'],record['archive_file'])
        self.assertEqual(value['revision_id'],self.graph['revision_id'])
        self.assertTrue(value['archive_file']['bytes']>0)
        for path,digest in files.items():
            from hashlib import sha256
            self.assertEqual(sha256((self.home/path).read_bytes()).hexdigest(),digest)

    def test_completed_request_and_candidate_retry_do_not_rebuild_archive(self):
        body=self.body();first=self.publish(body)
        with patch.object(self.model.archive_io,'write_archive',side_effect=AssertionError('不可重复打包')):
            again=self.publish(body)
        self.assertEqual(first['archive_id'],again['archive_id']);self.assertFalse(again['created'])

    def test_manifest_receipt_failure_recovers_same_candidate_and_preserves_orphan(self):
        body=self.body();save=self.w.save;failed=[]
        def stop(m):
            if m.get(self.model.INDEX) and not failed:failed.append(True);raise OSError('合成回执发表中断')
            return save(m)
        with patch.object(self.w,'save',stop),self.assertRaises(OSError):self.publish(body)
        m=self.w.load(self.sid);self.assertTrue(m[self.model.CANDIDATES]);self.assertFalse(m.get(self.model.INDEX))
        with patch.object(self.model.archive_io,'write_archive',side_effect=AssertionError('完整candidate不重包')):
            record=self.publish(body)
        self.assertEqual(len(self.w.load(self.sid)[self.model.INDEX]),1)
        self.assertEqual(record['candidate_file'],m[self.model.CANDIDATES][-1])

    def test_cancel_after_archive_write_does_not_register_success(self):
        build=self.model.archive_io.write_archive;cancelled=[]
        def check():
            if cancelled:raise ContractError('合成任务已取消')
        def cancel(*args,**kwargs):
            value=build(*args,**kwargs);cancelled.append(True);return value
        with patch.object(self.model.archive_io,'write_archive',cancel),self.assertRaises(ContractError):
            self.publish(check_task=check)
        self.assertFalse(self.w.load(self.sid).get(self.model.INDEX))
        self.assertFalse(self.w.load(self.sid).get(self.model.CANDIDATES))

    def test_archive_code_snapshot_corrupted_during_build_cannot_be_published(self):
        build=self.model.archive_io.write_archive;changed=[]
        def corrupt(*args,**kwargs):
            value=build(*args,**kwargs);m=self.w.load(self.sid)
            ref=m[self.model.REQUESTS][-1];request=json.loads((self.home/ref['path']).read_text('utf8'))
            file=next(iter(request['implementation_files'].values()));target=self.home/file['path']
            raw=target.read_bytes();target.write_bytes(bytes([raw[0]^1])+raw[1:]);changed.append(True)
            return value
        with patch.object(self.model.archive_io,'write_archive',corrupt),self.assertRaises(ContractError):self.publish()
        self.assertTrue(changed);m=self.w.load(self.sid)
        self.assertFalse(m.get(self.model.CANDIDATES));self.assertFalse(m.get(self.model.INDEX))

    def test_paused_input_blocks_publish_but_historical_original_package_remains_readable(self):
        record=self.publish();self.w.review(self.sid,self.rid,'pending','合成暂停','不得生成新包')
        self.assertFalse(self.info()['enabled'])
        with self.assertRaises(ContractError):self.publish()
        self.assertEqual(self.w.read_rescue_acceptance_archive(self.sid,record['file'])['archive_id'],record['archive_id'])

    def test_changed_body_source_or_damaged_archive_cannot_be_used_as_success(self):
        body=self.body()
        with self.assertRaises(ContractError):self.publish(dict(body,expected_revision_sha256='f'*64))
        with self.assertRaises(ContractError):self.publish(dict(body,path='foreign'))
        record=self.publish(body)
        target=self.home/record['archive_file']['path'];target.write_bytes(b'broken')
        with self.assertRaises(ContractError):self.w.read_rescue_acceptance_archive(self.sid,record['file'])
        with self.assertRaises(ContractError):self.publish(body)

    def test_resealed_metadata_cannot_relabel_original_zip_as_another_run(self):
        record=self.publish();m=self.w.load(self.sid)
        def replace(ref,value):return self.seed.seed.seed.save(ref['path'],value)
        request=json.loads((self.home/record['request_file']['path']).read_text('utf8'))
        request['binding']['run_id']='run_'+'f'*32
        request['input_hash']=fingerprint(request['binding'])
        request['request']['expected_input_hash']=request['input_hash'];request['request_hash']=fingerprint(request['request'])
        request_ref=replace(record['request_file'],request);m[self.model.REQUESTS]=[request_ref]
        candidate=json.loads((self.home/record['candidate_file']['path']).read_text('utf8'))
        candidate.update(run_id=request['binding']['run_id'],request_file=request_ref,input_hash=request['input_hash'])
        candidate_ref=replace(record['candidate_file'],candidate);m[self.model.CANDIDATES]=[candidate_ref]
        receipt=dict(candidate,candidate_file=candidate_ref)
        ref=replace(record['file'],receipt);m[self.model.INDEX]=[ref];self.w.save(m)
        with self.assertRaises(ContractError):self.w.read_rescue_acceptance_archive(self.sid,ref)

    def reseal_implementation(self,empty):
        """成套重封技术元数据，但保留同一个实际ZIP，检验实现证据不能被同时删减。"""
        record=self.publish();m=self.w.load(self.sid)
        def replace(ref,value):return self.seed.seed.seed.save(ref['path'],value)
        request=json.loads((self.home/record['request_file']['path']).read_text('utf8'))
        removed=list(request['binding']['implementation']) if empty else [next(iter(request['binding']['implementation']))]
        for name in removed:
            request['binding']['implementation'].pop(name);request['implementation_files'].pop(name)
        request['input_hash']=fingerprint(request['binding'])
        request['request']['expected_input_hash']=request['input_hash'];request['request_hash']=fingerprint(request['request'])
        request_ref=replace(record['request_file'],request);m[self.model.REQUESTS]=[request_ref]
        candidate=json.loads((self.home/record['candidate_file']['path']).read_text('utf8'))
        candidate.update(request_file=request_ref,input_hash=request['input_hash'])
        candidate_ref=replace(record['candidate_file'],candidate);m[self.model.CANDIDATES]=[candidate_ref]
        receipt=dict(candidate,candidate_file=candidate_ref)
        ref=replace(record['file'],receipt);m[self.model.INDEX]=[ref];self.w.save(m)
        with self.assertRaises(ContractError):self.w.read_rescue_acceptance_archive(self.sid,ref)

    def test_resealed_empty_implementation_evidence_cannot_pass_historical_read(self):
        self.reseal_implementation(True)

    def test_resealed_one_missing_implementation_cannot_pass_historical_read(self):
        self.reseal_implementation(False)
