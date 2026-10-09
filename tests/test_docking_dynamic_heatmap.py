# A06动态热图测试；核对矩阵方向、PPI顺序和NA语义。
from pathlib import Path  # 定位当前项目源码。
import sys  # 加载独立项目模块。
import unittest  # 执行可重复检查。

ROOT = Path(__file__).resolve().parents[1]  # 取得暂存项目根目录。
sys.path.insert(0, str(ROOT / "src"))  # 只测试本轮代码。

from docking_dynamic_heatmap import _matrix  # 读取不依赖绘图库的矩阵构造函数。


class DynamicHeatmapTest(unittest.TestCase):  # 动态矩阵不得写死五乘五。
    def test_receptors_are_rows_and_missing_pair_is_na(self):  # 核对十行七列方向和真实空值。
        compounds = [{"compound_id": f"C{index}", "name": f"成分{index}"} for index in range(1, 8)]  # 建立七个成分。
        receptors = [{"target": f"G{index}"} for index in range(1, 11)]  # 建立十个按PPI顺序的受体。
        completed = [{"compound_id": compound["compound_id"], "target": receptor["target"], "score_kcal_mol": -6.0} for receptor in receptors for compound in compounds]  # 形成完整七十格。
        completed.pop()  # 最后一格模拟真实失败。
        generic = {"compounds": compounds, "receptors": receptors, "completed_pairs": completed}  # 仅传入矩阵函数需要的事实。
        actual_compounds, actual_receptors, rows = _matrix(generic)  # 构建受体行、成分列矩阵。
        self.assertEqual(len(actual_compounds), 7)  # 列数来自成分数。
        self.assertEqual(len(actual_receptors), 10)  # 行数来自受体数。
        self.assertEqual([row["target"] for row in rows], [f"G{index}" for index in range(1, 11)])  # 不按分值重新排序。
        self.assertIsNone(rows[-1]["values"][-1])  # 失败组合保持NA来源的None。


if __name__ == "__main__":  # 支持单文件运行。
    unittest.main(verbosity=2)  # 输出检查结果。
