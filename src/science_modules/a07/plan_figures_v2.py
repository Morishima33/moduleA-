"""报告二版同批图：Degree第二轮内部网络、已确认韦恩图及真实名称矩阵。"""
from copy import deepcopy
from pathlib import Path
import hashlib
import math

from contracts import fingerprint, require
from storage import file_record, read_json, verified_file, write_json
from . import plan_figures as original
from .plan_translations_v2 import check_readability

VERSION = 'A07.plan_figures.2'


def venn(summary, folder):
    """复用已确认网页几何和颜色；两圆面积为示意，数量取同批标准化结果。"""
    from science_modules.a05.figures import Canvas
    from PIL import Image, ImageChops, ImageDraw
    left, both, right = (summary[key] for key in ('仅方剂靶点数', '交集靶点数', '仅疾病靶点数'))
    require(all(type(x) is int and x >= 0 for x in (left, both, right)), '韦恩图数量缺失或不是非负整数')
    canvas = Canvas(1560, 900)
    canvas.text(780, 30, '方剂靶点与疾病靶点的交集', 42, bold=True, anchor='ma')
    if both:
        centers, radius, cy = (201.210 * 3, 318.790 * 3), 300, 430
        canvas.circle(centers[0], cy, radius, '#D9E7EA')
        canvas.circle(centers[1], cy, radius, '#F7E9D7')
        masks = []
        for cx in centers:
            mask = Image.new('L', canvas.image.size)
            ImageDraw.Draw(mask).ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=255)
            masks.append(mask)
        canvas.image.paste('#E6A9B5', (0, 0, canvas.width, canvas.height), ImageChops.darker(*masks))
        canvas.svg.append(f'<defs><clipPath id="intersection"><circle cx="{centers[1]:.2f}" cy="{cy}" r="{radius}"/></clipPath></defs>')
        canvas.svg.append(f'<circle cx="{centers[0]:.2f}" cy="{cy}" r="{radius}" fill="#E6A9B5" clip-path="url(#intersection)"/>')
        for x, label, count, color in ((444, '仅方剂', left, '#0A4350'), (780, '交集 I', both, '#71364A'), (1116, '仅疾病', right, '#7A4100')):
            canvas.text(x, 350, label, 39, color=color, anchor='ma')
            canvas.text(x, 420, count, 78 if x == 780 else 66, color=color, bold=True, anchor='ma')
    else:
        for x, count, label, fill in ((336, left, '方剂靶点', '#D9E7EA'), (1224, right, '疾病靶点', '#F7E9D7')):
            if count:
                canvas.circle(x, 430, 261, fill)
            else:
                canvas.rect(x-260, 200, 520, 450, '#F6F8F9', 25)
            canvas.text(x, 350, label if count else label+'为空', 39, anchor='ma')
            canvas.text(x, 420, count, 72, bold=True, anchor='ma')
        canvas.text(780, 350, '交集为空', 39, anchor='ma')
        canvas.text(780, 420, 0, 72, bold=True, anchor='ma')
    canvas.text(400, 775, f'方剂靶点 T = {left+both}', 33, anchor='ma')
    canvas.text(1160, 775, f'疾病靶点 D = {right+both}', 33, anchor='ma')
    canvas.text(780, 840, '图形面积仅示意；数字为同批标准化后的不同人类基因数。', 28, anchor='ma')
    return canvas.save(Path(folder)/'intersection')


def network_scope(result, selection, *, overview=False):
    """只选原Degree第二轮成员和内部边；不重新计算中心性或用最终受体名单替代。"""
    tables = result['tables']
    mapping = {row['target_id']: row for row in tables['mapping']}
    require(len(mapping) == len(tables['mapping']), '网络原节点编号重复')
    for row in tables['edges']:
        require(row['source'] in mapping and row['target'] in mapping, 'PPI原边含未登记节点')
    if overview:
        rows = tables['mapping']
    else:
        require(isinstance(selection, dict), '缺少本批Degree第二轮原名单，不能回退整网或最终受体名单')
        rows = selection.get('tables', selection).get('degree_round2')
        require(isinstance(rows, list), '本批选择记录未提供Degree第二轮表')
    ids = [row['target_id'] for row in rows]
    require(len(ids) == len(set(ids)) and set(ids) <= set(mapping), 'Degree第二轮含重复或非本批节点')
    members = set(ids)
    edges = [deepcopy(row) for row in tables['edges'] if row['source'] in members and row['target'] in members]
    participating = {row[key] for row in edges for key in ('source', 'target')}
    return {'kind': 'full_network_overview' if overview else 'degree_round2',
            'nodes': [deepcopy(mapping[key]) for key in ids], 'edges': edges,
            'isolates': [key for key in ids if key not in participating], 'source_result_hash': fingerprint(result)}


def network_positions(graph, *, overview=False):
    """分开排布连通分量，孤立点不会把主网络挤成一个小团；仅改变画面坐标。"""
    import networkx as nx
    components = sorted((sorted(part, key=str) for part in nx.connected_components(graph)),
                        key=lambda part: (-len(part), str(part[0])))
    coordinates = {}
    def place(part, box):
        left, top, right, bottom = box
        if len(part) == 1:
            coordinates[part[0]] = ((left+right)/2, (top+bottom)/2)
            return
        points = nx.spring_layout(graph.subgraph(part), seed=24, iterations=100 if overview else 250)
        low = [min(float(point[axis]) for point in points.values()) for axis in (0, 1)]
        span = [max(float(point[axis]) for point in points.values())-low[axis] for axis in (0, 1)]
        for key, point in points.items():
            coordinates[key] = (left+(float(point[0])-low[0])/max(span[0], 1e-9)*(right-left),
                                top+(float(point[1])-low[1])/max(span[1], 1e-9)*(bottom-top))
    if not components:
        return coordinates
    if len(components[0]) > len(graph)/2 and len(components) > 1:
        place(components[0], (130, 150, 1450, 1090))
        remainder, bounds = components[1:], (1530, 150, 1690, 1090)
    else:
        remainder, bounds = components, (130, 150, 1670, 1090)
    left, top, right, bottom = bounds
    cols = max(1, math.ceil(math.sqrt(len(remainder)*(right-left)/(bottom-top))))
    rows = max(1, math.ceil(len(remainder)/cols))
    width, height = (right-left)/cols, (bottom-top)/rows
    for index, part in enumerate(remainder):
        x, y = left+(index % cols)*width, top+(index//cols)*height
        pad = min(30, width/5, height/5)
        place(part, (x+pad, y+pad, x+width-pad, y+height-pad))
    return coordinates


def ppi(scope, folder):
    """正文图只标记少量关键标签，全部节点名称保留SVG提示，整网另作概览。"""
    import networkx as nx
    from science_modules.a05.figures import Canvas
    graph = nx.Graph()
    nodes = {row['target_id']: row for row in scope['nodes']}
    graph.add_nodes_from(nodes)
    graph.add_edges_from((row['source'], row['target']) for row in scope['edges'])
    overview = scope['kind'] == 'full_network_overview'
    canvas = Canvas(1800, 1300)
    title = '本批PPI全网络概览' if overview else 'Degree第二轮候选靶点的内部PPI网络'
    canvas.text(900, 25, title, 38, bold=True, anchor='ma')
    coords = network_positions(graph, overview=overview)
    for a, b in graph.edges():
        canvas.line(*coords[a], *coords[b], fill='#DCE5E9' if overview else '#C8D8DF')
    order = sorted(graph, key=lambda key: (-graph.degree(key), key))
    labels = set(order[:(0 if overview else 15)] if len(order) > 40 else order)
    from report_figures import _font
    label_font = _font(22, True)
    occupied = []
    for key in order:
        x, y = coords[key]
        radius = 5 if overview else 7 + min(6, math.sqrt(graph.degree(key)))
        name = nodes[key].get('symbol') or key
        canvas.circle(x, y, radius, '#9CC7D5' if graph.degree(key) else '#E6ECEF', name+' '+key)
    # 标签最后绘制并加白底，后绘节点不能遮住已经放好的名称。
    for key in order:
        x, y = coords[key]
        name = nodes[key].get('symbol') or key
        if key not in labels:
            continue
        width = max(40, float(label_font.getlength(name))+18)
        for dx, dy in ((0, 25), (0, -45), (width/2+25, 0), (-width/2-25, 0), (0, 70), (0, -90), (width+40, 65), (-width-40, -65), (0, 120), (0, -140)):
            box = (x+dx-width/2, y+dy-5, x+dx+width/2, y+dy+34)
            if box[0] < 20 or box[2] > 1780 or box[1] < 100 or box[3] > 1160:
                continue
            if any(not (box[2]+10 < old[0] or box[0]-10 > old[2] or box[3]+10 < old[1] or box[1]-10 > old[3]) for old in occupied):
                continue
            canvas.line(x, y, x+dx, y+dy+12, fill='#547889')
            canvas.rect(box[0], box[1], width, 39, '#FFFFFF')
            canvas.text(x+dx, y+dy, name, 22, bold=True, anchor='ma')
            occupied.append(box)
            break
    if not nodes:
        canvas.text(900, 600, '本批该筛选范围为空', 32, anchor='ma')
    caption = f'本图{len(nodes)}节点、{len(scope["edges"])}条内部边、{len(scope["isolates"])}个孤立点。'
    canvas.text(900, 1190, caption, 27, anchor='ma')
    canvas.text(900, 1235, '标签仅辅助阅读；完整成员见同批数据表，节点数不等于最终对接受体数。', 24, anchor='ma')
    return canvas.save(Path(folder)/('ppi_overview' if overview else 'ppi_degree_round2'))


def heatmaps(facts, folder):
    """真实成分名可换行，列名取本批受体符号；评分、完整NA及配色复用既有规则。"""
    from science_modules.a05.figures import Canvas, wrap
    from science_modules.a06.matrix_palette import color, text_color, RED_BLUE
    from science_modules.a06.trial_presentation import score_label, LEGEND
    scores = [row['score'] for row in facts['pairs'] if row['score'] is not None]
    low, high = (min(scores), max(scores)) if scores else (None, None)
    outputs = []
    for row_start in range(0, len(facts['compounds']), 20):
        for col_start in range(0, len(facts['receptors']), 8):
            compounds = facts['compounds'][row_start:row_start+20]
            receptors = facts['receptors'][col_start:col_start+8]
            labels = [wrap(row.get('name_zh') or row.get('name') or row['compound_id'], 540, 25) for row in compounds]
            pitches = [max(66, len(lines)*32+18) for lines in labels]
            width = 600+150*len(receptors)
            explanation = '本批无可用评分，全部缺失保持NA。' if not scores else f'同批原评分范围：{low:g} 至 {high:g} kcal/mol；越负越红，越不负越蓝。'
            footer = wrap(explanation, width-40, 20)+wrap(LEGEND, width-40, 20)
            height = 225+sum(pitches)+28*len(footer)
            canvas = Canvas(width, height)
            canvas.text(width/2, 18, '同批完整固定范围评分矩阵', 32, bold=True, anchor='ma')
            for j, row in enumerate(receptors):
                for index, line in enumerate(wrap(row.get('symbol') or row['target_id'], 140, 24)):
                    canvas.text(600+j*150+75, 80+index*28, line, 24, anchor='ma')
            cells = {(row['compound_id'], row['target_id']): row for row in facts['pairs']}
            y = 175
            for i, compound in enumerate(compounds):
                pitch = pitches[i]
                for k, line in enumerate(labels[i]):
                    canvas.text(575, y+(pitch-len(labels[i])*32)/2+k*32, line, 25, anchor='ra')
                for j, receptor in enumerate(receptors):
                    x = 600+j*150
                    score = cells[(compound['compound_id'], receptor['target_id'])]['score']
                    fill = color(score, low, high, RED_BLUE) if score is not None else '#FFFFFF'
                    canvas.rect(x, y, 150, pitch, fill)
                    if score is None:
                        for a, b, c, d in ((x,y,x+150,y),(x,y+pitch,x+150,y+pitch),(x,y,x,y+pitch),(x+150,y,x+150,y+pitch)):
                            length = max(abs(c-a), abs(d-b))
                            for offset in range(0, int(length), 10):
                                canvas.line(a+(c-a)*offset/length, b+(d-b)*offset/length,
                                            a+(c-a)*min(offset+5,length)/length, b+(d-b)*min(offset+5,length)/length, fill='#80939C')
                    canvas.text(x+75, y+(pitch-28)/2, score_label(score, mark=True), 26, color=text_color(fill), anchor='ma')
                y += pitch
            for index, line in enumerate(footer):
                canvas.text(20, y+20+index*28, line, 20)
            paths = canvas.save(Path(folder)/f'scores_{row_start+1}_{col_start+1}')
            outputs.append((paths, '完整同批评分矩阵；行列使用本批实际名称，全部NA和原始评分保留。'))
    return outputs


def attach(workflow, payload, folder):
    """独立二版归档，正文Degree图与全网概览分开；每件图与实现均留指纹。"""
    check_readability(payload)
    require(payload.get('figure_source') is None and payload.get('figures') == [], '事实包已有图件，不重复追加')
    home = workflow.location(payload['study_id']); folder = Path(folder).resolve()
    folder.relative_to(home.resolve())
    require(not folder.exists(), '报告图件目录已存在，不覆盖历史')
    folder.mkdir(parents=True)
    manifest = workflow.load(payload['study_id']); figures = []; files = []
    def add(paths, module, caption, scope_hash, group=None, role=None):
        """图像和SVG共用来源；概览有独立角色，不充当正文筛选网络。"""
        records = {key: file_record(home, path, 'plan_report_figure') for key, path in paths.items()}
        for path in paths.values():
            if Path(path).suffix == '.svg':
                from .plan_translations_v2 import PLACEHOLDER
                require(not PLACEHOLDER.search(Path(path).read_text(encoding='utf-8')), '最终SVG仍含缺译占位文字')
        files.extend(records.values())
        entry = {'module': module, 'record': records['png'], 'caption': caption, 'scope_hash': scope_hash}
        if group:
            entry['group'] = group
        if role:
            entry['role'] = role
        figures.append(entry)
    result = workflow.result(manifest, payload['run_ids']['A03'])
    add(venn(result['summary'], folder), 'A03', '同批标准化交集，圆形面积仅示意。', fingerprint(result))
    network = payload.get('network')
    if network:
        add(ppi(network['main'], folder), 'A04', '本批Degree第二轮成员及其内部边；完整成员见同批表，不等于最终对接受体名单。', fingerprint(network), role='degree_round2')
        add(ppi(network['overview'], folder), 'A04', '本批全网络概览；与Degree第二轮正文图分开解释，不改变筛选。', fingerprint(network), role='full_network_overview')
    if payload.get('enrichment'):
        from science_modules.a05.plan_display_figures import draw
        facts = payload['enrichment']; paths = draw(facts, payload['plan'], folder/'enrichment')
        for group in ('BP', 'CC', 'MF', 'KEGG'):
            if group+'_png' in paths:
                add({'png': paths[group+'_png'], 'svg': paths[group+'_svg']}, 'A05', group+' 同批实际展示范围；中英文按稳定编号核对，原统计保持。', fingerprint(facts), group)
    if payload.get('docking'):
        for paths, caption in heatmaps(payload['docking'], folder/'docking'):
            add(paths, 'A06', caption, fingerprint(payload['docking']))
    src = Path(__file__).resolve().parents[2]; implementation = []
    names = ('science_modules/a07/plan_figures_v2.py', 'science_modules/a07/plan_payload_v2.py',
             'science_modules/a07/plan_facts_v2.py', 'science_modules/a07/plan_translations_v2.py',
             'science_modules/a07/term_translation_supplement_v2.json', 'science_modules/a07/plan_documents_v2.py',
             'science_modules/a07/plan_report_flow_v2.py', 'modulea/core/plan_reports_v2.py',
             'science_modules/a07/plan_documents.py', 'science_modules/a07/plan_facts.py',
             'science_modules/a07/plan_payload.py', 'science_modules/a07/plan_document_style.py',
             'science_modules/a05/figures.py', 'science_modules/a05/plan_figures.py',
             'science_modules/a05/plan_display_figures.py', 'science_modules/a06/trial_presentation.py',
             'science_modules/a06/matrix_palette.py', 'report_figures.py', 'docking_formal.py',
             'science_modules/a07/appendix_documents.py', 'science_modules/a07/commented_documents.py',
             'modulea/core/plan_report_contract.py', 'modulea/core/analysis_plans.py',
             'modulea/core/system_validation.py', 'science_modules/analysis_protocol.py',
             'report_flow.py', 'contracts.py', 'workflow.py', 'storage.py')
    for name in names:
        target = folder/'code'/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((src/name).read_bytes())
        implementation.append(file_record(home, target, 'plan_report_implementation'))
    from report_figures import _font
    fonts = []
    for bold in (False, True):
        path = Path(_font(20, bold).path); content = path.read_bytes()
        fonts.append({'name': path.name, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
    source = {'schema_version': VERSION, 'study_id': payload['study_id'], 'payload_hash': fingerprint(payload),
              'run_ids': deepcopy(payload['run_ids']), 'figures': figures, 'files': files,
              'implementation_files': implementation, 'render_fonts': fonts, 'human_review_written': False}
    path = folder/'figures.json'; write_json(path, source)
    output = deepcopy(payload); output['figures'] = figures
    output['figure_source'] = file_record(home, path, 'plan_report_figure_index')
    return output


def validate(home, payload, base):
    """核查图像索引、来源和完整分支数量；正文和概览必须有不同明确角色。"""
    value = read_json(verified_file(home, payload['figure_source']))
    require(value.get('schema_version') == VERSION and value.get('study_id') == base['study_id']
            and value.get('payload_hash') == fingerprint(base) and value.get('run_ids') == base['run_ids']
            and value.get('human_review_written') is False, '报告图件不是同批实际第二版来源')
    require(value['figures'] == payload['figures'] and value['implementation_files'], '报告图件或实现索引不同')
    for ref in value['files'] + value['implementation_files']:
        verified_file(home, ref)
    required = {'A03': 1, 'A04': 2 if base.get('network') else 0,
                'A05': sum(row['included'] for row in (base.get('enrichment') or {}).get('groups', [])), 'A06': 0}
    if base.get('docking'):
        facts = base['docking']
        required['A06'] = ((len(facts['compounds'])+19)//20)*((len(facts['receptors'])+7)//8)
    require(all(sum(row['module'] == module for row in value['figures']) == count for module, count in required.items())
            and all(row['module'] in required for row in value['figures']), '报告图件缺少适用范围或包含额外分支')
    for row in value['figures']:
        require(row['record'] in value['files'], '报告图件未登记到本批索引')
        if row['module'] == 'A04':
            require(row['scope_hash'] == fingerprint(base['network']), '报告PPI范围与本批原选择不同')
    if base.get('network'):
        require({row.get('role') for row in value['figures'] if row['module'] == 'A04'}
                == {'degree_round2', 'full_network_overview'}, 'PPI正文和概览角色混淆')
    return value
