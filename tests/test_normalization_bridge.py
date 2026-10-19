"""新版范围保存到标准化的回归：使用虚构研究，保留版本和人工关口。"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_normalization as fixtures
from contracts import ContractError
from disease import run_disease
from modulea.core.normalization_bridge import bindings, context, execute, preview_path, validate
from modulea.core.status import map_state


class NormalizationBridgeTests(unittest.TestCase):
    """复用既有可手算基因夹具，验证衔接而非重写标准化规则。"""
    def setUp(self):
        self.fixture = fixtures.NormalizationTests()
        self.fixture.setUp()
        self.flow, self.sid = self.fixture.flow, self.fixture.sid
        self.settings = SimpleNamespace(runtime_dir=self.fixture.root / "runtime")

    def tearDown(self):
        self.fixture.tearDown()

    def decide(self, all_outside=False):
        """模拟用户完整保存范围，绝不对真实研究操作。"""
        m = self.flow.load(self.sid)
        r = self.flow.result(m, m["current"]["A02"])
        decisions = [dict(scope_id=g["scope_id"], scope="outside" if all_outside or g["disease_term"] != "COPD" else "direct", reviewer="test", note="合成范围决定") for g in r["tables"]["scope_groups"]]
        return run_disease(self.flow, self.sid, m["current"]["A00"], m["current"]["A02"], [], "虚构范围保存", scope_change=decisions)

    def payload(self, action="preview", **kwargs):
        return dict(bindings(self.flow.load(self.sid)), action=action, **kwargs)

    def test_pending_scope_cannot_be_silently_included(self):
        with self.assertRaisesRegex(ContractError, "待核验"):
            execute(self.settings, self.flow, self.sid, self.payload())
        m = self.flow.load(self.sid)
        info = context(self.flow, m, self.flow.result(m, m["current"]["A02"]), self.settings)
        self.assertFalse(info["enabled"])

    def test_all_excluded_reaches_reviewable_empty_without_approval(self):
        self.decide(True)
        before = self.flow.load(self.sid)
        _, pre = execute(self.settings, self.flow, self.sid, self.payload())
        self.assertEqual(self.flow.load(self.sid), before)
        self.assertEqual(pre["modules"][1]["summary"]["标准化基因数"], 0)
        _, made = execute(self.settings, self.flow, self.sid, self.payload("publish", stamp=pre["stamp"], reviewer="test", note="明确全排除的合成测试", confirmed=True, accept_omit=False, accept_source_exception=False))
        result = made["A02"]
        self.assertFalse(result["summary"]["handoff_blocked"])
        self.assertEqual(result["outcome"], "empty")
        state = map_state("A02", {"state": "awaiting_review", "result": result})
        self.assertEqual(state.code, "empty")
        after = self.flow.load(self.sid)
        self.assertEqual(after["reviews"], before["reviews"])
        self.assertNotIn("A03", after["current"])
        self.assertFalse(self.flow.approved(after, result["run_id"]))
        self.assertIsNone(context(self.flow, after, result, self.settings))

    def test_identity_exception_requires_explicit_omission(self):
        self.decide()
        _, pre = execute(self.settings, self.flow, self.sid, self.payload())
        before = self.flow.load(self.sid)
        payload = self.payload("publish", stamp=pre["stamp"], reviewer="test", note="仅测试", confirmed=True, accept_omit=False, accept_source_exception=False)
        with self.assertRaisesRegex(ContractError, "身份问题"):
            execute(self.settings, self.flow, self.sid, payload)
        self.assertEqual(self.flow.load(self.sid), before)
        payload["accept_omit"] = True
        _, made = execute(self.settings, self.flow, self.sid, payload)
        self.assertEqual(made["A02"]["summary"]["标准化基因数"], 1)
        self.assertFalse(made["A02"]["summary"]["handoff_blocked"])

    def test_scope_can_be_revised_after_publishing_empty_normalized_result(self):
        """已生成空标准化集合仍能按原入口修订范围，旧版本和批准不自动迁移。"""
        from modulea.core.disease_scope import context as scope_context, review_scope
        self.decide(True)
        _, pre = execute(self.settings, self.flow, self.sid, self.payload())
        _, made = execute(self.settings, self.flow, self.sid, self.payload("publish", stamp=pre["stamp"], reviewer="test", note="合成全排除", confirmed=True, accept_omit=False, accept_source_exception=False))
        manifest = self.flow.load(self.sid)
        old = made["A02"]
        info = scope_context(self.flow, manifest, old, True)
        decisions = [{"scope_id": row["scope_id"], "scope": "direct" if row["disease_term"] == "COPD" else "outside"} for row in info["items"]]
        candidate = review_scope(self.flow, self.sid, {"expected_a00": manifest["current"]["A00"], "expected_run": old["run_id"], "decisions": decisions, "reviewer": "test", "note": "合成纠正范围", "confirmed": True})
        self.assertNotIn("标准化基因数", candidate["summary"])
        _, preview = execute(self.settings, self.flow, self.sid, self.payload())
        self.assertEqual(preview["modules"][1]["summary"]["标准化基因数"], 1)
        after = self.flow.load(self.sid)
        self.assertIn(old["run_id"], after["runs"])
        self.assertEqual(after["reviews"], manifest["reviews"])
        self.assertNotIn("A03", after["current"])

    def test_stale_input_and_other_study_preview_are_rejected(self):
        self.decide()
        payload = self.payload()
        execute(self.settings, self.flow, self.sid, payload)
        self.decide(True)
        with self.assertRaisesRegex(ContractError, "版本已改变"):
            validate(self.flow, self.sid, payload)
        m = self.flow.load(self.sid)
        info = context(self.flow, m, self.flow.result(m, m["current"]["A02"]), self.settings)
        self.assertIsNone(info["preview"])
        execute(self.settings, self.flow, self.sid, self.payload())
        path = preview_path(self.settings, self.sid)
        cached = json.loads(path.read_text(encoding="utf-8"))
        cached["study_id"] = "study_" + "f" * 32
        path.write_text(json.dumps(cached), encoding="utf-8")
        self.assertIsNone(context(self.flow, m, self.flow.result(m, m["current"]["A02"]), self.settings)["preview"])

    def test_precise_candidate_reason_and_readonly_gate(self):
        result = self.decide(True)
        state = map_state("A02", {"state": "awaiting_review", "result": result})
        self.assertIn("范围决定已保存", state.reason_zh)
        m = self.flow.load(self.sid)
        self.assertFalse(context(self.flow, m, result, self.settings, busy=True)["enabled"])
        self.flow.set_trashed(self.sid, True, "test", "测试回收站", None)
        with self.assertRaisesRegex(ContractError, "回收站"):
            validate(self.flow, self.sid, self.payload())

    def test_unchanged_approved_formula_side_is_preserved(self):
        self.decide()
        _, pre = execute(self.settings, self.flow, self.sid, self.payload())
        _, made = execute(self.settings, self.flow, self.sid, self.payload("publish", stamp=pre["stamp"], reviewer="test", note="合成初始身份决定", confirmed=True, accept_omit=True, accept_source_exception=False))
        for result in made.values():
            self.flow.review(self.sid, result["run_id"], "approved", "test", "合成研究明确复核")
        a01 = self.flow.load(self.sid)["current"]["A01"]
        self.decide(True)
        _, pre = execute(self.settings, self.flow, self.sid, self.payload())
        _, made = execute(self.settings, self.flow, self.sid, self.payload("publish", stamp=pre["stamp"], reviewer="test", note="合成疾病范围变更", confirmed=True, accept_omit=False, accept_source_exception=False))
        self.assertEqual(made["A01"]["run_id"], a01)
        self.assertTrue(self.flow.approved(self.flow.load(self.sid), a01))

    def test_api_versions_and_explicit_preview_guard(self):
        from modulea.api.server import App
        from modulea.api.errors import ApiError
        from modulea.config import Settings
        from unittest.mock import patch
        self.decide(True)
        app = App(Settings(data_root=self.fixture.root, runtime_dir=self.settings.runtime_dir))
        payload = self.payload()
        request = SimpleNamespace(json=lambda: payload)
        with patch.object(app.tasks, "submit", return_value=({"task_id": "test", "state": "queued"}, True)) as submit:
            reply, status = app.post_normalization(request, self.sid)
            self.assertEqual(status, 202)
            self.assertEqual(submit.call_args.args[1], "normalization_preview")
        payload["expected_a01"] = "run_" + "f" * 32
        with self.assertRaises(ApiError) as error:
            app.post_normalization(request, self.sid)
        self.assertEqual(error.exception.status, 409)
        payload = self.payload("publish", stamp="not_a_current_preview", reviewer="test", note="test", confirmed=True, accept_omit=False, accept_source_exception=False)
        with self.assertRaises(ApiError) as error:
            app.post_normalization(request, self.sid)
        self.assertEqual(error.exception.status, 409)

    def test_missing_reference_is_reported_before_task_execution(self):
        result = self.decide(True)
        (self.fixture.root / "references/hgnc_complete_set_20260913.json").unlink()
        info = context(self.flow, self.flow.load(self.sid), result, self.settings)
        self.assertFalse(info["enabled"])
        self.assertIn("缺少公共基因身份参考文件", info["disabled_reason_zh"])
        before = self.flow.load(self.sid)
        with self.assertRaisesRegex(ContractError, "hgnc_complete_set_20260913.json"):
            execute(self.settings, self.flow, self.sid, self.payload())
        self.assertEqual(self.flow.load(self.sid), before)

    def test_current_preview_changes_hint_without_unlocking_review(self):
        from modulea.api.server import App
        from modulea.config import Settings
        self.decide(True)
        execute(self.settings, self.flow, self.sid, self.payload())
        app = App(Settings(data_root=self.fixture.root, runtime_dir=self.settings.runtime_dir))
        view = app.views.module(self.sid, "A02")
        self.assertIn("身份预览已完成", view["review"]["blocked_reason_zh"])
        self.assertNotIn("approved", view["review"]["allowed_decisions"])
        self.decide(True)
        view = app.views.module(self.sid, "A02")
        self.assertNotIn("身份预览已完成", view["review"]["blocked_reason_zh"])


if __name__ == "__main__":
    unittest.main()
