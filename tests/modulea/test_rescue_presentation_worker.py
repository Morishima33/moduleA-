"""名称修订沿现有SQLite单研究任务与公开Workflow；只用隔离合成资料。"""
import importlib
import json
import os
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError
from modulea.config import Settings
from modulea.tasks.manager import TaskManager, KINDS
from modulea.tasks.resource_runner import LIGHTWEIGHT
from tests.modulea.test_rescue_presentation_records import RescuePresentationRecordTests


class RescuePresentationWorkerTests(TestCase):
    def setUp(self):
        from modulea.tasks import worker
        self.assertIn('plan_rescue_presentation',KINDS,'缺少原任务管理器中的名称修订重任务')
        self.assertIn('plan_rescue_presentation',worker.HANDLERS)
        self.handler=worker.HANDLERS['plan_rescue_presentation']
        self.model=importlib.import_module('modulea.tasks.rescue_presentation')
        self.seed=RescuePresentationRecordTests('test_explicit_one_name_consent_and_public_publish_preserve_all_science')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        s=self.seed
        self.settings=Settings(data_root=s.root,runtime_dir=s.root/'runtime',font_regular=s.font)
        self.manager=TaskManager(self.settings)
        p=patch('modulea.core.kernel.Kernel.workflow',return_value=s.w);p.start();self.addCleanup(p.stop)

    def submit(self,payload,claim=True):
        with patch.object(self.manager,'_spawn'):
            task,created=self.manager.submit(self.seed.sid,'plan_rescue_presentation','合成用户',payload)
        self.assertTrue(created)
        if claim:
            self.assertTrue(self.manager.claim_resources(task['task_id'],os.getpid()))
            self.assertTrue(self.manager.claim(task['task_id'],os.getpid()))
        return self.manager._raw(task['task_id'])

    def test_heavy_kind_reuses_one_study_queue_and_public_publication(self):
        self.assertNotIn('plan_rescue_presentation',LIGHTWEIGHT)
        self.seed.approve_name();task=self.submit({'stage':'publish','request':self.seed.body()})
        with patch.object(self.manager,'_spawn') as spawn:
            again,created=self.manager.submit(self.seed.sid,'plan_rescue_presentation','相同研究另请求',{})
        self.assertFalse(created);self.assertEqual(task['task_id'],again['task_id']);spawn.assert_not_called()
        text=self.handler(self.settings,task,self.manager)
        self.assertIn('未改变',text)
        self.assertEqual(len(self.seed.w.load(self.seed.sid)[self.seed.model.INDEX]),1)

    def test_unclaimed_or_cancelled_task_cannot_write_research(self):
        self.seed.approve_name();task=self.submit({'stage':'publish','request':self.seed.body()},claim=False)
        before=self.seed.original_files()
        with self.assertRaises(ContractError):self.handler(self.settings,task,self.manager)
        self.assertTrue(self.manager.claim_resources(task['task_id'],os.getpid()))
        self.assertTrue(self.manager.claim(task['task_id'],os.getpid()))
        self.manager.finish(task['task_id'],'cancelled')
        with self.assertRaises(ContractError):self.handler(self.settings,task,self.manager)
        self.assertEqual(before,self.seed.original_files())

    def test_cancel_state_during_render_prevents_public_receipt(self):
        self.seed.approve_name();task=self.submit({'stage':'publish','request':self.seed.body()})
        from science_modules.a06 import system_rescue_presentation as render
        original=render.export
        def cancel(*args,**kwargs):
            value=original(*args,**kwargs);self.manager.finish(task['task_id'],'cancelled');return value
        with patch.object(render,'export',cancel),self.assertRaises(ContractError):
            self.handler(self.settings,task,self.manager)
        self.assertFalse(self.seed.w.load(self.seed.sid).get(self.seed.model.INDEX))
        self.assertFalse(self.seed.w.load(self.seed.sid).get(self.seed.model.CANDIDATES))

    def test_unknown_stage_or_payload_override_is_rejected(self):
        for payload in ({'stage':'publish','request':{},'font_path':'foreign'},
                        {'stage':'score','request':{}},{'request':{}}):
            task=self.submit(payload)
            with self.subTest(payload=payload),self.assertRaises(ContractError):
                self.handler(self.settings,task,self.manager)
            self.manager.finish(task['task_id'],'failed')

    def test_payload_changed_after_claim_cannot_publish(self):
        self.seed.approve_name();task=self.submit({'stage':'publish','request':self.seed.body()})
        self.manager.update(task['task_id'],payload=json.dumps({'stage':'publish','request':{}}))
        with self.assertRaises(ContractError):self.handler(self.settings,task,self.manager)
        self.assertFalse(self.seed.w.load(self.seed.sid).get(self.seed.model.INDEX))

    def test_unknown_process_birth_cannot_pass_as_two_matching_null_identities(self):
        self.seed.approve_name();payload={'stage':'publish','request':self.seed.body()}
        with patch('modulea.tasks.process_identity.identity',return_value=None),patch.object(self.model,'identity',return_value=None):
            task=self.submit(payload)
            self.assertEqual(json.loads(task['process_identity']),None)
            before=self.seed.w.load(self.seed.sid);files=self.seed.original_files()
            with self.assertRaises(ContractError):self.handler(self.settings,task,self.manager)
            self.assertEqual(self.seed.w.load(self.seed.sid),before)
            self.assertEqual(self.seed.original_files(),files)

    def test_explicit_name_decision_stage_replays_public_decision_without_duplicates(self):
        decision=self.seed.approve_name()
        task=self.submit({'stage':'original_name','request':decision['decision']})
        before=self.seed.w.load(self.seed.sid);files=self.seed.original_files()
        text=self.handler(self.settings,task,self.manager)
        self.assertIn('不计入已核中文',text)
        self.assertEqual(self.seed.w.load(self.seed.sid),before)
        self.assertEqual(self.seed.original_files(),files)
