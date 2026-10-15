"""回收站任务接口边界：只读研究不能从继续或旧任务重试启动后台进程。"""

import unittest
from unittest.mock import Mock

from modulea.api.errors import ApiError
from modulea.api.server import App


class TaskActionReadonlyTests(unittest.TestCase):
    def app(self):
        """建立接口应用替身，提交方法只记录是否被不当调用。"""
        app = object.__new__(App)
        app.views = Mock()
        app.tasks = Mock()
        app.views._manifest.return_value = {"study_id": "fixture", "trashed": True}
        app.tasks._raw.return_value = {"study_id": "fixture", "kind": "continue"}
        app.tasks.submit.return_value = ({"task_id": "unexpected"}, True)
        app.tasks.retry.return_value = ({"task_id": "unexpected"}, True)
        return app

    def test_continue_rejects_trashed_study_before_submit(self):
        app = self.app()
        with self.assertRaises(ApiError) as caught:
            app.post_continue(Mock(), "fixture")
        self.assertEqual(caught.exception.status, 423)
        app.tasks.submit.assert_not_called()

    def test_retry_rejects_trashed_study_before_submit(self):
        app = self.app()
        with self.assertRaises(ApiError) as caught:
            app.post_retry(Mock(), "task_fixture")
        self.assertEqual(caught.exception.status, 423)
        app.tasks.retry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
