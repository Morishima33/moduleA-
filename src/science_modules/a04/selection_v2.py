"""A04双分支第2版：保留两轮规则，Degree图表使用第一轮前十。"""

from science_modules.a04 import selection as previous

VERSION = "A04.dual.2"
DISPLAY_RULE = "A04.degree_round1_top10.1"


# 第一版名单、阈值、第二轮排名全部保留，新增第一轮明确命名的展示表。
def from_legacy(summary, tables):
    summary, tables = previous.from_legacy(summary, tables)
    first = previous.ranked(tables["degree_round1"], "degree", True)
    tables["degree_round1_top10"] = previous.boundary_top(first, 10, "degree")
    summary.update(
        selection_version=VERSION,
        degree_display_rule=DISPLAY_RULE,
        network_design_status="user_approved",
    )
    return summary, tables
