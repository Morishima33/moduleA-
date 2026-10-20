"""未提交结果的A06页面不能读取最终评分或提前开放出图。"""

from pathlib import Path
from types import SimpleNamespace
import unittest

from modulea.core.docking_artifacts import DockingArtifactWorkflow, catalog


class PendingDrawingTests(unittest.TestCase):
    def fixture(self, result, inputs=None):
        """仅替换归档读取，运行生产目录提取与页面上下文代码。"""
        workflow = SimpleNamespace(
            location=lambda sid: Path('.'),
            run=lambda manifest, run_id: {'inputs': inputs or {}},
            result=lambda manifest, run_id: result,
        )
        manifest = {'study_id': 'isolated', 'runs': {'pending': {'result_file': None}}}
        return workflow, manifest

    def test_pending_and_failed_without_result_have_no_catalog(self):
        """无结果时不读取试算原件，更不能将中间文件当作已完成评分。"""
        for inputs in ({}, {'trial_packet': {'path': 'must_not_read'}}):
            with self.subTest(inputs=inputs):
                workflow, manifest = self.fixture(None, inputs)
                binding, pairs = catalog(workflow, manifest, 'pending')
                self.assertEqual(binding['a06_run'], 'pending')
                self.assertEqual(pairs, [])
                self.assertIsNone(DockingArtifactWorkflow.docking_artifact_context(
                    workflow, manifest, 'pending', busy=True))

    def test_completed_empty_result_stays_empty(self):
        """有效空结果仍无出图对象。"""
        workflow, manifest = self.fixture({'tables': {}})
        self.assertEqual(catalog(workflow, manifest, 'pending')[1], [])

    def test_corrupt_result_is_not_silently_hidden(self):
        """仅处理合法的未提交状态，损坏的结果仍暴露错误。"""
        workflow, manifest = self.fixture([])
        with self.assertRaises(AttributeError):
            catalog(workflow, manifest, 'pending')
