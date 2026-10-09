# A06已完成对接出图任务包；把已核验姿势整理为PyMOL可直接使用的固定文件。
from hashlib import sha256  # 为任务包内每个文件生成可核对指纹。
from html import escape  # 防止研究名称进入HTML后破坏页面。
from pathlib import Path  # 安全处理项目内文件位置。
import json  # 读取对接记录并保存任务索引。
import shutil  # 复制已经核验的原始文件，不改写原件。
import subprocess  # 调用现有PyMOL生成合并结构和会话文件。

from contracts import require  # 使用项目统一的可读错误。
from storage import read_json, verified_file  # 每次读取前核验来源文件指纹。


PACKAGE_ID = "D001"  # 首个对接出图任务包使用稳定编号，后续只递增不改号。
PACKAGE_SCHEMA = "A06.visualization.task.package.1"  # 标识任务包结构版本。
PYMOL_EXE = Path("D:/pymol/Scripts/pymol.exe")  # 沿用用户此前确认的PyMOL 3.1.6.1环境。
TARGET_ORDER = ("AKT1", "MAPK1")  # 本包只含已经完成且通过检查的两个受体。
COMPOUND_ORDER = ("MOL000098", "MOL000422", "MOL000378", "MOL000173", "MOL000358")  # 沿用A03_SELECT确认顺序。


def _digest(path):  # 计算单个文件SHA-256供回传核对。
    return sha256(path.read_bytes()).hexdigest()  # 按原始字节计算，不受文件名影响。


def _write_new(path, content, encoding="utf-8"):  # 新文件只允许首次创建，避免覆盖任务历史。
    path.parent.mkdir(parents=True, exist_ok=True)  # 仅创建当前任务包所需父目录。
    with path.open("x", encoding=encoding, newline="") as stream:  # 已存在时直接停止。
        stream.write(content)  # 一次写入完整内容。


def _selected_pose(text, mode):  # 从多姿势Vina输出中抽取指定模式原文。
    lines = text.splitlines()  # 按原始行识别MODEL区段。
    selected = []  # 保存目标模式全部记录。
    active = False  # MODEL之外的内容不属于选定姿势。
    for line in lines:  # 顺序遍历保证坐标与备注原样保留。
        if line.startswith("MODEL "):  # 遇到一个新姿势。
            active = int(line.split()[1]) == mode  # 只接收已核验模式号。
        if active:  # 目标姿势内的行全部保存。
            selected.append(line)  # 保留Vina评分、坐标和原子类型。
        if active and line.startswith("ENDMDL"):  # 目标姿势完整结束。
            break  # 不读取其他模式。
    require(selected and selected[0].startswith("MODEL ") and selected[-1].startswith("ENDMDL"), "无法从Vina输出提取选定姿势")  # 截断文件不能交付。
    return "\n".join(selected) + "\n"  # 使用标准文本结尾便于PyMOL读取。


def _pml(pair_id):  # 生成纯ASCII脚本，避免PyMOL读取中文脚本失败。
    return f'''load receptor.pdbqt, protein
load selected_pose.pdbqt, ligand
hide everything
show cartoon, protein
color lightblue, protein
show sticks, ligand
color orange, ligand
select nearby_residues, byres (protein within 4.0 of ligand)
show sticks, nearby_residues
color hotpink, nearby_residues
distance polar_distance_contacts, (ligand and (elem N or elem O)), (protein and (elem N or elem O)), 3.5
color red, polar_distance_contacts
set dash_width, 2.5
set label_color, black
python
from pymol import cmd
import math
lig_atoms = cmd.get_model('ligand and (elem N or elem O)', state=1).atom
pro_atoms = cmd.get_model('protein and (elem N or elem O)', state=1).atom
contact_rows = []
for lig_atom in lig_atoms:
    for pro_atom in pro_atoms:
        dx = lig_atom.coord[0] - pro_atom.coord[0]
        dy = lig_atom.coord[1] - pro_atom.coord[1]
        dz = lig_atom.coord[2] - pro_atom.coord[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        if distance <= 3.5:
            contact_rows.append((distance, lig_atom.name, pro_atom.name, pro_atom.resn, pro_atom.resi, pro_atom.chain))
contact_rows.sort()
with open('hbond_info.txt', 'w') as contact_file:
    contact_file.write('classification=N_O_distance_contact_not_confirmed_hydrogen_bond\\n')
    contact_file.write('cutoff_angstrom=3.5\\n')
    contact_file.write('count=%d\\n' % len(contact_rows))
    for row in contact_rows:
        contact_file.write('%.3f|lig:%s|pro:%s|res:%s%s|chain:%s\\n' % row)
python end
bg_color white
orient ligand
zoom ligand, 12
save session_{pair_id}.pse
save result_{pair_id}.pdb, (protein or ligand)
'''


def _launcher(pair_id):  # 生成双击脚本，把文件复制到英文目录再打开可见PyMOL。
    return f'''@chcp 65001 >nul
@echo off
set "WORK=D:\\docking_viz\\{PACKAGE_ID}\\{pair_id}"
if not exist "%WORK%" mkdir "%WORK%"
copy /Y "%~dp0receptor.pdbqt" "%WORK%\\receptor.pdbqt" >nul
copy /Y "%~dp0selected_pose.pdbqt" "%WORK%\\selected_pose.pdbqt" >nul
copy /Y "%~dp001_open_in_pymol.pml" "%WORK%\\01_open_in_pymol.pml" >nul
if not exist "%WORK%\\figures" mkdir "%WORK%\\figures"
cd /d "%WORK%"
"D:\\pymol\\Scripts\\pymol.exe" -r "01_open_in_pymol.pml"
'''


def _collect_launcher(pair_ids):  # 生成把用户图片从英文工作目录收回项目包的脚本。
    lines = ["@chcp 65001 >nul", "@echo off", "setlocal", f'set "SOURCE=D:\\docking_viz\\{PACKAGE_ID}"']  # 固定本包英文工作根目录。
    for pair_id in pair_ids:  # 每组复制回自己的figures文件夹。
        lines.append(f'if exist "%SOURCE%\\{pair_id}\\figures\\*" xcopy /Y /I "%SOURCE%\\{pair_id}\\figures\\*" "%~dp004_pairs\\{pair_id}\\figures\\" >nul')  # 不覆盖任务输入。
        lines.append(f'if exist "%SOURCE%\\{pair_id}\\session_{pair_id}.pse" copy /Y "%SOURCE%\\{pair_id}\\session_{pair_id}.pse" "%~dp004_pairs\\{pair_id}\\pymol\\session_{pair_id}_returned.pse" >nul')  # 会话另存为returned避免覆盖初始会话。
    lines.extend(["echo 图片和PyMOL会话已收回任务包。", "pause", "endlocal"])  # 给普通用户明确完成提示。
    return "\n".join(lines) + "\n"  # Windows批处理使用普通换行也可执行。


def _build_session(stage, pair_id):  # 在纯英文临时目录调用PyMOL生成合并PDB和初始会话。
    command = [str(PYMOL_EXE), "-cq", "01_open_in_pymol.pml"]  # 无界面执行固定脚本。
    result = subprocess.run(command, cwd=stage, capture_output=True, text=True, errors="replace", timeout=120)  # 记录退出状态并限制等待时间。
    require(result.returncode == 0, "PyMOL生成任务文件失败：" + pair_id)  # 失败时不发布半成品包。
    require((stage / f"result_{pair_id}.pdb").is_file() and (stage / f"session_{pair_id}.pse").is_file(), "PyMOL未生成合并结构或会话：" + pair_id)  # 两种关键格式都必须存在。
    return result.stdout + "\n" + result.stderr  # 保存实际程序输出供追溯。


def build(root, study_id, a06_run_id):  # 从当前已批准A06生成不可覆盖的十组出图任务包。
    root = Path(root).resolve()  # 固定项目根目录。
    require(PYMOL_EXE.is_file(), "未找到已确认的PyMOL程序：" + str(PYMOL_EXE))  # 缺软件时不声称任务可直接使用。
    study = root / "studies" / study_id  # 定位明确研究包。
    manifest = read_json(study / "manifest.json")  # 读取研究当前版本索引。
    require(manifest.get("current", {}).get("A06") == a06_run_id, "指定A06不是当前版本")  # 避免从过期结果建包。
    run = manifest["runs"][a06_run_id]  # 读取当前A06运行记录。
    result = read_json(verified_file(study, run["result_file"]))  # 验证标准结果文件指纹。
    require(result.get("outcome") == "success" and result.get("summary", {}).get("成功组合数") == 10, "当前A06不是十组完整结果")  # 只接受本次已完成结果。
    matrix = {(row["compound_id"], target): row[target] for row in result["tables"]["score_matrix"] for target in TARGET_ORDER}  # 建立热图评分索引。
    valid_poses = [row for row in result["tables"]["pose_scores"] if row.get("纳入矩阵") is True]  # 只允许通过基础检查的姿势。
    files = {Path(record["path"]).name: record for record in result["files"]}  # 按唯一文件名定位A06证据。
    package = study / "task_packages" / f"{PACKAGE_ID}_Yupingfengsan_COPD_10pairs_PyMOL"  # 使用稳定英文目录保证工具兼容。
    require(not package.exists(), "任务包已经存在；不得覆盖：" + str(package))  # 新修订必须换新编号。
    stage_root = Path("D:/docking_viz") / ("build_" + PACKAGE_ID)  # PyMOL构建过程使用纯英文路径。
    require(not stage_root.exists(), "PyMOL构建目录已存在，请先核对：" + str(stage_root))  # 不删除来源不明目录。
    package.mkdir(parents=True)  # 创建本次唯一任务包。
    stage_root.mkdir(parents=True)  # 创建临时英文构建目录。
    pair_rows = []  # 保存10组总览与来源。
    pair_ids = []  # 保存稳定组号供回收脚本使用。
    try:  # 任何异常均保留已生成目录供诊断，不伪报完成。
        number = 0  # 组号按受体后成分顺序递增。
        for target in TARGET_ORDER:  # 先生成AKT1五组，再生成MAPK1五组。
            for compound_id in COMPOUND_ORDER:  # 按A03_SELECT顺序固定成分。
                number += 1  # 得到P01至P10。
                pose_candidates = [row for row in valid_poses if row["受体"] == target and row["成分编号"] == compound_id]  # 找到该组所有有效姿势。
                require(pose_candidates, "缺少有效姿势：" + target + " / " + compound_id)  # 不用未检查姿势凑数。
                selected = min(pose_candidates, key=lambda row: (float(row["结合能_kcal_mol"]), int(row["模式"])))  # 评分最负优先，并列取模式号较小者。
                require(float(selected["结合能_kcal_mol"]) == float(matrix[(compound_id, target)]), "选定姿势与热图评分不一致")  # 图片与热图必须同源。
                command_name = f"{compound_id}_{target}_{selected['PDB']}_command.json"  # 命令记录给出全部输入来源。
                docked_name = f"{compound_id}_{target}_{selected['PDB']}_docked.pdbqt"  # 原始文件含全部九个姿势。
                require(command_name in files and docked_name in files, "A06文件索引缺少任务来源")  # 不凭目录猜文件。
                command_path = verified_file(study, files[command_name])  # 核验命令记录。
                docked_path = verified_file(study, files[docked_name])  # 核验全部姿势输出。
                stdout_name = f"{compound_id}_{target}_{selected['PDB']}_stdout.txt"  # Vina标准输出保存原始评分表。
                stderr_name = f"{compound_id}_{target}_{selected['PDB']}_stderr.txt"  # Vina标准错误保存实际运行提示。
                require(stdout_name in files and stderr_name in files, "A06文件索引缺少Vina日志")  # 旧任务包要求的log不能凭空生成。
                stdout_path = verified_file(study, files[stdout_name])  # 核验Vina标准输出。
                stderr_path = verified_file(study, files[stderr_name])  # 核验Vina标准错误。
                command = read_json(command_path)  # 读取受体、配体和搜索盒来源。
                receptor_path = verified_file(root, command["receptor"])  # 受体记录以项目根目录为基准。
                ligand_path = verified_file(root, command["ligand_pdbqt"])  # 配体输入同样核验。
                pair_id = f"P{number:02d}_{target}_{compound_id}_{selected['成分']}"  # 文件夹同时包含组号、靶点、稳定成分编号和英文名。
                pair_ids.append(pair_id)  # 固定总览顺序。
                pair = package / "04_pairs" / pair_id  # 每组采用相同层级。
                for folder in ("input", "result", "pymol", "figures"):  # 创建用途明确的四个子目录。
                    (pair / folder).mkdir(parents=True)  # figures留给用户回传图片。
                shutil.copy2(receptor_path, pair / "input/receptor.pdbqt")  # 保存受体输入。
                shutil.copy2(ligand_path, pair / "input/ligand_input.pdbqt")  # 保存配体输入。
                shutil.copy2(docked_path, pair / "result/output_all_modes.pdbqt")  # 保存未经删减的Vina输出。
                shutil.copy2(command_path, pair / "result/command.json")  # 保存实际参数和文件来源。
                pose_text = _selected_pose(docked_path.read_text(encoding="utf-8"), int(selected["模式"]))  # 抽取热图对应姿势。
                _write_new(pair / "result/selected_pose.pdbqt", pose_text)  # 单独交付出图姿势。
                config = command["search_box"]  # 读取本组已批准搜索盒。
                params = command["vina_parameters"]  # 读取本组实际Vina参数。
                config_text = "\n".join([f"receptor = input/receptor.pdbqt", f"ligand = input/ligand_input.pdbqt", f"center_x = {config['center_angstrom'][0]}", f"center_y = {config['center_angstrom'][1]}", f"center_z = {config['center_angstrom'][2]}", f"size_x = {config['size_angstrom'][0]}", f"size_y = {config['size_angstrom'][1]}", f"size_z = {config['size_angstrom'][2]}", f"exhaustiveness = {params['exhaustiveness']}", f"num_modes = {params['num_modes']}", f"energy_range = {params['energy_range_kcal_mol']}", f"seed = {params['seed']}"]) + "\n"  # 生成人工可读配置。
                _write_new(pair / "result/config.txt", config_text)  # 格式沿用旧任务包。
                _write_new(pair / "pymol/01_open_in_pymol.pml", _pml(pair_id), encoding="ascii")  # PyMOL脚本严格ASCII。
                _write_new(pair / "pymol/START_PYMOL.cmd", _launcher(pair_id), encoding="utf-8")  # 双击入口处理中文路径。
                stage = stage_root / pair_id  # 当前组合纯英文构建目录。
                stage.mkdir()  # 每组互不混用文件。
                shutil.copy2(receptor_path, stage / "receptor.pdbqt")  # 为PyMOL准备英文受体路径。
                _write_new(stage / "selected_pose.pdbqt", pose_text)  # 为PyMOL准备英文姿势路径。
                _write_new(stage / "01_open_in_pymol.pml", _pml(pair_id), encoding="ascii")  # 运行同一份脚本。
                pymol_log = _build_session(stage, pair_id)  # 实际验证PyMOL可以打开并生成输出。
                shutil.copy2(stage / f"result_{pair_id}.pdb", pair / "pymol" / f"result_{pair_id}.pdb")  # 合并PDB是用户此前要求的核心格式。
                shutil.copy2(stage / f"session_{pair_id}.pse", pair / "pymol" / f"session_{pair_id}.pse")  # 会话文件可直接打开。
                shutil.copy2(stage / "hbond_info.txt", pair / "pymol/hbond_info.txt")  # 保存距离接触清单并明确不是已确认氢键。
                _write_new(pair / "pymol/pymol_generation.log", pymol_log)  # 保留实际软件输出。
                compound_letter = chr(ord("a") + COMPOUND_ORDER.index(compound_id))  # 沿用旧包a至e的成分编号。
                target_number = TARGET_ORDER.index(target) + 1  # 本任务包两个受体固定为1和2。
                shutil.copy2(receptor_path, pair / f"{target_number}_{target}.pdbqt")  # 旧PyMOL流程兼容受体文件名。
                shutil.copy2(ligand_path, pair / f"{compound_letter}_{selected['成分']}.pdbqt")  # 旧流程兼容配体文件名。
                shutil.copy2(docked_path, pair / "output.pdbqt")  # 旧流程兼容全部姿势文件名。
                shutil.copy2(pair / "result/config.txt", pair / "config.txt")  # 旧流程兼容配置文件位置。
                log_text = "[Vina stdout]\n" + stdout_path.read_text(encoding="utf-8", errors="replace") + "\n[Vina stderr]\n" + stderr_path.read_text(encoding="utf-8", errors="replace")  # 合并为旧流程使用的单一日志。
                _write_new(pair / "log.txt", log_text)  # 保留实际Vina输出，不重写评分。
                shutil.copy2(stage / f"result_{pair_id}.pdb", pair / f"result_{pair_id}.pdb")  # 旧流程可在组合根目录直接找到合并PDB。
                shutil.copy2(stage / f"session_{pair_id}.pse", pair / f"session_{pair_id}.pse")  # 允许直接双击初始PyMOL会话。
                shutil.copy2(stage / "hbond_info.txt", pair / "hbond_info.txt")  # 旧流程兼容接触记录位置。
                shutil.copy2(pair / "pymol/01_open_in_pymol.pml", pair / "01_open_in_pymol.pml")  # 根目录保留可检查脚本。
                shutil.copy2(pair / "pymol/START_PYMOL.cmd", pair / "START_PYMOL.cmd")  # 根目录提供醒目双击入口。
                note = f"组号：{pair_id}\n受体：{target}（PDB {selected['PDB']}）\n成分：{selected['成分']}（{compound_id}）\n用于热图和出图的姿势：模式{selected['模式']}\n结合能：{float(selected['结合能_kcal_mol']):.3f} kcal/mol\n\n使用方法：双击 pymol/START_PYMOL.cmd；调整完成后将图片保存到弹出工作目录的 figures 文件夹，最后运行任务包根目录的 02_收回PyMOL图片.cmd。\n\n红色虚线仅表示N/O原子距离不超过3.5 Å的距离接触，不能仅凭距离确认氢键。\n"  # 给非程序用户完整说明。
                _write_new(pair / "任务说明.txt", note)  # 中文说明与工具文件分开。
                pair_rows.append({"pair_id": pair_id, "target": target, "pdb": selected["PDB"], "compound_id": compound_id, "compound_name": selected["成分"], "selected_mode": selected["模式"], "score_kcal_mol": float(selected["结合能_kcal_mol"]), "status": "仅需PyMOL出图，无需重新对接"})  # 总览保存实际事实。
        _write_new(package / "02_收回PyMOL图片.cmd", _collect_launcher(pair_ids), encoding="utf-8")  # 一次收回全部用户图片。
        csv_lines = ["组号,受体,PDB,成分编号,成分英文名,选定姿势,结合能_kcal_mol,任务状态"]  # 提供Excel可直接打开的总表。
        csv_lines += [f"{row['pair_id']},{row['target']},{row['pdb']},{row['compound_id']},{row['compound_name']},{row['selected_mode']},{row['score_kcal_mol']:.3f},{row['status']}" for row in pair_rows]  # 每行一组。
        _write_new(package / "01_任务总览.csv", "\ufeff" + "\n".join(csv_lines) + "\n")  # UTF-8 BOM保证Excel中文正常。
        rows_html = "".join(f"<tr><td>{escape(row['pair_id'])}</td><td>{row['target']}</td><td>{row['compound_id']} / {escape(row['compound_name'])}</td><td>模式{row['selected_mode']}</td><td>{row['score_kcal_mol']:.3f}</td><td>{row['status']}</td></tr>" for row in pair_rows)  # 形成易读网页表格。
        html = "<!doctype html><meta charset='utf-8'><title>D001 对接出图任务包</title><style>body{font-family:Microsoft YaHei,sans-serif;max-width:1100px;margin:30px auto;color:#173042}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cad7df;padding:8px;text-align:left}th{background:#e7f0f4}.notice{background:#eef6f8;border-left:5px solid #26708a;padding:12px}</style><h1>D001 玉屏风散—COPD 对接出图任务包</h1><p class='notice'>本包包含已经完成并核验的10组对接。每组无需重新对接；双击组内 pymol/START_PYMOL.cmd 开始出图。图片与热图均采用表中同一个选定姿势。</p><p>红色虚线为N/O原子距离≤3.5 Å的距离接触，不能仅凭距离确认氢键。完成后把图片保存到英文工作目录的 figures 文件夹，再双击根目录“02_收回PyMOL图片.cmd”。</p><table><thead><tr><th>组号</th><th>受体</th><th>成分</th><th>选定姿势</th><th>结合能</th><th>任务</th></tr></thead><tbody>" + rows_html + "</tbody></table>"  # 任务首页突出实际操作。
        _write_new(package / "00_任务总览.html", html)  # 浏览器打开即可查看全部任务。
        index = {"schema_version": PACKAGE_SCHEMA, "package_id": PACKAGE_ID, "study_id": study_id, "source_a06_run": a06_run_id, "purpose": "PyMOL visualization of the 10 completed docking pairs", "pair_count": len(pair_rows), "pairs": pair_rows}  # 建立机器可读索引。
        for path in sorted(package.rglob("*")):  # 枚举已经生成的所有文件。
            if path.is_file():  # 文件夹不生成指纹。
                index.setdefault("files", []).append({"path": path.relative_to(package).as_posix(), "bytes": path.stat().st_size, "sha256": _digest(path)})  # 保存相对路径与完整指纹。
        _write_new(package / "package_index.json", json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n")  # 索引最后写入，代表任务包生成完成。
    finally:  # 构建目录只保存可重建副本。
        if stage_root.exists():  # 只删除本函数明确创建的固定构建目录。
            shutil.rmtree(stage_root)  # 正式任务包及研究文件不受影响。
    return package  # 返回任务包位置供网页或维护者显示。


if __name__ == "__main__":  # 允许维护者从命令行生成一次任务包。
    import argparse  # 解析三个明确参数。
    parser = argparse.ArgumentParser(description="生成已完成A06组合的PyMOL出图任务包")  # 提供中文帮助。
    parser.add_argument("--root", required=True)  # 必须明确项目根目录。
    parser.add_argument("--study", required=True)  # 必须明确研究编号。
    parser.add_argument("--a06-run", required=True)  # 必须明确来源A06运行。
    arguments = parser.parse_args()  # 读取调用参数。
    print(build(arguments.root, arguments.study, arguments.a06_run))  # 输出最终任务包路径。
