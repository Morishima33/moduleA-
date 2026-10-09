# A06三次参考配体重对接结果回归检查；独立复算RMSD并确认正式15组仍未运行。
import sys  # 加载新项目代码和固定科学依赖。
import unittest  # 使用标准测试框架。
from pathlib import Path  # 定位不可变研究包。
ROOT = Path(__file__).resolve().parents[1]  # 测试根固定为新项目。
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'environments' / 'docking_packages')]  # 不读取旧Kimi代码或全局依赖。
from docking_redocking import _poses, symmetry_rmsd  # 使用生产解析器复算每条诊断。
from docking_ui import load_preview  # 按网页同一路径检查嵌套指纹。
from storage import verified_file  # 结果文件使用统一完整性校验。
from workflow import Workflow  # 核对研究索引没有越过正式关口。


class RedockingResultTests(unittest.TestCase):  # 三条结果及执行边界必须同时成立。
    @classmethod  # 固定结果只加载一次。
    def setUpClass(cls):  # 取得当前诊断、候选包和研究索引。
        cls.study_id = 'study_28a9580bd87543c98892e3c7ce4d1426'  # 本次COPD流程测试研究。
        cls.workflow = Workflow(ROOT)  # 测试不注册或运行正式科学模块。
        cls.plan = load_preview(cls.workflow, cls.study_id)  # 与网页一致地校验当前预览。
        cls.report = cls.plan['redocking_result_data']  # 使用唯一当前结果引用。
        cls.package = cls.plan['preparation_package_data']  # 输入来自已复核候选包。

    def test_expected_three_diagnostics_and_pause(self):  # 使用固定种子后的三条结果须可稳定复查。
        rows = {row['symbol']: row for row in self.report['results']}  # 按靶点读取，不依赖文件排序。
        self.assertEqual(set(rows), {'AKT1', 'HSP90AA1', 'MAPK1'})  # 三个批准对象不漏不增。
        self.assertAlmostEqual(rows['AKT1']['rmsd_angstrom'], 1.3653136130, places=6)  # AKT1达到≤2 Å。
        self.assertAlmostEqual(rows['HSP90AA1']['rmsd_angstrom'], 5.6503989041, places=6)  # HSP90AA1未复现。
        self.assertAlmostEqual(rows['MAPK1']['rmsd_angstrom'], 0.2405621749, places=6)  # MAPK1达到≤2 Å。
        self.assertTrue(rows['AKT1']['passed'] and rows['MAPK1']['passed'])  # 两个受体可保留为候选。
        self.assertFalse(rows['HSP90AA1']['passed'])  # 未通过者必须暂停。
        self.assertEqual(self.report['summary']['paused_receptors'], ['HSP90AA1'])  # 暂停名单不能由页面另算。

    def test_rmsd_recomputes_from_archived_pose_and_reference(self):  # 每个保存值均从姿势与晶体结构重新计算。
        plans = {row['symbol']: row for row in self.package['redocking_plan']}  # 输入文件来自候选包指纹。
        for row in self.report['results']:  # 三个受体分别复算。
            with self.subTest(symbol=row['symbol']):  # 失败时明确对象。
                plan = plans[row['symbol']]  # 找到对应参考结构记录。
                sdf_record = next(record for record in plan['ligand_files'] if record['path'].endswith('.sdf'))  # 唯一晶体SDF。
                pdbqt_record = next(record for record in plan['ligand_files'] if record['path'].endswith('.pdbqt'))  # 唯一Meeko输入。
                output_path = verified_file(ROOT, row['output_file'])  # 输出姿势必须未被改写。
                top_pose = _poses(output_path.read_text(encoding='utf-8'))[0]  # 仅top-1参与规则判定。
                recomputed = symmetry_rmsd(verified_file(ROOT, sdf_record).read_bytes(), verified_file(ROOT, pdbqt_record).read_text(encoding='utf-8'), top_pose)  # 重新枚举对称映射。
                self.assertAlmostEqual(recomputed['rmsd_angstrom'], row['rmsd_angstrom'], places=12)  # 存档值和复算值严格一致。
                self.assertFalse(recomputed['alignment_performed'])  # 不允许刚体拟合掩盖错误位置。
                self.assertFalse(recomputed['hydrogen_included'] or recomputed['pseudoatom_included'])  # 氢和G0不进入重原子RMSD。

    def test_historical_redocking_record_remains_diagnostic_only(self):  # 后续授权不能改写历史诊断的当时边界。
        manifest = self.workflow.load(self.study_id)  # 查看统一研究索引。
        self.assertIn('A06_PREP', manifest['current'])  # 后续用户授权已经发布准备关口。
        self.assertIn('A06', manifest['current'])  # 后续十组正式对接已经形成新运行。
        self.assertFalse(self.report['summary']['formal_docking_authorized'])  # 结果明确记录未授权。
        self.assertEqual(self.report['summary']['formal_docking_completed_count'], 0)  # 正式完成数保持零。
        self.assertTrue(all(row['status'] == 'not_run' and row['score_kcal_mol'] is None for row in self.package['formal_docking_plan']))  # 15组原计划不被诊断结果改写。


if __name__ == '__main__':  # 支持独立验收。
    unittest.main(verbosity=2)  # 显示每项检查状态。
