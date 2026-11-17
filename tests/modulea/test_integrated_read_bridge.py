"""新继承接线不能丢失原只读证据范围；核实际原函数执行数、全SHA与scope外语义。"""
from pathlib import Path
import sys
from unittest import TestCase

from contracts import ContractError
from modulea.core.kernel import _ReadWorkflow
from modulea.core.rescue_read_evidence import json_evidence_scope
from tests.modulea import test_system_receptor_rescue_v2_core as fixture


class IntegratedReadBridgeTests(TestCase):
    def setUp(self):
        self.seed=fixture.ReceptorRescueV2CoreTests('test_original_paths_baseline_publishes_normal_v2_without_changing_preparation_or_reviews')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        self.result=self.seed.execute(self.seed.body());self.sid=self.seed.sid;self.rid=self.result['run_id']
        self.w=_ReadWorkflow(self.seed.w.root,self.seed.w.validators)
        self.manifest=self.w.load(self.sid)

    def count_source_calls(self,call):
        """只计当前测试线程的原source_binding函数体，无采样线程、栈转储或函数替换。"""
        code=self.seed.core.source_binding.__code__;count=0;previous=sys.getprofile()
        def profile(frame,event,arg):
            nonlocal count
            if event=='call' and frame.f_code is code:count+=1
        sys.setprofile(profile)
        try:call()
        finally:sys.setprofile(previous)
        return count

    def twice(self):
        self.assertTrue(self.w.active(self.manifest,self.rid))
        self.assertTrue(self.w.active(self.manifest,self.rid))

    def test_current_native_report_inheritance_keeps_same_request_fact_memoization(self):
        before=self.w.load(self.sid)
        for _ in range(2):
            with json_evidence_scope(self.w.root,self.sid) as evidence:
                self.assertEqual(self.count_source_calls(self.twice),1,'继承桥接不得使原scope重复完整重建相同来源')
            self.assertGreater(evidence.stats['exit_sha_checks'],0)
        self.assertEqual(self.count_source_calls(self.twice),2,'范围外仍按原严格函数逐次核验')
        self.assertEqual(self.w.load(self.sid),before)

    def test_same_request_cached_fact_does_not_allow_changed_original_on_exit(self):
        path=self.w.location(self.sid)/self.manifest['runs'][self.rid]['run_file']['path']
        original=path.read_bytes()
        with self.assertRaises(ContractError):
            with json_evidence_scope(self.w.root,self.sid):
                self.assertTrue(self.w.active(self.manifest,self.rid))
                path.write_bytes(b'['+original[1:])
                self.w.active(self.manifest,self.rid)
