"""已确认的第二轮圆形PPI图：完整保留候选和真实边，仅调整位置。"""

from pathlib import Path
from html import escape
import math
from PIL import Image, ImageDraw
from contracts import require
from report_figures import _font, COLORS, _save_svg
from science_modules.a04.figure_labels import label_positions

NETWORK_DESIGN_APPROVED = True


# 图注明确第二轮、红色范围及布局含义，不把位置解释为生物学结果。
def degree_caption(tables):
    return (
        f"Degree第二轮{len(tables['degree_round2'])}节点候选网络。"
        "第二轮前十及边界并列标红并标注，其余为蓝色。"
        "保留全部候选与候选间真实连边；节点大小表示完整网络Degree，圆形位置仅用于展示。"
    )


# 同心圆按人数扩展；当前已批准版式保持原半径，更多节点扩展画布而不丢弃。
def circular_layout(rows, top):
    red = {r["target_id"] for r in top}
    nodes = {r["target_id"] for r in rows}
    require(len(nodes) == len(rows) and red <= nodes, "圆形图节点重复或红色名单不属于第二轮")
    maximum = max((r["degree"] for r in rows), default=1) or 1
    sizes = {r["target_id"]: 8 + 17 * r["degree"] / maximum for r in rows}
    blue = sorted(
        [r for r in rows if r["target_id"] not in red], key=lambda r: (-r["degree"], r["target_id"])
    )
    red_radius = max(250, len(top) * 90 / (2 * math.pi))
    groups = [(top, red_radius, -math.pi / 2)] if top else []
    start = 0
    for count, radius, offset in [
        (11, 110, 0.2),
        (22, red_radius + 150, 0.08),
        (34, red_radius + 290, 0.03),
        (44, red_radius + 430, 0.04),
    ]:
        group = blue[start : start + count]
        if group:
            groups.append((group, radius, -math.pi / 2 + offset))
        start += len(group)
    radius = red_radius + 570
    while start < len(blue):
        capacity = max(1, int(2 * math.pi * radius / 100))
        group = blue[start : start + capacity]
        groups.append((group, radius, -math.pi / 2 + 0.04))
        start += len(group)
        radius += 140
    # 同Degree时节点可能都较大；增加该圆的半径以保证间距，已认可病例的半径不变。
    groups = [
        (
            group,
            max(
                radius,
                (2 * max(sizes[r["target_id"]] for r in group) + 20)
                / (2 * math.sin(math.pi / len(group))),
            )
            if len(group) > 1
            else radius,
            offset,
        )
        for group, radius, offset in groups
    ]
    outer = max((g[1] for g in groups), default=0)
    width = max(1800, math.ceil(2 * (outer + 220)))
    height = width - 170
    cx = width / 2
    cy = width / 2 - 65
    positions = {}
    for group, radius, offset in groups:
        for i, row in enumerate(group):
            angle = offset + 2 * math.pi * i / len(group)
            positions[row["target_id"]] = (
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
            )
    require(set(positions) == nodes, "圆形图遗漏候选节点")
    return positions, sizes, width, height, cx, cy


# 绘图子集不重新计算Degree、BC、CC；没有子图连边的候选也保留。
def draw_degree(tables, base):
    rows = tables["degree_round2"]
    top = tables["degree_top10"]
    nodes = [r["target_id"] for r in rows]
    selected = set(nodes)
    red = {r["target_id"] for r in top}
    edges = [
        (r["source"], r["target"])
        for r in tables["edges"]
        if r["source"] in selected and r["target"] in selected
    ]
    positions, sizes, width, height, cx, cy = circular_layout(rows, top)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    svg = []
    title = f"PPI Degree第二轮候选网络 {len(rows)}个节点"
    draw.text((cx, 35), title, font=_font(36, True), fill=COLORS["dark"], anchor="ma")
    svg.append(
        f'<text x="{cx}" y="65" text-anchor="middle" font-family="Microsoft YaHei" font-size="36" font-weight="700" fill="{COLORS["dark"]}">{escape(title)}</text>'
    )
    edge_color = "#DDE5EA"
    for a, b in edges:
        x1, y1 = positions[a]
        x2, y2 = positions[b]
        draw.line((x1, y1, x2, y2), fill=edge_color, width=1)
        svg.append(
            f'<line data-source="{escape(a)}" data-target="{escape(b)}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{edge_color}" stroke-width="1"/>'
        )
    for node in sorted(nodes, key=lambda n: n in red):
        x, y = positions[node]
        r = sizes[node]
        color = COLORS["red"] if node in red else COLORS["blue"]
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=COLORS["dark"], width=2)
        svg.append(
            f'<circle data-target-id="{escape(node)}" cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{color}" stroke="{COLORS["dark"]}" stroke-width="1.5"/>'
        )
    labels = {r["target_id"]: r["symbol"] for r in top}
    font = _font(24, True)
    label_layout = label_positions(nodes, positions, sizes, labels, font, width, height)
    label_boxes = []
    for node, text in labels.items():
        x, y = positions[node]
        r = sizes[node]
        lx, ly = label_layout[node]
        if abs(lx - x) > 10 or ly - y - r > 15:
            draw.line((x, y + r, lx, ly), fill="#526B7A", width=1)
            svg.append(
                f'<path d="M{x:.2f},{y + r:.2f} L{lx:.2f},{ly:.2f}" fill="none" stroke="#526B7A" stroke-width="1"/>'
            )
        draw.text(
            (lx, ly),
            text,
            font=font,
            fill=COLORS["dark"],
            stroke_width=3,
            stroke_fill="white",
            anchor="ma",
        )
        svg.append(
            f'<text x="{lx:.2f}" y="{ly + 24:.2f}" text-anchor="middle" font-family="Arial,Microsoft YaHei" font-size="24" font-weight="700" fill="{COLORS["dark"]}" stroke="white" stroke-width="3" paint-order="stroke">{escape(text)}</text>'
        )
        w = font.getlength(text) + 12
        label_boxes.append((lx - w / 2, ly, lx + w / 2, ly + 30))
    note = "节点位置仅用于展示；节点大小表示完整网络Degree。"
    draw.text((cx, height - 55), note, font=_font(20), fill="#526B7A", anchor="ma")
    svg.append(
        f'<text x="{cx}" y="{height - 35}" text-anchor="middle" font-family="Microsoft YaHei" font-size="20" fill="#526B7A">{escape(note)}</text>'
    )
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    paths = {k: base.with_suffix("." + k) for k in ("png", "svg")}
    image.save(paths["png"], dpi=(220, 220))
    _save_svg(paths["svg"], width, height, "".join(svg))
    return paths
