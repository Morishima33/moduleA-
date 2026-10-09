# A06正式分子对接；只执行用户明确授权的五成分×AKT1/MAPK1十组组合。
from copy import deepcopy  # 生成新预览时保留历史预览不变。
import json  # 读取和输出可复核的结构化记录。
import math  # 检查结合能和距离是否为有限值。
from pathlib import Path  # 安全定位项目和研究包文件。
import shutil  # 将本次实际代码保存到运行包。
import subprocess  # 以参数列表调用固定版本的Vina。
from contracts import ContractError, require  # 复用项目统一阻断规则。
from docking_redocking import _inside_box, _minimum_receptor_distance, _poses, _record_by_suffix, _write_text  # 复用已经验收的姿势解析和基础检查。
from docking_contract import receptor_setup_table, score_matrix_table, validate_generic_result  # 新研究使用不固定对象数量的通用A06契约。
from storage import file_record, now, read_json, verified_file, write_json  # 复用不可覆盖保存和文件指纹核验。
from workflow import Workflow  # 通过统一衔接框架发布A06_PREP和A06。


AUTHORIZED_TARGETS = ('AKT1', 'MAPK1')  # 本次只放行通过重对接诊断的两个受体。
PAUSED_TARGET = 'HSP90AA1'  # 未复现的受体保持暂停且不运行正式组合。
AUTHORIZED_COMPOUNDS = ('MOL000098', 'MOL000422', 'MOL000378', 'MOL000173', 'MOL000358')  # 五个成分来自已复核A03_SELECT版本。
VINA_PARAMETERS = {'scoring': 'vina', 'exhaustiveness': 8, 'num_modes': 9, 'energy_range_kcal_mol': 3, 'seed': 1}  # 参数完全沿用已批准配置。


def _project_record(root, path, role):  # 形成相对项目根目录的不可变文件索引。
    return file_record(Path(root).resolve(), Path(path).resolve(), role)  # 路径、大小和SHA256同时固定。


def _input_atoms(pdbqt_text):  # 读取正式配体输入文件中的实际原子身份。
    atoms = {}  # 以PDBQT原子序号建立唯一映射。
    for line in pdbqt_text.splitlines():  # 逐行读取Meeko生成的输入文件。
        if line.startswith(('ATOM  ', 'HETATM')):  # 只处理实际坐标原子。
            serial = int(line[6:11])  # 使用PDBQT固定列读取原子序号。
            atom_type = line[77:].strip().split()[0] if line[77:].strip() else ''  # 末列保存AutoDock原子类型。
            require(serial not in atoms and atom_type, '配体PDBQT原子序号重复或类型缺失')  # 身份不完整时停止。
            atoms[serial] = atom_type  # 保存序号与类型用于逐姿势比对。
    require(atoms, '配体PDBQT没有可用原子')  # 空结构不能进入Vina。
    return atoms  # 返回已解析的输入身份。


def _pose_identity(pose, input_atoms, expected_heavy_atoms):  # 核对Vina姿势没有丢失或替换配体原子。
    pose_atoms = {serial: atom['atom_type'] for serial, atom in pose['atoms'].items()}  # 将姿势转换为相同身份形式。
    serials_passed = set(pose_atoms) == set(input_atoms)  # 原子序号集合必须完全一致。
    types_passed = serials_passed and all(pose_atoms[serial] == input_atoms[serial] for serial in input_atoms)  # 每个序号的原子类型也必须一致。
    heavy_count = sum(atom_type not in ('H', 'HD', 'G0') for atom_type in pose_atoms.values())  # 氢和Meeko伪原子不计入真实重原子。
    heavy_passed = heavy_count == expected_heavy_atoms  # 与已核实SDF重原子数比较。
    return {'passed': serials_passed and types_passed and heavy_passed, 'serials_passed': serials_passed, 'atom_types_passed': types_passed, 'heavy_atom_count': heavy_count, 'expected_heavy_atom_count': expected_heavy_atoms}  # 保存各项事实供复核。


def _heat_color(value, minimum, maximum):  # 将描述性结合能映射为热图颜色。
    ratio = 0.5 if maximum == minimum else (value - minimum) / (maximum - minimum)  # 单一数值时采用中间色。
    red_end = (178, 24, 43)  # 用户最新确认用深红表示本次较低、更负的数值。
    light_red = (239, 169, 174)  # 中间偏强区域使用浅红，避免白色造成空值或中性暗示。
    light_blue = (164, 199, 224)  # 中间偏弱区域使用浅蓝，避免把紫色设为显眼锚点。
    blue_end = (33, 102, 172)  # 深蓝表示本次较高、较不负的数值。
    if ratio <= 0.5:  # 从深红平滑过渡到浅红。
        local = ratio * 2  # 将前半段重新映射到零至一。
        local = local * local * (3 - 2 * local)  # 使用平滑步进避免颜色斜率突变。
        start, end = red_end, light_red  # 最负端至范围中点保持红色系。
    elif ratio <= 0.56:  # 在很窄的中间区间由浅红平滑转为浅蓝。
        local = (ratio - 0.5) / 0.06  # 将过渡区间重新映射到零至一。
        local = local * local * (3 - 2 * local)  # 让浅红和浅蓝两端连接平滑。
        start, end = light_red, light_blue  # 不设置白色或紫色锚点。
    else:  # 从浅蓝平滑过渡到深蓝。
        local = (ratio - 0.56) / 0.44  # 将较弱半段重新映射到零至一。
        local = local * local * (3 - 2 * local)  # 使用相同平滑步进保持视觉连续。
        start, end = light_blue, blue_end  # 较不负区域保持蓝色系。
    red = round(start[0] + (end[0] - start[0]) * local)  # 插值红通道。
    green = round(start[1] + (end[1] - start[1]) * local)  # 插值绿通道。
    blue = round(start[2] + (end[2] - start[2]) * local)  # 插值蓝通道。
    return f'rgb({red},{green},{blue})'  # 返回浏览器可直接显示的颜色。


def _write_heatmap(path, matrix):  # 生成带原始数值的五成分×两受体SVG热图。
    expanded_targets = ('AKT1', 'MAPK1', 'HSP90AA1', 'TNF', 'ESR1')  # 五乘五扩展版保持固定受体顺序。
    display_targets = expanded_targets if any('TNF' in row or 'ESR1' in row for row in matrix) else AUTHORIZED_TARGETS + (PAUSED_TARGET,)  # 根据矩阵字段选择已发布三列版或新版五列版。
    values = [float(row[target]) for row in matrix for target in display_targets if row.get(target) is not None]  # 只使用真实完成组合。
    require(values, '没有可绘制的正式对接评分')  # 空图不能作为结果。
    minimum, maximum = min(values), max(values)  # 颜色范围仅描述本次结果分布。
    midpoint = (minimum + maximum) / 2  # 白色对应本次范围中点而不是零值。
    width, height = 590 + 132 * len(display_targets), 125 + 58 * len(matrix)  # 按三列或五列矩阵动态保留色标空间。
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">']  # 建立独立SVG文档。
    lines.append('<rect width="100%" height="100%" fill="white"/>')  # 使用白底保证打印可读。
    lines.append('<text x="20" y="30" font-family="Microsoft YaHei, sans-serif" font-size="20" font-weight="700">正式分子对接结合能热图（带数值）</text>')  # 标明图意。
    lines.append('<text x="20" y="54" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#526b7a">Vina affinity，单位：kcal/mol；深红→浅红→浅蓝→深蓝</text>')  # 明确颜色方向。
    for index, target in enumerate(display_targets):  # 绘制两个已运行受体和一个暂停受体标题。
        lines.append(f'<text x="{432 + index * 132}" y="88" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="15">{target}</text>')  # 标题使用已核实基因符号。
    for row_index, row in enumerate(matrix):  # 每个成分占一行。
        y = 98 + row_index * 58  # 行位置保持固定间距。
        label = str(row['compound_name']).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')  # 防止名称破坏SVG。
        lines.append(f'<text x="20" y="{y + 33}" font-family="Microsoft YaHei, sans-serif" font-size="15">{label} ({row["compound_id"]})</text>')  # 同时显示名称和稳定编号。
        for column_index, target in enumerate(display_targets):  # 逐格绘制真实评分或暂停状态。
            value = row.get(target)  # 缺失项保持明确空白。
            x = 366 + column_index * 132  # 三列位置固定。
            fill = '#d9dde1' if value is None else _heat_color(float(value), minimum, maximum)  # 未运行组合使用中性灰色。
            label_value = '未运行' if value is None else f'{float(value):.3f}'  # 不用零代替暂停组合。
            normalized = 0.5 if value is None or maximum == minimum else (float(value) - minimum) / (maximum - minimum)  # 文字颜色只依据本次相对位置。
            label_color = '#203342' if value is None or abs(normalized - 0.5) < 0.28 else 'white'  # 中间浅色格使用深色文字。
            lines.append(f'<rect x="{x}" y="{y}" width="126" height="48" fill="{fill}" stroke="white" stroke-width="1"/>')  # 使用参考图风格的紧凑方格。
            lines.append(f'<text x="{x + 63}" y="{y + 31}" text-anchor="middle" font-family="Arial, Microsoft YaHei, sans-serif" font-size="15" fill="{label_color}">{label_value}</text>')  # 每格直接写原始数值或未运行。
    bar_x, bar_y, bar_height = 390 + 132 * len(display_targets), 98, 58 * len(matrix) - 10  # 将竖直色标放在矩阵右侧。
    for step in range(100):  # 用一百条窄矩形形成平滑红白蓝渐变。
        ratio = 1 - step / 99  # 色标顶部对应较高、较不负的蓝色，底部对应更负的红色。
        value = minimum + ratio * (maximum - minimum)  # 将比例转换为本次真实结合能。
        step_y = bar_y + step * bar_height / 100  # 逐段向下排列。
        lines.append(f'<rect x="{bar_x}" y="{step_y:.2f}" width="24" height="{bar_height / 100 + 0.5:.2f}" fill="{_heat_color(value, minimum, maximum)}"/>')  # 每段使用同一颜色函数。
    lines.append(f'<text x="{bar_x + 34}" y="{bar_y + 5}" font-family="Arial, sans-serif" font-size="12">{maximum:.3f}</text>')  # 色标顶部显示本次最大值。
    lines.append(f'<text x="{bar_x + 34}" y="{bar_y + bar_height / 2 + 4:.2f}" font-family="Arial, sans-serif" font-size="12">{midpoint:.3f}</text>')  # 色标中部显示白色对应值。
    lines.append(f'<text x="{bar_x + 34}" y="{bar_y + bar_height}" font-family="Arial, sans-serif" font-size="12">{minimum:.3f}</text>')  # 色标底部显示本次最小值。
    lines.append(f'<text x="{bar_x - 5}" y="{bar_y - 12}" font-family="Microsoft YaHei, sans-serif" font-size="12">结合能</text>')  # 色标标题使用中文。
    missing_note = '；灰色表示未运行' if any(row.get(target) is None for row in matrix for target in display_targets) else ''  # 完整五乘五不再显示不存在的灰色说明。
    lines.append(f'<text x="20" y="{height - 14}" font-family="Microsoft YaHei, sans-serif" font-size="12" fill="#526b7a">红色越深表示数值越负，蓝色越深表示数值越不负；不设置中性阈值{missing_note}。</text>')  # 防止颜色被误解为科学分级。
    lines.append('</svg>')  # 结束SVG文档。
    with path.open('x', encoding='utf-8', newline='') as stream:  # 历史图形禁止覆盖。
        stream.write('\n'.join(lines))  # 一次写入完整图形。


def prep_validator(project_root):  # 建立A06_PREP领域校验器并绑定项目根目录。
    project_root = Path(project_root).resolve()  # 固定外部证据校验边界。
    def validate(run, summary, tables, anomalies, outcome):  # 校验准备结果与本次授权一致。
        if run.get('config', {}).get('schema_version') == 'A06.automation.preparation.1':  # 新通用准备在真正对接前独立复核。
            from docking_automation_compute import validate_preparation  # 沿用统一科学事实校验。
            return validate_preparation(project_root, run, summary, tables, anomalies, outcome)  # 不套用病例固定数量。
        if run.get('config', {}).get('mode') == 'ppi_top10_dynamic':  # 前十位和边界并列按本次实际对象校验。
            from docking_contract import validate_generic_result  # 使用同一动态契约。
            study_root = project_root / 'studies' / run['study_id']  # 只核对当前研究来源。
            generic = read_json(verified_file(study_root, run['inputs']['generic_candidate']))  # 从明确输入指纹读取真实事实。
            validate_generic_result(generic)  # 核对全矩阵及受体状态。
            diagnostics = tables.get('receptor_diagnostics', [])  # 当前窗口每个受体均须留存。
            config = run['config']  # 读取运行冻结参数。
            require(outcome == 'success' and len(diagnostics) == len(generic['receptors']) == config['target_count'], '动态A06_PREP受体记录不完整')  # 不硬编码疾病或十行边界。
            require([row.get('受体') for row in diagnostics] == [row['target'] for row in generic['receptors']], '动态A06_PREP顺序与绑定候选不一致')  # 不按结合能重排。
            require(summary.get('计划组合数') == len(generic['planned_pairs']) == config['planned_pair_count'], '动态A06_PREP计划数量不一致')  # 数量由实际成分与受体决定。
            strict = [row for row in generic['receptors'] if row.get('redocking_status') == 'passed' and row['target'] in generic.get('strict_qc_passed_targets', [])]  # 只核对实际严格集合。
            require(len(strict) >= 5 and all(isinstance(row['redocking_rmsd_A'], (int, float)) and 0 <= row['redocking_rmsd_A'] <= 2.0 for row in strict), '动态A06_PREP未满足五个严格受体')  # 不沿用历史RMSD。
            primary = [row['target'] for row in generic['receptors'] if row.get('primary_result') is True]  # 主结果必须按PPI顺序。
            require(primary == [row['target'] for row in strict[:5]] == generic.get('primary_targets'), '动态A06_PREP主要受体与严格PPI顺序不一致')  # 其余只能作扩展线索。
            require([row.get('受体') for row in diagnostics if row.get('主要结果') is True] == primary, '诊断表主要受体不同源')  # 防止表与事实包错配。
            require(summary.get('handoff_blocked') is False, '已满足五个主要受体时准备阶段不应阻断')  # 失败扩展项保留NA。
            return  # 不套用历史固定病例规则。
        if run.get('config', {}).get('mode') == 'expanded_5x5':  # 新版五受体准备使用独立且显式的校验分支。
            require(outcome == 'success' and summary.get('授权正式组合数') == 25 and summary.get('暂停组合数') == 0, '五乘五A06_PREP摘要数量不正确')  # 五受体均须通过后才能放行。
            diagnostics = tables.get('receptor_diagnostics', [])  # 读取五项参考配体重对接事实。
            require(len(diagnostics) == 5 and {row.get('受体') for row in diagnostics} == {'AKT1', 'MAPK1', 'HSP90AA1', 'TNF', 'ESR1'}, '五乘五受体诊断集合不完整')  # 不允许漏项或替换靶点。
            require(all(row.get('诊断通过') is True and isinstance(row.get('RMSD_A'), (int, float)) and row.get('RMSD_A') <= 2.0 for row in diagnostics), '五乘五受体存在未通过重对接的对象')  # 沿用已批准的二埃阈值。
            require(summary.get('handoff_blocked') is False, '五乘五A06_PREP仍有阻断事项')  # 技术失败不能进入正式计算。
            return  # 扩展版本完成专用核验后不套用历史三受体数量。
        package = read_json(verified_file(project_root, run['inputs']['preparation_package']))  # 重新读取候选包。
        redocking = read_json(verified_file(project_root, run['inputs']['redocking_result']))  # 重新读取三次诊断。
        authorization = read_json(verified_file(project_root, run['inputs']['formal_authorization']))  # 重新读取正式执行授权。
        require(outcome == 'success' and package['parent_runs'] == run['parent_runs'], 'A06_PREP结果或上游绑定不正确')  # 标准运行必须绑定当前三个上游。
        require(redocking['summary']['passed_count'] == 2 and redocking['summary']['paused_receptors'] == [PAUSED_TARGET], '重对接诊断状态与已确认结果不符')  # 不允许换用诊断版本。
        require(authorization.get('schema_version') == 'A06.formal.execution.authorization.1' and authorization.get('status') == 'user_approved', '正式对接授权记录无效')  # 只接受本轮授权结构。
        require(authorization.get('authorized_targets') == list(AUTHORIZED_TARGETS) and authorization.get('paused_targets') == [PAUSED_TARGET], '授权受体范围不正确')  # 防止夹带暂停受体。
        require(authorization.get('authorized_combination_count') == 10 and authorization.get('formal_docking_authorized') is True, '正式对接组合数量未获授权')  # 必须恰好十组。
        require(summary.get('授权正式组合数') == 10 and summary.get('暂停组合数') == 5 and summary.get('handoff_blocked') is False, 'A06_PREP摘要数量不正确')  # 准备关口已具备下游条件。
        require(len(tables.get('authorized_formal_plan', [])) == 10 and len(tables.get('paused_formal_plan', [])) == 5, 'A06_PREP计划表数量不完整')  # 计划明细不能只写摘要。
        require(all(row['受体'] in AUTHORIZED_TARGETS for row in tables['authorized_formal_plan']), '授权计划混入暂停受体')  # 十组仅限两个受体。
        require(all(row['受体'] == PAUSED_TARGET for row in tables['paused_formal_plan']), '暂停计划对象不正确')  # 五组HSP90AA1保持未运行。
        require(any(PAUSED_TARGET in item for item in anomalies), 'A06_PREP未记录暂停受体限制')  # 限制必须随结果保留。
    return validate  # 网页和执行器共用同一校验器。


def formal_validator(project_root):  # 建立A06正式结果领域校验器。
    project_root = Path(project_root).resolve()  # 固定授权和准备包的校验边界。
    def validate(run, summary, tables, anomalies, outcome):  # 对发布前的十组结果独立复算结构约束。
        if run.get('config', {}).get('schema_version') == 'A06.formal.config.3':  # 第三版按实际对象和组合校验。
            generic = tables.get('generic_docking')  # 读取唯一通用结果表。
            require(isinstance(generic, dict), 'A06通用结果表缺失')  # 不从其他表猜测对象。
            validate_generic_result(generic)  # 核对计划、成功、失败、评分和文件指纹字段。
            require(outcome == generic['outcome'], 'A06运行状态与通用结果状态不一致')  # 工作流与领域状态必须一致。
            require(summary.get('计划组合数') == len(generic['planned_pairs']), 'A06计划组合数不一致')  # 摘要不能手工改数。
            require(summary.get('成功组合数') == len(generic['completed_pairs']), 'A06成功组合数不一致')  # 成功数从明细复算。
            require(summary.get('失败组合数') == len(generic['failed_pairs']), 'A06失败组合数不一致')  # 失败数从明细复算。
            primary = [row for row in generic.get('receptors', []) if row.get('primary_result') is True and row.get('redocking_status') == 'passed' and isinstance(row.get('redocking_rmsd_A'), (int, float)) and row.get('redocking_rmsd_A') <= 2.0]  # 从结构事实复算主要受体。
            expected_blocked = generic['outcome'] == 'partial' and len(primary) < 5  # 扩展项失败可保留NA；五个主要受体不足才阻断。
            require(summary.get('handoff_blocked') == expected_blocked, 'A06交接状态与通用结果不一致')  # 有效空结果允许进入报告。
            require(tables.get('receptor_setup') == receptor_setup_table(generic), 'A06受体参数表不是由通用结果生成')  # 报告表不得人工抄写。
            require(tables.get('score_matrix') == score_matrix_table(generic), 'A06结合能矩阵不是由通用组合明细生成')  # 缺失组合必须保持空值。
            return  # 通用分支不套用历史十组或五乘五限制。
        authorization = read_json(verified_file(project_root, run['inputs']['formal_authorization']))  # 结果必须仍绑定原授权文件。
        if authorization.get('schema_version') == 'A06.formal.expansion.authorization.1':  # 用户新增五乘五任务使用独立授权格式。
            require(outcome == 'success' and authorization.get('authorized_combination_count') == 25, '五乘五A06结果未绑定25组授权')  # 不接受部分矩阵冒充完整结果。
            combinations = tables.get('combination_results', [])  # 读取合并后的全部组合。
            expected_targets = {'AKT1', 'MAPK1', 'HSP90AA1', 'TNF', 'ESR1'}  # 固定本次五个已授权受体。
            require(len(combinations) == 25 and len({(row['成分编号'], row['受体']) for row in combinations}) == 25, '五乘五组合结果数量或身份重复')  # 每格只能有一个结果。
            require({row['成分编号'] for row in combinations} == set(AUTHORIZED_COMPOUNDS) and {row['受体'] for row in combinations} == expected_targets, '五乘五成分或受体集合与授权不符')  # 不允许运行中换对象。
            require(summary.get('计划组合数') == 25 and summary.get('成功组合数') + summary.get('失败组合数') == 25, '五乘五A06摘要数量不正确')  # 摘要必须覆盖全部矩阵。
            require(summary.get('handoff_blocked') == (summary.get('失败组合数') > 0), '五乘五A06交接状态与失败数量不一致')  # 任一失败都应阻断。
            require(len(tables.get('score_matrix', [])) == 5 and all(all(isinstance(row.get(target), (int, float)) and math.isfinite(row[target]) for target in expected_targets) for row in tables['score_matrix']), '五乘五矩阵含缺失或无效评分')  # 用户要求的25格必须全部为真实有限值。
            return  # 扩展版本完成专用核验后不套用历史十组限制。
        require(outcome == 'success' and authorization.get('authorized_combination_count') == 10, 'A06结果未绑定十组授权')  # 不把部分计划伪装成完整授权。
        combinations = tables.get('combination_results', [])  # 读取十组汇总表。
        require(len(combinations) == 10 and len({(row['成分编号'], row['受体']) for row in combinations}) == 10, 'A06组合结果数量或身份重复')  # 每个成分受体对只出现一次。
        require({row['成分编号'] for row in combinations} == set(AUTHORIZED_COMPOUNDS), 'A06成分集合与授权不符')  # 不允许临时换成分。
        require({row['受体'] for row in combinations} == set(AUTHORIZED_TARGETS), 'A06结果混入未授权受体')  # HSP90AA1不得进入正式结果。
        require(summary.get('计划组合数') == 10 and summary.get('HSP90AA1未运行组合数') == 5, 'A06结果摘要数量不正确')  # 同时说明完成和暂停范围。
        require(summary.get('成功组合数') + summary.get('失败组合数') == 10, 'A06成功失败数量不能覆盖全部计划')  # 不允许遗漏组合。
        require(summary.get('handoff_blocked') == (summary.get('失败组合数') > 0), 'A06交接状态与失败数量不一致')  # 技术失败必须先处理。
        for row in combinations:  # 对每个完成组合检查关键数值。
            if row['状态'] == '完成':  # 只有真实完成项具有结合能。
                require(isinstance(row['最佳有效结合能_kcal_mol'], (int, float)) and math.isfinite(row['最佳有效结合能_kcal_mol']), 'A06结合能不是有限数值')  # 缺失不能补零。
                require(row['有效姿势数'] > 0 and row['输出姿势数'] >= row['有效姿势数'], 'A06有效姿势数量不正确')  # 至少一个通过七项检查的姿势。
        require(len(tables.get('score_matrix', [])) == 5, 'A06结合能矩阵应有五个成分')  # 双报告热图固定五行。
        require(all(row.get('HSP90AA1') is None for row in tables['score_matrix']), '暂停受体不得出现伪评分')  # 未运行保持空值。
    return validate  # 返回统一框架可调用的校验函数。


def validators(project_root):  # 集中提供两个新模块的校验器。
    return {'A06_PREP': prep_validator(project_root), 'A06': formal_validator(project_root)}  # 不改变其他模块的科学校验。


def _publish_prep(workflow, study_id, package_reference, redocking_reference, authorization_reference):  # 发布并按本轮对话决定批准A06_PREP。
    manifest = workflow.load(study_id)  # 先检查是否已经发布当前准备版本。
    existing = manifest['current'].get('A06_PREP')  # 已有版本时禁止重复生成竞争版本。
    if existing and workflow.approved(manifest, existing):  # 只复用仍为当前且已批准的同输入版本。
        run = workflow.run(manifest, existing)  # 读取实际输入用于比对。
        require(run['inputs'] == {'preparation_package': package_reference, 'redocking_result': redocking_reference, 'formal_authorization': authorization_reference}, '当前A06_PREP不是本次授权版本')  # 不自动复用其他授权。
        return existing  # 返回已批准的准确准备运行。
    package = read_json(verified_file(workflow.root, package_reference))  # 读取十五组原计划。
    redocking = read_json(verified_file(workflow.root, redocking_reference))  # 读取三个受体诊断结果。
    authorization = read_json(verified_file(workflow.root, authorization_reference))  # 读取用户本轮正式授权。
    require(package['study_id'] == study_id and redocking['study_id'] == study_id and authorization['study_id'] == study_id, 'A06_PREP输入不属于当前研究')  # 防止跨研究拼接。
    authorized = [row for row in package['formal_docking_plan'] if row['target_symbol'] in AUTHORIZED_TARGETS]  # 精确提取十组放行计划。
    paused = [row for row in package['formal_docking_plan'] if row['target_symbol'] == PAUSED_TARGET]  # 精确提取五组暂停计划。
    require(len(authorized) == 10 and len(paused) == 5, '正式计划无法拆分为十组授权和五组暂停')  # 输入数量不对时停止。
    inputs = {'preparation_package': package_reference, 'redocking_result': redocking_reference, 'formal_authorization': authorization_reference}  # 三份机器记录共同定义本次准备版本。
    config = {'schema_version': 'A06.prep.published.1', 'analysis_purpose': package['analysis_purpose'], 'authorized_targets': list(AUTHORIZED_TARGETS), 'paused_targets': [PAUSED_TARGET], 'authorized_compounds': list(AUTHORIZED_COMPOUNDS), 'vina_parameters': VINA_PARAMETERS, 'automatic_tuning_performed': False}  # 只保存已确认规则。
    run = workflow.begin(study_id, 'A06_PREP', inputs, config, '三次重对接诊断完成；用户接受HSP90AA1暂停并授权AKT1、MAPK1十组正式对接')  # 统一框架固定上游和代码版本。
    tables = {'receptor_diagnostics': [{'受体': row['symbol'], 'PDB': row['pdb'], 'RMSD_A': row.get('rmsd_angstrom'), '诊断通过': row['passed'], '处理': '进入正式对接' if row['passed'] else '暂停，不自动调参'} for row in redocking['results']], 'authorized_formal_plan': [{'成分编号': row['compound_id'], '成分': row['compound_name'], '受体': row['target_symbol'], 'PDB': row['pdb'], '关系依据': row['relation'], '状态': '已授权待运行'} for row in authorized], 'paused_formal_plan': [{'成分编号': row['compound_id'], '成分': row['compound_name'], '受体': row['target_symbol'], 'PDB': row['pdb'], '关系依据': row['relation'], '状态': '未运行，受体暂停'} for row in paused]}  # 保存可阅读的诊断和计划表。
    summary = {'分析用途': package['analysis_purpose'], '重对接通过受体数': 2, '暂停受体数': 1, '授权正式组合数': 10, '暂停组合数': 5, '自动调参': False, 'handoff_blocked': False}  # 明确准备关口已满足但有限制。
    result = workflow.finish(study_id, run['run_id'], summary, tables, [PAUSED_TARGET + '重对接RMSD超过2 Å；用户接受本次暂停，五组正式组合保持未运行。'], 'success')  # 发布待复核准备结果。
    workflow.review(study_id, run['run_id'], 'approved', '用户对话确认', '用户于2026-09-23明确回复“接受，继续”：接受HSP90AA1暂停，并授权AKT1、MAPK1共10组正式对接。', None)  # 如实登记本轮明确授权而不借用用户姓名。
    return result['run_id']  # A06随后只能依赖这个已批准版本。


def _resolve_inputs(root, package, plan):  # 从候选包已有指纹清单定位一个正式组合的输入。
    ligand_report = read_json(verified_file(root, package['config']))  # 主配置提供准备包引用。
    ligand_reference = ligand_report['ligand_preparation']  # 使用配置绑定的五配体准备报告。
    ligand_data = read_json(verified_file(root, ligand_reference))  # 读取不可变配体准备包。
    ligand = next((row for row in ligand_data['results'] if row['compound_id'] == plan['compound_id']), None)  # 按稳定成分编号选择唯一对象。
    require(ligand is not None and ligand['status'] == 'prepared_candidate', '未找到已核实的正式配体：' + plan['compound_id'])  # 不按名称模糊匹配。
    ligand_pdbqt = _record_by_suffix(ligand['files'], '.pdbqt')  # 唯一定位Meeko正式输入。
    ligand_sdf = _record_by_suffix(ligand['files'], '.sdf')  # 保存对应三维来源结构。
    receptor_plan = next((row for row in package['redocking_plan'] if row['symbol'] == plan['target_symbol']), None)  # 受体必须来自同一重对接计划。
    require(receptor_plan is not None and receptor_plan['pdb'] == plan['pdb'], '正式受体与诊断受体不一致')  # 不允许换PDB继续使用诊断结论。
    receptor_pdbqt = _record_by_suffix(receptor_plan['receptor_files'], '_' + plan['pdb'] + '_A.pdbqt')  # 唯一定位通过诊断的受体文件。
    return ligand, ligand_pdbqt, ligand_sdf, receptor_pdbqt  # 返回全部带指纹输入。


def _update_preview(workflow, study_id, result):  # 将只读预览切换为十组正式结果待复核状态。
    index_path = workflow.root / 'environments' / 'A06_previews.json'  # 沿用唯一预览指针。
    index = read_json(index_path)  # 不扫描治理目录猜当前文件。
    previous_reference = index['studies'][study_id]  # 记录旧预览来源。
    previous = read_json(verified_file(workflow.root, previous_reference))  # 旧预览必须保持完整。
    current = deepcopy(previous)  # 新文件保存新状态而不覆盖旧历史。
    current['notice'] = 'AKT1、MAPK1共10组正式对接已完成；HSP90AA1的5组保持未运行。请在A06卡片集中复核结合能矩阵和限制。'  # 明确当前任务。
    current['pending'] = [{'item': '复核A06正式对接结果', 'impact': '确认10组结果及HSP90AA1暂停限制是否可用于本次流程测试；无需逐个审核全部姿势。'}]  # 只保留一个人工重点。
    current['formal_docking_report'] = _project_record(workflow.root, workflow.location(study_id) / 'runs' / 'A06' / result['run_id'] / 'result.json', 'formal_docking_result')  # 指向统一框架结果。
    current['previous_preview'] = previous_reference  # 保存完整状态链。
    preview_path = workflow.root / 'governance' / 'A06准备预览_正式对接10组已完成待复核_20260923.json'  # 名称表达日期和用途。
    write_json(preview_path, current)  # 新预览不可覆盖。
    index['studies'][study_id] = _project_record(workflow.root, preview_path, 'a06_preview')  # 当前指针切换到新状态。
    write_json(index_path, index, replace=True)  # 仅唯一索引允许原子替换。


def run_formal(root, study_id, package_reference, redocking_reference, authorization_reference):  # 发布准备关口并执行十组正式对接。
    root = Path(root).resolve()  # 固定独立新项目根目录。
    module_validators = validators(root)  # 为A06_PREP和A06启用领域校验。
    workflow = Workflow(root, module_validators)  # 使用统一研究索引和复核状态。
    package = read_json(verified_file(root, package_reference))  # 读取已复核候选包。
    redocking = read_json(verified_file(root, redocking_reference))  # 读取三次真实诊断。
    authorization = read_json(verified_file(root, authorization_reference))  # 读取本轮明确执行授权。
    require(package.get('schema_version') == 'A06.preparation.package.1' and package.get('study_id') == study_id, 'A06候选包身份不符')  # 拒绝跨研究候选包。
    require(redocking.get('schema_version') == 'A06.redocking.result.1' and redocking.get('preparation_package') == package_reference, '重对接结果未绑定当前候选包')  # 诊断不可替换。
    require(authorization.get('preparation_package') == package_reference and authorization.get('redocking_result') == redocking_reference, '正式授权未绑定当前候选包和诊断结果')  # 授权对象必须精确。
    require(authorization.get('authorized_targets') == list(AUTHORIZED_TARGETS) and authorization.get('paused_targets') == [PAUSED_TARGET], '正式授权的受体范围不正确')  # 不允许执行第三个受体。
    _publish_prep(workflow, study_id, package_reference, redocking_reference, authorization_reference)  # 先形成已批准A06_PREP版本。
    plans = [row for row in package['formal_docking_plan'] if row['target_symbol'] in AUTHORIZED_TARGETS]  # 只选择十组授权计划。
    excluded = [row for row in package['formal_docking_plan'] if row['target_symbol'] == PAUSED_TARGET]  # 五组暂停计划只留痕。
    require(len(plans) == 10 and len(excluded) == 5 and all(row['status'] == 'not_run' for row in excluded), '授权或暂停组合数量不正确')  # HSP90AA1不得已有输出。
    environment_record = next(record for record in package['evidence'] if record.get('role') == 'vina_environment')  # 从候选包选择固定环境记录。
    executable_record = next(record for record in package['evidence'] if record.get('role') == 'vina_executable')  # 从同一包选择固定二进制。
    executable = verified_file(root, executable_record)  # 执行前再次校验Vina程序指纹。
    configuration = read_json(verified_file(root, package['config']))  # 读取已批准参数来源。
    require(configuration['vina_parameters'] == VINA_PARAMETERS, 'Vina参数与已批准配置不一致')  # 不使用程序默认值补参数。
    inputs = {'preparation_package': package_reference, 'redocking_result': redocking_reference, 'formal_authorization': authorization_reference, 'vina_environment': environment_record, 'vina_executable': executable_record}  # 固定本轮全部关键输入。
    config = {'schema_version': 'A06.formal.config.1', 'analysis_purpose': package['analysis_purpose'], 'targets': list(AUTHORIZED_TARGETS), 'paused_target': PAUSED_TARGET, 'compounds': list(AUTHORIZED_COMPOUNDS), 'combination_count': 10, 'vina_parameters': VINA_PARAMETERS, 'score_use': 'lowest_valid_raw_vina_affinity', 'automatic_tuning_performed': False}  # 仅保存已确认口径。
    run = workflow.begin(study_id, 'A06', inputs, config, '用户接受HSP90AA1暂停并授权AKT1、MAPK1十组正式分子对接')  # A06依赖刚批准的A06_PREP。
    folder = workflow.location(study_id) / 'runs' / 'A06' / run['run_id']  # 使用统一框架已创建的运行目录。
    code_snapshot = folder / 'docking_formal.py'  # 本次实际代码随结果保留。
    shutil.copyfile(Path(__file__).resolve(), code_snapshot)  # 复制完成后不再修改本次快照。
    results, pose_rows, anomalies = [], [], [PAUSED_TARGET + '因参考配体重对接未通过，本次5组正式组合未运行。']  # 分别收集组合、姿势和限制。
    for plan in plans:  # 按候选包固定顺序执行十组。
        ligand, ligand_record, ligand_sdf_record, receptor_record = _resolve_inputs(root, package, plan)  # 精确定位一组输入。
        ligand_path = verified_file(root, ligand_record)  # 校验配体PDBQT未改变。
        verified_file(root, ligand_sdf_record)  # 同时校验来源SDF未改变。
        receptor_path = verified_file(root, receptor_record)  # 校验受体PDBQT未改变。
        prefix = plan['compound_id'] + '_' + plan['target_symbol'] + '_' + plan['pdb']  # 文件名只用于阅读，不替代内部身份。
        output_path = folder / (prefix + '_docked.pdbqt')  # 姿势输出归入本次不可变运行。
        arguments = [str(executable), '--receptor', str(receptor_path), '--ligand', str(ligand_path), '--center_x', str(plan['search_box']['center_angstrom'][0]), '--center_y', str(plan['search_box']['center_angstrom'][1]), '--center_z', str(plan['search_box']['center_angstrom'][2]), '--size_x', str(plan['search_box']['size_angstrom'][0]), '--size_y', str(plan['search_box']['size_angstrom'][1]), '--size_z', str(plan['search_box']['size_angstrom'][2]), '--scoring', VINA_PARAMETERS['scoring'], '--exhaustiveness', str(VINA_PARAMETERS['exhaustiveness']), '--num_modes', str(VINA_PARAMETERS['num_modes']), '--energy_range', str(VINA_PARAMETERS['energy_range_kcal_mol']), '--seed', str(VINA_PARAMETERS['seed']), '--out', str(output_path)]  # 参数列表避免中文路径和转义改变值。
        command = {'schema_version': 'A06.formal.command.1', 'compound_id': plan['compound_id'], 'compound_name': plan['compound_name'], 'target_symbol': plan['target_symbol'], 'target_id': plan['target_id'], 'pdb': plan['pdb'], 'relation': plan['relation'], 'receptor': receptor_record, 'ligand_pdbqt': ligand_record, 'ligand_sdf': ligand_sdf_record, 'search_box': plan['search_box'], 'vina_parameters': VINA_PARAMETERS, 'arguments_without_absolute_paths': ['vina_1.2.7_win.exe', '--receptor', receptor_record['path'], '--ligand', ligand_record['path'], '--center_x', str(plan['search_box']['center_angstrom'][0]), '--center_y', str(plan['search_box']['center_angstrom'][1]), '--center_z', str(plan['search_box']['center_angstrom'][2]), '--size_x', str(plan['search_box']['size_angstrom'][0]), '--size_y', str(plan['search_box']['size_angstrom'][1]), '--size_z', str(plan['search_box']['size_angstrom'][2]), '--scoring', VINA_PARAMETERS['scoring'], '--exhaustiveness', '8', '--num_modes', '9', '--energy_range', '3', '--seed', '1', '--out', output_path.name]}  # 保存可迁移命令记录。
        write_json(folder / (prefix + '_command.json'), command)  # 在调用Vina前固定该组输入。
        completed = subprocess.run(arguments, cwd=folder, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)  # 捕获真实退出码和完整日志。
        _write_text(folder / (prefix + '_stdout.txt'), completed.stdout)  # 标准输出单独留存。
        _write_text(folder / (prefix + '_stderr.txt'), completed.stderr)  # 标准错误单独留存。
        result_row = {'成分编号': plan['compound_id'], '成分': plan['compound_name'], '受体': plan['target_symbol'], '靶点编号': plan['target_id'], 'PDB': plan['pdb'], '关系依据': plan['relation'], '状态': '失败', '最佳有效结合能_kcal_mol': None, '输出姿势数': 0, '有效姿势数': 0, '最近受体重原子距离_A': None, '自动调参': False}  # 先建立不以零代替缺失的结果行。
        validation = {'schema_version': 'A06.formal.validation.1', 'compound_id': plan['compound_id'], 'target_symbol': plan['target_symbol'], 'return_code': completed.returncode, 'process_complete': completed.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0, 'automatic_tuning_performed': False, 'poses': []}  # 保存七项检查的实际事实。
        try:  # 单组失败不影响其他已授权组合执行。
            require(validation['process_complete'], 'Vina进程未完整产生输出')  # 进程完整是第一项必要检查。
            input_atoms = _input_atoms(ligand_path.read_text(encoding='utf-8'))  # 读取精确配体身份。
            poses = _poses(output_path.read_text(encoding='utf-8'))  # 解析全部真实姿势和原始评分。
            valid_poses = []  # 只有身份及盒内检查均通过的姿势可进入矩阵。
            for pose in poses:  # 对九个模式逐一核验。
                identity = _pose_identity(pose, input_atoms, ligand['identity']['heavy_atom_count'])  # 核对配体没有换位或丢原子。
                inside = _inside_box(pose, plan['search_box'])  # 核对所有输出原子位于已批准搜索盒。
                distance = _minimum_receptor_distance(receptor_path.read_text(encoding='utf-8'), pose)  # 最近重原子距离只报告不设阈值。
                passed = identity['passed'] and inside['passed']  # 首版基础有效性不增加自拟距离阈值。
                pose_fact = {'mode': pose['mode'], 'score_kcal_mol': pose['score_kcal_mol'], 'identity_passed': identity['passed'], 'inside_box_passed': inside['passed'], 'minimum_receptor_heavy_atom_distance_angstrom': distance, 'valid_for_matrix': passed}  # 保存每个模式关键事实。
                validation['poses'].append({'mode': pose['mode'], 'score_kcal_mol': pose['score_kcal_mol'], 'identity': identity, 'inside_box': inside, 'minimum_receptor_heavy_atom_distance_angstrom': distance, 'valid_for_matrix': passed})  # 完整检查进入单组记录。
                pose_rows.append({'成分编号': plan['compound_id'], '成分': plan['compound_name'], '受体': plan['target_symbol'], 'PDB': plan['pdb'], '模式': pose['mode'], '结合能_kcal_mol': pose['score_kcal_mol'], '身份通过': identity['passed'], '全部原子在盒内': inside['passed'], '最近受体重原子距离_A': distance, '纳入矩阵': passed})  # 标准CSV便于逐姿势复核。
                if passed:  # 只纳入满足基础完整性规则的姿势。
                    valid_poses.append(pose_fact)  # 保存候选评分和距离。
            require(valid_poses, '没有姿势同时通过配体身份和搜索盒检查')  # 缺失不填零也不选无效姿势。
            best = min(valid_poses, key=lambda row: (row['score_kcal_mol'], row['mode']))  # 采用最低有效原始Vina评分，模式号处理完全相同的并列。
            result_row.update({'状态': '完成', '最佳有效结合能_kcal_mol': best['score_kcal_mol'], '输出姿势数': len(poses), '有效姿势数': len(valid_poses), '最近受体重原子距离_A': best['minimum_receptor_heavy_atom_distance_angstrom']})  # 汇总只保留实际最佳有效姿势。
            validation['status'] = 'completed'  # 标记该组合完整完成。
            validation['selected_mode'] = best['mode']  # 记录矩阵实际采用的模式。
            validation['selected_score_kcal_mol'] = best['score_kcal_mol']  # 保留未四舍五入原始数值。
        except (ContractError, OSError, ValueError, subprocess.SubprocessError) as error:  # 捕获可解释的单组技术失败。
            validation['status'] = 'failed'  # 不把失败项写成弱结合。
            validation['failure_reason'] = str(error)  # 保存具体原因供修复。
            anomalies.append(plan['compound_id'] + '×' + plan['target_symbol'] + '：' + str(error))  # 集中显示失败组合。
        write_json(folder / (prefix + '_validation.json'), validation)  # 单组验证最后独立发布。
        results.append(result_row)  # 无论成败均覆盖十组计划中的一项。
    require(len(results) == 10, '正式对接没有覆盖全部十组授权计划')  # 不允许提前退出后形成部分摘要。
    matrix = []  # 将十组结果重排为双报告使用的五行矩阵。
    for compound_id in AUTHORIZED_COMPOUNDS:  # 使用已批准候选顺序而非分数排序。
        rows = [row for row in results if row['成分编号'] == compound_id]  # 每个成分应对应两个受体。
        require(len(rows) == 2, '结合能矩阵缺少成分—受体组合：' + compound_id)  # 不从其他文件补值。
        matrix.append({'compound_id': compound_id, 'compound_name': rows[0]['成分'], 'AKT1': next(row['最佳有效结合能_kcal_mol'] for row in rows if row['受体'] == 'AKT1'), 'MAPK1': next(row['最佳有效结合能_kcal_mol'] for row in rows if row['受体'] == 'MAPK1'), 'HSP90AA1': None})  # 暂停受体明确留空。
    heatmap_path = folder / 'binding_energy_heatmap.svg'  # 图形与本次标准结果同目录。
    _write_heatmap(heatmap_path, matrix)  # 图中每格保留实际评分。
    summary = {'分析用途': package['analysis_purpose'], '计划组合数': 10, '成功组合数': sum(row['状态'] == '完成' for row in results), '失败组合数': sum(row['状态'] != '完成' for row in results), '输出姿势总数': sum(row['输出姿势数'] for row in results), 'HSP90AA1未运行组合数': 5, '评分口径': '每组通过身份与搜索盒检查的姿势中最低原始Vina评分', '自动调参': False, 'handoff_blocked': any(row['状态'] != '完成' for row in results)}  # 摘要不设结合能通过阈值。
    tables = {'combination_results': results, 'pose_scores': pose_rows, 'score_matrix': matrix, 'excluded_unrun_combinations': [{'成分编号': row['compound_id'], '成分': row['compound_name'], '受体': row['target_symbol'], 'PDB': row['pdb'], '状态': '未运行，受体暂停'} for row in excluded]}  # 完整保存已运行和明确未运行范围。
    study_root = workflow.location(study_id)  # 标准结果关联文件必须相对研究根目录。
    figures = [file_record(study_root, heatmap_path, 'figure')]  # 热图纳入结果指纹链。
    attachments = [file_record(study_root, code_snapshot, 'code_snapshot')]  # 保存本次实际执行代码。
    attachments.extend(file_record(study_root, path, 'docking_evidence') for path in sorted(folder.iterdir()) if path.is_file() and path.name not in {'run.json', 'docking_formal.py', 'binding_energy_heatmap.svg'})  # 命令、日志、姿势和验证记录全部归档。
    result = workflow.finish(study_id, run['run_id'], summary, tables, anomalies, 'success', figures=figures, attachments=attachments)  # 发布待用户复核的A06标准结果。
    _update_preview(workflow, study_id, result)  # 只读预览同步到真实完成状态。
    return _project_record(root, folder / 'result.json', 'formal_docking_result')  # 返回小型结果索引供调用方记录。


if __name__ == '__main__':  # 提供带明确文件记录的维护入口。
    import argparse  # 命令行不从目录猜输入版本。
    parser = argparse.ArgumentParser(description='发布A06_PREP并执行已授权的十组正式分子对接')  # 说明本入口的准确边界。
    parser.add_argument('--root', required=True)  # 项目根目录必须明确。
    parser.add_argument('--study', required=True)  # 研究编号必须明确。
    parser.add_argument('--package-record', required=True)  # 候选包文件记录以JSON传入。
    parser.add_argument('--redocking-record', required=True)  # 重对接结果文件记录以JSON传入。
    parser.add_argument('--authorization-record', required=True)  # 正式授权文件记录以JSON传入。
    arguments = parser.parse_args()  # 解析本次唯一输入。
    output = run_formal(arguments.root, arguments.study, json.loads(arguments.package_record), json.loads(arguments.redocking_record), json.loads(arguments.authorization_record))  # 执行并返回结果索引。
    print(json.dumps(output, ensure_ascii=False))  # 控制台只输出小型文件记录。
