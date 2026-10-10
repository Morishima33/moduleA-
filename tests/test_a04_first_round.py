"""第一轮展示来源、新旧版本兼容、同源图及独立A04任务回归；仅虚构资料。"""

from pathlib import Path
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from docx import Document
from contracts import ContractError
from storage import read_json
from workflow import Workflow
from test_a04_dual import metrics, source_bundle
from science_modules.a04 import selection
from science_modules.a04.selection_v2 import from_legacy, VERSION
from science_modules.a04.flow_v2 import run_ppi, validator
from science_modules.a07.first_round_reports import (
    add_dual_section,
    degree_rows,
    bc_cc_rows,
    validate_word_tables,
)
from modulea.presenters.network import present_a04


# 建立独立虚构研究，明确通过虚构A03，不读取真实病例。
def study(root):
    w = Workflow(root, {"A04": validator(root)})
    sid = w.create(
        {
            "formula": "合成方",
            "herbs": "合成药",
            "disease": "合成病",
            "disease_scope": "仅测试",
            "operator": "test",
            "species": 9606,
        },
        kind="contract_test",
    )
    m = w.load(sid)
    w.review(sid, m["current"]["A00"], "approved", "test", "虚构检查")
    target = [{"target_id": "HGNC:1", "symbol": "D1"}, {"target_id": "HGNC:2", "symbol": "D2"}]
    for mid in ("A01", "A02", "A03"):
        r = w.begin(sid, mid, {}, {}, "虚构输入")
        w.finish(
            sid,
            r["run_id"],
            {"analysis_purpose": "workflow_test"},
            {"intersection_targets": target} if mid == "A03" else {},
        )
        w.review(sid, r["run_id"], "approved", "test", "虚构检查")
    return w, sid, w.load(sid)["current"]["A03"], target


class FirstRoundTests(unittest.TestCase):
    def test_first_source_distinct_from_second_and_frozen_version(self):
        summary, tables = from_legacy(
            {"参与节点数": 8, "合格边数": 12}, {"metrics": metrics(), "edges": []}
        )
        self.assertEqual([r["degree"] for r in tables["degree_round1_top10"]], [40, 24, 20])
        self.assertEqual([r["degree"] for r in tables["degree_top10"]], [40, 24])
        old_s, old_t = selection.from_legacy(
            {"参与节点数": 8, "合格边数": 12}, {"metrics": metrics(), "edges": []}
        )
        self.assertNotIn("degree_round1_top10", old_t)
        self.assertEqual(old_s["network_design_status"], "awaiting_user_confirmation")
        parts = present_a04({"summary": summary, "tables": tables}, {})
        self.assertEqual(parts.special["ppi_dual"]["degree_rows"], tables["degree_round1_top10"])
        self.assertEqual(parts.special["ppi_dual"]["degree_round"], 1)
        document = Document()
        add_dual_section(document, {"tables": tables})
        archive = {"a04_degree_top10": degree_rows(tables), "a04_bc_cc_top15": bc_cc_rows(tables)}
        validate_word_tables(document, {"tables": tables}, archive)
        self.assertEqual(len(document.tables[0].rows), 4)
        self.assertIn("第一轮", document.paragraphs[0].text)
        document.tables[0].rows[-1].cells[2].text = "24"
        with self.assertRaises(ContractError):
            validate_word_tables(document, {"tables": tables}, archive)

    def test_same_run_graph_unapproved_tamper_and_history(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            w, sid, a03, targets = study(root)
            with patch("ppi_flow.request", side_effect=AssertionError("禁止联网")):
                result = run_ppi(w, sid, a03, "", "新图虚构检查", source_bundle(targets))
            m = w.load(sid)
            self.assertFalse(w.approved(m, result["run_id"]))
            network = result["tables"]["degree_network"][0]
            self.assertEqual(network["a03_run"], a03)
            self.assertEqual(network["run_id"], result["run_id"])
            self.assertEqual(result["summary"]["selection_version"], VERSION)
            run = w.run(m, result["run_id"])
            bad = copy.deepcopy(result["tables"])
            bad["degree_network"][0]["a03_run"] = "other"
            with self.assertRaises(ContractError):
                validator(root)(run, result["summary"], bad, [], result["outcome"])
            image = w.location(sid) / network["png_path"]
            image.write_bytes(image.read_bytes() + b"tampered")
            with self.assertRaises(ContractError):
                w.result(m, result["run_id"])

    def test_string_transport_preserves_parameters_and_legacy_globals(self):
        import ppi_flow
        import science_modules.a04.source_io as io

        old_request = ppi_flow.request
        targets = [{"target_id": "HGNC:1", "symbol": "D1"}, {"target_id": "HGNC:2", "symbol": "D2"}]
        expected = source_bundle(targets)
        with (
            patch.object(
                io, "request", side_effect=[expected["mapping"], expected["network"]]
            ) as get,
            patch("ppi_flow.time.sleep"),
        ):
            actual = io.fetch(targets)
        self.assertEqual(actual, expected)
        self.assertIs(ppi_flow.request, old_request)
        self.assertEqual(
            get.call_args_list[0].args, ("get_string_ids", expected["mapping"]["params"])
        )
        self.assertEqual(get.call_args_list[1].args, ("network", expected["network"]["params"]))
        with (
            patch("urllib.request.getproxies_environment", return_value={}),
            patch("urllib.request.build_opener") as build,
        ):
            response = build.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b"[]"
            result = io.request("get_string_ids", expected["mapping"]["params"])
        self.assertEqual(result["response_text"], "[]")
        self.assertEqual(result["params"], expected["mapping"]["params"])
        self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 40)

    def test_dense_labels_draw_after_nodes_and_isolate_kept(self):
        import xml.etree.ElementTree as ET
        from science_modules.a04.figures import draw_degree

        rows = [
            {"target_id": str(i), "symbol": "GENE" + str(i), "degree": 10 + i} for i in range(14)
        ]
        tables = {
            "degree_round1": rows,
            "degree_round1_top10": list(reversed(rows[-10:])),
            "edges": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = draw_degree(tables, Path(directory) / "isolates")
            tree = ET.parse(paths["svg"]).getroot()
        children = list(tree)
        circles = [i for i, c in enumerate(children) if c.tag.endswith("circle")]
        labels = [
            i
            for i, c in enumerate(children)
            if c.tag.endswith("text")
            and c.text in {r["symbol"] for r in tables["degree_round1_top10"]}
        ]
        self.assertEqual(len(circles), 14)
        self.assertEqual(len(labels), 10)
        self.assertGreater(min(labels), max(circles))

    def test_figure_revision_rejects_another_a03_source(self):
        from modulea.tasks.worker import run_a04_ppi

        w = Mock()
        w.run.return_value = {"module_id": "A04", "parent_runs": {"A03": "another"}}
        payload = {
            "expected_a03": "a03",
            "expected_a04": "old",
            "reuse_source_run": "old",
            "reason": "修图",
        }
        with (
            patch("modulea.tasks.worker.full_workflow", return_value=w),
            patch("ppi_dispatch.run_ppi") as calculate,
        ):
            with self.assertRaises(ContractError):
                run_a04_ppi(
                    SimpleNamespace(data_root=Path("unused")),
                    {"study_id": "s", "task_id": "t", "payload": json.dumps(payload)},
                    Mock(),
                )
            calculate.assert_not_called()

    def test_compute_action_guards_and_task_payload(self):
        from modulea.api.server import App
        from modulea.api.errors import ApiError

        app = App.__new__(App)
        app.views, app.tasks = Mock(), Mock()
        info = {
            "enabled": True,
            "disabled_reason_zh": "",
            "expected_a03": "a03",
            "expected_a04": "old",
        }
        app.views.module.return_value = {"ppi_run": info}
        body = {"expected_a03": "a03", "expected_a04": "old", "reason": " 明确启动 "}
        req = SimpleNamespace(json=lambda: body)
        with self.assertRaises(ApiError):
            app.post_run_ppi(req, "s", "A05")
        body["expected_a03"] = "stale"
        with self.assertRaises(ApiError) as error:
            app.post_run_ppi(req, "s", "A04")
        self.assertEqual(error.exception.code, "STALE_VERSION")
        body["expected_a03"] = "a03"
        info["enabled"] = False
        with self.assertRaises(ApiError):
            app.post_run_ppi(req, "s", "A04")
        info["enabled"] = True
        app.tasks.submit.return_value = ({"task_id": "t", "state": "queued"}, True)
        result, status = app.post_run_ppi(req, "s", "A04")
        self.assertEqual(status, 202)
        app.tasks.submit.assert_called_once_with(
            "s",
            "a04_ppi",
            "页面启动A04",
            {"expected_a03": "a03", "expected_a04": "old", "reason": "明确启动"},
        )

    def test_a04_only_worker_and_old_validator_delegation(self):
        from modulea.tasks.worker import run_a04_ppi

        payload = {"expected_a03": "a03", "expected_a04": "old", "reason": "明确启动"}
        with (
            patch("modulea.tasks.worker.full_workflow", return_value="workflow"),
            patch(
                "ppi_dispatch.run_ppi", return_value={"run_id": "new", "summary": {}}
            ) as calculate,
            patch("enrichment_flow.run_enrichment", side_effect=AssertionError("不启动A05")),
        ):
            text = run_a04_ppi(
                SimpleNamespace(data_root=Path("unused")),
                {"study_id": "s", "task_id": "t", "payload": json.dumps(payload)},
                Mock(),
            )
        calculate.assert_called_once_with("workflow", "s", "a03", "old", "明确启动")
        self.assertIn("未自动批准", text)
        with patch("science_modules.a04.flow_v2.prior_validator", return_value=Mock()) as previous:
            validator(Path("unused"))({"config": {"version": "A04.dual.1"}}, {}, {}, [], "success")
            previous.return_value.assert_called_once()


if __name__ == "__main__":
    unittest.main()
