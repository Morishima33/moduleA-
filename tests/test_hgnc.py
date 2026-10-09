# HGNC核对测试使用虚构身份，避免把测试当科研结果。
import sys  # 引用新项目内核。
import unittest  # 验证身份边界。
from pathlib import Path  # 稳定定位代码。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不依赖旧项目。
from hgnc import HgncMap  # 测试真实映射函数。

class MappingTests(unittest.TestCase):  # 歧义不能静默消失。
    def setUp(self):  # 构造共享别名与一致编号。
        raw = "hgnc_id\tsymbol\tprev_symbol\talias_symbol\tensembl_gene_id\tuniprot_ids\tstatus\nHGNC:1\tA\tOLD\tSHARED\tENSG1\tP1\tApproved\nHGNC:2\tB\t\tSHARED\tENSG2\tP2\tApproved\n"  # 保留完整必要列。
        self.mapping = HgncMap(raw.encode())  # 固定测试快照。
    def test_unique(self):  # 标准名、旧名及明确一致ID。
        self.assertEqual(self.mapping.resolve("OLD", "ENSG1", "P1")["target_id"], "HGNC:1")  # 唯一旧名自动归一。
    def test_ambiguity(self):  # 共享别名不能擅自选择。
        self.assertEqual(self.mapping.resolve("SHARED")["status"], "ambiguous_or_conflicting")  # 两个候选保留。
    def test_conflict(self):  # 名称与稳定ID不一致。
        self.assertEqual(self.mapping.resolve("A", "ENSG2")["target_id"], "")  # 冲突不进入标准表。
    def test_current_symbol_corroborated(self):  # 当前标准名也是另一基因别名时需要稳定编号支持。
        self.mapping.index[("alias_symbol", "A")].add("HGNC:2")  # 构造真实类型的别名碰撞。
        self.assertEqual(self.mapping.resolve("A")["status"], "matched")  # 用户批准无编号反证时标准名优先。
        self.mapping.rule = "HGNC.resolve.2"  # 历史版本仍能复算。
        self.assertEqual(self.mapping.resolve("A")["status"], "ambiguous_or_conflicting")  # 旧规则行为保持。
        self.mapping.rule = "HGNC.resolve.3"  # 恢复新规则。
        found = self.mapping.resolve("A", "ENSG1", "P1")  # 所有明确编号一致。
        self.assertEqual(found["target_id"], "HGNC:1")  # 应用用户批准规则。
        self.assertEqual(found["candidate_ids"], "HGNC:1|HGNC:2")  # 原有候选没有丢失。
        self.assertEqual(found["mapping_method"], "approved_symbol_and_stable_id")  # 来源规则可追溯。
        self.assertEqual(self.mapping.resolve("A", "ENSG1", "P2")["target_id"], "")  # 编号冲突仍不通过。
        self.assertEqual(self.mapping.resolve("A", uniprot="MISSING")["target_id"], "")  # 编号未找到仍不通过。

    def test_unknown_and_case(self):  # 不猜缺失字段或全部转大写。
        self.assertEqual(self.mapping.resolve("a")["status"], "unmapped")  # 原大小写保留。
        self.assertNotEqual(self.mapping.resolve("UNKNOWN", "ENSG1")["status"], "matched")  # 未确认名称仍需核对。

if __name__ == "__main__":  # 独立运行检查。
    unittest.main(verbosity=2)  # 显示实际检查结果。
