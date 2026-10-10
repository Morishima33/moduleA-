"""按用户参考报告生成Degree候选网络；用户已确认蓝红版式。"""

from pathlib import Path

NETWORK_DESIGN_APPROVED = True


# 图注与报告使用同一说明；按显式版本区分第一轮及旧第二轮前十。
def degree_caption(tables):
    return (
        f"图2 Degree第一轮{len(tables['degree_round1'])}节点候选网络。"
        f"全部第一轮节点保留；{'第一轮' if 'degree_round1_top10' in tables else '第二轮'}Degree前十及边界并列以红色突出并标注，其余为蓝色。"
        "节点指标来自完整网络，节点大小表示完整网络Degree。"
    )


# 复用冻结报告的蓝红色、细边、节点描边及下方标签，全部第一轮候选参与绘图。
def draw_degree(tables, destination, demo=False):
    if "degree_round1_top10" in tables:
        from science_modules.a04.figure_labels import draw_degree as draw

        return draw(tables, destination, demo)
    from report_figures import _network_pair

    first = tables["degree_round1"]
    nodes = [row["target_id"] for row in first]
    node_set = set(nodes)
    top = {
        row["target_id"]
        for row in tables.get("degree_round1_top10", tables.get("degree_top10", []))
    }
    edges = [
        (row["source"], row["target"])
        for row in tables["edges"]
        if row["source"] in node_set and row["target"] in node_set
    ]
    labels = {row["target_id"]: row["symbol"] for row in first if row["target_id"] in top}
    groups = {node: "core" if node in top else "other" for node in nodes}
    # 按完整网络Degree缩放半径，避免高Degree节点全部达到尺寸上限。
    maximum = max((row["degree"] for row in first), default=1)
    sizes = {row["target_id"]: 7 + 22 * row["degree"] / maximum for row in first}
    title = f"PPI Degree第一轮候选网络 {len(nodes)}个节点"
    if demo:
        title += " 演示数据"
    if not nodes:
        title += " 无符合条件的候选"
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = {kind: destination.with_suffix("." + kind) for kind in ("svg", "png")}
    # 冻结绘图器的标题区与顶部节点较近；新增独立标题区，保留原节点布局和描边。
    _network_pair(result["svg"], result["png"], "", nodes, edges, labels, groups, sizes, seed=24)
    from html import escape
    from PIL import Image, ImageDraw
    from report_figures import _font, COLORS

    note = "节点位置仅用于展示；节点大小表示完整网络Degree。"
    with Image.open(result["png"]) as original:
        width, height = original.size
        picture = original.copy()
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, height - 70, width, height), fill="white")
    draw.text((width / 2, height - 42), note, font=_font(18), fill="#526B7A", anchor="ma")
    page = Image.new("RGB", (width, height + 60), "white")
    page.paste(picture, (0, 60))
    ImageDraw.Draw(page).text(
        (width / 2, 28), title, font=_font(34, True), fill=COLORS["dark"], anchor="ma"
    )
    page.save(result["png"], dpi=(220, 220))
    raw = result["svg"].read_text(encoding="utf-8")
    body = raw[raw.index(">") + 1 : raw.rfind("</svg>")]
    body = body.replace("节点位置仅用于展示；节点大小表示Degree或连边数。", escape(note))
    result["svg"].write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height + 60}" viewBox="0 0 {width} {height + 60}">'
        '<rect width="100%" height="100%" fill="white"/>'
        f'<g transform="translate(0,60)">{body}</g>'
        f'<text x="{width / 2}" y="48" text-anchor="middle" font-family="Microsoft YaHei" font-size="34" font-weight="700" fill="{COLORS["dark"]}">{escape(title)}</text></svg>',
        encoding="utf-8",
    )
    return result
