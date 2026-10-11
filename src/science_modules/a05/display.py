"""A05第二版展示：从完整显著表选取图表，人工排除不改变ORA或BH统计。"""

from copy import deepcopy
from pathlib import Path
import json
from contracts import require

VERSION = "A05.display.2"
RULE = {"version": VERSION, "go_graph": 8, "go_table": 15, "kegg_graph": 15, "kegg_tables": 10, "sort": ["p.adjust", "ID"], "count_sort": ["Count descending", "p.adjust", "ID"], "exclusion": "display_only_user_confirmed"}
GROUPS = ("BP", "CC", "MF")
LEXICON = Path(__file__).with_name("term_translations.json")


# 中英文按稳定编号和官方原名对应；新名称不静默沿用旧译名。
def english(row):
    return str(row["Description"]).removesuffix(" - Homo sapiens (human)")


def translate(row, translations):
    entry = translations.get(row["ID"], {})
    valid = entry.get("english") == english(row) and bool(entry.get("zh"))
    return dict(row, description_zh=entry["zh"] if valid else "", translation_status="checked" if valid else "pending", translation_source=entry.get("source", "") if valid else "")


# 本次使用的译名随研究归档；代码词典以后更新不会改动历史图表。
def translation_snapshot(tables):
    entries = json.loads(LEXICON.read_text(encoding="utf-8"))
    required = [r for g in GROUPS for r in tables[g.lower()+"_significant"][:15]] + tables["kegg_significant"]
    return {r["ID"]: deepcopy(entries.get(r["ID"], {})) for r in required}


# 两张KEGG表均从同一人工展示范围产生，数值不改、不补不足名额。
def build(base, translations, proposals, control):
    tables = deepcopy(base["tables"])
    summary = deepcopy(base["summary"])
    added = {}
    for group in GROUPS:
        rows = sorted(tables[group.lower()+"_significant"], key=lambda r: (float(r["p.adjust"]), r["ID"]))
        bilingual = [translate(r, translations) for r in rows[:15]]
        added[group.lower()+"_graph8"] = bilingual[:8]
        added[group.lower()+"_top15"] = bilingual
    kegg = [translate(r, translations) for r in sorted(tables["kegg_significant"], key=lambda r: (float(r["p.adjust"]), r["ID"]))]
    excluded = set(control.get("excluded_ids", []))
    require(excluded <= {r["ID"] for r in kegg}, "排除项必须属于本次显著KEGG结果")
    kept = [r for r in kegg if r["ID"] not in excluded]
    added["kegg_graph15"] = kept[:15]
    added["kegg_p_top10"] = kept[:10]
    added["kegg_count_top10"] = sorted(kept, key=lambda r: (-int(r["Count"]), float(r["p.adjust"]), r["ID"]))[:10]
    added["kegg_excluded"] = [r for r in kegg if r["ID"] in excluded]
    added["kegg_catalog"] = [dict(r, proposed=r["ID"] in proposals, reason_zh=proposals.get(r["ID"], {}).get("reason_zh", ""), evidence_url=proposals.get(r["ID"], {}).get("evidence_url", "https://www.kegg.jp/pathway/"+r["ID"])) for r in kegg]
    shown = [r for g in GROUPS for r in added[g.lower()+"_top15"]] + added["kegg_graph15"] + added["kegg_p_top10"] + added["kegg_count_top10"]
    missing = sorted({r["ID"] for r in shown if r["translation_status"] != "checked"})
    control = dict(control, version=VERSION, missing_translations=missing, retained_count=len(kept), excluded_count=len(excluded), significant_count=len(kegg))
    # 普通表保持平面单元格；列表明确序列化，接口读出后再还原。
    added["display_metadata"] = [{"version": VERSION, "base_run":control.get("base_run"), "excluded_ids_json":json.dumps(sorted(excluded)), "missing_translations_json":json.dumps(missing), "exclusions_confirmed":bool(control.get("exclusions_confirmed")), "layout_confirmed":bool(control.get("layout_confirmed")), "decision_id":control.get("decision_id"), "retained_count":len(kept), "excluded_count":len(excluded), "significant_count":len(kegg)}]
    tables.update(added)
    summary.update(display_version=VERSION, display_exclusions_confirmed=bool(control.get("exclusions_confirmed")), display_layout_confirmed=bool(control.get("layout_confirmed")), display_missing_translation_count=len(missing))
    summary["handoff_blocked"] = bool(base["summary"].get("handoff_blocked") or missing or not control.get("exclusions_confirmed") or not control.get("layout_confirmed"))
    return summary, tables


# 统一还原归档的平面控制行，不能由前端自行推断确认状态。
def metadata(tables):
    rows = tables.get("display_metadata") or []
    if not rows:
        return None
    require(len(rows) == 1, "A05展示控制记录不唯一")
    row = dict(rows[0])
    row["excluded_ids"] = json.loads(row.pop("excluded_ids_json"))
    row["missing_translations"] = json.loads(row.pop("missing_translations_json"))
    return row


# 用于网页和报告的简短名称，图表保留原英文和标准中文。
def label(row):
    return english(row) + ("（" + row["description_zh"] + "）" if row.get("description_zh") else "（中文待核译）")


def p_text(value):
    return format(float(value), ".3e")


# GO图和表同序；图展示Count，表保留紧凑的校正后P值。
def go_rows(tables, group):
    return [{"条目名称（英文＋中文）": label(r), "校正后P值（BH）": p_text(r["p.adjust"])} for r in tables[group.lower()+"_top15"]]


def kegg_rows(tables, name):
    return [{"通路名称（英文＋中文）": label(r), "Count": int(r["Count"]), "校正后P值（BH）": p_text(r["p.adjust"])} for r in tables[name]]
