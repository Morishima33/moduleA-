"""旧CP只读文件循环应沿原判断并使用既有批量完整SHA，不改恢复名单或科学逻辑。"""
import os,threading
from contracts import ContractError
from unittest import TestCase
from unittest.mock import patch

from storage import file_record,read_json,write_json,new_id
from modulea.core.kernel import _ReadWorkflow
from modulea.core.checkpoint_json_read import json_evidence_scope
from tests.modulea import test_system_receptor_rescue_v2_core as fixture


class CheckpointJsonReadTests(TestCase):
    def setUp(self):
        self.seed=fixture.ReceptorRescueV2CoreTests('test_partial_binding_preserves_registered_objects_and_stays_identical_after_current_changes_to_v2')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        self.rid,self.checkpoints,_=self.seed.partial_first()
        self.sid=self.seed.sid;self.core=self.seed.core
        self.w=_ReadWorkflow(self.seed.w.root,self.seed.w.validators);self.home=self.w.location(self.sid)
        self.files=[]
        for index in range(40):
            path=self.home/'runs/A06'/self.rid/'bulk'/f'file_{index:03}.dat'
            path.parent.mkdir(exist_ok=True);path.write_bytes(('synthetic evidence '+str(index)).encode('ascii'))
            self.files.append(file_record(self.home,path,'synthetic_bulk_checkpoint_evidence'))
        ref=self.seed.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid,self.rid,'pair_000001_region_0002',
            {'state':'completed','score':-7.9},self.files)
        self.checkpoints.append(ref);self.manifest=self.w.load(self.sid)
        self.original=self.core.frozen.source_binding(self.w,self.manifest,self.seed.prep,self.seed.score)

    def read(self,evidence):
        return evidence.call(self.core.partial_recovery,self.w,self.manifest,self.seed.prep,self.seed.score,self.original)

    def test_original_partial_selection_batches_files_and_preserves_full_exit_sha(self):
        expected=self.core.partial_recovery(self.w,self.manifest,self.seed.prep,self.seed.score,self.original)
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            actual=evidence.raw_reader._verify;threads=set();batches=[]
            def verify(root,record,**kwargs):
                if record.get('role')=='synthetic_bulk_checkpoint_evidence':threads.add(threading.get_ident())
                return actual(root,record,**kwargs)
            bulk=evidence.verify_all
            def verify_all(root,records):
                records=list(records);batches.append(records)
                return bulk(root,records)
            with patch.object(evidence.raw_reader,'_verify',side_effect=verify),patch.object(evidence,'verify_all',side_effect=verify_all):
                self.assertEqual(self.read(evidence),expected)
            self.assertTrue(any(rows==self.files for rows in batches),'原CP文件循环未使用已存在的批量全SHA核验')
            self.assertGreater(len(threads),1,'至少两个实际原件读取线程应执行完整核验')
            for ref in self.files:self.assertIn((self.home.resolve(),ref['path'],ref['bytes'],ref['sha256']),evidence.proofs)
        self.assertEqual(evidence.stats['first_sha_checks'],evidence.stats['exit_sha_checks'])
        self.assertEqual(evidence.stats['first_bytes_hashed'],evidence.stats['exit_bytes_hashed'])

    def test_source_binding_real_call_chain_batches_without_changing_source_function(self):
        """实际source_binding的私有函数依赖也分派新适配，原模块globals始终不改。"""
        import sys
        original_json=self.core.partial_recovery.__globals__['read_json'];frames=[]
        previous=sys.getprofile();code=self.core.partial_recovery.__code__
        def profile(frame,event,arg):
            if event=='call' and frame.f_code is code:frames.append(frame.f_globals)
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            batches=[];bulk=evidence.verify_all
            def verify_all(root,records):
                rows=list(records);batches.append(rows);return bulk(root,rows)
            with patch.object(evidence,'verify_all',side_effect=verify_all):
                sys.setprofile(profile)
                try:
                    value=evidence.call(self.core.source_binding,self.w,self.manifest,self.seed.prep,self.seed.score)
                finally:sys.setprofile(previous)
            self.assertEqual(value['partial_recovery']['checkpoint_refs'],self.checkpoints)
            self.assertTrue(any(rows==self.files for rows in batches))
            self.assertTrue(frames)
            self.assertTrue(all(namespace is not self.core.partial_recovery.__globals__ for namespace in frames))
            self.assertIs(self.core.partial_recovery.__globals__['read_json'],original_json)

    def test_production_json_entry_uses_validated_checkpoint_batching(self):
        """实际App入口不能继续走旧范围；不在测试外另套新scope。"""
        from types import SimpleNamespace
        from modulea.api.server import App
        from modulea.core.checkpoint_json_read import CheckpointReadEvidence
        original=CheckpointReadEvidence.verify_all;batches=[]
        def verify_all(evidence,root,records):
            rows=list(records);batches.append(rows);return original(evidence,root,rows)
        app=SimpleNamespace(settings=SimpleNamespace(data_root=self.w.root))
        with patch.object(CheckpointReadEvidence,'verify_all',verify_all):
            value=App._json_read(app,self.sid,self.core.source_binding,self.w,self.manifest,self.seed.prep,self.seed.score)
        self.assertEqual(value['partial_recovery']['checkpoint_refs'],self.checkpoints)
        self.assertTrue(any(rows==self.files for rows in batches),'生产JSON应接入已验证的批量完整SHA')

    def replace_last_checkpoint(self,change):
        """只更改本测试合成原件并同步其索引，用于验证原内容规则而不是仅SHA损坏。"""
        reference=self.checkpoints[-1];path=self.home/reference['path'];value=read_json(path)
        change(value);write_json(path,value,replace=True)
        replacement=file_record(self.home,path,reference['role'])
        self.manifest[self.core.frozen.CHECKPOINTS]=[replacement if ref==reference else ref
            for ref in self.manifest[self.core.frozen.CHECKPOINTS]]
        self.seed.w.save(self.manifest)

    def test_invalid_checkpoint_chain_blocks_before_declared_files_are_read(self):
        missing={'path':'not_present.dat','bytes':1,'sha256':'0'*64,'role':'must_not_be_read'}
        self.replace_last_checkpoint(lambda value:value.update(previous=self.checkpoints[0],files=[missing]))
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            bulk=evidence.verify_all;batches=[]
            def verify_all(root,records):
                rows=list(records);batches.extend(rows);return bulk(root,rows)
            with patch.object(evidence,'verify_all',side_effect=verify_all):
                with self.assertRaisesRegex(ContractError,'归属、对象或配置不同'):self.read(evidence)
            self.assertNotIn(missing,batches,'原历史链拒绝必须在files核验之前')

    def test_ignored_other_run_checkpoint_does_not_read_its_unrelated_missing_files(self):
        missing={'path':'unrelated_not_present.dat','bytes':1,'sha256':'0'*64,'role':'unrelated'}
        value=read_json(self.home/self.checkpoints[-1]['path'])
        value.update(run_id='run_'+'f'*32,files=[missing])
        path=self.home/'ignored_checkpoint.json';write_json(path,value)
        self.manifest[self.core.frozen.CHECKPOINTS].append(file_record(self.home,path,'ignored_other_run_checkpoint'))
        self.seed.w.save(self.manifest)
        expected=self.core.partial_recovery(self.w,self.manifest,self.seed.prep,self.seed.score,self.original)
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            self.assertEqual(self.read(evidence),expected)
            self.assertFalse(any(key[1]==missing['path'] for key in evidence.proofs))

    def test_missing_and_same_mtime_tampered_bulk_originals_both_block(self):
        path=self.home/self.files[0]['path'];raw=path.read_bytes();stamp=path.stat()
        for missing in (False,True):
            with self.subTest(missing=missing):
                if missing:path.unlink()
                else:
                    path.write_bytes(b'x'*len(raw));os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                try:
                    with self.assertRaises(ContractError):
                        with json_evidence_scope(self.w.root,self.sid) as evidence:self.read(evidence)
                finally:path.write_bytes(raw)

    def test_file_changed_after_bulk_read_still_blocks_at_final_sha(self):
        path=self.home/self.files[0]['path'];stamp=path.stat()
        with self.assertRaises(ContractError):
            with json_evidence_scope(self.w.root,self.sid) as evidence:
                self.read(evidence)
                path.write_bytes(b'x'*self.files[0]['bytes'])
                os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))

    def test_partial_rejected_review_blocks_before_any_bulk_files(self):
        run=self.w.run(self.manifest,self.rid)
        path=self.home/'reviews'/(new_id('review')+'.json')
        write_json(path,{'artifact_id':run['artifact_id'],'run_id':self.rid,
            'review_id':new_id('review'),'decision':'rejected'})
        self.manifest['reviews'].append(file_record(self.home,path,'review'));self.seed.w.save(self.manifest)
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            with self.assertRaises(ContractError):self.read(evidence)
            self.assertFalse(any(key[1]==self.files[0]['path'] for key in evidence.proofs))

    def test_new_scope_rechecks_and_expired_wrapper_returns_original_strict_read(self):
        for _ in range(2):
            with json_evidence_scope(self.w.root,self.sid) as evidence:
                bound=evidence.bind(self.core.partial_recovery)
                self.read(evidence)
                self.assertGreaterEqual(evidence.stats['first_sha_checks'],len(self.files))
            self.assertEqual(evidence.stats['first_sha_checks'],evidence.stats['exit_sha_checks'])
        self.assertIs(type(read_json(self.home/self.checkpoints[-1]['path'])['files']),list)
        (self.home/self.files[0]['path']).write_bytes(b'broken')
        with self.assertRaises(ContractError):
            bound(self.w,self.manifest,self.seed.prep,self.seed.score,self.original)

    def test_copied_context_cannot_dispatch_batching_from_another_thread(self):
        from contextvars import copy_context
        from concurrent.futures import ThreadPoolExecutor
        with json_evidence_scope(self.w.root,self.sid) as evidence:
            bound=evidence.bind(self.core.partial_recovery);copied=copy_context()
            with ThreadPoolExecutor(max_workers=1) as pool:
                result=pool.submit(copied.run,bound,self.w,self.manifest,self.seed.prep,self.seed.score,self.original).result()
            self.assertEqual(result['checkpoint_refs'],self.checkpoints)
            self.assertEqual(evidence.stats['first_sha_checks'],0,'其他线程必须完整原读取，不能写入本范围证明')
