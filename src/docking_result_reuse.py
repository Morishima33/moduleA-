# 补库后核验复用已有对接事实；本程序不启动Vina。
import copy  # 保留原事实包不变。
from pathlib import Path  # 明确研究归属。
from storage import read_json, write_json, verified_file, file_record, new_id, now  # 统一追溯。
from contracts import require  # 统一阻断。
from docking_contract import validate_generic_result  # 检查矩阵。
from docking_top10_publish import _workflow  # 原版本衔接。

def create_candidate(root, input_check, current_redocking, boundary, display_label):  # 仅生成核验过的新候选，不计算、不审批、不生成报告。
    root = Path(root).resolve()  # 明确项目根。
    check_path = (root / input_check).resolve()  # 明确来源核验。
    qc_path = (root / current_redocking).resolve()  # 明确本轮参考质控。
    require(check_path.is_relative_to(root) and qc_path.is_relative_to(root), '核验位置超出项目')  # 保护路径。
    check = read_json(check_path)  # 获取绑定研究身份。
    sid = check['study_id']  # 不绑定固定疾病。
    home = root / 'studies' / sid  # 研究独立归档。
    require(read_json(qc_path)['study_id'] == sid, '参考质控来自不同研究')  # 禁止跨研究拼接。
    qc = read_json(qc_path)  # 精确读取两份来源。
    old_path = verified_file(home, check['old_generic'])  # 原评分带指纹。
    old = read_json(old_path)  # 不扫描目录猜版本。
    generic = copy.deepcopy(old)  # 新事实包不覆盖旧记录。
    w = _workflow(root)  # 生产校验器。
    manifest = w.load(sid)  # 当前上游。
    require(qc['status'] == 'qc_complete' and all(manifest['current'][k] == v for k, v in qc['parent_runs'].items()), '参考质控过期或未完成')  # 禁止过期复用。
    for record in check['file_records'] + qc['files']:  # 全部原计算和本轮质控证据。
        verified_file(home, record)  # 确认原件不变。
    screen_index = read_json(root / 'environments/A06_previews.json')  # 明确当前预览。
    screen = read_json(verified_file(root, screen_index['studies'][sid]))  # 当前筛查。
    require(screen['parent_runs'] == qc['parent_runs'], '筛查上游不一致')  # 不跨版本。
    old_receptors = {row['target']: row for row in old['receptors']}  # 靶点索引。
    qc_rows = {row['target']: row for row in qc['results']}  # 实测质控索引。
    order = [row['symbol'] for row in screen['screening_window']]  # 新PPI顺序。
    compound_order = [row['compound_id'] for row in old['compounds']]  # 原配体顺序。
    require(set(order) == set(old_receptors), '受体集合改变，不能全部复用')  # 新对象不得借分数。
    require([row['compound_id'] for row in screen['ligands']] == compound_order, '配体集合或顺序改变')  # 七个配体核对。
    for pair in generic['completed_pairs']:  # 逐项核验47组。
        receptor, new_qc = old_receptors[pair['target']], qc_rows[pair['target']]  # 原结构与本轮质控对应。
        require(all(receptor[k] == new_qc[k] for k in ('center', 'size', 'pdb_id', 'chains')), '受体身份或空间改变')  # 必须完全一致。
        if new_qc.get('inputs'):  # 有本轮参考质控输入时比对字节。
            require(pair['receptor_record']['sha256'] == new_qc['inputs']['receptor']['sha256'], '受体准备字节改变')  # 同名不能替代同输入。
        if not pair.get('all_poses_record'):  # 兼容原候选未直接登记全部模式角色。
            original_command = read_json(verified_file(home, pair['command_record']))  # 只能从原实测命令定位。
            arguments = original_command['arguments']  # 原参数列表。
            output_path = Path(arguments[arguments.index('--out') + 1]).resolve()  # 精确输出路径。
            require(output_path.is_relative_to(home), '原姿势输出超出研究')  # 禁止跨研究。
            matches = [record for record in check['file_records'] if record['path'] == output_path.relative_to(home).as_posix()]  # 必须已在核验清单。
            require(len(matches) == 1, '原全部姿势未唯一绑定')  # 不根据同名猜测。
            pair['all_poses_record'] = matches[0]  # 只补充原已归档角色。
        for key in ('pose_record', 'receptor_record', 'ligand_record', 'command_record', 'log_record', 'all_poses_record'):  # 全部必要记录。
            verified_file(home, pair[key])  # 确认姿势和输入日志。
        command = read_json(verified_file(home, pair['command_record']))  # 原实际命令。
        require(command['parameters'] == qc['vina_parameters'] and command['search_box'] == {'center': receptor['center'], 'size': receptor['size']}, '原参数或搜索盒不一致')  # 不能跨参数拼图。
    generic['receptors'] = []  # 只更新顺序和主要范围。
    for rank, target in enumerate(order, 1):  # 全部十项保留。
        row = copy.deepcopy(old_receptors[target])  # 结构限制原样保留。
        row.update(ppi_rank=rank, primary_result=target in qc['primary_targets'])  # 新PPI主次。
        if qc_rows[target]['rmsd_A'] is not None:  # 仅更新实际本轮测得值。
            row['redocking_rmsd_A'] = qc_rows[target]['rmsd_A']  # 不冒充原质控。
        row['interpretation_scope'] = '主要结果' if row['primary_result'] else ('扩展参考结果' if qc_rows[target]['strict_pass'] else old_receptors[target]['interpretation_scope'])  # 嵌合等限制保留。
        generic['receptors'].append(row)  # 十行完整。
    generic['primary_targets'], generic['strict_qc_passed_targets'] = qc['primary_targets'], qc['strict_targets']  # 本轮实测清单。
    generic['planned_pairs'] = [{'compound_id': cid, 'target': target} for target in order for cid in compound_order]  # 完整70组。
    for key in ('completed_pairs', 'failed_pairs'):  # 成功和失败同序。
        generic[key].sort(key=lambda row: (order.index(row['target']), compound_order.index(row['compound_id'])))  # 只变展示顺序。
    require(bool(boundary.strip()) and bool(display_label.strip()), '须提供本研究的真实来源和显示说明')  # 不猜来源元数据。
    generic['reuse_provenance'] = {'schema_version': 'A06.reuse.1', 'authorization': '用户明确要求相同对接复用，不重新计算', 'recorded_at': now(), 'source_generic': check['old_generic'], 'input_check': file_record(home, check_path, 'input_reuse_check'), 'current_redocking': file_record(home, qc_path, 'current_reference_redocking'), 'parent_runs': qc['parent_runs'], 'reused_completed_count': len(generic['completed_pairs']), 'retained_failed_count': len(generic['failed_pairs']), 'new_compound_docking_executed': False, 'display_label': display_label, 'source_boundary': boundary}  # 绑定完整复用说明。
    generic['evidence_files'].extend([file_record(home, old_path, 'reuse_source_generic'), file_record(home, check_path, 'input_reuse_check'), file_record(home, qc_path, 'current_reference_redocking')] + qc['files'])  # 新旧证据留痕。
    validate_generic_result(generic)  # 全矩阵校验。
    candidate = home / 'runs/A06_PREP' / new_id('reuse') / 'generic_docking.json'  # 唯一新候选位置。
    write_json(candidate, generic)  # 不覆盖历史。
    return candidate  # 将明确候选位置交给现有发布流程。
