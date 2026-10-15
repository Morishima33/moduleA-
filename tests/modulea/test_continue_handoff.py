"""自动接续验收：报告等待复核或发布后不能重复生成，也不能跨过A05复核。"""

from contextlib import nullcontext
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from modulea.config import Settings
from modulea.tasks.worker import run_continue


class ContinueHandoffTests(unittest.TestCase):
    def context(self, report="report", report_approved=False, a05_approved=True, active=True):
        """构造只读状态替身；报告生产入口被监控，避免测试写入真实研究。"""
        flow = Mock()
        current = {"A06": "docking", "A05": "enrichment"}
        if report:
            current["A07"] = report
        flow.load.return_value = {"current": current, "study_id": "fixture"}
        flow.run.return_value = {"config": {"schema_version": "A06.trial.handoff.1"}}
        flow.handoff_read_cache.side_effect = lambda: nullcontext()
        flow.approved.side_effect = lambda _, rid: (
            rid == "docking"
            or (rid == "enrichment" and a05_approved)
            or (rid == report and report_approved)
        )
        flow.active.side_effect = lambda _, rid: active if rid == report else True
        return flow, Settings(data_root=Path("fixture")), {"study_id": "fixture", "task_id": "t"}

    def test_existing_pending_report_does_not_regenerate(self):
        flow, settings, task = self.context()
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports") as generate,
        ):
            text = run_continue(settings, task, Mock())
        generate.assert_not_called()
        self.assertIn("复核", text)

    def test_published_report_is_terminal(self):
        flow, settings, task = self.context(report_approved=True)
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports") as generate,
        ):
            text = run_continue(settings, task, Mock())
        generate.assert_not_called()
        self.assertIn("流程完成", text)

    def test_unapproved_a05_does_not_invoke_report_builder(self):
        flow, settings, task = self.context(report=None, a05_approved=False)
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports") as generate,
        ):
            text = run_continue(settings, task, Mock())
        generate.assert_not_called()
        self.assertIn("A05", text)

    def test_missing_report_is_generated_once_without_signing(self):
        flow, settings, task = self.context(report=None)
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports", return_value={"run_id": "new_report"}) as generate,
        ):
            text = run_continue(settings, task, Mock())
        generate.assert_called_once_with(flow, "fixture", "", "用户通过扩展A06后接续双报告")
        flow.review.assert_not_called()
        self.assertIn("未自动批准A07", text)

    def test_stale_report_can_be_replaced(self):
        flow, settings, task = self.context(active=False)
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports", return_value={"run_id": "new_report"}) as generate,
        ):
            run_continue(settings, task, Mock())
        generate.assert_called_once()

    def test_unapproved_a06_stops_without_building_report(self):
        flow, settings, task = self.context(report=None)
        flow.approved.return_value = False
        flow.approved.side_effect = None
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports") as generate,
        ):
            text = run_continue(settings, task, Mock())
        generate.assert_not_called()
        self.assertIn("尚待正式复核", text)

    def test_coverage_preparation_stops_before_legacy_computation(self):
        flow, settings, task = self.context(report=None)
        flow.load.return_value = {"current": {"A06_PREP": "preparation"}, "study_id": "fixture"}
        flow.run.return_value = {"config": {"version": "A06.coverage.confirmed.4"}}
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("auto_continue.continue_after_review") as legacy,
            patch("report_dispatch.run_reports") as generate,
        ):
            text = run_continue(settings, task, Mock())
        legacy.assert_not_called()
        generate.assert_not_called()
        self.assertIn("明确授权", text)

    def test_new_candidates_keep_a05_independent_without_entering_docking(self):
        flow, settings, task = self.context(report=None)
        flow.load.return_value = {"current": {"A03": "intersection", "A04": "ppi"}}
        flow.run.return_value = {"config": {}}
        flow.active.return_value = True
        flow.active.side_effect = None
        flow.result.return_value = {"summary": {"docking_candidate_source_pending": True}}
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch(
                "modulea.core.docking_workflow.candidate_context",
                return_value={"data": {"ready": True}},
            ),
            patch("science_modules.a05.compact_flow.run_enrichment") as enrichment,
            patch("auto_continue.continue_after_review") as legacy,
        ):
            text = run_continue(settings, task, Mock())
        enrichment.assert_called_once()
        legacy.assert_not_called()
        self.assertIn("未启动A06", text)

    def test_significant_kegg_without_maps_waits_instead_of_failing_report(self):
        flow, settings, task = self.context(report=None)
        flow.ranked_maps_for.return_value = None
        flow.result.return_value = {"tables": {"kegg_p_top10": [{"ID": "hsa_fixture"}]}}
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports") as generate,
        ):
            text = run_continue(settings, task, Mock())
        generate.assert_not_called()
        self.assertIn("首位命中图", text)

    def test_empty_kegg_does_not_require_fabricated_maps(self):
        flow, settings, task = self.context(report=None)
        flow.ranked_maps_for.return_value = None
        flow.result.return_value = {"tables": {"kegg_p_top10": [], "kegg_count_top10": []}}
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=flow),
            patch("report_dispatch.run_reports", return_value={"run_id": "new_report"}) as generate,
        ):
            run_continue(settings, task, Mock())
        generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
