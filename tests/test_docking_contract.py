# A06通用契约测试；使用非COPD、非五乘五数据证明没有病例硬编码。
from pathlib import Path  # 定位项目源码。
import sys  # 加载独立新项目模块。
import unittest  # 执行可重复验收。

ROOT = Path(__file__).resolve().parents[1]  # 确定项目根目录。
sys.path.insert(0, str(ROOT / "src"))  # 只使用当前项目代码。

from contracts import check_result, ContractError  # 核对非法结构被明确阻断。
from docking_contract import SCHEMA_VERSION, receptor_limitation_table, receptor_setup_table, score_matrix_table, validate_generic_result  # 使用通用A06契约。
from docking_formal import formal_validator  # 核对通用契约已经接入生产A06校验器。


def sample():  # 构造两个成分和三个受体的非COPD部分完成案例。
    receptors = [{"target": target, "pdb_id": pdb, "chains": ["A"], "reference_ligand": ligand, "center": [1.0, 2.0, 3.0], "size": [20.0, 21.0, 22.0], "redocking_rmsd_A": rmsd, "qc_status": "通过", "ppi_rank": rank, "pocket_basis": "共晶参考配体", "structure_limitation": "无额外限制", "interpretation_scope": "可进入主要结果", "primary_result": rank <= 2, "redocking_status": "passed"} for rank, (target, pdb, ligand, rmsd) in enumerate((("EGFR", "1M17", "AQ4", 0.8), ("PIK3CA", "4JPS", "X6K", 1.1), ("STAT3", "6NJS", "KQV", 1.4)), 1)]  # 保存实际三受体参数和追溯字段。
    planned = [{"compound_id": compound, "target": target} for compound in ("C001", "C002") for target in ("EGFR", "PIK3CA", "STAT3")]  # 形成二乘三计划。
    completed = [{**row, "score_kcal_mol": -7.0, "pose_record": {"path": f"poses/{row['compound_id']}_{row['target']}.pdbqt", "bytes": 100, "sha256": "a" * 64, "role": "selected_pose"}} for row in planned[:-1]]  # 五组完成并绑定文件指纹。
    failed = [{**planned[-1], "reason": "受体结构质控后暂停"}]  # 一组失败并保留原因。
    return {"contract_version": SCHEMA_VERSION, "outcome": "partial", "compounds": [{"compound_id": "C001", "name": "compound one"}, {"compound_id": "C002", "name": "compound two"}], "receptors": receptors, "planned_pairs": planned, "completed_pairs": completed, "failed_pairs": failed}  # 返回通用结果。


class DockingContractTest(unittest.TestCase):  # 检查动态数量、失败和空结果。
    def test_non_copd_two_by_three_partial_result(self):  # 非五乘五结果应通过并正确形成受体表。
        result = sample()  # 读取合成案例。
        self.assertTrue(validate_generic_result(result))  # 通用校验不依赖固定靶点。
        self.assertEqual([row["靶点基因"] for row in receptor_setup_table(result)], ["EGFR", "PIK3CA", "STAT3"])  # 顺序来自本次输入。
        self.assertEqual(receptor_limitation_table(result)[0]["PPI顺序"], 1)  # 说明表保持PPI顺序。
        self.assertIsNone(score_matrix_table(result)[1]["STAT3"])  # 失败组合保持空值而不补零。

    def test_missing_pair_is_rejected(self):  # 组合不能在计划与结果之间失踪。
        result = sample()  # 复制测试案例。
        result["failed_pairs"] = []  # 删除唯一失败记录。
        with self.assertRaises(ContractError):  # 应明确阻断。
            validate_generic_result(result)  # 执行完整覆盖检查。

    def test_failed_receptor_cannot_have_scores(self):  # 失败受体必须保持NA。
        result = sample()  # 使用完整动态计划。
        result['receptors'][0].update(center=None, size=None, redocking_rmsd_A=None, redocking_status='failed_not_computable', qc_status='失败', primary_result=False)  # 标记真实准备失败。
        with self.assertRaises(ContractError):  # 仍有成功评分必须阻断。
            validate_generic_result(result)  # 不容许失败受体伪成功。

    def test_missing_entire_combination_rejected(self):  # 同时删计划和结果也不得缩小矩阵。
        result = sample()  # 完整二乘三范围。
        result['planned_pairs'].pop(0)  # 删除计划格。
        result['completed_pairs'].pop(0)  # 同时删对应结果。
        with self.assertRaises(ContractError):  # 全对象笛卡尔积仍应查出遗漏。
            validate_generic_result(result)  # 验证真实动态矩阵。

    def test_top_two_cannot_replace_top_one(self):  # 第一姿势失败时不能改选第二。
        result = sample()  # 使用有效计划。
        result['completed_pairs'][0]['selected_mode'] = 2  # 模拟错误自动改选。
        with self.assertRaises(ContractError):  # 必须拒绝。
            validate_generic_result(result)  # 严格绑定Top-1。

    def test_partial_result_shell_is_scoped(self):  # 部分成功接口只对对接事实开放。
        result = sample()  # 使用合法同源事实。
        check_result({}, {'generic_docking': result}, [], 'partial')  # 对接契约可以进入工作流。
        with self.assertRaises(ContractError):  # 普通模块不能借此放宽。
            check_result({}, {'normal_table': []}, [], 'partial')  # 普通表仍遵守旧外壳。

    def test_valid_empty_result_has_no_fabricated_pair(self):  # 无可对接受体时允许形成可报告空结果。
        result = {"contract_version": SCHEMA_VERSION, "outcome": "empty", "compounds": [], "receptors": [], "planned_pairs": [], "completed_pairs": [], "failed_pairs": [], "empty_reason": "没有通过结构质控的受体"}  # 保存真实空结果。
        self.assertTrue(validate_generic_result(result))  # 空结果不应被迫制造矩阵。

    def test_generic_contract_is_wired_to_a06_validator(self):  # 新研究可直接通过第三版A06配置发布。
        result = sample()  # 使用非COPD部分完成案例。
        tables = {"generic_docking": result, "receptor_setup": receptor_setup_table(result), "score_matrix": score_matrix_table(result)}  # 两张报告表均由程序生成。
        summary = {"计划组合数": 6, "成功组合数": 5, "失败组合数": 1, "handoff_blocked": True}  # 摘要从明细复算。
        validator = formal_validator(ROOT)  # 建立生产校验器。
        validator({"config": {"schema_version": "A06.formal.config.3"}}, summary, tables, [], "partial")  # 不依赖固定授权对象。


if __name__ == "__main__":  # 支持单文件运行。
    unittest.main(verbosity=2)  # 输出每项验收结果。
