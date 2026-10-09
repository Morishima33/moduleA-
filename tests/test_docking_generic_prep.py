# A06通用筛查规则检查；确认不会跳过高位未决靶点或退回固定五成分。
from pathlib import Path  # 定位项目源码。
import sys  # 加载当前项目模块。
import unittest  # 使用标准测试框架。

ROOT = Path(__file__).resolve().parents[1]  # 取得独立项目根目录。
sys.path.insert(0, str(ROOT / "src"))  # 测试生产代码。

from docking_generic_prep import _screen_rows  # 直接检查纯排序规则。


class GenericDockingPrepTests(unittest.TestCase):  # 通用自动化必须保留人工决定边界。
    def test_screen_keeps_unresolved_higher_ranked_candidates(self):  # 不能为了凑五个历史受体跳过前列对象。
        symbols = ["TP53", "JUN", "AKT1", "TNF", "HSP90AA1", "IL6", "ESR1", "IL1B", "BCL2", "MAPK1"]  # 模拟当前真实排序窗口。
        round1 = [{"symbol": symbol, "target_id": "HGNC:" + str(index), "degree": 100 - index} for index, symbol in enumerate(symbols, 1)]  # 构造严格递减Degree。
        library = {symbol: {"pdb": symbol + "1", "rmsd_angstrom": 1.0} for symbol in ("AKT1", "TNF", "HSP90AA1", "ESR1", "MAPK1")}  # 五项历史技术线索。
        rows = _screen_rows(round1, library)  # 生成连续筛查窗口。
        self.assertEqual([row["symbol"] for row in rows], symbols)  # TP53、JUN、IL6、IL1B、BCL2均不得消失。
        self.assertEqual(sum(bool(row["historical_pdb"]) for row in rows), 5)  # 窗口在第五项线索出现后停止。
        self.assertTrue(all(row["decision"] == "pending_manual_confirmation" for row in rows))  # 程序不得自动签署最终受体。

    def test_degree_ties_are_marked(self):  # PPI同分候选须提示并列而不是伪造唯一顺序。
        round1 = [{"symbol": "A", "target_id": "HGNC:1", "degree": 8}, {"symbol": "B", "target_id": "HGNC:2", "degree": 8}, {"symbol": "C", "target_id": "HGNC:3", "degree": 7}]  # A与B并列。
        library = {symbol: {"pdb": symbol + "1", "rmsd_angstrom": 1.0} for symbol in ("A", "B", "C")}  # 三项均有线索但不足五项。
        with self.assertRaisesRegex(Exception, "尚无可复用技术线索|A04"):  # 本断言占位防止误读。
            _screen_rows([], library)  # 空PPI必须停止。
        rows = _screen_rows(round1, library)  # 非空列表可以生成窗口。
        self.assertTrue(rows[0]["degree_tie"] and rows[1]["degree_tie"])  # 两个并列对象均有提示。
        self.assertEqual(rows[0]["ppi_order"], rows[1]["ppi_order"])  # 并列对象不能显示成两个唯一名次。

    def test_tenth_boundary_ties_are_all_kept(self):  # 第十位边界并列必须全部进入核查窗口。
        degrees = [30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 21, 20]  # 第十和第十一条同为21。
        round1 = [{"symbol": f"G{index}", "target_id": f"HGNC:{index}", "degree": degree} for index, degree in enumerate(degrees, 1)]  # 构造十二条排序数据。
        rows = _screen_rows(round1, {})  # 不依赖历史结构线索决定窗口。
        self.assertEqual(len(rows), 11)  # 同分第十一条必须保留，更低第十二条必须排除。
        self.assertEqual([row["symbol"] for row in rows[-2:]], ["G10", "G11"])  # 边界并列身份保持原顺序。
        self.assertTrue(rows[-1]["degree_tie"])  # 页面必须提示并列。


if __name__ == "__main__":  # 支持独立运行。
    unittest.main(verbosity=2)  # 输出每项检查结果。
