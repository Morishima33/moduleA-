"""第22版报告事实：只读已批准排序，显示筛选不改变对接来源或统计。"""

from contracts import require
from science_modules.a05.display import english


def degree_top(rows, count=10):
    """按原始Degree保留边界并列，使用稳定HGNC编号打破显示顺序并列。"""
    ordered = sorted(rows, key=lambda r: (-r["degree"], r["target_id"]))
    if len(ordered) > count:
        ordered = [r for r in ordered if r["degree"] >= ordered[count - 1]["degree"]]
    return ordered


def ppi_intersection(tables):
    """交集使用两分支第二轮完整名单，不能用展示前十/十五求交。"""
    members = {r["target_id"] for r in tables["bc_cc_round2"]}
    rows = [r for r in tables["degree_round2"] if r["target_id"] in members]
    return rows, degree_top(rows)


def bilingual(row):
    """富集名称来自已确认同源译名，缺译不得偷偷补定。"""
    require(bool(row.get("description_zh")), "报告条目中文名称尚待核译")
    return row["description_zh"] + "（" + english(row) + "）"


def enrichment_sections(tables):
    """摘要按已确认的两种KEGG排名及三类GO顺序逐项列名。"""
    sections = []
    for key, label, size in (
        ("bp_top15", "GO BP 生物过程前三", 3),
        ("cc_top15", "GO CC 细胞组分前三", 3),
        ("mf_top15", "GO MF 分子功能前三", 3),
        ("kegg_p_top10", "KEGG统计显著性前五", 5),
        ("kegg_count_top10", "KEGG命中基因数前五", 5),
    ):
        sections.append(
            {"层次": label, "结论": "；".join(bilingual(r) for r in tables[key][:size]) + "。"}
        )
    return sections


def strong_pairs(packet, names):
    """用未经四舍五入的原评分判断≤−8，保留全部实际组合。"""
    cmap = {c["compound_id"]: c for c in packet["compounds"]}
    tmap = {r["target_id"]: r for r in packet["receptors"]}
    rows = []
    for pair in packet["pairs"]:
        if pair["state"] != "completed" or pair["score"] > -8:
            continue
        compound = names.get(pair["compound_id"], {})
        zh = compound.get("name_zh") or cmap[pair["compound_id"]]["name_zh"]
        en = compound.get("name_en") or cmap[pair["compound_id"]].get("name", "")
        require(bool(zh and en), "对接成分中英文名称尚待核译")
        label = zh + "（" + en + "）" if zh != en else en
        rows.append(
            {
                "compound_id": pair["compound_id"],
                "target_id": pair["target_id"],
                "成分": label,
                "受体": tmap[pair["target_id"]]["symbol"],
                "结合能（kcal/mol）": pair["score"],
            }
        )
    return sorted(rows, key=lambda r: (r["受体"], r["结合能（kcal/mol）"], r["compound_id"]))


def pair_summary(rows):
    """按受体归组写完整≤−8清单，解释标记含义而非疗效阈值。"""
    targets = list(dict.fromkeys(r["受体"] for r in rows))
    lines = [
        target
        + "："
        + "、".join(
            r["成分"] + f" {r['结合能（kcal/mol）']:.2f}" for r in rows if r["受体"] == target
        )
        for target in targets
    ]
    return (
        f"原始Vina评分≤−8 kcal/mol的组合共{len(rows)}组。"
        + "；".join(lines)
        + "。该界值是本报告的展示标记，不表示统计显著性或实测药效。"
    )
