# PPI前十位动态对接发布器；把候选事实接入统一A06_PREP和A06版本链。
import json  # 输出新运行编号。
from pathlib import Path  # 管理项目和研究包路径。

from components import validate_components  # 注册A01校验器。
from disease import validate_disease  # 注册A02校验器。
from docking_contract import receptor_limitation_table, receptor_setup_table, score_matrix_table, validate_generic_result  # 从通用事实生成报告表。
from docking_formal import formal_validator, prep_validator  # 使用A06领域校验器。
from enrichment_flow import validator as enrichment_validator  # 注册A05校验器。
from intersection_flow import validate_intersection, validate_selection  # 注册A03校验器。
from normalization import validator as normalization_validator  # 注册标准化校验器。
from ppi_flow import validator as ppi_validator  # 注册A04校验器。
from report_flow import validator as report_validator  # 注册A07校验器。
from storage import file_record, now, read_json, write_json  # 使用统一文件指纹和时间。
from workflow import Workflow  # 使用唯一研究版本编排器。


TARGETS = ["TP53", "JUN", "AKT1", "TNF", "HSP90AA1", "IL6", "ESR1", "IL1B", "BCL2", "MAPK1"]  # 当前PPI前十位顺序。


def _workflow(root):  # 建立与网页一致的完整校验器集合。
    validators = {"A01": normalization_validator(root, validate_components), "A02": normalization_validator(root, validate_disease), "A03": validate_intersection, "A03_SELECT": validate_selection, "A04": ppi_validator(root), "A05": enrichment_validator(root), "A06_PREP": prep_validator(root), "A06": formal_validator(root), "A07": report_validator(root)}  # 各模块沿用生产校验器。
    return Workflow(root, validators)  # 返回统一工作流实例。


def publish(root, study_id, generic_path, heatmap_metadata_path, authorization_relative=None, source_notice=None):  # 支持明确的新授权路径与实际来源说明，历史调用保持兼容。
    root = Path(root).resolve()  # 固定项目根目录。
    generic_path = Path(generic_path).resolve()  # 固定候选事实包。
    heatmap_metadata_path = Path(heatmap_metadata_path).resolve()  # 固定图件元数据。
    workflow = _workflow(root)  # 连接统一状态体系。
    study = workflow.location(study_id)  # 限定当前研究包。
    generic = read_json(generic_path)  # 读取70组实际事实。
    validate_generic_result(generic)  # 发布前再次检查计划覆盖和NA原因。
    target_count, compound_count = len(generic["receptors"]), len(generic["compounds"])  # 所有数量读取实际研究对象。
    planned_count = len(generic["planned_pairs"])  # 动态矩阵不硬编码70组。
    targets = [row["target"] for row in generic["receptors"]]  # 保持本次PPI顺序。
    if len(generic.get("primary_targets", [])) != 5:  # 主要受体不足时必须暂停。
        raise ValueError("严格质控主要受体不足5个，不能发布主要结果")  # 不自动检查第11至15位。
    authorization_path = study / (authorization_relative or "governance/A06_PPI前10位扩展对接授权_20261007.json")  # 新结果用独立授权版本，不覆盖旧授权。
    if not authorization_path.resolve().is_relative_to(study.resolve()):  # 检查自定义路径仍属于本研究。
        raise ValueError("授权位置超出本研究")  # 不写到其他研究。
    source_notice = source_notice or "当前研究缺GeneCards，属于workflow_test。"  # 旧调用保持原说明，新调用须传入实际来源。
    authorization_path.parent.mkdir(parents=True, exist_ok=True)  # 沿用研究治理目录。
    authorization = {"schema_version": "A06.top10.authorization.1", "status": "user_approved", "study_id": study_id, "analysis_purpose": "workflow_test", "rule": "PPI前10位及第10位并列全部核查；严格质控至少5个主要受体；失败组合保留NA；热图不显示ABC等级", "targets": targets, "compound_count": compound_count, "planned_pair_count": planned_count, "generic_result_sha256": file_record(study, generic_path, "generic_docking_candidate")["sha256"], "recorded_at": now()}  # 把用户决定绑定到本次文件指纹。
    if authorization_path.exists():  # 中断重试时只接受相同授权事实。
        existing = read_json(authorization_path)  # 读取首次记录。
        if {key: existing.get(key) for key in authorization if key != "recorded_at"} != {key: value for key, value in authorization.items() if key != "recorded_at"}:  # 语义必须相同。
            raise ValueError("已有前十位授权记录与本次事实不一致")  # 禁止覆盖不同授权。
        authorization = existing  # 保留首次准确时间。
    else:  # 首次发布时建立记录。
        write_json(authorization_path, authorization)  # 不覆盖写入。
    generic_record = file_record(study, generic_path, "generic_docking_candidate")  # 绑定候选事实包。
    authorization_record = file_record(study, authorization_path, "user_authorization")  # 绑定用户授权。
    diagnostics = [{"PPI顺序": row["ppi_rank"], "受体": row["target"], "PDB": row["pdb_id"], "RMSD_A": row["redocking_rmsd_A"], "重对接状态": row["redocking_status"], "质控状态": row["qc_status"], "主要结果": row["primary_result"], "结构限制": row["structure_limitation"]} for row in generic["receptors"]]  # 形成十行可读诊断。
    prep_run = workflow.begin(study_id, "A06_PREP", {"generic_candidate": generic_record, "authorization": authorization_record}, {"schema_version": "A06.prep.top10.1", "mode": "ppi_top10_dynamic", "analysis_purpose": "workflow_test", "target_count": target_count, "compound_count": compound_count, "planned_pair_count": planned_count}, "用户批准PPI前十位扩展核查、失败保留NA并以五个严格受体形成主要结果")  # 建立新准备版本。
    prep_summary = {"分析用途": "workflow_test", "受体核查数": target_count, "成分数": compound_count, "计划组合数": planned_count, "严格质控通过受体数": len(generic["strict_qc_passed_targets"]), "主要受体数": len(generic["primary_targets"]), "扩展或失败受体数": target_count - len(generic["primary_targets"]), "handoff_blocked": False}  # 失败扩展项不阻断五个主要受体。
    prep_result = workflow.finish(study_id, prep_run["run_id"], prep_summary, {"receptor_diagnostics": diagnostics}, [source_notice, "扩展受体或配体结构失败项保留NA，不自动调参。"], "success", sources=[generic_record, authorization_record])  # 发布准备结果。
    workflow.review(study_id, prep_run["run_id"], "approved", "用户对话确认", "用户明确同意PPI前10位扩展对接、失败项保留NA、严格质控5个主要受体以及动态热图规则。")  # 记录本轮明确授权。
    manifest = workflow.load(study_id)  # 准备通过后刷新上游状态。
    heatmap_metadata = read_json(heatmap_metadata_path)  # 读取热图与来源绑定。
    heatmap_records = [file_record(study, heatmap_metadata_path, "heatmap_metadata")]  # 先登记元数据。
    for item in heatmap_metadata["files"]:  # 两种图件均与元数据同目录。
        heatmap_records.append(file_record(study, heatmap_metadata_path.parent / item["path"], item["role"]))  # 重新计算研究内指纹。
    formal_run = workflow.begin(study_id, "A06", {"generic_candidate": generic_record, "authorization": authorization_record, "heatmap_metadata": heatmap_records[0]}, {"schema_version": "A06.formal.config.3", "mode": "ppi_top10_dynamic", "analysis_purpose": "workflow_test", "target_count": target_count, "compound_count": compound_count, "planned_pair_count": planned_count, "vina_parameters": generic["vina_parameters"], "automatic_tuning_performed": False}, "发布PPI前十位与七成分的动态分子对接结果")  # 建立正式A06版本。
    summary = {"分析用途": "workflow_test", "计划组合数": len(generic["planned_pairs"]), "成功组合数": len(generic["completed_pairs"]), "失败组合数": len(generic["failed_pairs"]), "主要受体数": len(generic["primary_targets"]), "NA规则": "结构或身份失败不补造评分", "自动调参": False, "handoff_blocked": False}  # 五个主要受体满足时允许进入报告。
    tables = {"generic_docking": generic, "receptor_setup": receptor_setup_table(generic), "receptor_limitations": receptor_limitation_table(generic), "score_matrix": score_matrix_table(generic)}  # 全部表从同一事实包生成。
    formal_result = workflow.finish(study_id, formal_run["run_id"], summary, tables, [source_notice, f"{len(generic['failed_pairs'])}个NA格不参与色标，也不以零值替代。", "主要结论仅限五个当前研究重对接RMSD≤2 Å的受体。"], generic["outcome"], sources=[generic_record, authorization_record], figures=heatmap_records[1:], attachments=[heatmap_records[0]] + generic.get("evidence_files", []))  # 发布动态结果。
    workflow.review(study_id, formal_run["run_id"], "approved", "用户对话确认", "用户明确批准按PPI前10位及7个成分执行；严格质控5个主要受体，其他失败项保留NA。")  # 为自动化测试进入报告留下真实授权。
    return {"A06_PREP": prep_result["run_id"], "A06": formal_result["run_id"], "authorization": str(authorization_path)}  # 返回新版本定位。


if __name__ == "__main__":  # 提供明确参数入口。
    import argparse  # 解析项目、研究和来源文件。
    parser = argparse.ArgumentParser(description="发布PPI前十位动态A06结果")  # 说明用途。
    parser.add_argument("--root", required=True)  # 项目根目录。
    parser.add_argument("--study", required=True)  # 研究编号。
    parser.add_argument("--generic", required=True)  # 候选事实包。
    parser.add_argument("--heatmap-metadata", required=True)  # 动态热图元数据。
    arguments = parser.parse_args()  # 读取参数。
    print(json.dumps(publish(arguments.root, arguments.study, arguments.generic, arguments.heatmap_metadata), ensure_ascii=False))  # 输出运行编号。
