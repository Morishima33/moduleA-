# 配体准备内核；调用方必须明确传入配置并保留审阅状态。
import io  # 从固定来源读取SDF。
import inspect  # 确保工具参数完整记录。
from contracts import require  # 统一失败提示。
from docking_audit import ligand_identity  # 准备前再次核对实际对象。


def prepare_ligand(sdf_text, cid, inchi_key, settings):  # 不在线换结构，也不自动改变电离形态。
    from rdkit import Chem  # 保留原三维坐标与氢。
    from meeko import MoleculePreparation, PDBQTWriterLegacy, __version__  # 使用项目固定准备工具。
    identity = ligand_identity(sdf_text, cid, inchi_key)  # 错身份或立体信息先阻断。
    expected = set(inspect.signature(MoleculePreparation).parameters)  # 当前实际工具的所有参数。
    require(isinstance(settings, dict) and set(settings) == expected, '准备参数未完整记录或与工具版本不符')  # 不静默补默认参数。
    mol = next(Chem.ForwardSDMolSupplier(io.BytesIO(sdf_text.encode('utf-8')), removeHs=False))  # 身份检查已确保仅一结构。
    require(all(atom.GetNumImplicitHs() == 0 for atom in mol.GetAtoms()), '配体仍有隐式氢，需明确准备方式')  # 不声称已加氢。
    preparation = MoleculePreparation(**settings)  # 使用完整显式配置。
    setups = preparation.prepare(mol)  # 仅进行Meeko参数化。
    require(len(setups) == 1, '准备生成多个对象，需明确选择')  # 不任取第一个产物。
    pdbqt, success, message = PDBQTWriterLegacy.write_string(setups[0], add_index_map=True, remove_smiles=False, bad_charge_ok=False)  # 保留原子索引和结构回指，坏电荷不允许。
    require(success and bool(pdbqt.strip()), '配体准备失败：' + str(message))  # 空文件不能标成功。
    require('REMARK SMILES' in pdbqt and 'TORSDOF' in pdbqt, '配体输出缺结构回指或可转动键信息')  # 基础格式完整性。
    return {'identity': identity, 'meeko_version': __version__, 'settings': settings, 'writer_settings': {'add_index_map': True, 'remove_smiles': False, 'bad_charge_ok': False}, 'pdbqt_text': pdbqt, 'message': str(message), 'preparation_state': 'prepared_pending_review', 'docking_ready': False}  # 准备成功不自动取得对接许可。