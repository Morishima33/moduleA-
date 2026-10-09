# 有效组合热图测试：任何单对失败都不能误删其他成功组合。
from pathlib import Path  # 独立定位项目。
import sys  # 加载生产代码。
import unittest  # 检查通用排列规则。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 使用正式源码。
from docking_grouped_heatmap import groups, omission_text  # 不依赖外部科学计算。


class GroupedHeatmapTests(unittest.TestCase):  # 验证精确删图而非删研究对象。
    def test_only_failed_pair_removed_and_other_pairs_preserved(self):  # 某成分单对失败，其余成分与受体结果保留。
        generic = {'compounds': [{'compound_id': 'C1', 'name': '甲'}, {'compound_id': 'C2', 'name': '乙'}], 'receptors': [{'target': 'T1'}, {'target': 'T2'}, {'target': 'T3'}], 'completed_pairs': [{'target': 'T1', 'compound_id': 'C1', 'score_kcal_mol': -7}, {'target': 'T2', 'compound_id': 'C1', 'score_kcal_mol': -8}, {'target': 'T2', 'compound_id': 'C2', 'score_kcal_mol': -9}], 'failed_pairs': [{'target': 'T1', 'compound_id': 'C2', 'reason': '姿势未通过'}, {'target': 'T3', 'compound_id': 'C1', 'reason': '无可复算搜索盒'}, {'target': 'T3', 'compound_id': 'C2', 'reason': '无可复算搜索盒'}], 'planned_pairs': list(range(6))}  # 纯排列夹具，不用于科研。
        actual = groups(generic)  # 生产排列。
        self.assertEqual([row['target'] for row in actual], ['T1', 'T2'])  # 全失败受体不占图行。
        self.assertEqual([[pair['compound_id'] for pair in row['pairs']] for row in actual], [['C1'], ['C1', 'C2']])  # 单对失败不删完整成分列。
        self.assertEqual([pair['score_kcal_mol'] for row in actual for pair in row['pairs']], [-7, -8, -9])  # 原分数不变。
        explanation = omission_text(generic)  # 图下说明完整覆盖。
        for pair in generic['failed_pairs']:  # 每个失败都可找到。
            self.assertIn(pair['target'] + '—' + pair['compound_id'], explanation)  # 精确组合而非模糊缺库说明。
            self.assertIn(pair['reason'], explanation)  # 原因保留。


if __name__ == '__main__':  # 可独立运行。
    unittest.main()  # 执行必要检查。
