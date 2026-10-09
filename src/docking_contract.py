# A06通用结果契约；只校验实际对象、组合和失败事实，不固定疾病或矩阵大小。
import math  # 检查评分是否为有限数值。

from contracts import require  # 复用项目统一阻断规则。


SCHEMA_VERSION = "A06.generic.result.2"  # 第二版支持预测口袋、动态矩阵及无参考配体的真实空RMSD。
LEGACY_SCHEMA_VERSION = "A06.generic.result.1"  # 第一版历史结果继续保持可读和可复算。
RECEPTOR_FIELDS = {"target", "pdb_id", "chains", "reference_ligand", "center", "size", "redocking_rmsd_A", "qc_status"}  # 报告与复算共同需要的受体字段。
TRACE_FIELDS = {"ppi_rank", "pocket_basis", "structure_limitation", "interpretation_scope", "primary_result", "redocking_status"}  # 第二版新增的来源与解释边界。


def _identity_rows(rows, first, second):  # 建立两列稳定身份组合并检查重复。
    identities = [(str(row.get(first, "")).strip(), str(row.get(second, "")).strip()) for row in rows]  # 保留实际身份。
    require(all(left and right for left, right in identities), "A06组合存在空身份")  # 空身份不能追溯。
    require(len(identities) == len(set(identities)), "A06组合身份重复")  # 每个组合只允许一条记录。
    return identities  # 返回组合顺序供矩阵核对。


def validate_generic_result(result):  # 校验任意方剂疾病研究的A06标准结果。
    version = result.get("contract_version")  # 读取契约版本以兼容已冻结历史结果。
    require(version in {SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}, "A06通用结果契约版本不正确")  # 禁止静默套用未知结构。
    outcome = result.get("outcome")  # 读取成功、部分完成或有效空结果。
    require(outcome in {"success", "partial", "empty"}, "A06通用结果状态不正确")  # 三种状态均须明确。
    compounds = result.get("compounds", [])  # 候选成分来自本次实际选择。
    receptors = result.get("receptors", [])  # 受体来自本次实际质控。
    planned = result.get("planned_pairs", [])  # 计划组合必须逐项保存。
    completed = result.get("completed_pairs", [])  # 完成组合必须逐项保存。
    failed = result.get("failed_pairs", [])  # 失败或暂停组合必须逐项保存原因。
    compound_ids = [str(row.get("compound_id", "")).strip() for row in compounds]  # 提取稳定成分编号。
    target_ids = [str(row.get("target", "")).strip() for row in receptors]  # 提取受体基因符号。
    require(all(compound_ids) and len(compound_ids) == len(set(compound_ids)), "A06成分身份缺失或重复")  # 成分不能靠名称合并。
    require(all(target_ids) and len(target_ids) == len(set(target_ids)), "A06受体身份缺失或重复")  # 受体必须唯一。
    require(all(RECEPTOR_FIELDS <= set(row) for row in receptors), "A06受体参数表字段不完整")  # 缺少结构事实时不得出正式表。
    if version == SCHEMA_VERSION:  # 第二版必须携带PPI顺序、口袋来源和解释限制。
        require(all(TRACE_FIELDS <= set(row) for row in receptors), "A06第二版受体追溯字段不完整")  # 热图后说明表不能依靠人工补写。
    for row in receptors:  # 逐项核对搜索空间和重对接事实。
        failed_not_computable = version == SCHEMA_VERSION and row.get("redocking_status") == "failed_not_computable"  # 无法准备的受体允许真实空搜索盒。
        if failed_not_computable:  # 失败项不得用虚构坐标占位。
            require(row["center"] is None and row["size"] is None, "A06无法计算受体的搜索盒必须留空")  # 防止1,1,1等假坐标进入报告。
        else:  # 可运行或预测口袋受体必须有完整三维盒。
            require(len(row["center"]) == 3 and len(row["size"]) == 3, "A06搜索盒必须包含三个坐标和三个尺寸")  # 三维空间不能缺轴。
            require(all(isinstance(value, (int, float)) and math.isfinite(value) for value in row["center"] + row["size"]), "A06搜索盒含无效数值")  # 禁止空值补零。
            require(all(value > 0 for value in row["size"]), "A06搜索盒尺寸必须大于零")  # 非正尺寸无法运行。
        rmsd = row["redocking_rmsd_A"]  # 预测口袋没有参考配体时应真实保存为空。
        if rmsd is None:  # 第二版允许预测口袋不适用或结构准备失败而没有RMSD。
            require(version == SCHEMA_VERSION and row.get("redocking_status") in {"not_applicable_no_reference_ligand", "failed_not_computable"}, "A06缺少重对接RMSD且未说明不适用或失败原因")  # 失败不能冒充预测口袋不适用。
            if row.get("redocking_status") == "failed_not_computable":  # 失败受体必须明确限制下游解释。
                require(row.get("primary_result") is False and "失败" in str(row.get("qc_status", "")), "A06无法重对接受体不得作为主要结果")  # 禁止失败项进入主要结论。
        else:  # 有参考配体时必须保存有限数值。
            require(isinstance(rmsd, (int, float)) and math.isfinite(rmsd), "A06重对接RMSD无效")  # 保存真实数值。
    planned_ids = _identity_rows(planned, "compound_id", "target")  # 检查计划组合。
    if version == SCHEMA_VERSION and outcome != "empty":  # 扩展矩阵必须覆盖全部对象的笛卡尔积。
        require(set(planned_ids) == {(compound, target) for compound in compound_ids for target in target_ids}, "A06动态矩阵计划缺少对象组合")  # 防止整组静默遗漏。
    completed_ids = _identity_rows(completed, "compound_id", "target")  # 检查完成组合。
    failed_ids = _identity_rows(failed, "compound_id", "target")  # 检查失败组合。
    allowed = set(compound_ids) | {""}  # 形成当前成分范围。
    require(all(compound in allowed and target in set(target_ids) for compound, target in planned_ids), "A06计划组合超出本次对象范围")  # 不允许运行时换对象。
    require(set(completed_ids).isdisjoint(failed_ids), "A06同一组合不能同时成功和失败")  # 状态必须唯一。
    require(set(completed_ids) | set(failed_ids) == set(planned_ids), "A06完成与失败记录未覆盖全部计划")  # 不允许组合失踪。
    receiver_index = {row["target"]: row for row in receptors}  # 按身份核对成功组合对应的受体。
    for row in completed:  # 完成项必须有可报告评分和姿势来源。
        require(receiver_index[row["target"]].get("redocking_status") not in {"failed", "failed_not_computable"}, "A06失败受体不能包含成功评分")  # 失败项只能保留NA。
        require(version != SCHEMA_VERSION or row.get("selected_mode", 1) == 1, "A06动态结果仅允许Top-1姿势")  # 不自动改选较低模式。
        require(isinstance(row.get("score_kcal_mol"), (int, float)) and math.isfinite(row["score_kcal_mol"]), "A06完成组合缺少有限评分")  # 不用零或文本占位。
        pose_record = row.get("pose_record")  # 姿势必须使用带指纹文件记录。
        require(isinstance(pose_record, dict) and all(pose_record.get(key) not in (None, "") for key in ("path", "bytes", "sha256")), "A06完成组合缺少带指纹姿势记录")  # 图表必须能回到唯一文件。
    require(all(str(row.get("reason", "")).strip() for row in failed), "A06失败组合必须记录原因")  # 失败原因用于人工处理。
    if outcome == "success":  # 全部成功时不得保留失败组合。
        require(planned and not failed, "A06成功状态与组合事实不一致")  # 空计划不能称为成功。
    elif outcome == "partial":  # 部分完成必须同时存在成功和失败。
        require(completed and failed, "A06部分完成状态与组合事实不一致")  # 防止含糊状态。
    else:  # 有效空结果不得伪造候选和评分。
        require(not planned and not completed and not failed, "A06空结果不能包含对接组合")  # 空结果可继续报告但无结构结论。
        require(str(result.get("empty_reason", "")).strip(), "A06空结果必须说明原因")  # 报告需要解释为何为空。
    return True  # 所有约束通过后允许进入报告层。


def receptor_setup_table(result):  # 将通用受体记录转换为A07固定列名。
    validate_generic_result(result)  # 转换前先完成独立校验。
    return [{"靶点基因": row["target"], "PDB ID": row["pdb_id"], "蛋白链": "/".join(row["chains"]), "共晶参考配体": row["reference_ligand"], "搜索盒中心坐标": "未形成" if row["center"] is None else ", ".join(f"{axis}={value:.3f}" for axis, value in zip("XYZ", row["center"])), "搜索盒尺寸": "未形成" if row["size"] is None else ", ".join(f"{axis}={value:.3f}" for axis, value in zip("XYZ", row["size"])), "重对接RMSD（Å）": ("失败，未形成" if row.get("redocking_status") == "failed_not_computable" else "不适用") if row["redocking_rmsd_A"] is None else f"{row['redocking_rmsd_A']:.3f}", "质控状态": row["qc_status"]} for row in result["receptors"]]  # 预测不适用与真实失败分开呈现。


def receptor_limitation_table(result):  # 生成紧跟热图的中文结构限制与解释表。
    validate_generic_result(result)  # 所有文字必须来自已验证的第二版受体记录。
    if result.get("contract_version") != SCHEMA_VERSION:  # 历史结果没有这组结构化字段。
        return []  # 不从旧自由文本猜测限制。
    return [{"PPI顺序": row["ppi_rank"], "靶点": row["target"], "PDB ID": row["pdb_id"], "搜索盒依据": row["pocket_basis"], "重对接情况": ("失败，未形成可报告RMSD" if row.get("redocking_status") == "failed_not_computable" else "无参考配体，不适用") if row["redocking_rmsd_A"] is None else f"RMSD={row['redocking_rmsd_A']:.3f} Å", "结构或方法限制": row["structure_limitation"], "允许的解释范围": row["interpretation_scope"]} for row in result["receptors"]]  # 不使用A/B/C字母分级。


def score_matrix_table(result):  # 从组合明细生成动态结合能矩阵。
    validate_generic_result(result)  # 矩阵只能来自已核验组合。
    if result["outcome"] == "empty":  # 有效空结果不生成假矩阵。
        return []  # 报告层将明确写出空结果原因。
    scores = {(row["compound_id"], row["target"]): row["score_kcal_mol"] for row in result["completed_pairs"]}  # 建立完成组合索引。
    names = {row["compound_id"]: row.get("name", "") for row in result["compounds"]}  # 保存当前成分名称。
    targets = [row["target"] for row in result["receptors"]]  # 列顺序来自本次受体表。
    return [{"compound_id": compound["compound_id"], "compound_name": names[compound["compound_id"]], **{target: scores.get((compound["compound_id"], target)) for target in targets}} for compound in result["compounds"]]  # 失败格保留None而不补零。
