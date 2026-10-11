"""A05同源科研图：三栏GO柱图和KEGG气泡图，PNG与SVG使用同一坐标与指标。"""

from html import escape
from pathlib import Path
import math
from PIL import Image, ImageDraw
from report_figures import _font, _blend_hex
from .display import GROUPS, english, metadata

PALETTES = {"BP": ("#C6DBEF", "#2171B5"), "CC": ("#C7E9C0", "#238B45"), "MF": ("#DADAEB", "#6A51A3")}
KEGG_PALETTE = ("#A6BDDB", "#67A9CF", "#02818A", "#016C59")  # ColorBrewer PuBuGn顺序色。
DARK = "#223746"


# 双格式绘图共用实际文字宽度换行，不省略英文或中文名称。
class Canvas:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.image = Image.new("RGB", (width, height), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.svg = []

    def text(self, x, y, text, size=22, color=DARK, bold=False, anchor="la"):
        self.draw.text((x, y), str(text), font=_font(size, bold), fill=color, anchor=anchor)
        align = {"m": "middle", "r": "end"}.get(anchor[0], "start")
        # SVG基线与Pillow上沿统一，实际绘制内容与PNG一致。
        self.svg.append(f'<text x="{x:.2f}" y="{y+size:.2f}" text-anchor="{align}" font-family="Microsoft YaHei, Arial, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(str(text))}</text>')

    def rect(self, x, y, w, h, fill, radius=0):
        self.draw.rounded_rectangle((x,y,x+w,y+h), radius=radius, fill=fill)
        self.svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{radius}" fill="{fill}"/>')

    def line(self, x1, y1, x2, y2, fill="#E4ECEF"):
        self.draw.line((x1,y1,x2,y2), fill=fill, width=2)
        self.svg.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{fill}" stroke-width="2"/>')

    def circle(self, x, y, radius, fill, tooltip=""):
        self.draw.ellipse((x-radius,y-radius,x+radius,y+radius), fill=fill, outline="#335969", width=2)
        self.svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{fill}" stroke="#335969" stroke-width="2"><title>{escape(tooltip)}</title></circle>')

    def save(self, stem):
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        png, svg = stem.with_suffix(".png"), stem.with_suffix(".svg")
        self.image.save(png, dpi=(300,300))
        svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}"><rect width="100%" height="100%" fill="white"/>'+ "".join(self.svg)+"</svg>", encoding="utf-8")
        return {"png": png, "svg": svg}


# 按字号的实际宽度包裹标签，中文按字、英文优先按词切行。
def wrap(text, width, size=22):
    font = _font(size)
    lines, line = [], ""
    units = str(text).split(" ") if " " in str(text) else list(str(text))
    separator = " " if " " in str(text) else ""
    for unit in units:
        trial = line+separator+unit if line else unit
        if font.getlength(trial) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = ""
        for char in unit:
            if font.getlength(line+char) > width and line:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines or [""]


def names(row, width, size=22):
    return wrap(english(row), width, size) + wrap(row.get("description_zh") or "中文待核译", width, size)


# GO各类按同源排序各前八，柱长和深浅表示Count；面板尺度各自归一。
def draw_go(tables, stem):
    rows = {g: tables[g.lower()+"_graph8"] for g in GROUPS}
    labels = {g: [names(r, 650, 34) for r in rows[g]] for g in GROUPS}
    pitch = max(225, max((len(lines)*44+85 for lines_by_group in labels.values() for lines in lines_by_group), default=225))
    height = 185 + 8*pitch + 90
    canvas = Canvas(2200, height)
    canvas.text(1100, 25, "GO富集结果", 38, bold=True, anchor="ma")
    for panel, group in enumerate(GROUPS):
        x0 = 30+panel*730
        canvas.text(x0+340, 90, group, 29, PALETTES[group][1], True, "ma")
        values = [int(r["Count"]) for r in rows[group]]
        maximum, minimum = max(values, default=1), min(values, default=0)
        if not rows[group]:
            canvas.text(x0+20, 180, "无符合阈值的显著条目", 23)
        for index, row in enumerate(rows[group]):
            y = 165+index*pitch
            for j, line in enumerate(labels[group][index]):
                canvas.text(x0+12, y+j*44, line, 34)
            bar_y = y+len(labels[group][index])*44+12
            count = int(row["Count"])
            fill = _blend_hex(*PALETTES[group], (count-minimum)/max(maximum-minimum,1))
            length = 545*count/max(maximum,1)
            canvas.rect(x0+12, bar_y, length, 32, fill, 6)
            canvas.text(x0+length+24, bar_y+2, count, 22, bold=True)
    canvas.text(1100, height-66, "各类按校正后P值升序取前八；柱长及同组颜色深浅表示Count，三个面板独立缩放。", 22, "#526B7A", anchor="ma")
    canvas.text(1100, height-35, "BP、CC、MF分别进行BH校正；仅展示p.adjust < 0.05的条目。", 22, "#526B7A", anchor="ma")
    return canvas.save(stem)


def color_scale(t):
    position = max(0,min(1,t))*(len(KEGG_PALETTE)-1)
    index = min(int(position),len(KEGG_PALETTE)-2)
    return _blend_hex(KEGG_PALETTE[index], KEGG_PALETTE[index+1], position-index)


# 气泡面积正比于Count，颜色使用实际-log10(BH P)范围，并明确图例。
def draw_kegg(tables, stem):
    rows = tables["kegg_graph15"]
    labels = [names(r, 900, 34) for r in rows]
    pitches = [max(128,len(x)*44+24) for x in labels]
    height = 190+sum(pitches)+210
    canvas = Canvas(2250,max(height,650))
    canvas.text(1125, 23, "KEGG富集结果", 38, bold=True, anchor="ma")
    left, right = 980, 2010
    top, bottom = 120, 120+sum(pitches)
    if not rows:
        canvas.text(1125, 250, "当前展示范围无显著通路，不降低阈值补项。", 28, anchor="ma")
        return canvas.save(stem)
    rich = [float(r["RichFactor"]) for r in rows]
    maximum = max(max(rich), 1e-12)*1.06
    strengths = [-math.log10(max(float(r["p.adjust"]),1e-300)) for r in rows]
    low, high = min(strengths), max(strengths)
    counts = [int(r["Count"]) for r in rows]
    for index in range(6):
        x = left+(right-left)*index/5
        canvas.line(x,top,x,bottom)
        canvas.text(x,bottom+15,f"{maximum*index/5:.3f}",22,"#526B7A",anchor="ma")
    canvas.text((left+right)/2,bottom+55,"RichFactor（命中数／该通路背景基因数）",24,anchor="ma")
    y = top
    for i,row in enumerate(rows):
        cy = y+pitches[i]/2
        text_y = cy-len(labels[i])*44/2
        for j,line in enumerate(labels[i]):
            canvas.text(left-30,text_y+j*44,line,34,anchor="ra")
        radius = 29*math.sqrt(int(row["Count"])/max(counts))
        fill = color_scale((strengths[i]-low)/(high-low) if high>low else .65)
        canvas.circle(left+(right-left)*rich[i]/maximum,cy,radius,fill,f'{row["ID"]}; Count={row["Count"]}; RichFactor={row["RichFactor"]}; BH P={row["p.adjust"]}')
        y += pitches[i]
    # 同一颜色映射用于图例，不能把Count与颜色含义混为一谈。
    legend_x,legend_y = 2080,top+55
    for i in range(160):
        canvas.rect(legend_x,legend_y+i*2,30,2,color_scale(1-i/159))
    canvas.text(legend_x-7,legend_y-42,"−log10",21)
    canvas.text(legend_x-7,legend_y-15,"(BH P)",19)
    canvas.text(legend_x+41,legend_y-3,f"{high:.2f}",19)
    canvas.text(legend_x+41,legend_y+306,f"{low:.2f}",19)
    canvas.text(legend_x-8,legend_y+375,"Count",22,bold=True)
    choices = sorted(set((min(counts),sorted(counts)[len(counts)//2],max(counts))))
    for j,count in enumerate(choices):
        cy = legend_y+430+j*80
        canvas.circle(legend_x+15,cy,29*math.sqrt(count/max(counts)),"#67A9CF")
        canvas.text(legend_x+55,cy-15,count,21)
    canvas.text(1125,height-88,"按校正后P值升序取前十五；气泡面积表示Count，颜色越深表示统计显著性越强。",22,"#526B7A",anchor="ma")
    canvas.text(1125,height-53,"疾病名称型通路不直接代表疗效；人工排除仅影响展示，完整统计及BH校正值保留。",22,"#526B7A",anchor="ma")
    if not metadata(tables).get("exclusions_confirmed"):
        canvas.text(1125,height-22,"预览：KEGG排除清单尚待人工确认。",20,"#90621A",anchor="ma")
    return canvas.save(stem)


def draw_all(tables, directory):
    directory = Path(directory)
    return {"go":draw_go(tables,directory/"A05_01_GO三分类前八"),"kegg":draw_kegg(tables,directory/"A05_02_KEGG统计显著性前十五")}
