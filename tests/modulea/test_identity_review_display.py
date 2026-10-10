"""身份核验展示只读原值，已解决问题不生成新待办，缺证据不伪造结果。"""

import copy
import unittest
from modulea.presenters.network import present_a04


class IdentityReviewDisplayTests(unittest.TestCase):
    def test_preserves_archive_rows_and_missing_return(self):
        result = {
            "summary": {"身份待核验数": 2},
            "tables": {
                "identity_issues": [
                    {
                        "target_id": "HGNC:1",
                        "symbol": "TEST1",
                        "returned": "OTHER",
                        "reason": "返回名称需核对",
                    },
                    {
                        "target_id": "HGNC:2",
                        "symbol": "TEST2",
                        "returned": "",
                        "reason": "缺少匹配",
                    },
                ]
            },
        }
        original = copy.deepcopy(result)
        parts = present_a04(result, {})
        data = parts.special["ppi_identity"]
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["rows"][1]["returned"], "")
        self.assertEqual(data["rows"][0]["reason_zh"], "返回名称需核对")
        self.assertEqual(parts.focus[0]["source_table"], "identity_issues")
        self.assertEqual(result, original)

    def test_resolved_archive_does_not_create_new_pending_item(self):
        result = {
            "summary": {"身份待核验数": 0},
            "tables": {"identity_issues": [{"symbol": "HISTORY", "target_id": "HGNC:1"}]},
        }
        parts = present_a04(result, {})
        self.assertNotIn("ppi_identity", parts.special)
        self.assertFalse(parts.focus)

    def test_missing_detail_keeps_block_without_fake_rows(self):
        parts = present_a04({"summary": {"身份待核验数": 2}, "tables": {}}, {})
        self.assertNotIn("ppi_identity", parts.special)
        self.assertEqual(parts.focus[0]["tier"], "must_handle")
        self.assertIn("未提供", parts.focus[0]["body_zh"])


if __name__ == "__main__":
    unittest.main()
