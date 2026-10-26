"""研究级追溯摘要、JSON和CSV导出；使用隔离虚构研究，不访问真实资料。"""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from modulea.core.trace_export import build_trace, trace_csv, trace_file_json
from workflow import Workflow
from contracts import ContractError


class TraceExportTests(unittest.TestCase):
    """导出必须绑定当前研究、保留运行关系并在文件篡改时阻断。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="modulea_trace_")
        root = Path(self.temp.name)
        self.workflow = Workflow(root / "data", {})
        self.sid = self.workflow.create({"formula": "虚构追溯方", "herbs": "虚构药", "disease": "虚构病",
                                         "disease_scope": "仅本病", "operator": "隔离测试", "species": 9606}, kind="contract_test")
        a00 = self.workflow.load(self.sid)["current"]["A00"]
        self.workflow.review(self.sid, a00, "approved", "隔离测试", "允许A01")
        run = self.workflow.begin(self.sid, "A01", {"source": "fixture"}, {"threshold": 30}, "隔离测试")
        self.workflow.finish(self.sid, run["run_id"], {"records": 2}, {"components": [{"id": "C1"}, {"id": "C2"}]}, ["fixture evidence"], "success")

    def tearDown(self):
        self.temp.cleanup()

    def test_summary_and_exports_are_current_read_only_and_downloadable(self):
        before = hashlib.sha256((self.workflow.location(self.sid) / "manifest.json").read_bytes()).hexdigest()
        summary = build_trace(self.workflow, self.sid, include_data=False)
        self.assertTrue(summary["read_only"])
        self.assertEqual(summary["study_id"], self.sid)
        self.assertEqual({row["module_id"] for row in summary["modules"]}, {"A00", "A01", "A02", "A03", "A03_SELECT", "A04", "A05", "A06_PREP", "A06", "A07"})
        a01 = next(row for row in summary["modules"] if row["module_id"] == "A01")
        self.assertEqual(a01["state"], "completed")
        self.assertEqual(a01["result"]["summary"]["records"], 2)
        exported = json.loads(trace_file_json(build_trace(self.workflow, self.sid, include_data=True)))
        self.assertEqual(exported["study_id"], self.sid)
        self.assertTrue(exported["read_only"])
        self.assertTrue(any(row["path"].endswith("run.json") for row in exported["files"]))
        exported_a01 = next(row for row in exported["modules"] if row["module_id"] == "A01")
        self.assertEqual(exported_a01["result"]["tables"]["components"][0]["id"], "C1")
        self.assertEqual(hashlib.sha256((self.workflow.location(self.sid) / "manifest.json").read_bytes()).hexdigest(), before)

        csv_text = trace_csv(exported).decode("utf-8-sig")
        self.assertIn("study_id,module_id,run_id,table_name,row_index,record_json", csv_text)
        self.assertIn("__summary__", csv_text)
        self.assertIn(self.sid, csv_text)

    def test_tampered_registered_file_blocks_all_trace_exports(self):
        manifest_path = self.workflow.location(self.sid) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = manifest["current"]["A01"]
        result_ref = manifest["runs"][run_id]["result_file"]
        result_path = self.workflow.location(self.sid) / result_ref["path"]
        result_path.write_bytes(result_path.read_bytes() + b"tamper")
        with self.assertRaises(ContractError):
            build_trace(self.workflow, self.sid, include_data=True)

    def test_cross_study_trace_is_isolated(self):
        other = self.workflow.create({"formula": "另一个方", "herbs": "另一个药", "disease": "另一个病",
                                      "disease_scope": "仅本病", "operator": "隔离测试", "species": 9606}, kind="contract_test")
        self.assertEqual(build_trace(self.workflow, other)["study_id"], other)


if __name__ == "__main__":
    unittest.main()
