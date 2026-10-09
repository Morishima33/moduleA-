# 可独立下载的科学SVG图；图表使用同一display表。
import math  # 面积与Count一致。
import textwrap  # 长英文术语换行。
from html import escape  # 防止术语作为HTML执行。

def chart(rows, group, kind):  # 柱长Count，气泡横轴GeneRatio。
    height=150+len(rows)*66  # 固定行距适应长标签。
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 {max(height,230)}"><rect width="1100" height="100%" fill="white"/><g font-family="Arial, sans-serif" font-size="13" fill="#243746">',f'<text x="25" y="28" font-size="19">{group} — {"Count" if kind=="bar" else "GeneRatio"} (BH adjusted P &lt; 0.05)</text>']  # 原数值含义明确。
    if not rows:  # 无显著项正常出图。
        return ''.join(parts)+'<text x="25" y="90">No significant terms under the fixed threshold.</text></g></svg>'  # 不用非显著排名替代。
    logs=[-math.log10(max(float(r["p.adjust"]),1e-300)) for r in rows]  # 仅绘图防止log零；原始P值不改。
    lo,hi=min(logs),max(logs)  # 色标使用实际展示范围。
    values=[float(r["Count"]) if kind=="bar" else int(r["GeneRatio"].split("/")[0])/int(r["GeneRatio"].split("/")[1]) for r in rows]  # 使用有效分母。
    maximum=max(values)*1.1  # 轴从零开始，留少量边距。
    def color(value):  # 单调色标而非成分分类颜色。
        t=(value-lo)/(hi-lo) if hi>lo else 0.5  # 全同值时用中间色。
        return f'rgb({int(55+170*t)},{int(135-65*t)},{int(180-115*t)})'  # 蓝至红。
    for j in range(6):  # 明确数值刻度。
        x=410+j*100  # 横轴500单位显示宽。
        parts.append(f'<line x1="{x}" y1="55" x2="{x}" y2="{height-75}" stroke="#e1e7ed"/><text x="{x}" y="{height-50}" text-anchor="middle">{maximum*j/5:.3g}</text>')  # 网格不代替刻度。
    for i,(row,value,logp) in enumerate(zip(rows,values,logs)):  # 排序沿用已冻结display表。
        y=85+i*66  # 每条同高。
        lines=textwrap.wrap(row["Description"],width=48)  # 不截断标签。
        for j,line in enumerate(lines):  # 可读完整术语。
            parts.append(f'<text x="395" y="{y-12+j*15}" text-anchor="end">{escape(line)}</text>')  # 转义原名。
        x=410+500*value/maximum  # 与轴同一比例。
        if kind=="bar":  # 柱状图用命中数。
            parts.append(f'<rect x="410" y="{y-12}" width="{x-410:.3f}" height="24" fill="{color(logp)}"/>')  # 不使用负logP作为柱长。
        else:  # 气泡面积与命中Count成比例。
            radius=14*math.sqrt(row["Count"]/max(r["Count"] for r in rows))  # 最大半径固定。
            parts.append(f'<circle cx="{x:.3f}" cy="{y}" r="{radius:.3f}" fill="{color(logp)}"><title>Count={row["Count"]}; GeneRatio={row["GeneRatio"]}; p.adjust={row["p.adjust"]}</title></circle>')  # 原值可悬停查看。
        parts.append(f'<text x="925" y="{y+4}">Count {row["Count"]}</text>')  # 命中数明确显示。
    parts.append(f'<text x="410" y="{height-15}">{"Count" if kind=="bar" else "GeneRatio (effective input denominator)"}</text>')  # 明确横轴。
    for i in range(30):  # 可见色标。
        parts.append(f'<rect x="{650+i*7}" y="40" width="7" height="10" fill="{color(lo+(hi-lo)*i/29)}"/>')  # 与图内颜色同标度。
    parts.append(f'<text x="650" y="35">-log10(BH adjusted P): {lo:.2f} to {hi:.2f}</text></g></svg>')  # 科学色标注明统计量。
    return ''.join(parts)  # 文件无外部依赖。
