# P2Rank口袋适配器测试；核对残基包络和每侧5 Å外扩。
from pathlib import Path  # 定位源码。
import sys  # 加载当前模块。
import unittest  # 执行测试。

ROOT = Path(__file__).resolve().parents[1]  # 取得项目根目录。
sys.path.insert(0, str(ROOT / "src"))  # 只导入本轮源码。

from docking_p2rank import box_from_prediction  # 测试不依赖联网或Java的纯计算部分。


def atom(serial, name, residue, chain, number, x, y, z, element):  # 生成固定列PDB蛋白原子。
    return f"ATOM  {serial:5d} {name:^4s} {residue:>3s} {chain}{number:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00          {element:>2s}"  # 保持链和残基列位置。


class P2RankBoxTest(unittest.TestCase):  # 搜索盒必须可由保存的输入重算。
    def test_adjacent_residue_envelope_plus_five_angstrom(self):  # 两个口袋残基决定三维包络。
        pdb = "\n".join([atom(1, "CA", "ALA", "A", 10, 1.0, 2.0, 3.0, "C"), atom(2, "CB", "ALA", "A", 10, 4.0, 6.0, 8.0, "C"), atom(3, "CA", "GLY", "A", 11, -1.0, 5.0, 9.0, "C"), atom(4, "CA", "GLY", "B", 12, 99.0, 99.0, 99.0, "C")])  # B链原子不应进入盒子。
        prediction = {"residue_ids": "A_10 A_11", "center_x": "2.0", "center_y": "4.0", "center_z": "6.0"}  # 使用P2Rank常见残基格式。
        box = box_from_prediction(pdb, prediction, 5.0)  # 应用批准规则。
        self.assertEqual(box["center"], [1.5, 4.0, 6.0])  # 中心来自口袋原子包络。
        self.assertEqual(box["size"], [15.0, 14.0, 16.0])  # 三轴均在两侧各外扩5 Å。
        self.assertEqual(box["adjacent_residue_count"], 2)  # 保存可追溯残基数。


if __name__ == "__main__":  # 支持独立运行。
    unittest.main(verbosity=2)  # 输出检查结果。
