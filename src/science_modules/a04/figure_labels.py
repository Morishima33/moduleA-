"""已确认蓝红版式的密集网络排版；标签最后绘制，避让节点和其他标签。"""

from pathlib import Path
from html import escape
import math


# 下方标签优先；必要时小幅移动并使用引导线，位置不代表指标。
def label_positions(nodes, positions, sizes, labels, font, width, height):
    boxes, result = [], {}
    for node, text in labels.items():
        x, y = positions[node]
        radius = sizes[node]
        w = font.getlength(text) + 12
        candidates = []
        for dy in (4, 28, 52, 76, 100, 124, 148):
            for dx in (0, -45, 45, -90, 90, -135, 135):
                cx, cy = x + dx, y + radius + dy
                box = (cx - w / 2, cy, cx + w / 2, cy + 30)
                if box[0] < 30 or box[2] > width - 30 or box[3] > height - 80:
                    continue
                hits = sum(
                    not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3])
                    for b in boxes
                )
                node_hits = 0
                for other in nodes:
                    ox, oy = positions[other]
                    nearx = max(box[0], min(ox, box[2]))
                    neary = max(box[1], min(oy, box[3]))
                    if math.hypot(ox - nearx, oy - neary) < sizes[other] + 3:
                        node_hits += 1
                candidates.append(
                    (hits * 100000 + node_hits * 10000 + abs(dx) + dy * 1.4, cx, cy, box)
                )
        if not candidates:
            cx = min(width - w / 2 - 30, max(w / 2 + 30, x))
            cy = min(height - 115, y + radius + 4)
            candidates = [(0, cx, cy, (cx - w / 2, cy, cx + w / 2, cy + 30))]
        _, cx, cy, box = min(candidates)
        boxes.append(box)
        result[node] = (cx, cy)
    return result


# 所有边与蓝色节点先画，红色节点后画，最后标注；SVG与PNG共用坐标。
def draw_degree(tables, destination, demo=False):
    from PIL import Image, ImageDraw
    from report_figures import _network_positions, _font, COLORS, _save_svg
    from science_modules.a04.figures import degree_caption

    first = tables["degree_round1"]
    top = tables["degree_round1_top10"]
    red = {r["target_id"] for r in top}
    nodes = [r["target_id"] for r in first]
    node_set = set(nodes)
    edges = [
        (r["source"], r["target"])
        for r in tables["edges"]
        if r["source"] in node_set and r["target"] in node_set
    ]
    width, height = 1800, 1310
    positions = _network_positions(nodes, edges, 24, width, height - 60)
    positions = {k: (x, y + 60) for k, (x, y) in positions.items()}
    maximum = max((r["degree"] for r in first), default=1)
    sizes = {r["target_id"]: 7 + 22 * r["degree"] / maximum for r in first}
    labels = {r["target_id"]: r["symbol"] for r in top}
    title = f"PPI Degree第一轮候选网络 {len(nodes)}个节点"
    if demo:
        title += " 演示数据"
    if not nodes:
        title += " 无符合条件的候选"
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    svg = [
        f'<text x="900" y="48" text-anchor="middle" font-family="Microsoft YaHei" font-size="34" font-weight="700" fill="{COLORS["dark"]}">{escape(title)}</text>'
    ]
    draw.text((900, 28), title, font=_font(34, True), fill=COLORS["dark"], anchor="ma")
    for a, b in edges:
        x1, y1 = positions[a]
        x2, y2 = positions[b]
        draw.line((x1, y1, x2, y2), fill=COLORS["gray"], width=2)
        svg.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{COLORS["gray"]}" stroke-width="1"/>'
        )
    for node in sorted(nodes, key=lambda n: n in red):
        x, y = positions[node]
        r = sizes[node]
        color = COLORS["red"] if node in red else COLORS["blue"]
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=COLORS["dark"], width=2)
        svg.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}" stroke="{COLORS["dark"]}" stroke-width="1.5"/>'
        )
    font = _font(20, True)
    layout = label_positions(nodes, positions, sizes, labels, font, width, height)
    for node, text in labels.items():
        x, y = positions[node]
        r = sizes[node]
        lx, ly = layout[node]
        if abs(lx - x) > 10 or ly - y - r > 15:
            draw.line((x, y + r, lx, ly), fill="#526B7A", width=1)
            svg.append(
                f'<path d="M{x:.1f},{y + r:.1f} L{lx:.1f},{ly:.1f}" fill="none" stroke="#526B7A" stroke-width="1"/>'
            )
        draw.text(
            (lx, ly),
            text,
            font=font,
            fill=COLORS["dark"],
            stroke_width=4,
            stroke_fill="white",
            anchor="ma",
        )
        svg.append(
            f'<text x="{lx:.1f}" y="{ly + 20:.1f}" text-anchor="middle" font-family="Arial,Microsoft YaHei" font-size="20" font-weight="700" fill="{COLORS["dark"]}" stroke="white" stroke-width="4" paint-order="stroke">{escape(text)}</text>'
        )
    note = "节点位置仅用于展示；节点大小表示完整网络Degree。"
    draw.text((900, height - 42), note, font=_font(18), fill="#526B7A", anchor="ma")
    svg.append(
        f'<text x="900" y="{height - 25}" text-anchor="middle" font-family="Microsoft YaHei" font-size="18" fill="#526B7A">{note}</text>'
    )
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = {k: destination.with_suffix("." + k) for k in ("svg", "png")}
    _save_svg(result["svg"], width, height, "".join(svg))
    image.save(result["png"], dpi=(220, 220))
    return result
