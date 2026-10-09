# A06_PREP候选包完整性检查；确认配置生成没有越过人工关口。
import sys  # 加载新项目代码。
import unittest  # 使用标准测试框架。
from pathlib import Path  # 定位当前项目和研究包。
ROOT = Path(__file__).resolve().parents[1]  # 不访问旧Kimi目录。
sys.path.insert(0, str(ROOT / 'src'))  # 使用生产加载与指纹规则。
from docking_ui import load_preview  # 检查网页实际读取的数据。
from workflow import Workflow  # 复用统一研究索引。


class PreparationPackageTests(unittest.TestCase):  # 当前候选包必须可复核且不可直接执行。
    @classmethod  # 只读数据只需加载一次。
    def setUpClass(cls):  # 读取当前研究和候选包。
        cls.study_id = 'study_28a9580bd87543c98892e3c7ce4d1426'  # 本次COPD流程测试研究。
        cls.workflow = Workflow(ROOT)  # 不注册科学运行器，避免测试触发模块运行。
        cls.plan = load_preview(cls.workflow, cls.study_id)  # 同网页一样验证全部嵌套指纹。
        cls.package = cls.plan['preparation_package_data']  # 使用唯一当前指针。

    def test_counts_and_approved_box_values(self):  # 盒子和计划数量须与用户批准完全一致。
        self.assertEqual(self.package['counts'], {'approved_boxes': 3, 'pose_integrity_rules': 7, 'reference_ligands_prepared': 3, 'redocking_planned': 3, 'redocking_completed': 0, 'formal_planned': 15, 'formal_completed': 0})  # 摘要不能少项。
        boxes = {row['symbol']: (row['center_angstrom'], row['size_angstrom']) for row in self.package['approved_boxes']}  # 按受体核对具体值。
        self.assertEqual(boxes['AKT1'], ([9.657, -7.761, 10.604], [17.712, 25.771, 22.332]))  # AKT1使用IQO包络。
        self.assertEqual(boxes['HSP90AA1'], ([41.067, -46.782, 65.505], [18.676, 19.013, 17.495]))  # HSP90AA1使用GDM包络。
        self.assertEqual(boxes['MAPK1'], ([6.487, -3.734, 17.175], [20.033, 14.602, 17.358]))  # MAPK1使用FRZ包络。

    def test_candidate_package_remains_immutable_after_later_execution(self):  # 后续发布和执行不得回写历史候选包。
        manifest = self.workflow.load(self.study_id)  # 读取当前正式研究索引。
        self.assertNotEqual(manifest['current']['A06_PREP'], self.package['run_id'])  # 标准准备结果使用新运行，不把候选目录冒充模块结果。
        self.assertIn('A06', manifest['current'])  # 当前研究已经按后续授权形成正式结果。
        self.assertFalse(self.package['published'])  # 仍待整体复核。
        self.assertFalse(self.package['execution_authorized'])  # 没有Vina执行许可。
        self.assertFalse(self.package['vina_invoked'])  # 记录明确为零次调用。
        self.assertTrue(all(row['status'] == 'not_run' and row['score_kcal_mol'] is None and row['execution_authorized'] is False for row in self.package['formal_docking_plan']))  # 15组没有伪造分数。
        self.assertTrue(all(row['status'] == 'not_run' and row['rmsd_angstrom'] is None and row['execution_authorized'] is False for row in self.package['redocking_plan']))  # 三次重对接没有伪造RMSD。

    def test_reference_ligands_are_ready_for_review(self):  # 三份输入必须带官方来源、实验坐标和原子检查。
        self.assertEqual({row['reference_ligand']['code'] for row in self.package['reference_ligands']}, {'IQO', 'GDM', 'FRZ'})  # 不漏或夹带组件。
        self.assertTrue(all(row['status'] == 'prepared_for_redocking_review' and row['redocking_executed'] is False for row in self.package['reference_ligands']))  # 准备成功不写成诊断通过。
        self.assertTrue(all(row['validation']['heavy_atoms_preserved'] and row['identity']['experimental_coordinates_preserved'] for row in self.package['reference_ligands']))  # 实验重原子坐标完整保留。


if __name__ == '__main__':  # 支持独立运行。
    unittest.main(verbosity=2)  # 输出每项验收状态。
