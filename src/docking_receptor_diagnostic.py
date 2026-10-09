# A06受体准备诊断；临时生成仅含拟用聚合物链的PDB，不发布正式受体文件。
from pathlib import Path  # 明确项目与临时文件位置。
import re  # 限制诊断标签，避免路径混入。
import subprocess  # 调用固定版本的Meeko命令行入口。
import sys  # 使用当前隔离Python解释器。
import tempfile  # 诊断文件在退出后清理。
from contracts import require  # 统一输入和依赖错误。


def polymer_only_pdb(cif_text, expected_pdb, auth_chains):  # 生成仅用于能力诊断的聚合物坐标。
    import gemmi  # 使用项目固定结构解析器。
    require(isinstance(auth_chains, list) and auth_chains, "须明确诊断作者链")  # 不自动取第一链。
    block = gemmi.cif.read_string(cif_text).sole_block()  # 只接受一个原始数据块。
    require(str(block.find_value("_entry.id")).upper() == expected_pdb.upper(), "诊断坐标PDB身份不符")  # 不凭文件名判断身份。
    source = gemmi.make_structure_from_block(block)  # 保留原始重原子坐标。
    require(len(source) == 1, "诊断受体包含多个模型")  # 多模型不能默认合并。
    require(set(auth_chains) <= {chain.name for chain in source[0]}, "诊断坐标缺少拟用作者链")  # 链缺失直接停止。
    target = gemmi.Structure()  # 新结构仅用于判断Meeko是否能处理蛋白坐标。
    target.name = expected_pdb.upper()  # 保留结构身份。
    model = gemmi.Model("1")  # 已确认只有一个模型。
    for chain_name in auth_chains:  # 按明确顺序建立拟用链。
        output_chain = gemmi.Chain(chain_name)  # 作者链名称不改写。
        for chain in source[0]:  # 同一作者链可能分成多个坐标片段。
            if chain.name != chain_name:  # 其他链不进入本次诊断。
                continue  # 原始文件仍完整保留在来源归档。
            for residue in chain:  # 检查每个原始残基实体类型。
                if residue.entity_type == gemmi.EntityType.Polymer:  # 只复制蛋白聚合物。
                    output_chain.add_residue(residue.clone())  # 不改变已有原子坐标或占有率。
        require(len(output_chain) > 0, "诊断作者链没有聚合物坐标：" + chain_name)  # 不输出空链。
        model.add_chain(output_chain)  # 将该链加入唯一模型。
    target.add_model(model)  # 完成临时结构。
    return target.make_pdb_string()  # 水、配体和离子仅从临时诊断副本排除，原始资料不变。


def run_meeko_diagnostic(project_root, pdb_text, label):  # 测试Meeko能否在无宽松删除参数时准备受体。
    root = Path(project_root).resolve()  # 固定新项目根目录。
    require(re.fullmatch(r"[A-Za-z0-9_-]+", label or "") is not None, "诊断标签格式不正确")  # 不接受路径字符。
    packages = root / "environments" / "docking_packages"  # 使用项目内固定依赖。
    script = packages / "meeko" / "cli" / "mk_prepare_receptor.py"  # 明确Meeko 0.8.0入口。
    require(script.is_file(), "项目内Meeko受体准备入口缺失")  # 不回退全局环境或旧Kimi。
    with tempfile.TemporaryDirectory(prefix="moduleA_a06_receptor_") as temporary:  # 不污染正式研究目录。
        temporary_path = Path(temporary)  # 统一路径对象。
        input_path = temporary_path / (label + ".pdb")  # 临时PDB只服务本次诊断。
        input_path.write_text(pdb_text, encoding="ascii")  # PDB格式使用ASCII并保留原坐标字段。
        output_base = temporary_path / (label + "_prepared")  # 临时输出基名可预测且隔离。
        runner = "import sys,runpy;sys.path.insert(0,r'" + str(packages) + "');sys.argv=['mk_prepare_receptor.py','--read_pdb',r'" + str(input_path) + "','-o',r'" + str(output_base) + "','-p'];runpy.run_path(r'" + str(script) + "',run_name='__main__')"  # 禁止Meeko使用隐式默认环境，但不添加宽松删除参数。
        completed = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", runner], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)  # 有限时间执行并保留完整日志。
        output_path = Path(str(output_base) + ".pdbqt")  # 检查Meeko实际声明的刚性受体文件。
        return {"returncode": completed.returncode, "pdbqt_created": output_path.is_file(), "pdbqt_bytes": output_path.stat().st_size if output_path.is_file() else None, "stdout": completed.stdout, "stderr": completed.stderr, "diagnostic_only": True, "published_receptor": False, "temporary_files_removed": True, "lenient_deletion_enabled": False}  # 失败也是有效诊断，不冒充正式准备。
