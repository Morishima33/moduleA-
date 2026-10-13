"""同批矩阵图件输出：颜色、数值、色标统一，空评分不伪造图件。"""
from pathlib import Path
from html import escape
from math import isfinite
from contracts import require
from .matrix_palette import color,PALETTE,LEGACY,RED_BLUE

# 检查已经过结果契约核验的视图，拒绝被替换的颜色、范围或不完整单元格。
def validate_matrix(matrix):
    require(matrix.get("ready") is True,"没有本轮真实评分，不能导出结果图")
    palette=matrix["palette"];require(palette in (PALETTE,LEGACY,RED_BLUE),"未知热图配色")
    low,high=matrix["score_range"]
    require((low is None and high is None) or (all(isinstance(x,(int,float)) and isfinite(x) for x in (low,high)) and low<=high),"色标范围无效")
    for name in ("heatmap","table"):
        part=matrix[name];require(len(part["cells"])==len(part["rows"]),"矩阵缺行")
        for source,line in zip(part["rows"],part["cells"]):
            require(len(line)==len(part["columns"]),"矩阵缺列")
            for target,cell in zip(part["columns"],line):
                require(cell["compound_id"]==source["compound_id"] and cell["target_id"]==target["target_id"],"图表对象与归档不一致")
                if cell["state"]=="completed":
                    score=cell["score"];require(isinstance(score,(int,float)) and isfinite(score) and low is not None and low<=score<=high,"单元格评分无效")
                    require(cell["color"].lower()==color(score,low,high,palette).lower(),"单元格颜色与本批色标不同")
                else:require(cell["state"]=="NA" and cell["score"] is None and cell["reason_zh"] and cell["color"]==palette["na_color"],"NA须保留原因与灰色")
    return matrix

# NA原因按首次出现编号，静态PNG也可核查，不依赖悬停。
def na_reasons(matrix):
    return list(dict.fromkeys(c["reason_zh"] for line in matrix["heatmap"]["cells"] for c in line if c["score"] is None))

def na_lines(matrix):
    from textwrap import wrap
    return [line for i,reason in enumerate(na_reasons(matrix),1) for line in wrap(f"NA[{i}]：{reason}",width=72,break_long_words=True,break_on_hyphens=False)]

def cell_label(cell,matrix):
    return f'{cell["score"]:.2f}' if cell["score"] is not None else 'NA['+str(na_reasons(matrix).index(cell["reason_zh"])+1)+']'

# SVG和PNG共用几何位置；标签与单位不会依赖浏览器外部资源。
def layout(matrix):
    h=matrix["heatmap"];return {"left":270,"top":94,"cw":92,"rh":52,"width":290+len(h["columns"])*92,"height":260+len(h["rows"])*52+len(na_lines(matrix))*18}

def label(matrix):
    low,high=matrix["score_range"]
    if low is None:return "本批次全部为NA，无有效评分范围"
    return f"本批次有效评分范围：{low:.4g} 至 {high:.4g} kcal/mol"

# 使用标准库生成完整SVG，前端与下载使用同一份图件。
def heatmap_svg(matrix):
    validate_matrix(matrix);h=matrix["heatmap"];g=layout(matrix);p=matrix["palette"];low,high=matrix["score_range"];x,y=g["left"],g["top"];bottom=y+len(h["rows"])*g["rh"]
    pieces=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{g["width"]}" height="{g["height"]}" viewBox="0 0 {g["width"]} {g["height"]}" role="img" aria-label="重点结合能热图">', '<rect width="100%" height="100%" fill="white"/>',f'<defs><linearGradient id="scores"><stop offset="0%" stop-color="{p["high_color"]}"/><stop offset="100%" stop-color="{p["low_color"]}"/></linearGradient></defs>']
    # 色标与单元格共用函数；红蓝使用历史平滑分段，不能只线性连接两个端点。
    if low is not None:
        stops=''.join(f'<stop offset="{i}%" stop-color="{color(high-(high-low)*i/100,low,high,p)}"/>' for i in range(101))
        pieces[2]=f'<defs><linearGradient id="scores">{stops}</linearGradient></defs>'
    def text(tx,ty,value,size=13,anchor="start",fill="#10253C"):
        pieces.append(f'<text x="{tx}" y="{ty}" font-family="Microsoft YaHei,Arial,sans-serif" font-size="{size}" text-anchor="{anchor}" fill="{fill}">{escape(str(value))}</text>')
    text(g["width"]/2,30,f'重点结合能热图 {len(h["rows"])}×{len(h["columns"])}',18,"middle")
    for j,r in enumerate(h["columns"]):
        text(x+(j+.5)*g["cw"],59,r.get("symbol",r["target_id"]),12,"middle")
        text(x+(j+.5)*g["cw"],79,r.get("candidate_grade","")+" / "+r.get("quality_zh","待质控"),11,"middle")
    for i,r in enumerate(h["rows"]):
        text(x-12,y+i*g["rh"]+31,r.get("name_zh",r.get("name",r["compound_id"])),12,"end")
        for j,c in enumerate(h["cells"][i]):
            tx=x+j*g["cw"];ty=y+i*g["rh"]
            pieces.append(f'<g><title>{escape(str(c.get("reason_zh", "")))}</title><rect x="{tx}" y="{ty}" width="{g["cw"]-2}" height="{g["rh"]-2}" fill="{c["color"]}"/>')
            text(tx+(g["cw"]-2)/2,ty+31,cell_label(c,matrix),13,"middle",c["text_color"]);pieces.append('</g>')
    if low is not None:
        if low==high:
            pieces.append(f'<rect x="{x}" y="{bottom+28}" width="300" height="18" fill="{color(low,low,high,p)}"/>')
        else:pieces.append(f'<rect x="{x}" y="{bottom+28}" width="300" height="18" fill="url(#scores)"/>')
        text(x,bottom+64,f'{high:.4g}',12);text(x+300,bottom+64,f'{low:.4g}',12,"end");text(x+320,bottom+43,"kcal/mol",12)
    text(20,bottom+94,label(matrix),12);text(20,bottom+116,p["label_zh"]+"；完整同批范围，不设通用阈值。",12)
    text(20,bottom+138,"A/B为候选梯队，与结构质控分开；对接评分不能直接证明药效。",12)
    for i,reason in enumerate(na_lines(matrix)):text(20,bottom+160+i*18,reason,12)
    pieces.append('</svg>');return ''.join(pieces)

# 科学后台才加载Pillow；接口读取与SVG生成仍只使用标准库。
def export_heatmap(matrix,directory,font_path=None):
    from PIL import Image,ImageDraw,ImageFont
    import os
    validate_matrix(matrix);folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
    font=Path(font_path) if font_path else Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts/msyh.ttc"
    require(font.is_file(),"请明确可用中文绘图字体")
    g=layout(matrix);scale=3;image=Image.new("RGB",(g["width"]*scale,g["height"]*scale),"white");draw=ImageDraw.Draw(image);h=matrix["heatmap"];p=matrix["palette"];low,high=matrix["score_range"];x,y=g["left"],g["top"];bottom=y+len(h["rows"])*g["rh"]
    def text(tx,ty,value,size=13,anchor="start",fill="#10253C"):
        face=ImageFont.truetype(str(font),size*scale);draw.text((tx*scale,ty*scale),str(value),font=face,fill=fill,anchor={"start":"ls","middle":"ms","end":"rs"}[anchor])
    text(g["width"]/2,30,f'重点结合能热图 {len(h["rows"])}×{len(h["columns"])}',18,"middle")
    for j,r in enumerate(h["columns"]):
        text(x+(j+.5)*g["cw"],59,r.get("symbol",r["target_id"]),12,"middle");text(x+(j+.5)*g["cw"],79,r.get("candidate_grade","")+" / "+r.get("quality_zh","待质控"),11,"middle")
    for i,r in enumerate(h["rows"]):
        text(x-12,y+i*g["rh"]+31,r.get("name_zh",r.get("name",r["compound_id"])),12,"end")
        for j,c in enumerate(h["cells"][i]):
            tx=x+j*g["cw"];ty=y+i*g["rh"];draw.rectangle((tx*scale,ty*scale,(tx+g["cw"]-2)*scale-1,(ty+g["rh"]-2)*scale-1),fill=c["color"]);text(tx+(g["cw"]-2)/2,ty+31,cell_label(c,matrix),13,"middle",c["text_color"])
    if low is not None:
        for pixel in range(300*scale):
            fraction=pixel/(300*scale-1);shade=color(high-(high-low)*fraction,low,high,p);px=x*scale+pixel;draw.line((px,(bottom+28)*scale,px,(bottom+46)*scale-1),fill=shade)
        text(x,bottom+64,f'{high:.4g}',12);text(x+300,bottom+64,f'{low:.4g}',12,"end");text(x+320,bottom+43,"kcal/mol",12)
    text(20,bottom+94,label(matrix),12);text(20,bottom+116,p["label_zh"]+"；完整同批范围，不设通用阈值。",12);text(20,bottom+138,"A/B为候选梯队，与结构质控分开；对接评分不能直接证明药效。",12)
    for i,reason in enumerate(na_lines(matrix)):text(20,bottom+160+i*18,reason,12)
    svg=folder/"A06_01_重点结合能热图.svg";png=folder/"A06_01_重点结合能热图.png";svg.write_text(heatmap_svg(matrix),encoding="utf-8");image.save(png,dpi=(288,288))
    return {"svg":svg,"png":png}
