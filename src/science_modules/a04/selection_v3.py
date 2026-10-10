"""A04第3版：筛选及第一轮表不变，采用用户确认的第二轮圆形网络图。"""

from science_modules.a04 import selection_v2 as previous

VERSION = "A04.dual.3"
DISPLAY_RULE = previous.DISPLAY_RULE
NETWORK_RULE = "A04.degree_round2_circular.1"


# 图与表分别标明来源；只增规则版本，不修改旧版本结果。
def from_legacy(summary, tables):
    summary, tables = previous.from_legacy(summary, tables)
    summary.update(selection_version=VERSION, degree_network_rule=NETWORK_RULE)
    return summary, tables
