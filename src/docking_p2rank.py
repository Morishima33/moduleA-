# P2Rank预测口袋适配器；固定首位口袋并从相邻残基原子范围建立搜索盒。
import csv  # 读取P2Rank官方预测表。
import hashlib  # 核对重复运行和工具包指纹。
import math  # 检查坐标与尺寸均为有限值。
from pathlib import Path  # 管理固定版本工具和输出目录。
import re  # 解析P2Rank残基身份。
import subprocess  # 以参数列表调用固定P2Rank版本。

from contracts import require  # 复用项目统一阻断规则。
from storage import file_record, now, write_json  # 保存来源、版本和运行记录。


SCHEMA_VERSION = "A06.p2rank.pocket.1"  # 首个预测口袋追溯结构。
P2RANK_VERSION = "2.5"  # 使用稳定版，不采用2.6 alpha。


def _sha256(path):  # 计算工具或原始输出指纹。
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()  # 逐字节计算SHA256。


def _prediction_rows(path):  # 读取官方CSV并按rank稳定排序。
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:  # P2Rank输出为UTF-8 CSV。
        rows = [{str(key).strip(): str(value).strip() for key, value in row.items()} for row in csv.DictReader(stream)]  # 清理字段空白。
    require(rows, "P2Rank没有输出任何预测口袋")  # 空预测不能建立搜索盒。
    required = {"rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids"}  # 可复算首位口袋所需字段。
    require(required <= set(rows[0]), "P2Rank预测表缺少必要字段")  # 不猜列名或列位置。
    return sorted(rows, key=lambda row: int(row["rank"]))  # 官方rank决定口袋顺序。


def _pdb_atoms(pdb_text):  # 读取PDB中可用于口袋包络的蛋白重原子。
    atoms = []  # 保存链、残基、原子名及三维坐标。
    for line in pdb_text.splitlines():  # PDB固定列便于与P2Rank残基标识对应。
        if not line.startswith("ATOM  "):  # 只使用蛋白原子，不让配体或水扩大搜索盒。
            continue  # 跳过非蛋白记录。
        element = line[76:78].strip().upper() if len(line) >= 78 else ""  # 读取元素字段。
        if element == "H":  # 氢不决定口袋几何包络。
            continue  # 跳过氢原子。
        chain = line[21:22].strip()  # 使用作者链标识。
        residue = line[22:27].strip()  # 保留插入码以避免错位。
        xyz = [float(line[30:38]), float(line[38:46]), float(line[46:54])]  # 读取三维坐标。
        require(all(math.isfinite(value) for value in xyz), "PDB含无效原子坐标")  # 坏结构立即停止。
        atoms.append({"chain": chain, "residue": residue, "atom": line[12:16].strip(), "xyz": xyz})  # 保存可追溯身份。
    require(atoms, "PDB没有可用蛋白重原子")  # 空蛋白不能预测口袋。
    return atoms  # 返回全部重原子。


def _residue_keys(value):  # 将P2Rank残基列表转换为链与残基编号集合。
    keys = set()  # 使用集合避免重复残基扩大统计。
    for token in re.split(r"[\s,;]+", str(value).strip()):  # 兼容空格、逗号和分号分隔。
        if not token:  # 跳过空片段。
            continue  # 继续解析。
        match = re.match(r"^([^_:\s]+)[_:](-?\d+[A-Za-z]?)$", token)  # 接受A_45或A:45等官方常见形式。
        if match:  # 只接收身份明确的条目。
            keys.add((match.group(1), match.group(2)))  # 保存作者链与残基号。
    require(keys, "P2Rank首位口袋残基标识无法解析")  # 不用中心加固定尺寸代替真实包络。
    return keys  # 返回唯一残基集合。


def box_from_prediction(pdb_text, prediction_row, padding=5.0):  # 从首位口袋相邻残基重原子建立外包络搜索盒。
    require(isinstance(padding, (int, float)) and math.isfinite(padding) and padding > 0, "口袋外扩值必须是正数")  # 不使用隐式默认值。
    keys = _residue_keys(prediction_row["residue_ids"])  # 解析官方预测残基。
    atoms = [row for row in _pdb_atoms(pdb_text) if (row["chain"], row["residue"]) in keys]  # 只取首位口袋相邻残基。
    require(atoms, "P2Rank首位口袋残基在输入PDB中没有匹配原子")  # 身份不一致时停止。
    lower = [min(row["xyz"][axis] for row in atoms) for axis in range(3)]  # 计算每个方向下界。
    upper = [max(row["xyz"][axis] for row in atoms) for axis in range(3)]  # 计算每个方向上界。
    center = [round((low + high) / 2, 3) for low, high in zip(lower, upper)]  # 中心来自真实原子范围。
    size = [round(high - low + 2 * padding, 3) for low, high in zip(lower, upper)]  # 每侧外扩5 Å。
    require(all(value > 0 for value in size), "预测口袋搜索盒尺寸无效")  # 非正盒子不能运行Vina。
    reported_center = [float(prediction_row[key]) for key in ("center_x", "center_y", "center_z")]  # 保存P2Rank直接报告的中心供复核。
    require(all(math.isfinite(value) for value in reported_center), "P2Rank报告的口袋中心无效")  # 防止坏CSV进入记录。
    return {"center": center, "size": size, "padding_angstrom": float(padding), "envelope_atom_count": len(atoms), "adjacent_residue_count": len(keys), "adjacent_residues": [f"{chain}:{residue}" for chain, residue in sorted(keys)], "p2rank_reported_center": reported_center, "box_rule": "adjacent_residue_heavy_atom_envelope_plus_5A_each_side"}  # 返回完整计算依据。


def run_twice(tool_dir, pdb_path, output_dir, target, root):  # 重复运行P2Rank并确认首位口袋完全一致。
    tool_dir = Path(tool_dir).resolve()  # 固定工具目录。
    pdb_path = Path(pdb_path).resolve()  # 固定输入蛋白。
    output_dir = Path(output_dir).resolve()  # 固定本次研究输出目录。
    root = Path(root).resolve()  # 文件记录相对于项目根目录。
    require((tool_dir / "prank.bat").is_file(), "未找到固定P2Rank prank.bat")  # Windows入口必须存在。
    require(pdb_path.is_file(), "P2Rank输入PDB不存在")  # 不创建空运行。
    output_dir.mkdir(parents=True, exist_ok=False)  # 新版本禁止覆盖。
    runs = []  # 保存两次独立结果。
    for repeat in (1, 2):  # 重复运行验证确定性。
        folder = output_dir / f"repeat_{repeat}"  # 两次原始输出分开保存。
        command = [str(tool_dir / "prank.bat"), "predict", "-f", str(pdb_path), "-threads", "1", "-visualizations", "0", "-o", str(folder)]  # 单线程固定输入和输出。
        completed = subprocess.run(command, cwd=tool_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)  # 超时不自动重试改参。
        write_json(output_dir / f"repeat_{repeat}_execution.json", {"command": command, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "finished_at": now()})  # 原始日志完整留存。
        require(completed.returncode == 0, f"P2Rank第{repeat}次运行失败")  # 部分文件不能冒充成功。
        predictions = list(folder.rglob("*_predictions.csv"))  # 官方每个输入生成唯一预测表。
        require(len(predictions) == 1, f"P2Rank第{repeat}次预测表数量不唯一")  # 不按时间选择文件。
        first = _prediction_rows(predictions[0])[0]  # 固定采用rank=1口袋。
        require(int(first["rank"]) == 1, "P2Rank首行不是排名第一口袋")  # 不接受错序输出。
        runs.append({"prediction_file": predictions[0], "first": first})  # 保存实际路径和首位记录。
    keys = ("rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids")  # 影响口袋和搜索盒的字段必须一致。
    require(all(runs[0]["first"][key] == runs[1]["first"][key] for key in keys), "P2Rank两次运行首位口袋不一致")  # 非确定结果停止。
    pdb_text = pdb_path.read_text(encoding="ascii", errors="strict")  # 使用实际输入结构计算搜索盒。
    box = box_from_prediction(pdb_text, runs[0]["first"], 5.0)  # 应用已批准的包络规则。
    record = {"schema_version": SCHEMA_VERSION, "target": target, "p2rank_version": P2RANK_VERSION, "tool_sha256": _sha256(tool_dir / "prank.bat"), "input_pdb": file_record(root, pdb_path, "p2rank_input_pdb"), "selected_pocket_rank": 1, "score": float(runs[0]["first"]["score"]), "probability": float(runs[0]["first"]["probability"]), "box": box, "repeat_consistent": True, "redocking_status": "not_applicable_no_reference_ligand", "files": [file_record(root, run["prediction_file"], "p2rank_prediction") for run in runs] + [file_record(root, output_dir / f"repeat_{repeat}_execution.json", "p2rank_execution") for repeat in (1, 2)], "created_at": now()}  # 形成完整追溯记录。
    write_json(output_dir / "pocket.json", record)  # 保存不可覆盖口袋事实。
    return record  # 交给A06_PREP组装器。
