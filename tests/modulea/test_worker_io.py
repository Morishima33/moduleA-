"""在真实Workflow合成研究中验证显式I/O适配、原二版恢复及篡改阻断。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError, fingerprint
import storage
from modulea.core.worker_io import WorkerIO
from modulea.core import system_receptor_rescue_v2 as core
from modulea.core.rescue_recovery import preflight
from tests.modulea import test_system_receptor_rescue_v2_core as fixture


class WorkerIOTests(unittest.TestCase):
    def setUp(self):
        self.seed = fixture.ReceptorRescueV2CoreTests('test_exact_incomplete_v2_request_resumes_same_run_and_checkpoint_dispatches')
        self.seed.setUp()
        self.addCleanup(self.seed.doCleanups)
        self.io = WorkerIO()
        self.addCleanup(self.io.close)
        self.w = self.io.wrap(self.seed.w)
        self.sid = self.seed.sid

    def interrupted(self):
        body = self.seed.body()
        self.seed.science.compute.side_effect = RuntimeError('合成二版中断')
        with self.assertRaises(RuntimeError):self.seed.execute(body)
        rid = self.w.load(self.sid)['current']['A06']
        return body, rid

    def test_original_namespace_is_untouched_and_streamed_workflow_keeps_original_result(self):
        old = core.execute.__globals__['verified_file']
        m = self.w.load(self.sid)
        self.assertEqual(self.w.run(m,self.seed.score), self.seed.w.run(m,self.seed.score))
        self.assertEqual(self.w.result(m,self.seed.score), self.seed.w.result(m,self.seed.score))
        self.assertIs(core.execute.__globals__['verified_file'],old)
        self.assertEqual(self.w.code_version,self.seed.w.code_version)
        self.assertIsInstance(self.w,type(self.seed.w))

    def test_old_v2_registered_object_resumes_same_run_without_new_approval(self):
        body, rid = self.interrupted()
        home = self.w.location(self.sid)
        p = home/'registered.pdbqt';p.write_bytes(b'actual fixture receptor')
        f = storage.file_record(home,p,'receptor')
        cp = self.seed.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid,rid,'receptor_HGNC_1',
              {'state':'ready','receptor':f},[f])
        m = self.w.load(self.sid);original = deepcopy(m['runs'][rid]);reviews = deepcopy(m['reviews'])
        self.assertEqual(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid,rid,'receptor_HGNC_1')[0],cp)
        self.seed.science.compute.side_effect = self.seed.seed.compute
        answer = self.w.execute_analysis_plan_receptor_rescue_v2(self.sid,body,
                 tools=self.seed.seed.tools,repair_packages=self.seed.seed.repair)
        self.assertEqual(answer['run_id'],rid)
        final = self.w.load(self.sid)
        self.assertEqual(final['runs'][rid]['run_file'],original['run_file'])
        self.assertEqual(final['reviews'],reviews)
        self.assertEqual(len(final['runs']),len(m['runs']))

    def test_checkpoint_payloads_are_not_cached_and_header_cache_is_bounded(self):
        body,rid = self.interrupted()
        home = self.w.location(self.sid);m = self.w.load(self.sid);run = self.w.run(m,rid)
        for i in range(48):
            key=f'pair_{i+1:06d}_region_0001'
            p=home/f'runs/A06/{rid}/rescue_checkpoints/{key}/checkpoint.json'
            storage.write_json(p,dict(schema_version=core.VERSION,study_id=self.sid,run_id=rid,key=key,
                config_hash=run['config_hash'],payload={'state':'completed','score':-7,'padding':'x'*8192},
                files=[],previous=None,human_review_written=False))
            m.setdefault(core.CHECKPOINTS,[]).append(storage.file_record(home,p,'checkpoint'))
        self.w.save(m)
        for i in range(48):
            self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid,rid,f'pair_{i+1:06d}_region_0001')
        self.assertLessEqual(self.io.stats['checkpoint_json_parses'],96)
        self.assertGreaterEqual(self.io.stats['checkpoint_sha_checks'],48*48)
        self.assertLessEqual(len(self.io.headers),self.io.header_limit)
        p.write_bytes(b'corrupt')
        with self.assertRaises(ContractError):
            self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid,rid,'pair_000001_region_0001')

    def test_corruption_or_changed_configuration_still_blocks_resume(self):
        body,rid = self.interrupted()
        self.seed.science.configuration.side_effect=lambda *_,**__:dict(self.seed.seed.configuration,version=core.VERSION,vina_sha256='changed')
        with self.assertRaises(ContractError):
            self.w.execute_analysis_plan_receptor_rescue_v2(self.sid,body,
                 tools=self.seed.seed.tools,repair_packages=self.seed.seed.repair)

    def test_preflight_checks_original_binding_and_names_actual_changed_fields(self):
        body,rid=self.interrupted()
        args=(self.io,self.w,self.sid,rid,body,self.seed.seed.tools,self.seed.seed.repair)
        _,run=preflight(*args)
        self.assertEqual(run['run_id'],rid)
        self.seed.science.configuration.side_effect=lambda *_,**__:dict(self.seed.seed.configuration,version=core.VERSION,vina_sha256='changed')
        with self.assertRaisesRegex(ContractError,'configuration.vina_sha256'):preflight(*args)

    def test_explicit_adapter_snapshot_preserves_run_and_guards_later_corruption(self):
        body,rid = self.interrupted()
        before = self.w.load(self.sid)
        reference = self.w.register_worker_io(self.sid,rid,body)
        self.io.activate_registration(self.w,self.sid,reference)
        after = self.w.load(self.sid)
        self.assertEqual(after['runs'],before['runs'])
        self.assertEqual(after['reviews'],before['reviews'])
        self.assertEqual(self.w.register_worker_io(self.sid,rid,body),reference)
        value = storage.read_json(self.w.location(self.sid)/reference['path'])
        (self.w.location(self.sid)/value['files'][0]['path']).write_bytes(b'tampered adapter')
        with self.assertRaises(ContractError):
            self.w.append_analysis_plan_receptor_rescue_checkpoint(self.sid,rid,
                 'pair_000001_region_0001',{'state':'completed'},[])

    def test_real_workflow_result_verifies_large_attachment_without_full_read(self):
        m=self.w.load(self.sid);rid=self.seed.score;home=self.w.location(self.sid)
        large=home/'large.dat'
        with large.open('wb') as stream:
            for _ in range(32):stream.write(b'x'*1024*1024)
        result_ref=m['runs'][rid]['result_file']
        result=storage.read_json(home/result_ref['path'])
        result['files'].append(storage.file_record(home,large,'large'))
        storage.write_json(home/result_ref['path'],result,replace=True)
        m['runs'][rid]['result_file']=storage.file_record(home,home/result_ref['path'],result_ref['role'])
        self.w.save(m)
        original=Path.read_bytes
        def guarded(path):
            if path.resolve()==large.resolve():raise AssertionError('大原件不能整件读入')
            return original(path)
        with patch.object(Path,'read_bytes',guarded):
            self.assertEqual(self.w.result(m,rid),result)


if __name__ == '__main__':unittest.main()
