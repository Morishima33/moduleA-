# 三库A01版本化发布，保留原TCMSP计算内核与历史运行。
from pathlib import Path  # 明确项目和研究文件归属。
from copy import deepcopy  # 不修改原候选事实包。
from contracts import require  # 统一错误及门控规则。
from storage import read_json, verified_file, write_lock, file_record  # 统一溯源及写锁。
from components import run_components as legacy_run_components  # 旧研究继续走原算法。
VERSION = "A01.multisource.1"  # 独立契约，不改旧配置。
CONFIG = {"version": VERSION, "sources": ["TCMSP", "HERB", "BATMAN"], "tcmsp_ob_min": 30, "tcmsp_dl_min": 0.18, "new_sources_adme_filter": False, "new_relations": "database_existing_only", "dedup": "full_inchikey_no_formula_conflict"}  # 已由用户批准的规则。
def facts(home, inputs):  # 从固定事实包及复核决定生成结果。
    source = read_json(verified_file(home, inputs["candidate_file"]))  # 结果不能脱离已核查资料。
    for item in inputs["source_files"]:  # 全部原始来源及核查代码参与指纹验证。
        verified_file(home, item)  # 缺失或篡改立即阻断。
    require(inputs["decisions"] == {"omit_three_identity_exceptions": True, "retain_pending_structures": True}, "三库例外决定未确认")  # 不扩大本次授权。
    summary = deepcopy(source["result"]["summary"])  # 保留同一HGNC快照和计数。
    summary.update(candidate_only=False, handoff_blocked=False, component_source_profile=VERSION, **{"资料阶段": "已确认三库流程测试，结构待核仅标记", "身份例外处理": "3条暂不纳入，原始记录保留", "结构待核处理": "独立编号保留，进入对接前须核实"})  # 结构待核不冒充已完成身份核验。
    tables = deepcopy(source["result"]["tables"])  # 保留既有A03接口。
    tables.update(component_sources=source["source_records"], identity_exclusions=source["identity_issues"], pending_structures=source["structural_pending"])  # 来源和例外可在网页查看下载。
    anomalies = ["三库并集含416个结构待核分组，828不是已完全核实的独立成分数。", "新增DUSP27、Cyp2b10、Il33三条关系按用户决定暂不纳入。", "数据库已有关系与HGNC人类身份不等于人体直接结合实验证据；不自动增加新预测。", "柠檬酸等常见成分可因数据库关联数多而排名靠前，主候选须另行复核。"]  # 不隐藏解释限制。
    return summary, tables, anomalies  # 输出可复核事实。
def validator(root, fallback):  # 新旧契约分别严格校验。
    def check(run, summary, tables, anomalies, outcome):  # 发布前绑定明确版本。
        if run["config"].get("version") != VERSION:  # 原有科学规则不变。
            return fallback(run, summary, tables, anomalies, outcome)  # 历史计算仍可复算。
        require(run["config"] == CONFIG, "三库参数被修改")  # 禁止静默修改阈值。
        expected = facts(Path(root)/"studies"/run["study_id"], run["inputs"])  # 从已核查绑定文件重建。
        require((summary, tables, anomalies) == expected and outcome == "success", "三库发布结果与绑定事实不一致")  # 不能手工修改统计或漏掉例外。
    return check  # 加入原Workflow而非另建状态体系。
def publish(workflow, study_id, inputs, expected_a00, expected_a01, reason):  # 首次切换和再次复算共用版本门控。
    with write_lock(workflow.root):  # 原子发布当前指针。
        manifest = workflow.load(study_id)  # 不复用旧页面状态。
        require(manifest["current"]["A00"] == expected_a00 and manifest["current"].get("A01", "") == expected_a01, "研究版本已改变")  # 拒绝并发旧页。
        require(inputs["bound_a00"] == expected_a00, "三库来源不属于当前方剂身份")  # 科学身份变更必须重新准备来源。
        summary, tables, anomalies = facts(workflow.location(study_id), inputs)  # 先完整核对再创建运行。
        run = workflow._begin(manifest, "A01", inputs, dict(CONFIG), reason)  # 旧运行留在历史索引。
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success", sources=[inputs["candidate_file"]]+inputs["source_files"])  # 原始资料和结果均保留指纹。
        workflow.save(manifest)  # 上游变化使旧下游自动失效。
        return result  # 新结果仍有独立复核记录。
def run_components(workflow, study_id, expected_a00, expected_a01, reason):  # 网页重新运行不退回单库。
    manifest = workflow.load(study_id)  # 明确当前科学方案。
    previous = workflow.run(manifest, expected_a01) if expected_a01 else None  # 不猜最新目录。
    if previous and previous["config"].get("version") == VERSION:  # 已切换三库的研究继续沿用绑定来源。
        return publish(workflow, study_id, previous["inputs"], expected_a00, expected_a01, reason)  # 来源变化需新的资料绑定，不暗中抓取。
    return legacy_run_components(workflow, study_id, expected_a00, expected_a01, reason)  # 未切换的旧研究不变。
