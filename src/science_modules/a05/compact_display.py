"""A05第三版展示：中英文分列及单蓝渐变；原统计、排名和第二版实现保留。"""
from types import FunctionType
from . import display as previous

VERSION = "A05.display.3"
RULE = dict(previous.RULE, version=VERSION, table_names="english_chinese_separate", kegg_palette="ColorBrewer Blues", palette=["#C6DBEF", "#6BAED6", "#3182BD", "#08519C"])
GROUPS = previous.GROUPS
english, metadata = previous.english, previous.metadata
translation_snapshot = previous.translation_snapshot
p_text = previous.p_text

# 仅替换展示版本标识，选取范围、P值、Count和缺译门控沿用已验证第二版。
build = FunctionType(previous.build.__code__, dict(vars(previous), VERSION=VERSION, RULE=RULE), "build")

# 英文列附标准编号；报告将编号独立缩小，不把标识混进中文译名。
def go_rows(tables, group):
    return [{"条目名称（英文）": english(r)+" "+r["ID"], "中文名称": r.get("description_zh") or "中文待核译", "校正后P值（BH）": p_text(r["p.adjust"])} for r in tables[group.lower()+"_top15"]]

# KEGG两张表使用同一套四列；命中规模与统计显著性保持原数值。
def kegg_rows(tables, name):
    return [{"通路名称（英文）": english(r)+" "+r["ID"], "中文名称": r.get("description_zh") or "中文待核译", "Count": int(r["Count"]), "校正后P值（BH）": p_text(r["p.adjust"])} for r in tables[name]]
