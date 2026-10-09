# 共晶参考配体实际来源回归检查；只读项目内已归档RCSB资料。
import json  # 读取现有准备包和固定参数。
import sys  # 加载新项目代码与隔离科学依赖。
import unittest  # 使用标准测试框架。
from pathlib import Path  # 定位项目内不可变资料。
ROOT = Path(__file__).resolve().parents[1]  # 测试根固定为新项目。
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'environments' / 'docking_packages')]  # 不读取旧Kimi代码或全局依赖。
from contracts import ContractError  # 检查明确拒绝。
from docking_audit import source_body  # 使用真实来源指纹校验。
from docking_reference_ligand import _element_symbol, prepare_reference_ligand  # 测试元素规范化和生产准备逻辑。


class ReferenceLigandTests(unittest.TestCase):  # 三个当前共结构配体均须可复算。
    @classmethod  # 固定资料只需读取一次。
    def setUpClass(cls):  # 准备真实路径和显式Meeko设置。
        cls.study = ROOT / 'studies' / 'study_28a9580bd87543c98892e3c7ce4d1426'  # 当前COPD流程测试研究。
        cls.receptor_dir = cls.study / 'runs' / 'A06_PREP' / 'run_cbb3c71d15ab49e2bd8a04761e5cef3a'  # 已验收受体准备包。
        ligand_path = cls.study / 'runs' / 'A06_PREP' / 'run_ddd2f6e19f504fe88560008d4f7a63bf' / 'preparation.json'  # 已验收五配体设置来源。
        cls.settings = json.loads(ligand_path.read_text(encoding='utf-8'))['results'][0]['settings']  # 不调用工具隐式默认值。
        cls.cases = [  # 每项绑定官方组件、实验坐标和预期身份。
            ('IQO', 'A', '444', 'AKT1_3O96_A_reference.pdb', {'path': 'references/structure_81f36dceb3d0e1f2b93fc48aaff487d7ee285fa4788b84e6f6447042c945948c.json', 'sha256': '81f36dceb3d0e1f2b93fc48aaff487d7ee285fa4788b84e6f6447042c945948c', 'bytes': 14904, 'role': 'structure_source'}, 'C34H29N7O', 42, 0),  # AKT1参考配体。
            ('GDM', 'A', '275', 'HSP90AA1_1YET_A_reference.pdb', {'path': 'references/structure_1256c4678a592a349e015b861c04c1c7116de9954ab8917266ae8bd1fe3476c0.json', 'sha256': '1256c4678a592a349e015b861c04c1c7116de9954ab8917266ae8bd1fe3476c0', 'bytes': 13523, 'role': 'structure_source'}, 'C29H40N2O9', 40, 6),  # HSP90AA1参考配体。
            ('FRZ', 'A', '1001', 'MAPK1_1TVO_A_reference.pdb', {'path': 'references/structure_4a863dad8c8f84750727100e3973ed87f347bb5a1ff4efea074e06b864bd1101.json', 'sha256': '4a863dad8c8f84750727100e3973ed87f347bb5a1ff4efea074e06b864bd1101', 'bytes': 9715, 'role': 'structure_source'}, 'C18H13N7', 25, 0),  # MAPK1参考配体。
        ]  # 恰好三项，不自动扩充。

    def test_actual_components_preserve_identity_and_coordinates(self):  # 实际三份输入均须完成拓扑、手性和坐标检查。
        for code, chain, sequence, pdb_name, source, formula, heavy_atoms, stereo_count in self.cases:  # 每个受体独立核验。
            with self.subTest(component=code):  # 失败时明确指出组件。
                result = prepare_reference_ligand(source_body(ROOT, source), (self.receptor_dir / pdb_name).read_text(encoding='ascii'), code, chain, sequence, self.settings)  # 运行生产准备逻辑但不写文件。
                self.assertEqual(result['identity']['formula'], formula)  # 化学式与RCSB一致。
                self.assertEqual(result['identity']['heavy_atom_count'], heavy_atoms)  # 晶体重原子没有增删。
                self.assertEqual(len(result['identity']['declared_stereo_centers']), stereo_count)  # 明确手性中心全部被核对。
                self.assertTrue(result['validation']['heavy_atoms_preserved'])  # PDBQT保留实验重原子坐标。
                self.assertFalse(result['redocking_executed'])  # 准备测试不得调用Vina。

    def test_wrong_component_identity_is_rejected(self):  # 不允许按相近名称或坐标猜组件。
        code, chain, sequence, pdb_name, source, _, _, _ = self.cases[0]  # 使用IQO真实资料构造错身份输入。
        with self.assertRaises(ContractError):  # 错代码必须停止。
            prepare_reference_ligand(source_body(ROOT, source), (self.receptor_dir / pdb_name).read_text(encoding='ascii'), 'BAD', chain, sequence, self.settings)  # 不产生候选文件。

    def test_uppercase_two_letter_element_is_normalized(self):  # 含卤素的新共晶配体也应按标准元素身份读取。
        self.assertEqual(_element_symbol('CL'), 'Cl')  # RCSB常见大写氯元素不能被误判为未知元素。
        self.assertEqual(_element_symbol('BR'), 'Br')  # 同一规则覆盖溴，避免仅修补单一配体。
        self.assertEqual(_element_symbol('C'), 'C')  # 单字母元素保持原身份。


if __name__ == '__main__':  # 支持独立运行。
    unittest.main(verbosity=2)  # 显示每项真实检查结果。
