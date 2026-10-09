# A06通用任务包；按实际研究、成分和受体生成，不固定COPD或组合数量。
from hashlib import sha256  # 为交付文件建立内容指纹。
from html import escape  # 安全生成浏览器总览。
from pathlib import Path  # 管理研究包内路径。
import json  # 保存机器可读索引。
import os  # 为PyMOL隔离不同Python版本的依赖路径。
import subprocess  # 调用PyMOL只生成固定姿势结构与会话。
import csv  # 正确保存含逗号的失败说明。
import io  # 生成可读的完整组合清单。

import shutil  # 复制已核验的姿势和输入文件。

from contracts import require  # 使用统一可读阻断规则。
from docking_contract import validate_generic_result  # 先核对通用A06契约。
from storage import read_json, verified_file  # 读取并复核来源文件。


PACKAGE_SCHEMA = "A06.docking.task.package.2"  # 通用任务包结构版本。


def _digest(path):  # 计算单个交付文件指纹。
    return sha256(path.read_bytes()).hexdigest()  # 使用原始字节保持跨电脑一致。


def _safe_name(value):  # 将研究标签转换为稳定英文目录片段。
    cleaned = "".join(character if character.isalnum() or character in "-_" else "_" for character in str(value).strip())  # 去除路径特殊字符。
    return cleaned.strip("_") or "study"  # 空标签使用中性名称。


def _write_new(path, text):  # 新任务包文件禁止覆盖。
    path.parent.mkdir(parents=True, exist_ok=True)  # 创建明确父目录。
    with path.open("x", encoding="utf-8", newline="") as stream:  # 已存在即停止。
        stream.write(text)  # 一次写入完整内容。


def _pymol_files(study, pair, row, receptor, pymol_exe, pair_id):  # 创建用户要求的PyMOL兼容输出。
    from docking_task_package import _pml  # 复用已验收的固定姿势及距离接触脚本。
    from docking_redocking import _poses  # 确保固定文件只有Top-1。
    require(len(_poses((pair / 'selected_pose.pdbqt').read_text('ascii'))) == 1, 'PyMOL输入不是唯一固定姿势')  # 不让用户选择九种模式。
    extra = []  # 保存本组新增的交付文件名。
    for key, name in (('receptor_record', 'receptor.pdbqt'), ('ligand_record', 'ligand.pdbqt'), ('log_record', 'log.txt'), ('all_poses_record', 'output.pdbqt')):  # 对接输入、日志和全部姿势齐备。
        require(row.get(key), 'PyMOL任务缺少实际文件：' + key)  # 不猜路径。
        shutil.copy2(verified_file(study, row[key]), pair / name)  # 原样复制同源字节。
        extra.append(name)  # 纳入组索引。
    values = read_json(verified_file(study, row['command_record']))  # 固定实际软件参数。
    parameters = values['parameters']  # 不引入出图阶段新参数。
    config = ['receptor = receptor.pdbqt', 'ligand = ligand.pdbqt']  # 相对路径使包可迁移。
    config += [f'{kind}_{axis} = {value}' for kind in ('center', 'size') for axis, value in zip('xyz', values['search_box'][kind])]  # 完整搜索空间。
    config += [f'{key} = {parameters[key]}' for key in ('scoring', 'exhaustiveness', 'num_modes', 'seed')]  # 保存统一Vina参数。
    config.append(f"energy_range = {parameters['energy_range_kcal_mol']}")  # 单位字段转换为Vina配置名。
    _write_new(pair / 'config.txt', '\n'.join(config) + '\n')  # 供复算使用，出图不重新对接。
    _write_new(pair / '01_open_in_pymol.pml', _pml(pair_id))  # 脚本不移动配体或改变盒。
    launcher = '@echo off\ncd /d "%~dp0"\n"' + str(pymol_exe) + '" -r "01_open_in_pymol.pml"\n'  # 用户双击时打开可见PyMOL。
    _write_new(pair / 'START_PYMOL.cmd', launcher)  # 入口放在对应组合旁边。
    command = [str(pymol_exe), '-cq', '01_open_in_pymol.pml']  # 制作任务时只进行无界面格式导出。
    environment = dict(os.environ)  # 复制环境，不改变主程序。
    environment.pop("PYTHONPATH", None)  # PyMOL使用自己的Python3.10依赖，不能加载对接Python3.13包。
    environment.pop("PYTHONHOME", None)  # 避免继承其他Python安装根。
    process = subprocess.run(command, cwd=pair, env=environment, capture_output=True, text=True, errors='replace', timeout=120)  # 保存实际状态，超时不伪造输出。
    _write_new(pair / 'pymol_build_log.txt', process.stdout + '\n' + process.stderr)  # 保存会话制作日志。
    require(process.returncode == 0, 'PyMOL会话制作失败：' + pair_id)  # 不交付半成品。
    generated = ['config.txt', '01_open_in_pymol.pml', 'START_PYMOL.cmd', 'pymol_build_log.txt', 'hbond_info.txt', f'result_{pair_id}.pdb', f'session_{pair_id}.pse']  # 必须包含PDB与会话。
    require(all((pair / name).is_file() and (pair / name).stat().st_size for name in generated), 'PyMOL输出不完整：' + pair_id)  # 空文件不视为完成。
    return extra + generated  # 全部文件进入索引与指纹。


def build(root, study_id, a06_run_id, package_id, pymol_exe=None, output_parent=None):  # 从通用A06结果生成可移交任务包。
    root = Path(root).resolve()  # 固定项目根目录。
    study = root / "studies" / study_id  # 定位当前研究包。
    manifest = read_json(study / "manifest.json")  # 读取版本索引。
    require(manifest.get("current", {}).get("A06") == a06_run_id, "指定A06不是当前版本")  # 不从过期结果建立新任务。
    run_record = manifest["runs"][a06_run_id]  # 读取运行记录。
    result = read_json(verified_file(study, run_record["result_file"]))  # 用指纹读取A06标准结果。
    generic = result.get("tables", {}).get("generic_docking")  # 新版A06在固定表名交付通用结构。
    require(isinstance(generic, dict), "A06尚未提供通用任务包数据")  # 历史结果不由程序猜测转换。
    validate_generic_result(generic)  # 独立核对对象、组合、评分与文件引用。
    require(generic["outcome"] in {"success", "partial"}, "有效空A06没有可生成的对接任务")  # 空结果直接进入报告。
    a00_id = manifest.get("current", {}).get("A00")  # 读取研究显示名称。
    a00 = read_json(verified_file(study, manifest["runs"][a00_id]["result_file"])) if a00_id else {"summary": {}}  # 仅用于命名与说明。
    formula = a00.get("summary", {}).get("formula", "formula")  # 不使用固定方剂名。
    disease = a00.get("summary", {}).get("disease", "disease")  # 不使用固定疾病名。
    package_name = f"{_safe_name(package_id)}_{_safe_name(formula)}_{_safe_name(disease)}_{len(generic['planned_pairs'])}pairs"  # 名称直接反映本次任务。
    destination = Path(output_parent).resolve() if output_parent is not None else study / 'task_packages'  # 后台制作可在同研究任务目录先完成草案。
    require(destination.resolve().is_relative_to(study.resolve()), '任务包草案位置超出本研究')  # 不允许跨研究输出。
    package = destination / package_name  # 完整后由编排器原子移入task_packages。
    require(not package.exists(), "任务包已经存在；请使用新的稳定编号")  # 历史包不得覆盖。
    package.mkdir(parents=True)  # 创建本次唯一目录。
    require(pymol_exe is None or Path(pymol_exe).is_file(), "未找到指定PyMOL程序")  # 缺软件不能声称已生成会话。
    receptor_index = {row["target"]: row for row in generic["receptors"]}  # 将结构限制绑定到每组。
    pair_numbers = {(row["target"], row["compound_id"]): number for number, row in enumerate(generic["planned_pairs"], 1)}  # 组号绑定完整70组计划，失败后不会挤占其他组号。
    rows = []  # 保存人工总览。
    for number, row in enumerate(generic["completed_pairs"], 1):  # 只为真实完成组合复制姿势。
        row = dict(row)  # 补充已有文件索引时不改写A06原事实。
        if pymol_exe is not None and not row.get("all_poses_record"):  # 部分旧执行记录未直接登记全部姿势角色。
            command_fact = read_json(verified_file(study, row["command_record"]))  # 只读取已绑定的实际命令。
            arguments = command_fact["arguments"]  # 输出位置来自显式命令参数。
            source_path = Path(arguments[arguments.index("--out") + 1]).resolve()  # 不扫描目录猜输入。
            require(source_path.is_relative_to(study), "原始全部姿势不在当前研究包")  # 保持研究隔离。
            output_record = next((item for item in result.get("files", []) if item["path"] == source_path.relative_to(study).as_posix()), None)  # 使用A06已经归档的文件指纹。
            require(output_record is not None, "A06未绑定全部姿势文件指纹")  # 缺少来源时停止。
            verified_file(study, output_record)  # 不用重新计算指纹掩盖文件修改。
            row["all_poses_record"] = output_record  # 仅用于当前交付文件复制。
        number = pair_numbers[(row["target"], row["compound_id"])]  # 使用完整计划位置而非完成顺序。
        pair_id = f"P{number:03d}_{_safe_name(row['target'])}_{_safe_name(row['compound_id'])}"  # 组合数增加时仍能稳定排序。
        pair = package / "pairs" / pair_id  # 每组使用独立目录。
        pair.mkdir(parents=True)  # 创建组合目录。
        pose = verified_file(study, row["pose_record"])  # 先核对路径、大小和SHA256。
        shutil.copy2(pose, pair / "selected_pose.pdbqt")  # 保存热图对应姿势原文。
        source_records = []  # 收集可选受体、配体和命令文件。
        for key in ("receptor_record", "ligand_record", "command_record", "log_record"):  # 不要求所有流程都生成同样附件。
            record = row.get(key)  # 读取显式文件记录。
            if record:  # 有记录时必须通过指纹核验。
                source = verified_file(study, record)  # 禁止扫描目录猜文件。
                target = pair / f"{key}{source.suffix}"  # 使用稳定角色名避免原名冲突。
                shutil.copy2(source, target)  # 复制原始证据。
                source_records.append(target.name)  # 写入总览。
        if pymol_exe is not None:  # 本次实际交付时生成PDB与PSE，合成测试可不调用外部程序。
            source_records += _pymol_files(study, pair, row, receptor_index[row["target"]], Path(pymol_exe), pair_id)  # 保留固定姿势坐标。
        note = {"pair_id": pair_id, "compound_id": row["compound_id"], "compound_name": row.get("compound_name"), "target": row["target"], "score_kcal_mol": row["score_kcal_mol"], "status": "已完成，可用于结构查看", "files": ["selected_pose.pdbqt"] + source_records, "primary_result": receptor_index[row["target"]].get("primary_result", False), "structure_limitation": receptor_index[row["target"]].get("structure_limitation", ""), "search_box": {"center": receptor_index[row["target"]]["center"], "size": receptor_index[row["target"]]["size"]}}  # 保存当前组合事实。
        _write_new(pair / "pair.json", json.dumps(note, ensure_ascii=False, sort_keys=True, indent=2) + "\n")  # 机器和人工均可读取。
        rows.append(note)  # 加入任务总览。
    failed_rows = [{"compound_id": row["compound_id"], "target": row["target"], "reason": row["reason"]} for row in generic["failed_pairs"]]  # 失败组合不伪造姿势。
    csv_lines = ["组号,成分编号,成分名称,受体,结合能_kcal_mol,状态"] + [f"{row['pair_id']},{row['compound_id']},{row.get('compound_name') or ''},{row['target']},{row['score_kcal_mol']:.3f},{row['status']}" for row in rows]  # 提供可直接检查的完成表。
    _write_new(package / "01_已完成组合.csv", "\ufeff" + "\n".join(csv_lines) + "\n")  # Excel打开中文不乱码。
    _write_new(package / "02_失败或暂停组合.json", json.dumps(failed_rows, ensure_ascii=False, sort_keys=True, indent=2) + "\n")  # 单独呈现问题组合及原因。
    table_stream = io.StringIO()  # 生成完整计划的中文CSV。
    writer = csv.writer(table_stream)  # 对逗号和换行正确转义。
    writer.writerow(['计划组号', '受体', '成分编号', '状态', '结合能_kcal_mol', '失败或限制说明'])  # 一次核对全部70组。
    completed_index = {(row['target'], row['compound_id']): row for row in rows}  # 已完成事实索引。
    failed_index = {(row['target'], row['compound_id']): row for row in failed_rows}  # 失败事实索引。
    for item in generic['planned_pairs']:  # 原计划顺序不变。
        key = (item['target'], item['compound_id'])  # 稳定身份组合。
        done = completed_index.get(key)  # 不以文件存在猜状态。
        writer.writerow([f'P{pair_numbers[key]:03d}', item['target'], item['compound_id'], '完成' if done else 'NA', f"{done['score_kcal_mol']:.3f}" if done else 'NA', done['structure_limitation'] if done else failed_index[key]['reason']])  # 如实呈现全部组合。
    _write_new(package / '03_全部计划与运行状态.csv', '\ufeff' + table_stream.getvalue())  # 中文Excel可直接打开。
    _write_new(package / '使用说明.txt', '先打开00_任务总览.html查看全部结果。每组selected_pose.pdbqt为热图同源固定Top-1，output.pdbqt保存全部模式。使用result_组号.pdb或session_组号.pse在PyMOL查看；START_PYMOL.cmd使用本机指定安装路径，换电脑需调整该路径。图中的N/O距离接触不能直接当作已确认氢键。不要移动配体或重新选择姿势来替换热图结果。NA项不生成伪姿势。\n')  # 说明实际可移植范围。
    html_rows = "".join(f"<tr><td>{escape(row['pair_id'])}</td><td>{escape(row['compound_id'])}</td><td>{escape(str(row.get('compound_name') or ''))}</td><td>{escape(row['target'])}</td><td>{row['score_kcal_mol']:.3f}</td></tr>" for row in rows)  # 生成人工总览行。
    html = f"<!doctype html><meta charset='utf-8'><title>{escape(package_id)} 分子对接任务包</title><style>body{{font-family:Microsoft YaHei,sans-serif;max-width:1100px;margin:30px auto;color:#173042}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #cad7df;padding:8px}}th{{background:#e7f0f4}}</style><h1>{escape(str(formula))}—{escape(str(disease))} 分子对接任务包</h1><p>来源A06：{escape(a06_run_id)}；计划{len(generic['planned_pairs'])}组，完成{len(rows)}组，失败或暂停{len(failed_rows)}组。失败项不生成伪姿势。</p><table><tr><th>组号</th><th>成分编号</th><th>成分名称</th><th>受体</th><th>结合能</th></tr>{html_rows}</table>"  # 首页只显示实际研究和数量。
    _write_new(package / "00_任务总览.html", html)  # 浏览器可直接查看。
    index = {"schema_version": PACKAGE_SCHEMA, "package_id": package_id, "study_id": study_id, "source_a06_run": a06_run_id, "formula": formula, "disease": disease, "planned_pair_count": len(generic["planned_pairs"]), "completed_pair_count": len(rows), "failed_pair_count": len(failed_rows), "pairs": rows, "failed_pairs": failed_rows, "files": []}  # 建立统一索引。
    for path in sorted(package.rglob("*")):  # 对已生成文件逐个固定指纹。
        if path.is_file():  # 文件夹不进入索引。
            index["files"].append({"path": path.relative_to(package).as_posix(), "bytes": path.stat().st_size, "sha256": _digest(path)})  # 保存跨电脑可核对记录。
    _write_new(package / "package_index.json", json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n")  # 最后写索引表示生成完成。
    return package  # 返回明确交付位置。


if __name__ == "__main__":  # 提供明确参数的维护入口。
    import argparse  # 解析研究、运行和稳定任务编号。
    parser = argparse.ArgumentParser(description="从A06第三版结果生成通用分子对接任务包")  # 说明入口用途。
    parser.add_argument("--root", required=True)  # 必须明确项目根目录。
    parser.add_argument("--study", required=True)  # 必须明确研究编号。
    parser.add_argument("--a06-run", required=True)  # 必须明确当前A06运行。
    parser.add_argument("--package-id", required=True)  # 使用D003等稳定编号，禁止自动猜号。
    parser.add_argument("--pymol-exe")  # 可指定实际PyMOL程序生成兼容PDB和PSE。
    arguments = parser.parse_args()  # 读取全部参数。
    print(build(arguments.root, arguments.study, arguments.a06_run, arguments.package_id, arguments.pymol_exe))  # 输出唯一任务包位置。
