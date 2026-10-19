"""官方分类筛选、疾病身份保护与修订边界，只使用隔离合成研究。"""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from contracts import ContractError
from science_modules.a05 import screening, compact_flow, display
from modulea.core.enrichment_workflow import EnrichmentWorkflow, display_context
from tests.test_a05_display import DisplayWorkflowTests


class ScreeningClassificationTests(unittest.TestCase):
    # 官方固定分类包含癌症总览和耐药，不能再以共享机制为由漏掉。
    def test_official_categories_and_cancer_mechanisms(self):
        ids = ["hsa05215", "hsa05235", "hsa05205", "hsa05207", "hsa01521", "hsa04668", "hsa04657", "hsa00010", "hsa99999"]
        rows = [{"ID": tid, "Description": "archived name"} for tid in ids]
        screen = screening.snapshot(rows, {"mesh_id": "TEST", "mesh_term": "Synthetic disease", "mesh_verification": {"status": "verified", "mesh_id": "TEST", "preferred_term": "Synthetic disease", "entry_terms": []}})
        assessments = screen["assessments"]
        self.assertEqual(set(screening.proposals(screen)), set(ids[:5]))
        self.assertTrue(all(assessments[tid]["classification_status"] == "retain" for tid in ids[5:8]))
        self.assertEqual(assessments[ids[-1]]["classification_status"], "uncertain")
        self.assertIn("癌症", assessments["hsa05235"]["classification_zh"])

    # 本病及精确同义词受到保护；同器官其他病、亚型和缺身份不能模糊放行。
    def test_current_disease_aliases_and_uncertainty(self):
        cat = {"pathways": {"00001": [{"category": "Human Diseases", "subcategory": "test", "name": "Synthetic asthma"}], "00002": [{"category": "Human Diseases", "subcategory": "test", "name": "Other lung disease"}], "00003": [{"category": "Human Diseases", "subcategory": "test", "name": "Severe Synthetic asthma"}]}}
        rows = [{"ID": "hsa" + number, "Description": value[0]["name"]} for number, value in cat["pathways"].items()]
        identity = {"verified": True, "names": ["synthetic asthma"]}
        statuses = screening.assess(rows, cat, identity)
        self.assertEqual([statuses[r["ID"]]["classification_status"] for r in rows], ["retain", "exclude", "uncertain"])
        self.assertTrue(all(r["classification_status"] == "uncertain" for r in screening.assess(rows, cat, {"verified": False, "names": []}).values()))
        self.assertFalse(screening.disease_identity({"mesh_id": "X", "mesh_verification": {"status": "verified", "mesh_id": "Y"}})["verified"])


class ScreeningWorkflowTests(DisplayWorkflowTests):
    # 通过真实接口确认额外全排除字段不会在提交后台前丢失。
    def test_all_exclusion_api_requires_and_preserves_consent(self):
        import http.client
        import threading
        from modulea.api.server import create_server
        from modulea.config import load_settings
        server, app = create_server(load_settings(data_root=self.root_case, runtime_dir=self.root_case.parent / "api-runtime"), 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        payload = self.payload(ids=[row["ID"] for row in self.base["tables"]["kegg_significant"]])
        payload.pop("exclude_all_confirmed")
        def call(body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
            connection.request("POST", f"/api/v1/studies/{self.sid}/modules/A05/actions/display_confirmation", json.dumps(body), {"Content-Type": "application/json", "X-ModuleA-Token": app.token})
            response = connection.getresponse()
            status, result = response.status, json.loads(response.read())
            connection.close()
            return status, result
        try:
            status, error = call(payload)
            self.assertEqual(status, 409, error)
            self.assertEqual(error["error"]["code"], "GATE_BLOCKED")
            self.assertIn("单独确认全部排除", error["error"]["message_zh"])
            with patch.object(app.tasks, "_spawn"):
                status, result = call(dict(payload, exclude_all_confirmed=True))
            self.assertEqual(status, 202)
            task = app.tasks._raw(result["task"]["task_id"])
            self.assertTrue(json.loads(task["payload"])["exclude_all_confirmed"])
        finally:
            server.shutdown()
            server.server_close()

    # 从已确认旧展示追加候选，原统计和历史保持；新范围不能沿用旧签名。
    def test_refresh_requires_confirmation_and_preserves_statistics(self):
        self.w = EnrichmentWorkflow(self.root_case, {"A05": compact_flow.validator(self.root_case)})
        old = compact_flow.apply_confirmation(self.w, self.sid, self.payload())
        old = compact_flow.apply_confirmation(self.w, self.sid, self.payload("layout"))
        self.w.review(self.sid, old["run_id"], "approved", "合成核验人", "仅自测")
        before = deepcopy(self.w.load(self.sid))
        new = compact_flow.refresh_screening(self.w, self.sid, old["run_id"])
        m = self.w.load(self.sid)
        meta = display.metadata(new["tables"])
        self.assertFalse(meta["exclusions_confirmed"])
        self.assertFalse(meta["layout_confirmed"])
        self.assertEqual(meta["excluded_ids"], [])
        self.assertEqual(before["reviews"], m["reviews"])
        self.assertEqual(self.w.result(m, old["run_id"]), old)
        for key, value in self.base["tables"].items():
            self.assertEqual(new["tables"][key], value)
        info = display_context(self.w, m, self.w.run(m, new["run_id"]), new, False, False)
        self.assertEqual(info["screening"]["version"], screening.VERSION)
        self.assertEqual(info["screening"]["uncertain_count"], len(self.base["tables"]["kegg_significant"]))
        with self.assertRaises(ContractError):
            compact_flow.refresh_screening(self.w, self.sid, new["run_id"])
        with self.assertRaises(ContractError):
            compact_flow.refresh_screening(self.w, self.sid, old["run_id"])
        self.assertEqual(self.w.load(self.sid), m)

    # 自动接续的prepare无外部候选时也必须生成分类快照，不再默认为空建议来源。
    def test_prepare_generates_snapshot_and_all_exclusion_needs_extra_consent(self):
        p = self.payload(ids=[row["ID"] for row in self.base["tables"]["kegg_significant"]])
        p.pop("exclude_all_confirmed")
        with self.assertRaises(ContractError):
            self.w.validate_display_confirmation(self.sid, p)
        p["exclude_all_confirmed"] = True
        self.w.validate_display_confirmation(self.sid, p)
        m = self.w.load(self.sid)
        rid = self.base["run_id"]
        m["current"]["A05"] = rid
        # 截获发布以核对自动prepare的数据流，不伪造真实研究统计。
        with patch.object(compact_flow, "publish", return_value="prepared") as publish, patch.object(self.w, "load", return_value=m), patch.object(self.w, "active", return_value=True):
            self.assertEqual(compact_flow.prepare(self.w, self.sid, rid), "prepared")
            self.assertIn("screening", publish.call_args.args[4])
            self.assertIn("screening_a00", publish.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
