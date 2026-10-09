# 核对结合能热图的数值与颜色方向，防止后续再次画反。
import sys  # 将项目源码目录加入测试导入路径。
from pathlib import Path  # 根据测试文件位置定位项目根目录。
import unittest  # 使用标准库执行最小必要回归检查。

ROOT = Path(__file__).resolve().parents[1]  # 固定当前独立Module A项目根目录。
sys.path.insert(0, str(ROOT / 'src'))  # 让测试直接加载当前源码而不是旧项目代码。

from docking_formal import _heat_color  # 导入生产环境使用的唯一颜色函数。


class DockingHeatmapColorTests(unittest.TestCase):  # 集中验证用户确认的颜色规则。
    def test_more_negative_is_red_and_less_negative_is_blue(self):  # 最负值必须为红端，最不负值必须为蓝端。
        minimum, maximum = -10.934, -6.367  # 使用当前五乘五矩阵的真实范围。
        self.assertEqual(_heat_color(minimum, minimum, maximum), 'rgb(178,24,43)')  # 最负值对应深红。
        self.assertEqual(_heat_color(maximum, minimum, maximum), 'rgb(33,102,172)')  # 最不负值对应深蓝。
        self.assertEqual(_heat_color((minimum + maximum) / 2, minimum, maximum), 'rgb(239,169,174)')  # 中点对应浅红且不使用白色。

    def test_transition_is_continuous_without_white_anchor(self):  # 中间过渡必须连续且不出现白色锚点。
        minimum, maximum = -10.934, -6.367  # 使用当前五乘五矩阵的真实范围。
        colors = [_heat_color(minimum + (maximum - minimum) * step / 1000, minimum, maximum) for step in range(1001)]  # 密集检查整条色带。
        self.assertNotIn('rgb(247,247,247)', colors)  # 全范围不得再出现旧白色中点。
        for left, right in zip(colors, colors[1:]):  # 逐对核对相邻采样颜色没有跳变。
            left_rgb = [int(value) for value in left[4:-1].split(',')]  # 解析左侧RGB。
            right_rgb = [int(value) for value in right[4:-1].split(',')]  # 解析右侧RGB。
            self.assertLessEqual(max(abs(a - b) for a, b in zip(left_rgb, right_rgb)), 3)  # 每千分之一步的通道变化保持平滑。


if __name__ == '__main__':  # 允许单独双击或命令行运行本检查。
    unittest.main()  # 交由标准测试运行器汇报结果。
