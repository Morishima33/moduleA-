"""同修订完整包沿原重任务和取消检查；真实SQLite加合成公开Workflow，不启动科学计算。"""
import json
import os
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError
from modulea.config import Settings
from modulea.tasks.manager import TaskManager
from modulea.tasks.rescue_presentation import run
from tests.modulea.test_rescue_acceptance_archives import RescueAcceptanceArchivesTests


class RescueAcceptanceArchiveWorkerTests(TestCase):
    def setUp(self):
        self.seed=RescueAcceptanceArchivesTests('test_info_is_read_only_and_complete_publication_preserves_scientific_records')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        root=self.seed.w.root
        self.settings=Settings(data_root=root,runtime_dir=root/'runtime',compute_min_free_bytes=0)
        self.manager=TaskManager(self.settings)
        p=patch('modulea.core.kernel.Kernel.workflow',return_value=self.seed.w);p.start();self.addCleanup(p.stop)

    def submit(self):
        with patch.object(self.manager,'_spawn'):
            task,created=self.manager.submit(self.seed.sid,'plan_rescue_presentation','合成完整包',
                                             {'stage':'archive','request':self.seed.body()})
        self.assertTrue(created);self.assertTrue(self.manager.claim_resources(task['task_id'],os.getpid()))
        self.assertTrue(self.manager.claim(task['task_id'],os.getpid()))
        return self.manager._raw(task['task_id'])

    def test_archive_stage_uses_public_workflow_and_preserves_scientific_reviews(self):
        before=self.seed.w.load(self.seed.sid);task=self.submit()
        text=run(self.settings,task,self.manager)
        self.assertIn('完整包',text)
        after=self.seed.w.load(self.seed.sid)
        for key in ('current','runs','reviews'):self.assertEqual(after[key],before[key])
        self.assertEqual(len(after[self.seed.model.INDEX]),1)

    def test_cancellation_after_disk_build_cannot_register_complete_candidate(self):
        task=self.submit();build=self.seed.model.archive_io.write_archive;triggered=[]
        def cancel(*args,**kwargs):
            value=build(*args,**kwargs);triggered.append(True);self.manager.finish(task['task_id'],'cancelled');return value
        with patch.object(self.seed.model.archive_io,'write_archive',cancel),self.assertRaises(ContractError):
            run(self.settings,task,self.manager)
        self.assertTrue(triggered,'必须实际完成落盘后才触发取消，不能以入口拒绝冒充取消核验')
        after=self.seed.w.load(self.seed.sid)
        self.assertFalse(after.get(self.seed.model.CANDIDATES));self.assertFalse(after.get(self.seed.model.INDEX))
