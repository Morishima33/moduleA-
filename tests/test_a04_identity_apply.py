"""身份方案真正应用、失败与历史复算回归；只替换外部请求及合成快照指纹。"""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contracts import ContractError
from storage import verified_file, read_json
from identity_plan_fixture import seed, synthetic_snapshot, official_response
from science_modules.a04.identity_flow import run_identity, validator
from modulea.core.identity_workflow import plan_view


class IdentityApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.w, self.sid, self.payload = seed(self.root)
        self.original = self.w.result(self.w.load(self.sid), self.payload["expected_a04"])
        self.original_bytes = (
            self.w.location(self.sid) / "runs/A04" / self.payload["expected_a04"] / "result.json"
        ).read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def simulate(self, response=official_response):
        with (
            synthetic_snapshot(),
            patch("science_modules.a04.source_io.request", side_effect=response),
            patch("ppi_flow.time.sleep"),
        ):
            return run_identity(self.w, self.sid, self.payload)

    # 方案成功与人工通过分别显示；模拟确认不能改变旧结果或替真实研究代签。
    def test_plan_status_follows_actual_workflow_approval(self):
        result = self.simulate()
        manifest = self.w.load(self.sid)
        run = self.w.run(manifest, result["run_id"])
        info = plan_view(self.w, manifest, run, result, True)
        self.assertEqual(info["latest"]["status_zh"], "已应用，新A04仍待独立复核")
        with synthetic_snapshot():
            self.w.review(self.sid, result["run_id"], "approved", "虚构核验人", "仅测试通过状态")
        manifest = self.w.load(self.sid)
        info = plan_view(self.w, manifest, run, result, True)
        self.assertEqual(info["latest"]["status_zh"], "已应用，A04已通过复核")
        self.assertEqual(
            (self.w.location(self.sid) / "runs/A04" / self.payload["expected_a04"] / "result.json").read_bytes(),
            self.original_bytes,
        )
        self.assertNotIn("A05", manifest["current"])
        self.assertNotIn("A06", manifest["current"])

    def test_save_then_apply_removes_only_evidence_resolved_issue_without_approving(self):
        result = self.simulate()
        manifest = self.w.load(self.sid)
        self.assertNotEqual(result["run_id"], self.payload["expected_a04"])
        self.assertEqual(result["summary"]["身份待核验数"], 0)
        self.assertEqual(result["summary"]["参与节点数"], 8)
        self.assertEqual(len(result["tables"]["identity_adjustments"]), 1)
        self.assertFalse(self.w.approved(manifest, result["run_id"]))
        self.assertNotIn("A05", manifest["current"])
        self.assertNotIn("A06", manifest["current"])
        self.assertEqual(
            (
                self.w.location(self.sid)
                / "runs/A04"
                / self.payload["expected_a04"]
                / "result.json"
            ).read_bytes(),
            self.original_bytes,
        )
        run = self.w.run(manifest, result["run_id"])
        self.assertIn("identity_authorization", run["inputs"])
        # 独立按来源复算，不靠“任务已成功”来断言正确。
        with synthetic_snapshot():
            validator(self.root)(run, result["summary"], result["tables"], [], result["outcome"])
        info = plan_view(self.w, manifest, run, result, True)
        self.assertEqual(info["latest"]["applied_run_id"], result["run_id"])
        self.assertEqual(info["latest"]["pending_count"], 0)
        self.assertFalse(info["enabled"])

    def test_conflict_fails_preserves_old_result_and_probes_and_retry_single_decision(self):
        with self.assertRaisesRegex(ContractError, "相互冲突"):
            self.simulate(lambda method, params: official_response(method, params, conflict=True))
        m = self.w.load(self.sid)
        self.assertEqual(m["current"]["A04"], self.payload["expected_a04"])
        self.assertEqual(len(m["identity_decisions"]), 1)
        self.assertEqual(len(m["identity_evidence"]), 1)
        failure = read_json(verified_file(self.w.location(self.sid), m["identity_evidence"][0]))
        self.assertIn("相互冲突", failure["error_zh"])
        self.assertEqual(len(failure["responses"]), 3)
        result = self.simulate()
        self.assertEqual(len(self.w.load(self.sid)["identity_decisions"]), 1)
        self.assertEqual(result["summary"]["身份待核验数"], 0)

    def test_no_hit_requires_explicit_limited_permission_and_failure_is_not_zero(self):
        self.payload["omit_ids"] = ["HGNC:1"]
        result = self.simulate(lambda method, params: official_response(method, params, empty=True))
        self.assertEqual(result["summary"]["本次PPI暂不采用数"], 1)
        self.assertEqual(len(result["tables"]["ppi_exclusions"]), 1)
        parent = self.w.result(self.w.load(self.sid), self.payload["expected_a03"])
        self.assertEqual(len(parent["tables"]["intersection_targets"]), 8)

    def test_new_plan_does_not_change_old_run_authorization_and_stale_apply_is_rejected(self):
        first = self.simulate()
        with self.assertRaisesRegex(ContractError, "刷新"):
            self.simulate()
        m = self.w.load(self.sid)
        run = self.w.run(m, first["run_id"])
        record = run["inputs"]["identity_authorization"]
        decision = read_json(verified_file(self.w.location(self.sid), record))
        self.assertEqual(decision["a04_run"], self.payload["expected_a04"])
        # 来源或授权指纹被篡改，校验器须阻止采用。
        bad = copy.deepcopy(run)
        bad["inputs"]["identity_authorization"]["sha256"] = "0" * 64
        with synthetic_snapshot(), self.assertRaises(ContractError):
            validator(self.root)(bad, first["summary"], first["tables"], [], first["outcome"])

    def test_request_failure_keeps_pending_and_does_not_publish_zero(self):
        def unavailable(method, params):
            if params.get("identifiers") == "TEST_ENSEMBL":
                raise ContractError("合成测试：STRING获取失败，不是无命中")
            return official_response(method, params)

        with self.assertRaisesRegex(ContractError, "获取失败"):
            self.simulate(unavailable)
        m = self.w.load(self.sid)
        self.assertEqual(m["current"]["A04"], self.payload["expected_a04"])
        self.assertEqual(
            self.w.result(m, self.payload["expected_a04"])["summary"]["身份待核验数"], 1
        )
        probe = read_json(verified_file(self.w.location(self.sid), m["identity_evidence"][0]))
        self.assertFalse(probe["completed"])
        self.assertEqual(len(probe["responses"]), 2)

    def test_empty_success_without_permission_stays_pending(self):
        result = self.simulate(lambda method, params: official_response(method, params, empty=True))
        self.assertEqual(result["summary"]["身份待核验数"], 1)
        self.assertEqual(result["summary"]["本次PPI暂不采用数"], 0)
        self.assertTrue(result["summary"]["handoff_blocked"])

    def test_recompute_keeps_applied_authorization_without_new_signature(self):
        from ppi_dispatch import run_ppi

        first = self.simulate()
        manifest = self.w.load(self.sid)
        run = self.w.run(manifest, first["run_id"])
        source = read_json(verified_file(self.w.location(self.sid), run["inputs"]["source_file"]))
        with synthetic_snapshot():
            newer = run_ppi(
                self.w,
                self.sid,
                self.payload["expected_a03"],
                first["run_id"],
                "合成再次计算保留方案",
                bundle=source,
            )
        self.assertEqual(newer["summary"]["身份待核验数"], 0)
        self.assertEqual(len(self.w.load(self.sid)["identity_decisions"]), 1)
        self.assertEqual(
            self.w.run(self.w.load(self.sid), newer["run_id"])["inputs"]["identity_authorization"],
            run["inputs"]["identity_authorization"],
        )

    def test_second_item_preserves_first_item_and_history_recomputes_independently(self):
        w, sid, payload = seed(self.root / "two-item", two_issues=True)

        def response(method, params):
            value = official_response(method, params)
            if method == "get_string_ids" and "\r" in params["identifiers"]:
                records = json.loads(value["response_text"])
                records[1]["preferredName"] = "OLDB"
                value["response_text"] = json.dumps(records)
            return value

        with (
            synthetic_snapshot(),
            patch("science_modules.a04.source_io.request", side_effect=response),
            patch("ppi_flow.time.sleep"),
        ):
            first = run_identity(w, sid, payload)
            self.assertEqual(first["summary"]["身份待核验数"], 1)
            next_payload = dict(
                payload,
                expected_a04=first["run_id"],
                expected_decision_id=payload["decision_id"],
                decision_id="decision_" + "2" * 32,
                check_ids=["HGNC:2"],
                note="合成核验第二项，保留已确认第一项",
            )
            second = run_identity(w, sid, next_payload)
            self.assertEqual(second["summary"]["身份待核验数"], 0)
            manifest = w.load(sid)
            first_run = w.run(manifest, first["run_id"])
            second_run = w.run(manifest, second["run_id"])
            decision = read_json(
                verified_file(w.location(sid), second_run["inputs"]["identity_authorization"])
            )
            self.assertEqual(decision["scope"]["check_ids"], ["HGNC:1", "HGNC:2"])
            self.assertEqual(len(manifest["identity_decisions"]), 2)
            validator(w.root)(first_run, first["summary"], first["tables"], [], first["outcome"])
            self.assertEqual(
                read_json(
                    verified_file(w.location(sid), first_run["inputs"]["identity_authorization"])
                )["scope"]["check_ids"],
                ["HGNC:1"],
            )
