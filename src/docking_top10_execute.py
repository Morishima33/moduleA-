# PPI前十位动态对接执行器；为每个研究建立新版本，不覆盖历史结果。
import inspect  # 读取Meeko全部显式参数。
import json  # 保存执行事实和可复算配置。
import math  # 检查评分和坐标有效性。
from pathlib import Path  # 管理研究包内路径。
import shutil  # 复制已核验的历史输入作为当前研究输入。
import subprocess  # 调用固定版本Meeko和Vina。
import sys  # 固定当前Python运行环境。

from contracts import require  # 复用项目统一阻断规则。
from docking_contract import receptor_limitation_table, receptor_setup_table, score_matrix_table, validate_generic_result  # 生成动态报告表。
from docking_formal import _input_atoms, _pose_identity  # 复用姿势身份检查。
from docking_ligand import prepare_ligand  # 使用现有配体准备内核。
from docking_redocking import _inside_box, _minimum_receptor_distance, _poses, symmetry_rmsd  # 复用已验收的结构检查。
from storage import file_record, new_id, now, read_json, write_json  # 使用统一编号、时间和指纹。


STUDY_ID = "study_26fce8e06ccc44a1a4fa7cefc8f789ba"  # 当前过敏性鼻炎流程测试研究。
VINA = {"scoring": "vina", "exhaustiveness": 8, "num_modes": 9, "energy_range_kcal_mol": 3, "seed": 1}  # 用户批准的固定参数。
COMPOUNDS = [  # 七个成分保持A03_SELECT顺序。
    ("MOL000098", "quercetin", "5280343"),  # 槲皮素。
    ("MOL000422", "kaempferol", "5280863"),  # 山柰酚。
    ("MOL000173", "wogonin", "5281703"),  # 汉黄芩素。
    ("MOL000378", "7-O-methylisomucronulatol", "15689652"),  # 黄芪候选。
    ("MOL000354", "isorhamnetin", "5281654"),  # 异鼠李素。
    ("MOL000392", "formononetin", "5280378"),  # 芒柄花素。
    ("MOL000049", "3β-acetoxyatractylone", "177825605"),  # 白术代表成分。
]  # 完成成分清单。
TARGETS = ["TP53", "JUN", "AKT1", "TNF", "HSP90AA1", "IL6", "ESR1", "IL1B", "BCL2", "MAPK1"]  # PPI顺序不可按评分重排。
TARGET_IDS = {"TP53": "HGNC:11998", "JUN": "HGNC:6204", "AKT1": "HGNC:391", "TNF": "HGNC:11892", "HSP90AA1": "HGNC:5253", "IL6": "HGNC:6018", "ESR1": "HGNC:3467", "IL1B": "HGNC:5992", "BCL2": "HGNC:990", "MAPK1": "HGNC:6871"}  # 稳定基因身份。


def _copy(source, target):  # 复制输入并拒绝覆盖。
    target.parent.mkdir(parents=True, exist_ok=True)  # 创建当前版本目录。
    require(not target.exists(), "目标文件已存在：" + str(target))  # 历史版本不可覆盖。
    shutil.copy2(source, target)  # 保留文件字节和时间信息。
    return target  # 返回新研究内路径。


def _write_text(path, text, encoding="utf-8"):  # 保存不可覆盖文本。
    path.parent.mkdir(parents=True, exist_ok=True)  # 按需建立目录。
    with path.open("x", encoding=encoding, newline="\n") as stream:  # 已存在时停止。
        stream.write(text)  # 原样保存内容。
    return path  # 返回实际文件。


def _run(arguments, cwd, stdout_path, stderr_path):  # 运行外部程序并完整保存日志。
    completed = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)  # 不把失败吞掉。
    _write_text(stdout_path, completed.stdout)  # 保存标准输出。
    _write_text(stderr_path, completed.stderr)  # 保存标准错误。
    return completed  # 调用方按真实退出状态处理。


def _protein_pdb(source, chains, altloc=None):  # 从官方PDB提取指定蛋白链。
    rows = []  # 收集唯一模型中的蛋白坐标。
    for line in source.read_text("ascii", errors="strict").splitlines():  # PDB官方文件为ASCII。
        if line.startswith("MODEL") and rows:  # 不合并多个模型。
            break  # 首模型结束后停止。
        if line.startswith("ATOM  ") and line[21:22] in chains:  # 只保留指定链的蛋白原子。
            require(line[16:17] == " " or altloc is not None, "存在未审定替代构象，需人工选择：" + source.name)  # 不自动采用A构象。
            if line[16:17] not in (" ", altloc):  # 不混合替代构象。
                continue  # 跳过非选定构象。
            rows.append(line[:16] + " " + line[17:] if line[16:17] == altloc else line)  # 选定构象转为空标记。
    require(rows, "受体没有可用蛋白原子：" + source.name)  # 空结构不能继续。
    return "\n".join(rows + ["TER", "END"]) + "\n"  # 写成单模型蛋白PDB。


def _ligand_lines(source, code, chain, sequence, altloc=None):  # 精确提取共晶参考配体。
    selected = []  # 收集指定残基的坐标行。
    for line in source.read_text("ascii", errors="strict").splitlines():  # 保持官方坐标精度。
        if line.startswith("HETATM") and line[17:20].strip() == code and line[21:22] == chain and line[22:26].strip() == str(sequence):  # 四项身份同时匹配。
            require(line[16:17] == " " or altloc is not None, "存在未审定替代构象，需人工选择：" + source.name)  # 不自动采用A构象。
            if line[16:17] not in (" ", altloc):  # 不混合替代构象。
                continue  # 跳过非选定构象。
            selected.append(line[:16] + " " + line[17:] if line[16:17] == altloc else line)  # 消除已选构象标记。
    require(selected, f"未找到参考配体{code} {chain}:{sequence}")  # 不能猜测其他小分子。
    serials = {int(line[6:11]) for line in selected}  # 保存选中原子号。
    conect = []  # 只保留选中原子内部的连接记录。
    for line in source.read_text("ascii", errors="strict").splitlines():  # 第二遍读取连接表。
        if line.startswith("CONECT"):  # 解析PDB连接记录。
            values = [int(line[index:index + 5]) for index in range(6, len(line), 5) if line[index:index + 5].strip()]  # 提取原子序号。
            if values and values[0] in serials:  # 连接必须从选中原子出发。
                kept = [values[0]] + [value for value in values[1:] if value in serials]  # 去除与环境的连接。
                if len(kept) > 1:  # 至少保留一条内部键。
                    conect.append("CONECT" + "".join(f"{value:5d}" for value in kept))  # 恢复固定列格式。
    return "\n".join(selected + conect + ["END"]) + "\n"  # 返回单一参考配体PDB。


def _box_from_lines(pdb_text):  # 以参考配体重原子外包络向各方向外扩5埃。
    coordinates = []  # 收集非氢坐标。
    for line in pdb_text.splitlines():  # 读取固定列。
        if line.startswith("HETATM") and line[76:78].strip().upper() not in {"H", "D"}:  # 氢不决定搜索盒。
            coordinates.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))  # 保存XYZ。
    require(coordinates, "参考配体没有重原子坐标")  # 禁止空盒。
    lows = [min(row[index] for row in coordinates) for index in range(3)]  # 计算三轴最小值。
    highs = [max(row[index] for row in coordinates) for index in range(3)]  # 计算三轴最大值。
    center = [round((lows[index] + highs[index]) / 2, 3) for index in range(3)]  # 中心保留三位小数。
    size = [round(highs[index] - lows[index] + 10.0, 3) for index in range(3)]  # 两侧各外扩5埃。
    return {"center": center, "size": size}  # 返回可复算盒参数。


def _meeko_settings():  # 显式固定当前Meeko全部参数。
    from meeko import MoleculePreparation  # 读取实际版本签名。
    signature = inspect.signature(MoleculePreparation)  # 获取全部构造参数。
    settings = {}  # 保存每一个参数。
    for name, parameter in signature.parameters.items():  # 不遗漏新增参数。
        require(parameter.default is not inspect.Parameter.empty, "Meeko出现无默认值的新参数：" + name)  # 版本变化时停止。
        settings[name] = parameter.default  # 固定当前默认值为本次配置事实。
    return settings  # 交给既有准备内核核对完整性。


def _prepare_compounds(root, study, folder):  # 将七个PubChem三维结构转换为PDBQT。
    raw = study / "raw"  # 原始下载集中保存。
    prepared = {}  # 按稳定成分编号索引。
    settings = _meeko_settings()  # 一次取得完整参数。
    for compound_id, name, cid in COMPOUNDS:  # 按用户确认顺序处理。
        sdf = raw / f"{compound_id}_pubchem_cid{cid}_3d_20261007.sdf"  # 唯一原始结构。
        properties = raw / f"{compound_id}_pubchem_cid{cid}_properties_20261007.json"  # 官方身份响应。
        data = read_json(properties)["PropertyTable"]["Properties"][0]  # 读取唯一CID记录。
        require(str(data["CID"]) == cid, "PubChem CID不一致：" + compound_id)  # 防止下载错对象。
        try:  # 单个结构身份失败时保留该成分但不阻断其余成分。
            prepared_value = prepare_ligand(sdf.read_text("utf-8"), cid, data["InChIKey"], settings)  # 完成身份和三维准备。
            target = folder / "ligands" / f"{compound_id}_{cid}.pdbqt"  # 当前研究专属配体输入。
            _write_text(target, prepared_value["pdbqt_text"], "ascii")  # 保存Meeko结果。
            prepared[compound_id] = {"compound_id": compound_id, "name": name, "cid": cid, "inchi_key": data["InChIKey"], "pdbqt": target, "sdf": sdf, "properties": properties, "status": "ready"}  # 保存来源与输入。
        except Exception as error:  # 错误结构不得进入Vina。
            prepared[compound_id] = {"compound_id": compound_id, "name": name, "cid": cid, "inchi_key": data["InChIKey"], "sdf": sdf, "properties": properties, "status": "failed", "error": str(error)}  # 十个计划组合随后均保留为NA。
    return prepared  # 返回七个可对接配体。


def _prepare_receptor_cli(root, pdb_text, box, label, folder):  # 用固定Meeko版本准备一个受体。
    input_path = folder / "receptors" / f"{label}_input.pdb"  # 保存当前研究使用的蛋白坐标。
    _write_text(input_path, pdb_text, "ascii")  # 不覆盖写入。
    output_base = folder / "receptors" / label  # Meeko输出稳定前缀。
    packages = root / "environments" / "docking_packages"  # 固定隔离依赖。
    environment = dict(**__import__("os").environ)  # 复制当前环境避免污染父进程。
    environment["PYTHONPATH"] = str(packages)  # 只加载项目固定包。
    arguments = [sys.executable, "-m", "meeko.cli.mk_prepare_receptor", "--read_pdb", str(input_path), "-o", str(output_base), "-p", "--write_pdb", str(output_base) + "_prepared.pdb", "--box_center", *[str(value) for value in box["center"]], "--box_size", *[str(value) for value in box["size"]], "--delete_bad_res_from_box_radius", "0.0"]  # 缺失残基只允许在搜索盒外删除。
    completed = subprocess.run(arguments, cwd=folder, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)  # 保留真实失败。
    _write_text(folder / "receptors" / f"{label}_prepare_stdout.txt", completed.stdout)  # 保存工具输出。
    _write_text(folder / "receptors" / f"{label}_prepare_stderr.txt", completed.stderr)  # 保存诊断信息。
    output = Path(str(output_base) + ".pdbqt")  # Meeko刚性受体输出。
    require(completed.returncode == 0 and output.is_file() and output.stat().st_size > 0, "Meeko受体准备失败：" + label)  # 失败时不换参数。
    return output  # 返回当前研究受体文件。


def _vina_arguments(executable, receptor, ligand, box, output):  # 生成固定Vina命令。
    return [str(executable), "--receptor", str(receptor), "--ligand", str(ligand), "--center_x", str(box["center"][0]), "--center_y", str(box["center"][1]), "--center_z", str(box["center"][2]), "--size_x", str(box["size"][0]), "--size_y", str(box["size"][1]), "--size_z", str(box["size"][2]), "--scoring", VINA["scoring"], "--exhaustiveness", str(VINA["exhaustiveness"]), "--num_modes", str(VINA["num_modes"]), "--energy_range", str(VINA["energy_range_kcal_mol"]), "--seed", str(VINA["seed"]), "--out", str(output)]  # 参数顺序稳定。


def _current_redock(executable, receptor, reference_pdbqt, reference_sdf, box, label, folder):  # 在当前研究重新执行参考配体重对接。
    output = folder / "redocking" / f"{label}_redocked.pdbqt"  # 独立保存输出。
    output.parent.mkdir(parents=True, exist_ok=True)  # 创建诊断目录。
    command = _vina_arguments(executable, receptor, reference_pdbqt, box, output)  # 使用统一参数。
    completed = _run(command, folder, folder / "redocking" / f"{label}_stdout.txt", folder / "redocking" / f"{label}_stderr.txt")  # 实际执行并留痕。
    require(completed.returncode == 0 and output.is_file(), "参考配体重对接失败：" + label)  # 不沿用历史分数补齐。
    top = _poses(output.read_text("ascii"))[0]  # 只以Top-1计算质控RMSD。
    rmsd = symmetry_rmsd(reference_sdf.read_bytes(), reference_pdbqt.read_text("ascii"), top)["rmsd_angstrom"]  # 对称性校正重原子RMSD。
    return rmsd, output  # 返回真实数值和文件。


def _legacy_specs(root):  # 定义五个已具备可复算共晶输入的受体。
    old = root / "studies" / "study_28a9580bd87543c98892e3c7ce4d1426"  # 仅作为显式输入来源。
    d001 = old / "task_packages" / "D001_Yupingfengsan_COPD_10pairs_PyMOL"  # 两受体PDBQT来源。
    d002 = old / "task_packages" / "D002_Yupingfengsan_COPD_15pairs_extension_candidate_retry1"  # 三受体完整来源。
    prep = old / "runs" / "A06_PREP" / "run_a3d6a783a9624128b1b092bb5fbde855"  # AKT1和MAPK1参考配体来源。
    return {  # 每项都明确PDB、链、参考配体和搜索盒。
        "AKT1": {"pdb": "3O96", "chains": ["A"], "reference": "IQO A:444", "box": {"center": [9.657, -7.761, 10.604], "size": [17.712, 25.771, 22.332]}, "receptor": d001 / "04_pairs" / "P01_AKT1_MOL000098_quercetin" / "input" / "receptor.pdbqt", "ref_pdbqt": prep / "AKT1_3O96_IQO_reference.pdbqt", "ref_sdf": prep / "AKT1_3O96_IQO_reference.sdf"},  # AKT1。
        "TNF": {"pdb": "2AZ5", "chains": ["A", "B"], "reference": "307 A:1", "box": {"center": [-19.163, 74.451, 33.837], "size": [19.067, 18.231, 18.481]}, "receptor": d002 / "TNF_2AZ5.pdbqt", "ref_pdbqt": d002 / "TNF_2AZ5_reference.pdbqt", "ref_sdf": d002 / "TNF_2AZ5_reference.sdf"},  # TNF。
        "HSP90AA1": {"pdb": "4LWE", "chains": ["A"], "reference": "FJ2 A:301", "box": {"center": [-0.696, -36.031, -25.280], "size": [17.111, 17.889, 17.317]}, "receptor": d002 / "HSP90AA1_4LWE.pdbqt", "ref_pdbqt": d002 / "HSP90AA1_4LWE_reference.pdbqt", "ref_sdf": d002 / "HSP90AA1_4LWE_reference.sdf"},  # HSP90AA1。
        "ESR1": {"pdb": "5T92", "chains": ["A"], "reference": "77W A:601", "box": {"center": [-38.914, 7.523, -29.146], "size": [15.448, 20.305, 20.999]}, "receptor": d002 / "ESR1_5T92.pdbqt", "ref_pdbqt": d002 / "ESR1_5T92_reference.pdbqt", "ref_sdf": d002 / "ESR1_5T92_reference.sdf"},  # ESR1。
        "MAPK1": {"pdb": "1TVO", "chains": ["A"], "reference": "FRZ A:1001", "box": {"center": [6.487, -3.734, 17.175], "size": [20.033, 14.602, 17.358]}, "receptor": d001 / "04_pairs" / "P06_MAPK1_MOL000098_quercetin" / "input" / "receptor.pdbqt", "ref_pdbqt": prep / "MAPK1_1TVO_FRZ_reference.pdbqt", "ref_sdf": prep / "MAPK1_1TVO_FRZ_reference.sdf"},  # MAPK1。
    }  # 完成五个共晶输入定义。


def _prepare_receptors(root, study, folder, executable):  # 准备十个受体并完成当前研究重对接。
    receptors = {}  # 保存全部成功、失败和限制。
    for target, spec in _legacy_specs(root).items():  # 五个共晶输入复制后重新计算。
        label = f"{target}_{spec['pdb']}"  # 形成可读前缀。
        receptor = _copy(spec["receptor"], folder / "receptors" / f"{label}.pdbqt")  # 复制受体输入。
        ref_pdbqt = _copy(spec["ref_pdbqt"], folder / "receptors" / f"{label}_reference.pdbqt")  # 复制参考配体输入。
        ref_sdf = _copy(spec["ref_sdf"], folder / "receptors" / f"{label}_reference.sdf")  # 复制实验姿势。
        rmsd, redocked = _current_redock(executable, receptor, ref_pdbqt, ref_sdf, spec["box"], label, folder)  # 当前研究重新执行。
        receptors[target] = {**spec, "receptor": receptor, "ref_pdbqt": ref_pdbqt, "ref_sdf": ref_sdf, "rmsd": rmsd, "redocked": redocked, "status": "ready" if rmsd <= 2.0 else "redocking_failed"}  # 保存当前质控结论。
    predicted = {"TP53": ("7B46", study / "raw" / "pdb_7b46_rcsb_20261007.pdb", study / "runs" / "A06_PREP" / "p2rank_tp53_20261007" / "pocket.json"), "IL6": ("1ALU", study / "raw" / "pdb_1alu_rcsb_20261007.pdb", study / "runs" / "A06_PREP" / "p2rank_il6_20261007" / "pocket.json")}  # 两个可重复预测口袋。
    for target, (pdb_id, source, pocket_path) in predicted.items():  # 逐项准备预测口袋受体。
        pocket = read_json(pocket_path)  # 使用两次运行一致的固定记录。
        box = {"center": pocket["box"]["center"], "size": pocket["box"]["size"]}  # 不人工抄坐标。
        try:  # 结构准备失败时保留真实失败。
            receptor = _prepare_receptor_cli(root, _protein_pdb(source, {"A"}), box, f"{target}_{pdb_id}", folder)  # 使用链A和固定口袋。
            receptors[target] = {"pdb": pdb_id, "chains": ["A"], "reference": "无；P2Rank排名第一口袋", "box": box, "receptor": receptor, "rmsd": None, "status": "ready", "pocket": pocket_path}  # 无参考配体不伪造RMSD。
        except Exception as error:  # 受体准备失败不调参。
            receptors[target] = {"pdb": pdb_id, "chains": ["A"], "reference": "无；P2Rank排名第一口袋", "box": box, "rmsd": None, "status": "failed", "error": str(error), "pocket": pocket_path}  # 保存失败事实。
    receptors["JUN"] = {"pdb": "5T01", "chains": ["A", "B"], "reference": "无；P2Rank未形成口袋", "box": None, "rmsd": None, "status": "failed", "error": "固定版本P2Rank两次运行均未输出可用预测口袋，无法建立可复算搜索盒"}  # 七组保持NA。
    crystal = {"IL1B": ("8C3U", "T9C", "A", 201, False), "BCL2": ("6O0K", "LBM", "A", 301, True)}  # 新增共晶结构及限制。
    for target, (pdb_id, code, chain, sequence, chimera) in crystal.items():  # 逐项准备共晶受体。
        box = None  # 每个受体独立初始化搜索盒，避免沿用上一项。
        source = study / "raw" / f"pdb_{pdb_id.lower()}_rcsb_20261007.pdb"  # 使用本次官方原始文件。
        try:  # 任一步失败均保留NA。
            ligand_pdb = _ligand_lines(source, code, chain, sequence)  # 提取共晶姿势。
            box = _box_from_lines(ligand_pdb)  # 按批准规则建立搜索盒。
            receptor = _prepare_receptor_cli(root, _protein_pdb(source, {chain}), box, f"{target}_{pdb_id}", folder)  # 准备蛋白。
            ligand_pdb_path = folder / "receptors" / f"{target}_{pdb_id}_reference.pdb"  # 保存参考配体坐标。
            _write_text(ligand_pdb_path, ligand_pdb, "ascii")  # 形成可检查文件。
            from docking_reference_ligand import prepare_reference_ligand  # 使用已验收的官方CCD拓扑内核。
            ccd_path = study / "raw" / f"ccd_{code}_rcsb_20261007.cif"  # 显式绑定官方化学组件。
            require(ccd_path.is_file(), "缺少官方CCD拓扑：" + code)  # 不从空间距离猜键级。
            reference = prepare_reference_ligand(ccd_path.read_text("utf-8"), ligand_pdb, code, chain, sequence, _meeko_settings())  # 核对键级、手性和实验坐标。
            ref_sdf = _write_text(folder / "receptors" / f"{target}_{pdb_id}_reference.sdf", reference["sdf_text"], "ascii")  # 保存实验参考SDF。
            ref_pdbqt = _write_text(folder / "receptors" / f"{target}_{pdb_id}_reference.pdbqt", reference["pdbqt_text"], "ascii")  # 保存同源参考PDBQT。
            write_json(folder / "receptors" / f"{target}_{pdb_id}_reference_identity.json", {"identity": reference["identity"], "ccd_file": file_record(study, ccd_path, "chemical_component")})  # 保存参考身份证据。
            rmsd, redocked = _current_redock(executable, receptor, ref_pdbqt, ref_sdf, box, f"{target}_{pdb_id}", folder)  # 执行当前重对接。
            receptors[target] = {"pdb": pdb_id, "chains": [chain], "reference": f"{code} {chain}:{sequence}", "box": box, "receptor": receptor, "ref_pdbqt": ref_pdbqt, "ref_sdf": ref_sdf, "redocked": redocked, "rmsd": rmsd, "status": "ready" if rmsd <= 2.0 else "redocking_failed", "chimera": chimera}  # 保存结构限制。
        except Exception as error:  # 不自动换结构或参数。
            receptors[target] = {"pdb": pdb_id, "chains": [chain], "reference": f"{code} {chain}:{sequence}", "box": locals().get("box"), "rmsd": None, "status": "failed", "error": str(error), "chimera": chimera}  # 保留失败原因。
    return receptors  # 返回十项真实状态。


def _dock_pairs(root, study, folder, executable, compounds, receptors):  # 运行全部可执行组合并保留失败项。
    planned, completed, failed = [], [], []  # 三张表必须覆盖全部70组。
    for target in TARGETS:  # 受体顺序固定为PPI顺序。
        receptor = receptors[target]  # 读取本项准备状态。
        for compound_id, name, _ in COMPOUNDS:  # 成分保持A03_SELECT顺序。
            planned.append({"compound_id": compound_id, "target": target})  # 无论成功失败都登记计划。
            if compounds[compound_id].get("status") != "ready":  # 配体身份或准备失败时直接记录NA。
                failed.append({"compound_id": compound_id, "target": target, "reason": compounds[compound_id].get("error") or "配体未通过结构身份核查"})  # 不以错误立体结构计算。
                continue  # 处理下一组合。
            if receptor.get("status") != "ready":  # 没有可复算受体时直接记录NA。
                failed.append({"compound_id": compound_id, "target": target, "reason": receptor.get("error") or "受体参考配体重对接RMSD未通过2 Å质控"})  # 不补造评分。
                continue  # 处理下一组合。
            pair_label = f"{target}_{compound_id}"  # 使用稳定身份命名。
            pair_folder = folder / "pairs" / pair_label  # 每组使用独立目录。
            pair_folder.mkdir(parents=True, exist_ok=False)  # 禁止覆盖历史组合。
            output = pair_folder / "top9_poses.pdbqt"  # 保存全部Vina模式。
            command = _vina_arguments(executable, receptor["receptor"], compounds[compound_id]["pdbqt"], receptor["box"], output)  # 生成固定参数命令。
            command_path = pair_folder / "command.json"  # 保存迁移友好的命令事实。
            write_json(command_path, {"executable": "vina_1.2.7_win.exe", "parameters": VINA, "receptor": receptor["receptor"].name, "ligand": compounds[compound_id]["pdbqt"].name, "search_box": receptor["box"], "arguments": [str(value) for value in command]})  # 不依赖口头说明。
            process = _run(command, pair_folder, pair_folder / "stdout.txt", pair_folder / "stderr.txt")  # 执行并留存日志。
            if process.returncode != 0 or not output.is_file():  # 进程失败保持NA。
                failed.append({"compound_id": compound_id, "target": target, "reason": f"Vina执行失败，退出码{process.returncode}"})  # 明确失败原因。
                continue  # 不读取残缺文件。
            try:  # 对全部姿势执行一致检查。
                poses = _poses(output.read_text("ascii"))  # 解析九个模式。
                input_atoms = _input_atoms(compounds[compound_id]["pdbqt"].read_text("ascii"))  # 固定配体身份。
                expected_heavy = sum(atom_type not in ("H", "HD", "G0") for atom_type in input_atoms.values())  # 计算真实重原子数。
                valid = []  # 收集同时通过身份和盒内检查的姿势。
                for pose in poses:  # 不只检查Top-1。
                    identity = _pose_identity(pose, input_atoms, expected_heavy)  # 核对原子身份。
                    inside = _inside_box(pose, {"center_angstrom": receptor["box"]["center"], "size_angstrom": receptor["box"]["size"]})  # 检查盒边界。
                    if identity["passed"] and inside["passed"]:  # 两项同时通过才可评分。
                        valid.append(pose)  # 保留原始模式顺序。
                require(valid, "没有同时通过身份和搜索盒检查的姿势")  # 空结果不伪造分数。
                require(poses[0] in valid and poses[0]["mode"] == 1, "Top-1未通过姿势检查，不以其他模式替代")  # 严格固定第一姿势。
                chosen = poses[0]  # 热图与出图使用同一Top-1。
                distance = _minimum_receptor_distance(receptor["receptor"].read_text("ascii"), chosen)  # 报告最近重原子距离。
                top1 = pair_folder / "selected_top1_pose.pdbqt"  # 任务包固定姿势文件。
                first_model = output.read_text("ascii").split("ENDMDL", 1)[0] + "ENDMDL\n"  # 截取唯一第一模型。
                require(len(_poses(first_model)) == 1, "固定姿势文件必须只有一个模式")  # 阻止九模式冒充单姿势。
                _write_text(top1, first_model, "ascii")  # 全部九个模式仍留在原始输出。
                completed.append({"compound_id": compound_id, "compound_name": name, "target": target, "score_kcal_mol": chosen["score_kcal_mol"], "selected_mode": chosen["mode"], "pose_count": len(poses), "valid_pose_count": len(valid), "minimum_receptor_distance_A": distance, "pose_record": file_record(study, top1, "selected_pose"), "receptor_record": file_record(study, receptor["receptor"], "receptor"), "ligand_record": file_record(study, compounds[compound_id]["pdbqt"], "ligand"), "command_record": file_record(study, command_path, "command"), "log_record": file_record(study, pair_folder / "stdout.txt", "log")})  # 保存完整追溯。
            except Exception as error:  # 校验失败保持NA且保留原始输出。
                failed.append({"compound_id": compound_id, "target": target, "reason": str(error)})  # 不自动调参重跑。
    return planned, completed, failed  # 返回覆盖全部计划的事实。


def execute(root):  # 完成当前研究的70组候选事实包。
    root = Path(root).resolve()  # 固定项目根目录。
    study = root / "studies" / STUDY_ID  # 所有资料留在独立研究包。
    require(study.is_dir(), "当前研究不存在")  # 防止误建到其他目录。
    run_id = new_id("run")  # 新执行使用独立编号。
    folder = study / "runs" / "A06_PREP" / run_id  # 先落入准备阶段，发布时另建A06。
    folder.mkdir(parents=True, exist_ok=False)  # 禁止覆盖既有筛查和核查记录。
    executable = root / "environments" / "vina_1.2.7" / "vina_1.2.7_win.exe"  # 固定Vina版本。
    require(executable.is_file(), "缺少固定Vina 1.2.7程序")  # 不用系统其他版本替代。
    write_json(folder / "execution.json", {"schema_version": "A06.top10.execution.1", "study_id": STUDY_ID, "run_id": run_id, "analysis_purpose": "workflow_test", "started_at": now(), "ppi_window": TARGETS, "compound_count": len(COMPOUNDS), "planned_pair_count": len(TARGETS) * len(COMPOUNDS), "vina_parameters": VINA})  # 执行前固定范围。
    compounds = _prepare_compounds(root, study, folder)  # 准备七个配体。
    receptors = _prepare_receptors(root, study, folder, executable)  # 准备十个受体并重对接。
    strict_passed = [target for target in TARGETS if target in {"AKT1", "TNF", "HSP90AA1", "ESR1", "IL1B", "MAPK1"} and receptors[target].get("status") == "ready" and receptors[target].get("rmsd") is not None and receptors[target]["rmsd"] <= 2.0]  # 按PPI顺序选严格质控受体。
    require(len(strict_passed) >= 5, "严格质控受体不足5个；不得发布主要结果")  # 不自动检查第11至15位。
    primary = strict_passed[:5]  # 主要结论只取PPI顺序前五个严格通过者。
    planned, completed, failed = _dock_pairs(root, study, folder, executable, compounds, receptors)  # 运行可执行组合。
    receptor_rows = []  # 建立报告受体事实表。
    limitations = {"TP53": "使用P2Rank预测口袋，无共晶参考配体，不能进行重对接RMSD质控。", "JUN": "固定版本P2Rank未输出可用口袋，未建立搜索盒，相关组合为NA。", "IL6": "使用P2Rank预测口袋，无共晶参考配体，不能进行重对接RMSD质控。", "BCL2": "当前结构含工程化嵌合设计，数值仅作探索线索。"}  # 集中定义关键限制。
    for rank, target in enumerate(TARGETS, 1):  # 按PPI顺序形成十行。
        value = receptors[target]  # 读取真实结构状态。
        box = value.get("box") if value.get("status") == "ready" or value.get("rmsd") is not None else None  # 准备失败的可用搜索盒留空，尝试值保留在命令记录。
        redocking_status = "passed" if value.get("rmsd") is not None and value.get("rmsd") <= 2.0 else ("not_applicable_no_reference_ligand" if value.get("status") == "ready" and value.get("rmsd") is None else ("failed_not_computable" if value.get("rmsd") is None else "failed"))  # 区分预测口袋不适用和真实失败。
        receptor_rows.append({"target": target, "pdb_id": value["pdb"], "chains": value["chains"], "reference_ligand": value["reference"], "center": box["center"] if box else None, "size": box["size"] if box else None, "redocking_rmsd_A": value.get("rmsd"), "qc_status": "严格质控通过" if target in strict_passed else ("探索性可运行" if value.get("status") == "ready" else "失败，组合为NA"), "ppi_rank": rank, "pocket_basis": "共晶参考配体位置并各方向外扩5 Å" if value.get("rmsd") is not None else ("P2Rank 2.5排名第一预测口袋" if value.get("status") == "ready" else "未形成可复算搜索盒"), "structure_limitation": limitations.get(target, "当前研究已完成参考配体重对接；结构质控不等同于实验结合证据。"), "interpretation_scope": "主要结果" if target in primary else ("扩展或探索线索" if value.get("status") == "ready" else "不得解释结合能"), "primary_result": target in primary, "redocking_status": redocking_status})  # 不在热图显示等级。
    generic = {"contract_version": "A06.generic.result.2", "outcome": "partial" if failed else "success", "analysis_purpose": "workflow_test", "compounds": [{"compound_id": item[0], "name": item[1], "pubchem_cid": item[2]} for item in COMPOUNDS], "receptors": receptor_rows, "planned_pairs": planned, "completed_pairs": completed, "failed_pairs": failed, "primary_targets": primary, "strict_qc_passed_targets": strict_passed, "vina_parameters": VINA, "automatic_parameter_tuning": False}  # 形成动态契约事实。
    write_json(folder / "execution_facts.json", generic)  # 校验前保存计算事实，校验失败也不丢失运行证据。
    validate_generic_result(generic)  # 发布前独立核对70组覆盖和文件记录。
    result_path = folder / "generic_docking.json"  # 保存候选事实包。
    write_json(result_path, generic)  # 不覆盖写入。
    write_json(folder / "receptor_limitations.json", receptor_limitation_table(generic))  # 保存热图后中文说明表。
    write_json(folder / "receptor_setup.json", receptor_setup_table(generic))  # 保存对接空间参数表。
    write_json(folder / "score_matrix.json", score_matrix_table(generic))  # 保存动态矩阵。
    write_json(folder / "completion.json", {"finished_at": now(), "strict_qc_passed": strict_passed, "primary_targets": primary, "planned_pairs": len(planned), "completed_pairs": len(completed), "failed_pairs": len(failed), "published": False})  # 保存执行完成状态。
    return result_path  # 后续发布与制图只读取该明确文件。


if __name__ == "__main__":  # 提供明确项目根目录入口。
    import argparse  # 解析命令行参数。
    parser = argparse.ArgumentParser(description="执行PPI前十位和七成分的动态分子对接")  # 说明用途。
    parser.add_argument("--root", required=True)  # 项目根目录必须明确。
    arguments = parser.parse_args()  # 读取参数。
    print(execute(arguments.root))  # 输出候选事实包位置。
