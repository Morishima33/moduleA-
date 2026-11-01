"""补查原候选字段的标准库契约；兼容归档管道文本和列表，不解释或采用基因身份。"""
import re
from contracts import require


def candidate_hgnc_ids(issue):
    """保留原字段，仅提取显式HGNC编号；文本不能按单个字符遍历而漏查。"""
    value = issue.get('candidate_ids', '')
    if isinstance(value, str): value = value.split('|') if value else []
    require(isinstance(value, list) and all(isinstance(cid, str) for cid in value), '原候选编号字段格式无法核对')
    return {cid for cid in value if re.fullmatch(r'HGNC:[0-9]+', cid)}
