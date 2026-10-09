# A06身份检查的错误案例测试；虚构输入不作为研究资料。
import sys  # 引用项目内核和独立化学环境。
import unittest  # 执行边界检查。
from pathlib import Path  # 定位项目根目录。
ROOT = Path(__file__).resolve().parents[1]  # 不依赖启动位置。
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'environments/docking_packages')]  # 不读取旧Kimi环境。
from rdkit import Chem  # 创建虚构化学结构。
from rdkit.Chem import AllChem  # 生成确定性的测试构象。
from contracts import ContractError  # 预期校验失败。
from docking_audit import ligand_identity, receptor_identity, receptor_geometry  # 调用实际核查代码。
from docking_receptor import inspect_reference_site, inspect_structure  # 调用受体原始坐标与位点清点。
from docking_receptor_diagnostic import polymer_only_pdb  # 调用临时受体诊断坐标生成。


class DockingIdentityTests(unittest.TestCase):  # 覆盖化学和蛋白身份错误。
    def molecule(self):  # 创建一个有手性的虚构分子。
        mol = Chem.AddHs(Chem.MolFromSmiles('F[C@](Cl)(Br)I'))  # 明确单一手性对象。
        self.assertEqual(AllChem.EmbedMolecule(mol, randomSeed=1), 0)  # 测试构象必须成功。
        mol.SetProp('PUBCHEM_COMPOUND_CID', '123')  # 虚构编号，仅作字段测试。
        return mol  # 返回内存对象。

    def sdf(self, mol):  # 保留测试分子的编号字段。
        return Chem.MolToMolBlock(mol) + '\n> <PUBCHEM_COMPOUND_CID>\n123\n\n$$$$\n'  # 单个SDF对象。

    def test_identity_and_wrong_inputs(self):  # 正常对象可核对，错编号或错结构拒绝。
        mol = self.molecule()  # 固定虚构分子。
        sdf = self.sdf(mol)  # 序列化用于真实解析。
        key = Chem.MolToInchiKey(mol)  # 预期对象身份。
        self.assertEqual(ligand_identity(sdf, 123, key)['identity_check'], 'matched')  # 完整对象通过身份核查。
        for text, cid, identity in [(sdf, 124, key), (sdf, 123, 'WRONG'), (sdf + sdf, 123, key), ('broken', 123, key)]:  # 四种独立错误。
            with self.subTest(cid=cid, length=len(text), identity=identity):  # 显示具体错误案例。
                with self.assertRaises(ContractError):  # 不可静默继续。
                    ligand_identity(text, cid, identity)  # 执行真实入口。

    def test_coordinate_stereo_mismatch(self):  # 原立体标签正确但几何镜像也应拒绝。
        mol = self.molecule()  # 使用有手性对象。
        key = Chem.MolToInchiKey(mol)  # 记录原始身份。
        conformer = mol.GetConformer()  # 获取实际坐标。
        for index in range(mol.GetNumAtoms()):  # 镜像所有原子而不修改标签。
            p = conformer.GetAtomPosition(index)  # 原始坐标。
            conformer.SetAtomPosition(index, (-p.x, p.y, p.z))  # 只翻转一个坐标轴。
        with self.assertRaises(ContractError):  # 必须发现对映体身份不符。
            ligand_identity(self.sdf(mol), 123, key)  # 不只依赖文件文字编号。

    def test_target_chain_and_species(self):  # 不把表达宿主、另一条链或无身份实体当目标。
        entity = {'rcsb_polymer_entity_container_identifiers': {'uniprot_ids': ['PTEST'], 'auth_asym_ids': ['C'], 'asym_ids': ['B']}, 'entity_poly': {'rcsb_entity_polymer_type': 'Protein'}, 'rcsb_entity_source_organism': [{'ncbi_taxonomy_id': 9606}]}  # 作者链和标签链刻意不同。
        self.assertFalse(receptor_identity(entity, 'PTEST', 'C')['docking_ready'])  # 身份符合不等于可运行。
        for accession, chain in [('OTHER', 'C'), ('PTEST', 'A'), ('PTEST', 'B')]:  # 错目标、第一链和错编号体系。
            with self.assertRaises(ContractError):  # 全部阻断身份通过。
                receptor_identity(entity, accession, chain)  # 使用真实检查。
        entity['rcsb_entity_source_organism'] = [{'ncbi_taxonomy_id': 10090}]  # 换成小鼠。
        with self.assertRaises(ContractError):  # 不默认跨物种。
            receptor_identity(entity, 'PTEST', 'C')  # 人类研究必须对应。


    def test_geometry_keeps_other_chain_and_water(self):  # 口袋跨链和水不能在预检中丢失。
        import gemmi  # 创建简单且可手算的结构。
        structure = gemmi.Structure()  # 空结构不含真实研究数据。
        model = gemmi.Model('1')  # 明确一个模型。
        for chain_name, name, number, x, flag, element in [('A', 'LIG', 1, 0, 'H', 'C'), ('B', 'ALA', 2, 2, 'A', 'C'), ('A', 'HOH', 3, 3, 'H', 'O')]:  # 距离分别为2和3埃。
            chain = gemmi.Chain(chain_name)  # 保留作者链片段。
            residue = gemmi.Residue()  # 创建单一残基。
            residue.name, residue.seqid, residue.het_flag = name, gemmi.SeqId(number, ' '), flag  # 明确残基身份。
            atom = gemmi.Atom()  # 创建重原子。
            atom.name, atom.element, atom.pos = element, gemmi.Element(element), gemmi.Position(x, 0, 0)  # 坐标可独立手算。
            residue.add_atom(atom)  # 挂接到残基。
            chain.add_residue(residue)  # 挂接到作者链。
            model.add_chain(chain)  # 重复作者链片段也需遍历。
        structure.add_model(model)  # 形成唯一模型。
        structure.setup_entities()  # 补齐mmCIF实体结构。
        cif = structure.make_mmcif_document().as_string()  # 使用实际解析格式。
        result = receptor_geometry(cif, 'LIG', 'A', '1')  # 精确查询一个配体。
        self.assertEqual([r['minimum_distance_angstrom'] for r in result['neighbor_residues']], [2.0, 3.0])  # 与手算一致。
        self.assertEqual(result['neighbor_residues'][0]['auth_chain'], 'B')  # 不默认删掉其他链。
        self.assertEqual(result['neighbor_residues'][1]['residue'], 'HOH')  # 水也保留用于判断。
        self.assertFalse(result['box_defined'])  # 配体边界不能冒充搜索盒。
        with self.assertRaises(ContractError):  # 不自动改选另一条链。
            receptor_geometry(cif, 'LIG', 'B', '1')  # 错链应拒绝。

    def test_preparation_requires_full_configuration(self):  # 准备时不静默补参数。
        from docking_ligand import prepare_ligand  # 实际准备内核。
        mol = self.molecule()  # 使用明确测试对象。
        with self.assertRaises(ContractError):  # 空参数必须报错。
            prepare_ligand(self.sdf(mol), 123, Chem.MolToInchiKey(mol), {})  # 不使用隐式默认。

    def test_receptor_inspection_is_read_only(self):  # 清点不能把水、其他组分或缺失类别隐藏。
        import gemmi  # 创建无真实研究信息的合成坐标。
        structure = gemmi.Structure()  # 从空结构开始。
        structure.name = "TEST"  # 固定虚构PDB身份。
        model = gemmi.Model("1")  # 只提供一个模型。
        chain = gemmi.Chain("A")  # 明确作者链。
        residue = gemmi.Residue()  # 创建一个聚合物残基。
        residue.name, residue.seqid, residue.entity_type = "ALA", gemmi.SeqId(1, " "), gemmi.EntityType.Polymer  # 虚构编号与聚合物身份。
        atom = gemmi.Atom()  # 创建一个重原子。
        atom.name, atom.element, atom.pos = "CA", gemmi.Element("C"), gemmi.Position(0, 0, 0)  # 有限坐标。
        residue.add_atom(atom)  # 原子归入聚合物残基。
        chain.add_residue(residue)  # 残基归入目标链。
        water = gemmi.Residue()  # 水必须独立留存。
        water.name, water.seqid, water.het_flag, water.entity_type = "HOH", gemmi.SeqId(2, " "), "H", gemmi.EntityType.Water  # 标记水而非聚合物。
        oxygen = gemmi.Atom()  # 水氧原子。
        oxygen.name, oxygen.element, oxygen.pos = "O", gemmi.Element("O"), gemmi.Position(2, 0, 0)  # 保持明确坐标。
        water.add_atom(oxygen)  # 水原子归入水残基。
        chain.add_residue(water)  # 水与同一作者链关联。
        model.add_chain(chain)  # 目标链归入模型。
        structure.add_model(model)  # 模型归入结构。
        structure.setup_entities()  # 让mmCIF建立完整实体字段。
        cif = structure.make_mmcif_document().as_string()  # 使用与真实来源一致的解析格式。
        result = inspect_structure(cif, "TEST", ["A"])  # 运行实际清点入口。
        self.assertEqual(len(result["waters"]), 1)  # 水没有被自动删除。
        self.assertFalse(result["unobserved"]["pdbx_unobs_or_zero_occ_residues"]["category_reported"])  # 缺类别不冒充零缺失。
        self.assertFalse(result["coordinate_modified"])  # 清点不修改坐标。
        self.assertFalse(result["docking_ready"])  # 清点不自动放行对接。
        with self.assertRaises(ContractError):  # 错误PDB不能依靠文件名通过。
            inspect_structure(cif, "OTHER", ["A"])  # 核对内容身份。
        with self.assertRaises(ContractError):  # 不存在的链不能回退第一链。
            inspect_structure(cif, "TEST", ["B"])  # 明确拒绝错链。

    def test_reference_site_keeps_altloc_and_water_without_threshold(self):  # 位点预检只报告距离，不自行删改。
        import gemmi  # 创建距离可手算的虚构结构。
        structure = gemmi.Structure()  # 不含真实研究数据。
        model = gemmi.Model("1")  # 只提供一个模型。
        chain = gemmi.Chain("A")  # 配体和受体位于同一作者链。
        ligand = gemmi.Residue()  # 创建参考小分子。
        ligand.name, ligand.seqid, ligand.het_flag, ligand.entity_type = "LIG", gemmi.SeqId(1, " "), "H", gemmi.EntityType.NonPolymer  # 明确非聚合物身份。
        ligand_atom = gemmi.Atom()  # 参考配体重原子。
        ligand_atom.name, ligand_atom.element, ligand_atom.pos = "C1", gemmi.Element("C"), gemmi.Position(0, 0, 0)  # 作为距离原点。
        ligand.add_atom(ligand_atom)  # 原子归入配体。
        chain.add_residue(ligand)  # 配体归入作者链。
        residue = gemmi.Residue()  # 创建带替代构象的蛋白残基。
        residue.name, residue.seqid, residue.entity_type = "ALA", gemmi.SeqId(2, " "), gemmi.EntityType.Polymer  # 标记为受体聚合物。
        for location, occupancy, x in [("A", 0.6, 2.0), ("B", 0.4, 3.0)]:  # 两个构象都必须保留。
            atom = gemmi.Atom()  # 创建一个替代位置原子。
            atom.name, atom.altloc, atom.occ = "CA", location, occupancy  # 保存位置标签与占有率。
            atom.element, atom.pos = gemmi.Element("C"), gemmi.Position(x, 0, 0)  # 最近距离应为2埃。
            residue.add_atom(atom)  # 两个位置归入同一残基。
        chain.add_residue(residue)  # 蛋白残基归入作者链。
        water = gemmi.Residue()  # 创建不应被自动删除的水。
        water.name, water.seqid, water.het_flag, water.entity_type = "HOH", gemmi.SeqId(3, " "), "H", gemmi.EntityType.Water  # 明确水身份。
        oxygen = gemmi.Atom()  # 创建水氧。
        oxygen.name, oxygen.element, oxygen.pos = "O", gemmi.Element("O"), gemmi.Position(4, 0, 0)  # 与配体相距4埃。
        water.add_atom(oxygen)  # 水氧归入水。
        chain.add_residue(water)  # 水归入同一作者链。
        model.add_chain(chain)  # 作者链归入模型。
        structure.add_model(model)  # 模型归入结构。
        structure.setup_entities()  # 建立完整mmCIF实体。
        result = inspect_reference_site(structure.make_mmcif_document().as_string(), "LIG", "A", "1", ["A"])  # 执行实际位点预检。
        self.assertEqual(result["alternate_residues"][0]["locations"], ["A", "B"])  # 两个构象没有被任选其一。
        self.assertEqual(result["alternate_residues"][0]["minimum_distance_angstrom"], 2.0)  # 距离与手算一致。
        self.assertEqual(result["waters_by_distance"][0]["minimum_distance_angstrom"], 4.0)  # 水距离完整保留。
        self.assertFalse(result["distance_filter_applied"])  # 没有隐含距离阈值。
        self.assertEqual(result["site_quality_decision"], "pending")  # 预检不自动批准位点。

    def test_diagnostic_copy_excludes_nonpolymer_without_changing_source(self):  # 临时能力诊断不把删水误写为正式准备。
        import gemmi  # 创建含蛋白、配体和水的虚构原始结构。
        structure = gemmi.Structure()  # 不含真实研究数据。
        structure.name = "TEST"  # 固定PDB身份。
        model = gemmi.Model("1")  # 提供唯一模型。
        chain = gemmi.Chain("A")  # 使用明确作者链。
        for name, number, entity_type in [("ALA", 1, gemmi.EntityType.Polymer), ("LIG", 2, gemmi.EntityType.NonPolymer), ("HOH", 3, gemmi.EntityType.Water)]:  # 三类对象同时存在。
            residue = gemmi.Residue()  # 建立虚构残基。
            residue.name, residue.seqid, residue.entity_type = name, gemmi.SeqId(number, " "), entity_type  # 明确实体身份。
            atom = gemmi.Atom()  # 每个对象放一个可辨识原子。
            atom.name, atom.element, atom.pos = "CA" if name == "ALA" else "O", gemmi.Element("C" if name == "ALA" else "O"), gemmi.Position(number, 0, 0)  # 坐标有限。
            residue.add_atom(atom)  # 原子归入残基。
            chain.add_residue(residue)  # 残基归入目标链。
        model.add_chain(chain)  # 作者链归入模型。
        structure.add_model(model)  # 模型归入结构。
        structure.setup_entities()  # 建立可解析mmCIF实体。
        original = structure.make_mmcif_document().as_string()  # 保存完整原始文字用于前后比较。
        diagnostic = polymer_only_pdb(original, "TEST", ["A"])  # 生成临时蛋白副本。
        self.assertIn("ALA", diagnostic)  # 蛋白聚合物保留。
        self.assertNotIn("LIG", diagnostic)  # 配体不进入能力诊断副本。
        self.assertNotIn("HOH", diagnostic)  # 水不进入能力诊断副本。
        self.assertIn("LIG", original)  # 原始输入没有被修改。
        self.assertIn("HOH", original)  # 原始水仍可追溯。


if __name__ == '__main__':  # 独立验收入口。
    unittest.main(verbosity=2)  # 明确输出通过和失败。
