# A07历史附件完整性验收；任何已知缺口必须有明确审计记录，不能静默忽略。
from hashlib import sha256  # 独立计算附件指纹。
import json  # 读取索引和审计记录。
from pathlib import Path  # 安全定位项目文件。
import unittest  # 使用标准库执行验收。


ROOT = Path(__file__).resolve().parents[1]  # 从测试文件定位独立新项目。
AUDIT = ROOT / "governance/A07历史附件指纹审计_20261001.json"  # 固定已知历史例外记录。


class ReportHistoryTests(unittest.TestCase):  # 核查全部报告修订的独立差异说明。
    def test_comparison_attachments_match_or_are_audited(self):  # 不允许出现未登记的指纹漂移。
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))  # 读取人工可查的历史审计事实。
        exceptions = {(row["report_revision"], row["recorded_sha256"], row["observed_sha256"]) for row in audit["affected_records"]}  # 建立唯一例外集合。
        observed_exceptions = set()  # 收集本次实际遇到的例外。
        for index_path in ROOT.glob("studies/*/reports/*/report_index.json"):  # 遍历所有已发布报告索引。
            index = json.loads(index_path.read_text(encoding="utf-8"))  # 读取本次修订索引。
            record = index.get("comparison_report")  # 差异说明允许为空。
            if not record:  # 没有绑定比较附件的研究不参加该项检查。
                continue  # 继续核查下一修订。
            base = index_path.parents[2] if index.get("schema_version") == "A07.report.index.3" else ROOT  # 新版以研究包为根，旧版以项目为根。
            path = base / record["path"]  # 按索引版本解析真实路径。
            self.assertTrue(path.is_file(), f"差异说明缺失：{path}")  # 文件缺失不能仅靠审计豁免。
            actual = sha256(path.read_bytes()).hexdigest()  # 独立复算SHA-256。
            if actual != record["sha256"]:  # 指纹不一致必须精确命中已知例外。
                key = (index["report_revision"], record["sha256"], actual)  # 形成不可模糊匹配的三元组。
                self.assertIn(key, exceptions, f"发现未登记的历史附件漂移：{key}")  # 新异常直接失败。
                observed_exceptions.add(key)  # 记录本次确认的已知例外。
        self.assertEqual(observed_exceptions, exceptions)  # 审计记录也不能残留已不存在的虚假例外。


if __name__ == "__main__":  # 支持单独运行本验收。
    unittest.main(verbosity=2)  # 显示检查结果。
