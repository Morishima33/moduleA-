"""第二版自动对接补救策略；第一版定义和已归档确认保持可回放。"""
from copy import deepcopy
from contracts import fingerprint
from .automatic_rules import POLICY as ORIGINAL_POLICY, binding as original_binding

VERSION = "A06.automatic.2"
POLICY = dict(deepcopy(ORIGINAL_POLICY), version=VERSION, search_limit=None, page_size=100,
    network_attempts=3, receptor_identity="human_unique_UniProt_actual_mapped_sequence_no_mutation",
    alternative_conformer="complete_global_highest_occupancy_lexical_tie_exploratory",
    site="strict_reference_else_all_mapped_predicted_sites_else_30_15_5_partitions_exploratory",
    rescue="paginate_until_usable_then_independent_structures_limited_sidechain_repair_published_AlphaFold",
    alphafold_confidence={"mean_plddt":80,"min_plddt":70,"max_pae_A":10},
    repair="observed_residue_sidechains_only_original_heavy_coordinates_unchanged")
SUMMARY = "连接先复用同源合格原件并补查异常；一次授权后自动接续替代结构、有限修补与探索路线，不保证每组都有有效评分。"
DETAILS = ["网络暂时失败最多重试三次；实验结构按官方分页检索，不在前20项停止。",
    "以同一人类UniProt及实际坐标残基映射核验身份；明确匹配的实验功能域可单列探索，突变或未知身份不放行。",
    "替代构象须覆盖全部替代原子；按占有率选择，并列按字母固定选择并记录，仅作探索。",
    "准备失败继续独立替代结构；只允许补已解析残基的侧链，禁止重建主链、长环或改变原重原子坐标。",
    "实验来源补救后仍不适用，读取已发布AlphaFold模型；每个采用区域核验80／70／10置信度，仅作探索。",
    "预测区域在评分前固定；无可映射预测口袋时使用原30Å盒、15Å步长、外围5Å分区；工具失败不冒充无口袋。",
    "同一受体所有成分使用同一结构及区域集合；保留每个区域Top-1，取有效区域最低值并注明失败区域。",
    "必要伙伴、金属或未解决缺失不强行忽略；严格、探索、NA分开，不自动批准，不承诺全覆盖成功。"]


def binding(workflow, manifest):
    """仅换策略指纹，沿用同研究的已批准输入版本保护。"""
    value = original_binding(workflow, manifest)
    return dict(value, policy=fingerprint(POLICY))
