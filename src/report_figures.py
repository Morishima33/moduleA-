# 报告图件生成器；所有图形直接读取已归档表，不改变科学计算结果。
from html import escape  # 安全写入SVG文字。
import math  # 计算节点和图形坐标。
from pathlib import Path  # 统一处理输出路径。
import sys  # 加载项目固定依赖。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'environments' / 'python_packages'))  # 不依赖旧Kimi环境。
import networkx as nx  # 使用项目已固定版本生成确定性网络布局。
from PIL import Image, ImageDraw, ImageFont  # 生成Word可直接嵌入的高分辨率PNG。

COLORS = {'blue': '#3D7FA6', 'light_blue': '#D9EAF3', 'purple': '#8661A8', 'green': '#4E9474', 'red': '#D9555D', 'gray': '#CAD5DC', 'dark': '#223746'}  # 固定报告图形配色。

def _font(size, bold=False):  # 取得支持中文的本机字体。
    path = Path('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc')  # 优先使用微软雅黑。
    return ImageFont.truetype(str(path), size)  # 返回指定字号字体。

def _save_svg(path, width, height, body):  # 保存可编辑SVG图形。
    header = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>'  # 建立白底画布。
    Path(path).write_text(header + body + '</svg>', encoding='utf-8')  # 一次写入完整SVG。

def _blend_hex(light, dark, ratio):  # 在同一学术色系内按数值生成平滑深浅。
    start = tuple(int(light[index:index + 2], 16) for index in (1, 3, 5))  # 解析浅色RGB。
    end = tuple(int(dark[index:index + 2], 16) for index in (1, 3, 5))  # 解析深色RGB。
    values = tuple(round(start[i] + (end[i] - start[i]) * max(0, min(1, ratio))) for i in range(3))  # 线性插值得到当前颜色。
    return '#%02X%02X%02X' % values  # 返回PNG和SVG共用颜色。

def _network_positions(nodes, edges, seed, width, height):  # 为同一事实网络生成可复算布局。
    graph = nx.Graph()  # 使用无向图表达当前展示关系。
    graph.add_nodes_from(nodes)  # 保留无边节点以反映完整集合。
    graph.add_edges_from(edges)  # 加入实际归档连边。
    components = sorted(nx.connected_components(graph), key=lambda values: (-len(values), sorted(values)[0]))  # 按大小稳定排列所有连通分量。
    main_nodes = components[0] if components else set()  # 最大分量作为主体网络。
    main_graph = graph.subgraph(main_nodes)  # 单独布局主体，避免少量孤立点压缩主体图。
    raw = nx.spring_layout(main_graph, seed=seed, iterations=350, k=1.25 / max(1, math.sqrt(len(main_nodes)))) if main_nodes else {}  # 使用固定种子避免漂移。
    xs = [point[0] for point in raw.values()] or [0, 1]  # 收集主体横坐标范围。
    ys = [point[1] for point in raw.values()] or [0, 1]  # 收集主体纵坐标范围。
    scale_x = lambda value: 90 + (value - min(xs)) / max(max(xs) - min(xs), 1e-9) * (width - 180)  # 主体铺满可用宽度。
    scale_y = lambda value: 90 + (value - min(ys)) / max(max(ys) - min(ys), 1e-9) * (height - (300 if len(components) > 1 else 180))  # 有小分量时预留底部区域。
    positions = {node: (scale_x(point[0]), scale_y(point[1])) for node, point in raw.items()}  # 保存主体坐标。
    minor_nodes = [node for component in components[1:] for node in sorted(component)]  # 汇总其余分量的全部节点。
    for index, node in enumerate(minor_nodes):  # 将小分量整齐置于底部，保持全部177节点可见。
        x = 100 + index * (width - 200) / max(1, len(minor_nodes) - 1)  # 在底部横向均匀排列。
        positions[node] = (x, height - 125)  # 与图注保留足够间距。
    return positions  # 返回稳定且主体清晰的像素坐标。

def _network_pair(svg_path, png_path, title, nodes, edges, labels, groups, sizes, seed=24):  # 同源生成SVG和PNG网络图。
    width, height = 1800, 1250  # 使用横向高分辨率画布适配Word。
    positions = _network_positions(nodes, edges, seed, width, height)  # 计算一次布局供两种格式共用。
    image = Image.new('RGB', (width, height), 'white')  # 建立PNG白底画布。
    draw = ImageDraw.Draw(image)  # 创建PNG绘图对象。
    svg = [f'<text x="{width/2}" y="48" text-anchor="middle" font-family="Microsoft YaHei" font-size="34" font-weight="700" fill="{COLORS["dark"]}">{escape(title)}</text>']  # 添加SVG标题。
    draw.text((width / 2, 28), title, font=_font(34, True), fill=COLORS['dark'], anchor='ma')  # 添加PNG标题。
    for source, target in edges:  # 绘制全部实际边。
        x1, y1 = positions[source]  # 取得起点坐标。
        x2, y2 = positions[target]  # 取得终点坐标。
        svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{COLORS["gray"]}" stroke-width="1"/>')  # SVG使用浅灰边。
        draw.line((x1, y1, x2, y2), fill=COLORS['gray'], width=2)  # PNG使用相同边色。
    palette = {'herb': COLORS['green'], 'compound': COLORS['purple'], 'target': COLORS['blue'], 'core': COLORS['red'], 'other': COLORS['blue']}  # 定义节点类别颜色。
    for node in nodes:  # 绘制每个节点。
        x, y = positions[node]  # 读取节点位置。
        radius = max(7, min(29, sizes.get(node, 10)))  # 限制节点大小避免遮挡。
        color = palette.get(groups.get(node, 'other'), COLORS['blue'])  # 按类别选择颜色。
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" stroke="{COLORS["dark"]}" stroke-width="1.5"/>')  # 添加可编辑SVG节点。
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=COLORS['dark'], width=2)  # 添加PNG节点。
        if node in labels:  # 只标注预先确定的重要节点。
            label = labels[node]  # 取得可读名称。
            svg.append(f'<text x="{x:.1f}" y="{y + radius + 23:.1f}" text-anchor="middle" font-family="Arial,Microsoft YaHei" font-size="20" font-weight="700" fill="{COLORS["dark"]}" stroke="white" stroke-width="4" paint-order="stroke">{escape(label)}</text>')  # 添加带白描边标签。
            draw.text((x, y + radius + 3), label, font=_font(20, True), fill=COLORS['dark'], stroke_width=4, stroke_fill='white', anchor='ma')  # PNG使用相同标签。
    note = '节点位置仅用于展示；节点大小表示Degree或连边数。'  # 明确布局不属于科学指标。
    svg.append(f'<text x="{width/2}" y="{height-25}" text-anchor="middle" font-family="Microsoft YaHei" font-size="18" fill="#526B7A">{note}</text>')  # 写入SVG说明。
    draw.text((width / 2, height - 42), note, font=_font(18), fill='#526B7A', anchor='ma')  # 写入PNG说明。
    _save_svg(svg_path, width, height, ''.join(svg))  # 保存SVG版本。
    image.save(png_path, dpi=(220, 220))  # 保存高分辨率PNG版本。

def _venn_pair(svg_path, png_path, summary, formula, disease):  # 生成方剂和疾病靶点韦恩图。
    width, height = 1500, 760  # 使用适合单栏报告的横向画布。
    left = int(summary['仅方剂靶点数'])  # 读取仅方剂靶点数。
    middle = int(summary['交集靶点数'])  # 读取交集靶点数。
    right = int(summary['仅疾病靶点数'])  # 读取仅疾病靶点数。
    image = Image.new('RGB', (width, height), 'white')  # 建立PNG画布。
    draw = ImageDraw.Draw(image, 'RGBA')  # 启用透明叠加。
    draw.text((width / 2, 30), '方剂靶点与疾病靶点交集', font=_font(36, True), fill=COLORS['dark'], anchor='ma')  # 写入标题。
    draw.ellipse((260, 180, 900, 650), fill=(61, 127, 166, 90), outline=COLORS['blue'], width=5)  # 绘制方剂集合。
    draw.ellipse((600, 180, 1240, 650), fill=(134, 97, 168, 90), outline=COLORS['purple'], width=5)  # 绘制疾病集合。
    for x, text in ((480, formula + ' T'), (1020, disease + ' D')):  # 写入两个集合名称。
        draw.text((x, 120), text, font=_font(25, True), fill=COLORS['dark'], anchor='ma')  # 集合名称居中显示。
    for x, value in ((430, left), (750, middle), (1070, right)):  # 写入三部分数量。
        draw.text((x, 405), str(value), font=_font(48, True), fill=COLORS['dark'], anchor='mm')  # 数字置于对应区域。
    draw.text((750, 700), '交集 I = T ∩ D；面积仅作示意，不代表数量比例', font=_font(19), fill='#526B7A', anchor='ma')  # 添加图义限制。
    image.save(png_path, dpi=(220, 220))  # 保存PNG版本。
    body = f'<text x="750" y="55" text-anchor="middle" font-family="Microsoft YaHei" font-size="36" font-weight="700" fill="{COLORS["dark"]}">方剂靶点与疾病靶点交集</text><ellipse cx="580" cy="415" rx="320" ry="235" fill="{COLORS["blue"]}" fill-opacity=".35" stroke="{COLORS["blue"]}" stroke-width="5"/><ellipse cx="920" cy="415" rx="320" ry="235" fill="{COLORS["purple"]}" fill-opacity=".35" stroke="{COLORS["purple"]}" stroke-width="5"/><g text-anchor="middle" font-family="Microsoft YaHei" fill="{COLORS["dark"]}"><text x="480" y="145" font-size="25" font-weight="700">{escape(formula)} T</text><text x="1020" y="145" font-size="25" font-weight="700">{escape(disease)} D</text><text x="430" y="425" font-size="48" font-weight="700">{left}</text><text x="750" y="425" font-size="48" font-weight="700">{middle}</text><text x="1070" y="425" font-size="48" font-weight="700">{right}</text><text x="750" y="720" font-size="19" fill="#526B7A">交集 I = T ∩ D；面积仅作示意，不代表数量比例</text></g>'  # 构建同源SVG内容。
    _save_svg(svg_path, width, height, body)  # 保存可编辑SVG。

def _go_pair(svg_path, png_path, displays):  # 生成BP、CC、MF三面板柱状图。
    width, height = 1900, 1500  # 使用三栏横向高分辨率画布。
    image = Image.new('RGB', (width, height), 'white')  # 建立PNG画布。
    draw = ImageDraw.Draw(image)  # 创建PNG绘图对象。
    draw.text((width / 2, 28), 'GO富集结果', font=_font(38, True), fill=COLORS['dark'], anchor='ma')  # 写入总标题。
    svg = [f'<text x="{width/2}" y="52" text-anchor="middle" font-family="Microsoft YaHei" font-size="38" font-weight="700" fill="{COLORS["dark"]}">GO富集结果</text>']  # 建立SVG标题。
    panel_width = 610  # 固定每个分类面板宽度。
    palettes = {'BP': ('#C6DBEF', '#2171B5'), 'CC': ('#C7E9C0', '#238B45'), 'MF': ('#DADAEB', '#6A51A3')}  # 使用蓝、青绿、紫三组学术配色。
    for panel, group in enumerate(('BP', 'CC', 'MF')):  # 三类分别绘制，保持独立校正口径。
        rows = displays[group][:8]  # 每类显示前八项避免文字过密。
        x0 = 25 + panel * 625  # 计算面板起点。
        draw.text((x0 + panel_width / 2, 88), group, font=_font(28, True), fill=palettes[group][1], anchor='ma')  # 分类名使用本组深色。
        svg.append(f'<text x="{x0+panel_width/2}" y="115" text-anchor="middle" font-family="Arial" font-size="28" font-weight="700" fill="{palettes[group][1]}">{group}</text>')  # SVG分类名使用同色。
        maximum = max((float(row['Count']) for row in rows), default=1)  # 取得该类独立计数上限。
        minimum = min((float(row['Count']) for row in rows), default=0)  # 取得该类独立计数下限。
        for index, row in enumerate(rows):  # 绘制当前分类条目。
            y = 155 + index * 155  # 为换行标签预留垂直空间。
            label = str(row['Description']).replace(' - Homo sapiens (human)', '')  # 去除重复物种后缀。
            short = label if len(label) <= 48 else label[:46] + '…'  # 限制图内标签长度。
            value = float(row['Count'])  # 使用命中基因数作为柱长。
            bar_width = 420 * value / maximum  # 在本分类内缩放柱长。
            ratio = (value - minimum) / max(maximum - minimum, 1)  # 按本组Count范围计算颜色深浅。
            bar_color = _blend_hex(palettes[group][0], palettes[group][1], ratio)  # Count越大颜色越深。
            draw.text((x0 + 10, y), short, font=_font(17), fill=COLORS['dark'])  # 写入PNG条目名。
            draw.rounded_rectangle((x0 + 10, y + 43, x0 + 10 + bar_width, y + 80), radius=8, fill=bar_color)  # 按组别和Count绘制PNG柱形。
            draw.text((x0 + 20 + bar_width, y + 60), f'{int(value)}', font=_font(16, True), fill=COLORS['dark'], anchor='lm')  # 标注命中数。
            svg.append(f'<text x="{x0+10}" y="{y+18}" font-family="Microsoft YaHei" font-size="17" fill="{COLORS["dark"]}">{escape(short)}</text><rect x="{x0+10}" y="{y+43}" width="{bar_width:.1f}" height="37" rx="8" fill="{bar_color}"/><text x="{x0+20+bar_width:.1f}" y="{y+69}" font-family="Arial" font-size="16" font-weight="700" fill="{COLORS["dark"]}">{int(value)}</text>')  # 添加同源SVG条目。
    note = 'BP、CC、MF分别进行BH校正；柱长和同组颜色深浅均表示命中基因数Count。'  # 说明三个面板不做跨类联合排序。
    draw.text((width / 2, height - 38), note, font=_font(19), fill='#526B7A', anchor='ma')  # 写入PNG图注。
    svg.append(f'<text x="{width/2}" y="{height-24}" text-anchor="middle" font-family="Microsoft YaHei" font-size="19" fill="#526B7A">{note}</text>')  # 写入SVG图注。
    image.save(png_path, dpi=(220, 220))  # 保存PNG版本。
    _save_svg(svg_path, width, height, ''.join(svg))  # 保存SVG版本。

def _kegg_pair(svg_path, png_path, rows):  # 生成KEGG气泡图。
    width, height = 1700, 1250  # 使用适合横向标签的画布。
    rows = rows[:12]  # 显示前十二项显著通路。
    values = [-math.log10(max(float(row['p.adjust']), 1e-300)) for row in rows]  # 将校正后P值转换为可视尺度。
    rich = [float(row['RichFactor']) for row in rows]  # 读取富集比例。
    counts = [int(float(row['Count'])) for row in rows]  # 读取命中基因数。
    image = Image.new('RGB', (width, height), 'white')  # 建立PNG画布。
    draw = ImageDraw.Draw(image)  # 创建PNG绘图对象。
    draw.text((width / 2, 25), 'KEGG富集结果', font=_font(38, True), fill=COLORS['dark'], anchor='ma')  # 写入标题。
    svg = [f'<text x="{width/2}" y="50" text-anchor="middle" font-family="Microsoft YaHei" font-size="38" font-weight="700" fill="{COLORS["dark"]}">KEGG富集结果</text>']  # 建立SVG标题。
    left, right, top, bottom = 670, 1570, 110, 1120  # 固定绘图区边界。
    for tick in range(6):  # 绘制RichFactor横轴网格。
        value = max(rich, default=1) * tick / 5  # 计算当前刻度值。
        x = left + (right - left) * tick / 5  # 计算当前刻度位置。
        draw.line((x, top, x, bottom), fill='#E6ECEF', width=2)  # 绘制PNG网格。
        draw.text((x, bottom + 20), f'{value:.2f}', font=_font(16), fill='#526B7A', anchor='ma')  # 写入PNG刻度。
        svg.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{bottom}" stroke="#E6ECEF" stroke-width="2"/><text x="{x}" y="{bottom+40}" text-anchor="middle" font-family="Arial" font-size="16" fill="#526B7A">{value:.2f}</text>')  # 添加SVG网格和刻度。
    for index, row in enumerate(rows):  # 绘制每条通路。
        y = top + 45 + index * ((bottom - top - 80) / max(1, len(rows) - 1))  # 均匀分布纵坐标。
        x = left + (right - left) * float(row['RichFactor']) / max(max(rich, default=1), 1e-9)  # 按RichFactor放置横坐标。
        radius = 12 + 22 * counts[index] / max(counts, default=1)  # 用命中数表示气泡大小。
        strength = values[index] / max(values, default=1)  # 用显著性控制颜色强度。
        color = (round(217 - 100 * strength), round(120 - 55 * strength), round(145 + 45 * (1 - strength)))  # 从浅紫红到深红平滑变化。
        label = str(row['Description']).replace(' - Homo sapiens (human)', '')  # 删除重复物种后缀。
        short = label if len(label) <= 62 else label[:60] + '…'  # 控制长通路名。
        draw.text((left - 20, y), short, font=_font(17), fill=COLORS['dark'], anchor='rm')  # 写入PNG通路名。
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=COLORS['dark'], width=2)  # 绘制PNG气泡。
        hex_color = '#%02X%02X%02X' % color  # 将PNG颜色转换为SVG颜色。
        svg.append(f'<text x="{left-20}" y="{y+6:.1f}" text-anchor="end" font-family="Microsoft YaHei" font-size="17" fill="{COLORS["dark"]}">{escape(short)}</text><circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{hex_color}" stroke="{COLORS["dark"]}" stroke-width="2"/>')  # 添加同源SVG通路。
    note = '横轴为RichFactor；气泡大小表示Count；颜色深浅表示BH校正后P值的相对显著性。'  # 明确气泡三种编码。
    draw.text(((left + right) / 2, height - 45), note, font=_font(18), fill='#526B7A', anchor='ma')  # 写入PNG说明。
    svg.append(f'<text x="{(left+right)/2}" y="{height-28}" text-anchor="middle" font-family="Microsoft YaHei" font-size="18" fill="#526B7A">{note}</text>')  # 写入SVG说明。
    image.save(png_path, dpi=(220, 220))  # 保存PNG版本。
    _save_svg(svg_path, width, height, ''.join(svg))  # 保存SVG版本。

def generate_report_figures(output, payload):  # 一次生成专业报告需要的全部新图件。
    output = Path(output)  # 统一输出目录类型。
    output.mkdir(parents=True, exist_ok=False)  # 新修订图件目录不得覆盖历史。
    paths = {}  # 保存供报告和索引使用的路径。
    def pair(name):  # 为一张图生成固定SVG和PNG路径。
        paths[name] = {'svg': output / (name + '.svg'), 'png': output / (name + '.png')}  # 保存两种格式。
        return paths[name]['svg'], paths[name]['png']  # 返回本次调用需要的路径。
    _venn_pair(*pair('01_方剂疾病靶点韦恩图'), payload['a03_summary'], payload['research']['formula'], payload['research']['disease'])  # 生成韦恩图。
    mixed_edges = [(row['source'], row['target']) for row in payload['a03_tables']['network_edges']]  # 读取药味成分靶点真实连边。
    mixed_nodes = sorted({node for edge in mixed_edges for node in edge})  # 建立混合网络节点集。
    mixed_groups = {node: 'herb' if node.startswith('药味:') else ('compound' if node.startswith('成分:') else 'target') for node in mixed_nodes}  # 按前缀识别节点类型。
    top_compounds = {row['compound_id'] for row in payload['selected_compounds']}  # 取得已批准五个主候选。
    mixed_labels = {node: node.split(':', 1)[1] for node in mixed_nodes if node.startswith('药味:') or (node.startswith('成分:') and node.split(':', 1)[1] in top_compounds)}  # 只标注药味和主候选成分。
    mixed_degree = dict(nx.Graph(mixed_edges).degree())  # 计算仅用于图形大小的实际连边数。
    mixed_sizes = {node: 8 + min(20, int(math.sqrt(max(1, mixed_degree[node])) * 3)) for node in mixed_nodes}  # 平滑缩放混合网络节点。
    _network_pair(*pair('02_药味成分交集靶点网络图'), '药味 成分 交集靶点网络', mixed_nodes, mixed_edges, mixed_labels, mixed_groups, mixed_sizes, seed=31)  # 生成混合网络图。
    ppi_rows = payload['a04_tables']['metrics']  # 读取全部PPI参与节点。
    ppi_edges = [(row['source'], row['target']) for row in payload['a04_tables']['edges']]  # 读取全部合格PPI边。
    ppi_nodes = [row['target_id'] for row in ppi_rows]  # 保留177个参与节点。
    round1_ids = {row['target_id'] for row in payload['a04_tables']['round1']}  # 取得52个第一轮主候选。
    top10 = sorted(payload['a04_tables']['round1'], key=lambda row: (-int(row['degree']), row['symbol']))[:10]  # 按Degree稳定选择图中前十标签。
    top10_ids = {row['target_id'] for row in top10}  # 建立前十身份集合。
    ppi_labels = {row['target_id']: row['symbol'] for row in top10}  # 只标注前十避免重叠。
    ppi_groups = {node: 'core' if node in round1_ids else 'other' for node in ppi_nodes}  # 完整图突出第一轮节点。
    ppi_sizes = {row['target_id']: 7 + min(22, int(row['degree']) // 2) for row in ppi_rows}  # 节点大小表示Degree。
    _network_pair(*pair('03_PPI完整网络图'), f'PPI完整网络 {len(ppi_nodes)}个参与节点', ppi_nodes, ppi_edges, ppi_labels, ppi_groups, ppi_sizes, seed=24)  # 图题使用本次实际节点数。
    core_nodes = [row['target_id'] for row in payload['a04_tables']['round1']]  # 取得第一轮52节点。
    core_set = set(core_nodes)  # 建立过滤边所需集合。
    core_edges = [(source, target) for source, target in ppi_edges if source in core_set and target in core_set]  # 使用原网络诱导子图，不重算筛选。
    core_groups = {node: 'core' if node in top10_ids else 'other' for node in core_nodes}  # 核心图只突出Degree前十。
    core_sizes = {row['target_id']: 9 + min(22, int(row['degree']) // 2) for row in payload['a04_tables']['round1']}  # 使用原网络Degree控制大小。
    _network_pair(*pair('04_PPI第一轮主候选网络图'), f'PPI第一轮主候选网络 {len(core_nodes)}个节点', core_nodes, core_edges, ppi_labels, core_groups, core_sizes, seed=24)  # 图题使用本次实际候选数。
    _go_pair(*pair('05_GO富集三分类柱状图'), payload['enrichment_highlights'])  # 生成GO三面板柱状图。
    _kegg_pair(*pair('06_KEGG富集气泡图'), payload['enrichment_highlights']['KEGG'])  # 生成KEGG气泡图。
    return paths  # 返回全部图件路径供Word和索引使用。
