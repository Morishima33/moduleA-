"""新方案A05图件从同批展示表绘制；数量及显著性文字只读实际方案。"""
import math
from .figures import Canvas, PALETTES, _blend_hex, wrap


def draw(tables, plan, folder):
    """按实际纳入类别分别出同源PNG/SVG，动态高度承载1—25前列。"""
    p = plan["parameters"]
    output = {}
    groups = (["BP", "CC", "MF"] if p["a05.include_go"] else []) + (["KEGG"] if p["a05.include_kegg"] else [])
    for group in groups:
        rows = tables[group.lower()+"_display"]
        labels = [wrap(row["Description"], 1000, 28) for row in rows]
        pitches = [max(100, 36*len(lines)+55) for lines in labels]
        height = max(550 if group == 'KEGG' else 400, 150+sum(pitches)+(230 if group == 'KEGG' else 110))
        canvas = Canvas(2000, height)
        top = p["a05.kegg_plot_top"] if group == "KEGG" else p["a05.go_plot_top"]
        canvas.text(1000, 22, f"{group} 富集：本方案前 {top} 项", 34, bold=True, anchor="ma")
        metric = '横轴RichFactor；气泡面积Count；颜色−log10(BH P)' if group == 'KEGG' else '柱长与颜色深浅表示命中数Count'
        canvas.text(1000, 72, f"BH p.adjust < {p['a05.adjusted_p_max']:g}；{metric}", 24, anchor="ma")
        if not rows:
            canvas.text(1000, 190, "本类无符合方案阈值的显著条目，不放宽阈值补项。", 25, anchor="ma")
        maximum = max((int(row["Count"]) for row in rows), default=1)
        palette = PALETTES.get(group, ("#C6DBEF", "#08519C"))
        rich_max = max((float(row['RichFactor']) for row in rows), default=1)*1.1
        strengths = [-math.log10(max(float(row['p.adjust']),1e-300)) for row in rows]
        low, high = min(strengths, default=0), max(strengths, default=0)
        if group == 'KEGG' and rows:
            for i in range(6):
                x=1180+560*i/5
                canvas.line(x,120,x,135+sum(pitches))
                canvas.text(x,145+sum(pitches),f'{rich_max*i/5:.3g}',20,anchor='ma')
        y = 135
        for row, lines, pitch in zip(rows, labels, pitches):
            for i, line in enumerate(lines):
                canvas.text(25, y+i*36, line, 28)
            bar_y = y+len(lines)*36+8
            count = int(row["Count"])
            length = 560*count/max(maximum, 1)
            if group == 'KEGG':
                strength=-math.log10(max(float(row['p.adjust']),1e-300))
                canvas.circle(1180+560*float(row['RichFactor'])/max(rich_max,1e-12),bar_y+12,
                              25*math.sqrt(count/max(maximum,1)),_blend_hex(*palette,(strength-low)/(high-low) if high>low else .65))
            else:
                canvas.rect(1180, bar_y, length, 30, _blend_hex(*palette, count/max(maximum, 1)), 4)
            canvas.text(1760, bar_y, f"{count}；BH P={float(row['p.adjust']):.3g}", 19)
            y += pitch
        if group == 'KEGG' and rows:
            legend_y=height-155
            canvas.text(30,legend_y-8,'颜色：−log10(BH P)',21)
            for i in range(100):
                canvas.rect(280+i*5,legend_y,5,18,_blend_hex(*palette,i/99))
            canvas.text(280,legend_y+25,f'{low:.3g}',20)
            canvas.text(780,legend_y+25,f'{high:.3g}',20,anchor='ra')
            canvas.text(920,legend_y-8,'气泡面积：Count',21)
            for i,count in enumerate(sorted({int(row['Count']) for row in rows})[:3]):
                x=1220+i*180
                canvas.circle(x,legend_y+10,25*math.sqrt(count/max(maximum,1)),palette[0])
                canvas.text(x+38,legend_y,count,20)
        canvas.text(1000, height-65, "排序：BH校正后P值、稳定编号；完整统计见结果表，图中不足按实际数量。", 22, anchor="ma")
        canvas.text(1000, height-32, "各检验族独立BH校正；统计富集不证明通路激活、抑制或疗效。", 22, anchor="ma")
        for kind, path in canvas.save(folder / (group+"_plan")).items():
            output[group+"_"+kind] = path
    return output
