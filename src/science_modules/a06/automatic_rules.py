"""一次授权自动对接的独立科学策略；旧两遍、严格和225组合协议保持冻结。"""
from contracts import fingerprint, require
from .two_pass import VINA, VINA_VERSION

VERSION = "A06.automatic.1"
PARENTS = ("A00", "A01", "A02", "A03", "A03_SELECT", "A04")
POLICY = {"version": VERSION, "vina_version": VINA_VERSION, "vina": VINA,
          "source_3d": "official_single_cid_single_3d_no_pH_prediction",
          "receptor_identity": "unique_HGNC_UniProt_human_protein_zero_reported_sequence_changes",
          "search_limit": 20, "structures_per_target": 2,
          "structure_order": "resolution_ascending_official_search_order_then_author_chain",
          "alternative_conformer": "unique_consistent_highest_occupancy_A_or_B_else_exception",
          "site": "connected_reference_redocking_else_twice_identical_P2Rank_top1_exploratory",
          "reference_rmsd_max_A": 2.0, "environment": "unresolved_environment_or_missing_pocket_skip",
          "failure": "retain_all_pairs_and_evidence_continue_other_objects",
          "automatic_scientific_approval": False}
SUMMARY = "一次授权后自动准备、质控、对接和出图；失败项留因，其余继续。结果不自动批准。"
DETAILS = ["仅使用本研究已批准的成分和A/B受体，来源身份冲突不猜测。",
           "来源三维不自动改立体构型、质子化或互变异构体；每个实际输入文件留存。",
           "已有明确共晶位点优先按原规则重对接；否则两次一致的P2Rank首位口袋仅作探索。",
           "搜索盒环境未解决、口袋不完整或工具失败时不强行填分；严格不足五个不补主要名额。",
           "固定Vina 1.2.7及原参数，所有搜索盒、姿势、命令和软件指纹可回溯。"]


# 当前批准输入全部纳入指纹，重签或换源都会使旧连接与授权失效。
def binding(workflow, manifest):
    require(not manifest.get("trashed"), "回收站中的研究只读")
    runs, reviews, results = {}, {}, {}
    for module in PARENTS:
        rid = manifest["current"].get(module)
        require(rid and workflow.approved(manifest, rid), "请先完成当前" + module + "复核后连接对接资料")
        run = workflow.run(manifest, rid)
        runs[module] = rid
        reviews[module] = workflow.latest_review(manifest, run["artifact_id"])["review_id"]
        results[module] = manifest["runs"][rid]["result_file"]
    return {"study_id": manifest["study_id"], "runs": runs, "reviews": reviews, "results": results, "policy": fingerprint(POLICY)}


# 只有证据满足当前规则才计算；预测位点由本次策略授权，不冒充人工核验。
def assess(spec, evidence, authorization_id, target):
    from .two_pass import assess_attempt
    if spec.get("pocket") == "reference":
        return assess_attempt(spec, evidence, target, 1)
    require(authorization_id, "自动预测位点缺少本次执行授权")
    identity = evidence.get("identity", {})
    require(identity.get("target_id") == target["target_id"] and identity.get("uniprot") == spec["uniprot"] and identity.get("chains") == spec["chains"] and identity.get("species") == 9606 and identity.get("polymer_type") == "Protein" and identity.get("sequence_matches") is True and evidence.get("structure_id") == spec["pdb_id"], "受体身份未核对一致")
    require(evidence.get("receptor_ready") and evidence.get("pocket_complete") and evidence.get("environment_resolved"), "受体准备、口袋完整性或必要环境未通过")
    pocket = evidence.get("pocket", {})
    runs = pocket.get("runs", [])
    require(pocket.get("rank") == 1 and len(runs) == 2 and runs[0] == runs[1] and bool(runs[0]), "预测首位口袋两次不一致")
    from .two_pass import pocket_key
    require(pocket.get("pocket_key") == pocket_key(spec, pocket), "预测口袋证据键不一致")
    return {"state": "ready", "quality": "探索", "reason_zh": "按本次自动策略采用两次一致首位预测口袋；不代表已验证真实结合位点", "authorization_id": authorization_id, "pocket_key": pocket["pocket_key"]}
