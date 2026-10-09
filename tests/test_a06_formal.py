# A06正式对接回归检查；核对当前五乘五结果和统一工作流状态。
import sys  # 加载新项目代码。
import unittest  # 使用标准测试框架。
from pathlib import Path  # 定位研究包和归档文件。
ROOT = Path(__file__).resolve().parents[1]  # 测试只访问独立新项目。
sys.path.insert(0, str(ROOT / 'src'))  # 使用当前生产解析与完整性规则。
from docking_ui import load_preview  # 通过网页同一入口读取正式结果。
from web import review_focus  # 核对网页按当前矩阵动态显示。
from workflow import Workflow  # 核对当前版本、复核和所有文件指纹。


class FormalDockingTests(unittest.TestCase):  # 正式结果必须完整且不夹带暂停受体。
    @classmethod  # 固定归档只需读取一次。
    def setUpClass(cls):  # 加载当前COPD流程测试研究。
        cls.study_id = 'study_28a9580bd87543c98892e3c7ce4d1426'  # 使用用户本轮确认的研究。
        cls.workflow = Workflow(ROOT)  # 只读检查不触发运行。
        cls.plan = load_preview(cls.workflow, cls.study_id)  # 同时核验预览及标准结果全部文件。
        cls.result = cls.plan['formal_result_data']  # 取得当前A06标准结果。
        cls.manifest = cls.workflow.load(cls.study_id)  # 读取唯一当前版本索引。

    def test_twenty_five_combinations_and_quality_control(self):  # 五乘五组合必须全部有真实评分。
        summary = self.result['summary']  # 数量直接来自标准结果。
        self.assertEqual(summary['计划组合数'], 25)  # 执行用户确认的五乘五计划。
        self.assertEqual(summary['成功组合数'], 25)  # 二十五组均有有效评分。
        self.assertEqual(summary['失败组合数'], 0)  # 没有技术失败被填成零分。
        self.assertFalse(summary['handoff_blocked'])  # 技术结果可进入人工复核。
        rows = self.result['tables']['combination_results']  # 使用完整二十五组表核对身份。
        self.assertEqual(len(rows), 25)  # 不遗漏任何授权组合。
        self.assertEqual({row['受体'] for row in rows}, {'AKT1', 'MAPK1', 'HSP90AA1', 'TNF', 'ESR1'})  # 五个受体不漏不增。
        self.assertTrue(all(row['状态'] == '完成' and row['最佳有效结合能_kcal_mol'] is not None for row in rows))  # 每组真实完成且无缺失评分。
        diagnostics = self.result['tables']['receptor_diagnostics']  # 读取五受体重对接质控。
        self.assertEqual(len(diagnostics), 5)  # 每个受体恰有一条诊断。
        self.assertTrue(all(row['诊断通过'] and row['RMSD_A'] <= 2 for row in diagnostics))  # 所有受体均满足既定RMSD标准。

    def test_matrix_values_and_pose_integrity(self):  # 矩阵必须来自通过身份和盒内检查的实际姿势。
        matrix = {row['compound_id']: row for row in self.result['tables']['score_matrix']}  # 按稳定成分编号核对。
        self.assertEqual(set(matrix), {'MOL000098', 'MOL000422', 'MOL000378', 'MOL000173', 'MOL000358'})  # 五个候选不漏不增。
        self.assertAlmostEqual(matrix['MOL000098']['AKT1'], -9.640, places=6)  # 槲皮素—AKT1原始评分。
        self.assertAlmostEqual(matrix['MOL000098']['MAPK1'], -8.372, places=6)  # 槲皮素—MAPK1原始评分。
        self.assertAlmostEqual(matrix['MOL000358']['AKT1'], -10.934, places=6)  # beta-sitosterol—AKT1原始评分。
        for row in matrix.values():  # 检查五个受体列均为有限数值。
            self.assertTrue(all(isinstance(row[target], (int, float)) for target in ('AKT1', 'MAPK1', 'HSP90AA1', 'TNF', 'ESR1')))  # 不允许缺失或补零占位。

    def test_workflow_state_and_files(self):  # 准备关口与A06均已按用户明确决定批准。
        prep_id = self.manifest['current']['A06_PREP']  # 取得当前准备运行。
        formal_id = self.manifest['current']['A06']  # 取得当前正式运行。
        self.assertTrue(self.workflow.approved(self.manifest, prep_id))  # 对话中的明确授权已登记为准备关口通过。
        self.assertTrue(self.workflow.approved(self.manifest, formal_id))  # 用户明确回复“A06通过”，当前版本应保持已批准。
        modules = {row['module_id']: row for row in self.workflow.view(self.study_id)['modules']}  # 按模块编号读取页面状态。
        self.assertEqual(modules['A06']['state'], 'approved')  # A06卡片应显示已复核通过。
        verified = self.workflow.result(self.manifest, formal_id)  # 重新校验结果、热图、日志和姿势文件指纹。
        self.assertEqual(verified['run_id'], formal_id)  # 当前指针与完整结果一致。
        self.assertEqual(len(verified['figures']), 2)  # 五乘五热图同时归档SVG和PNG。

    def test_web_focus_uses_actual_targets_and_counts(self):  # A06重点区不再固定十组或三个受体。
        item = next(row for row in self.workflow.view(self.study_id)['modules'] if row['module_id'] == 'A06')  # 读取生产页面数据。
        item = dict(item, state='awaiting_review')  # 仅检查待复核重点区，不改写正式研究状态。
        html = review_focus(item, self.study_id)  # 生成当前A06重点区。
        self.assertIn('计划25组；完成25组；失败或暂停0组', html)  # 数量来自当前摘要。
        for target in ('AKT1', 'MAPK1', 'HSP90AA1', 'TNF', 'ESR1'):  # 核对五个实际矩阵列。
            self.assertIn(target + '（kcal/mol）', html)  # 不使用历史固定列。


if __name__ == '__main__':  # 支持独立执行验收。
    unittest.main(verbosity=2)  # 输出每项检查状态。
