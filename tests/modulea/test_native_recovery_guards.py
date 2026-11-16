"""原生新协议恢复不能混用代码/环境，原准备被暂存或退回不得派生放行版本。"""
from unittest import TestCase
from types import SimpleNamespace
from unittest.mock import patch

from contracts import ContractError
from tests.modulea import test_native_execution as fixture


class NativeRecoveryGuardTests(TestCase):
    def setUp(self):
        self.seed = fixture.NativeExecutionTests('test_new_protocol_full_matrix_keeps_na_and_never_auto_approves')
        self.seed.setUp(); self.addCleanup(self.seed.doCleanups)

    def test_same_request_with_changed_code_version_cannot_reuse_completed_run(self):
        self.seed.execute()
        self.seed.w.code_version += '_changed'
        with self.assertRaises(ContractError): self.seed.execute()

    def test_same_request_with_changed_environment_cannot_reuse_completed_run(self):
        self.seed.execute()
        self.seed.w.environment = dict(self.seed.w.environment, system='changed_environment')
        with self.assertRaises(ContractError): self.seed.execute()

    def source_review_blocks(self, decision):
        result = self.seed.ready_preparation(); body = self.seed.qualification_body(result)
        self.seed.w.review(self.seed.sid, result['run_id'], decision,
                           '明确合成复核人', '原包暂停或退回，禁止派生放行', expected_review=None)
        before = self.seed.w.load(self.seed.sid)
        with self.assertRaises(ContractError):
            self.seed.w.qualify_native_preparation(self.seed.sid, body, settings=self.seed.settings)
        self.assertEqual(self.seed.w.load(self.seed.sid), before)
        from modulea.api.native_execution import info
        with patch('modulea.api.native_execution.configuration_blockers',return_value=[]):
            value=info(self.seed.base.app,SimpleNamespace(),self.seed.sid)
        prepare=next(row for row in value['stages'] if row['key']=='prepare')
        self.assertTrue(prepare['enabled'],'原包暂存或退回后应允许明确新请求整改，不能绕过原决定')
        self.assertEqual(prepare['request_template']['expected_preparation_run_id'],result['run_id'])

    def test_pending_source_preparation_blocks_qualification(self):
        self.source_review_blocks('pending')

    def test_rejected_source_preparation_blocks_qualification(self):
        self.source_review_blocks('rejected')

    def test_source_history_review_is_refused_and_adverse_projection_cannot_bypass_gate(self):
        raw=self.seed.ready_preparation();body=self.seed.qualification_body(raw)
        qualified=self.seed.w.qualify_native_preparation(self.seed.sid,body,settings=self.seed.settings)
        w=self.seed.w;sid=self.seed.sid;rid=qualified['run_id']
        self.assertTrue(w.active(w.load(sid),rid))
        manifest=w.load(sid)
        # 原状态机不允许给已被新版本替代的RAW追加意见，不能为测门控扩大历史复核权限。
        with self.assertRaises(ContractError):
            w.review(sid,raw['run_id'],'rejected','合成测试','历史原包不可重新复核',expected_review=None)
        self.assertTrue(w.active(w.load(sid),rid))
        raw_artifact=w.run(manifest,raw['run_id'])['artifact_id'];latest=w.latest_review
        # 仅合成读取投影验证防御门控；未伪造归档意见、修改研究或声称历史review入口允许此动作。
        def adverse(m,artifact):
            return {'decision':'rejected'} if artifact==raw_artifact else latest(m,artifact)
        with patch.object(w,'latest_review',side_effect=adverse):
            self.assertFalse(w.active(manifest,rid))
            self.assertEqual(w.result(manifest,rid),qualified,'归档历史仍可读，不删除或混用原件')
            with self.assertRaises(ContractError):w.qualify_native_preparation(sid,body,settings=self.seed.settings)
        self.assertEqual(w.load(sid),manifest)
