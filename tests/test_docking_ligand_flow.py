# 配体准备与组合清单的必要边界检查；不使用真实病例作断言。
import unittest  # 使用标准测试框架。
from contracts import ContractError  # 检查明确阻断。
from docking_ligand_flow import check_ligand_coordinates, combination_plan  # 测试实际实现。


class LigandFlowTests(unittest.TestCase):  # 覆盖配体坐标和组合分类的关键风险。
    def test_combination_count_and_relation(self):  # 组合数及证据分类必须由输入决定。
        ligands = [{'compound_id': 'C1', 'name': '甲'}, {'compound_id': 'C2', 'name': '乙'}]  # 两个虚构成分。
        receptors = [{'target_id': 'T1', 'symbol': '靶一', 'pdb': '1ABC', 'chains': 'A'}, {'target_id': 'T2', 'symbol': '靶二', 'pdb': '2ABC', 'chains': 'B'}]  # 两个虚构受体。
        evidence = [{'compound_id': 'C1', 'target_id': 'T1', 'source_ref': 'source:1'}]  # 只有一组有上游记录。
        pairs = combination_plan(ligands, receptors, evidence)  # 形成完整二维清单。
        self.assertEqual(len(pairs), 4)  # 不能因无记录而删掉探索组合。
        self.assertEqual(sum(x['relation'] == 'upstream_record' for x in pairs), 1)  # 仅真实记录标为上游支持。
        self.assertTrue(all(x['status'] == 'not_run' and x['score_kcal_mol'] is None and x['search_box'] is None for x in pairs))  # 不生成假分数或盒子。

    def test_duplicate_objects_are_rejected(self):  # 重复对象会造成计划数与热图歧义。
        ligands = [{'compound_id': 'C1', 'name': '甲'}, {'compound_id': 'C1', 'name': '甲重复'}]  # 故意重复稳定编号。
        receptors = [{'target_id': 'T1', 'symbol': '靶一', 'pdb': '1ABC', 'chains': 'A'}]  # 保持受体正常。
        with self.assertRaises(ContractError):  # 不自动去重掩盖问题。
            combination_plan(ligands, receptors, [])  # 调用真实入口。

    def test_ligand_mapping_detects_changed_coordinates(self):  # 原子映射存在也不能接受坐标改变。
        sdf = '''test
  RDKit          3D

  1  0  0  0  0  0  0  0  0  0999 V2000
    1.0000    2.0000    3.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
M  END
$$$$
'''  # 一个虚构三维碳原子。
        atom = 'ATOM      1  C   UNL     1       9.000   2.000   3.000  1.00  0.00    +0.000 C\n'  # x坐标被改动。
        pdbqt = 'REMARK INDEX MAP 1 1\n' + atom  # 映射字段形式正确。
        with self.assertRaises(ContractError):  # 坐标改变仍须阻断。
            check_ligand_coordinates(sdf, pdbqt)  # 使用实际质量检查。


if __name__ == '__main__':  # 支持独立运行。
    unittest.main(verbosity=2)  # 输出每项真实结果。
