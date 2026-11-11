"""独立救援结果展示与图表导出；完整名单、原始评分和NA原因只读保留。"""
from collections import Counter
from copy import deepcopy
import csv
from html import escape
import math
import os
from pathlib import Path
import unicodedata

from contracts import require
from storage import file_record, write_json
from .matrix_palette import text_color

SCIENCE_VERSION = 'A06.system_rescue.1'
VERSION = 'A06.system_rescue.display.1'
STATE_ZH = {'completed': '已评分', 'failed': '评分失败', 'NA': '准备NA'}
SOURCE_ZH = {'original': '沿用原评分', 'rescue': '本轮补救评分'}
COLOUR_NOTE = '色标取完整同批有效评分；越负越红，越不负越蓝；NA白底虚线，不设通用结合能阈值。'
SCOPE_NOTE = '保留全部固定成分记录与受体；来源记录不等同独立结构。严格与探索按逐组合归档类别解释，评分不能直接证明药效。'
REVIEW_NOTE = '本轮新A06结果须独立人工复核；图表生成不代表复核通过。'


def _selected(rows, key, selected):
    """只按原顺序裁切显示，默认使用全部身份，不沿用旧8×8默认值。"""
    ids = [row[key] for row in rows]
    chosen = ids if selected is None else selected
    require(isinstance(chosen, list) and chosen and all(isinstance(item, str) for item in chosen)
            and len(set(chosen)) == len(chosen) and set(chosen) <= set(ids), '显示范围包含未知、重复或空对象')
    return [deepcopy(row) for row in rows if row[key] in chosen]


def _label_rows(rows, key, name_key):
    """同名条目保留独立身份，以不冲突的短编号区分标签。"""
    counts = Counter(row[name_key] for row in rows)
    ids = [row[key] for row in rows]
    for row in rows:
        identity = row[key]
        length = min(8, len(identity))
        while length < len(identity) and sum(item.endswith(identity[-length:]) for item in ids) > 1:
            length += 1
        row['label'] = row[name_key] + (f' [{identity[-length:]}]' if counts[row[name_key]] > 1 else '')
    return rows


def _shade(value, low, high):
    """沿已确认的红蓝平滑色带格式化颜色，独立于科学计算与评分阈值。"""
    ratio = .5 if low == high else (value - low) / (high - low)
    if ratio <= .5:
        local, start, end = ratio * 2, (178, 24, 43), (239, 169, 174)
    elif ratio <= .56:
        local, start, end = (ratio - .5) / .06, (239, 169, 174), (164, 199, 224)
    else:
        local, start, end = (ratio - .56) / .44, (164, 199, 224), (33, 102, 172)
    local = local * local * (3 - 2 * local)
    return '#' + ''.join(f'{round(a + (b - a) * local):02X}' for a, b in zip(start, end))


def _wrapped(value, width=48):
    """按中英文实际字宽近似换行，避免中文长名称越过左侧画布。"""
    lines, current, units = [], '', 0
    for character in str(value):
        size = 2 if unicodedata.east_asian_width(character) in ('W', 'F') else 1
        if character == '\n' or units + size > width:
            if current:
                lines.append(current)
            current, units = '', 0
        if character != '\n':
            current += character
            units += size
    if current:
        lines.append(current)
    return lines or ['']


def build_view(packet, *, selected_compounds=None, selected_targets=None):
    """只接受救援协议，从同批固定名称建立完整矩阵与可选焦点子图。"""
    require(packet.get('schema_version') == SCIENCE_VERSION, '不支持的受体补救结果协议')
    fixed = packet['source_fixed']
    compounds, targets = packet['compounds'], packet['receptors']
    cids = [row['compound_id'] for row in compounds]
    tids = [row['target_id'] for row in targets]
    require(cids and tids and all(isinstance(i, str) and i for i in cids + tids)
            and len(set(cids)) == len(cids) and len(set(tids)) == len(tids), '固定对象身份缺失或重复')
    require(cids == [row['compound_id'] for row in fixed['compounds']]
            and tids == [row['target_id'] for row in fixed['receptors']], '补救展示与固定范围或顺序不同')
    rows = []
    for source in fixed['compounds']:
        en = source.get('name_en') or source.get('name') or source['compound_id']
        zh = source.get('name_zh') or ''
        rows.append({'compound_id': source['compound_id'], 'name_en': en, 'name_zh': zh, 'name': zh or en})
    rows = _label_rows(rows, 'compound_id', 'name')
    columns = _label_rows([{'target_id': row['target_id'], 'symbol': row.get('symbol') or row['target_id'],
                          'quality': row.get('quality', ''), 'candidate_grade': row.get('candidate_grade', '')}
                         for row in fixed['receptors']], 'target_id', 'symbol')
    lookup = {(row['compound_id'], row['target_id']): row for row in packet['pairs']}
    require(len(lookup) == len(packet['pairs']) and set(lookup) == {(c, t) for c in cids for t in tids},
            '受体补救评分不是完整唯一矩阵')
    values = []
    for pair in lookup.values():
        require(pair['state'] in STATE_ZH, '未知补救评分状态')
        if pair['state'] == 'completed':
            require(type(pair.get('score')) in (int, float) and math.isfinite(pair['score']), '有效评分非法')
            values.append(pair['score'])
        else:
            require(pair.get('score') is None and isinstance(pair.get('reason_zh'), str) and pair['reason_zh'].strip(),
                    'NA和失败组合必须保留空评分及原因')
    low, high = (min(values), max(values)) if values else (None, None)

    def part(cs, rs):
        """所有子图复用完整同批色标与原格子，不重新排序或计算评分。"""
        cells = []
        for compound in cs:
            line = []
            for receptor in rs:
                pair = lookup[(compound['compound_id'], receptor['target_id'])]
                score = pair['score']
                shade = _shade(score, low, high) if score is not None else '#FFFFFF'
                line.append({'compound_id': compound['compound_id'], 'target_id': receptor['target_id'],
                             'score': score, 'score_text': str(score) if score is not None else 'NA',
                             'display_score': f'{score:.2f}' if score is not None else 'NA',
                             'state': pair['state'], 'state_zh': pair.get('state_zh') or STATE_ZH[pair['state']],
                             'quality': pair.get('quality', ''), 'reason_zh': pair.get('reason_zh', ''),
                             'source_kind': pair.get('source_kind', ''),
                             'source_zh': SOURCE_ZH.get(pair.get('source_kind'), '来源类别未登记'),
                             'color': shade, 'text_color': text_color(shade), 'downloads': []})
            cells.append(line)
        return {'rows': deepcopy(cs), 'columns': deepcopy(rs), 'cells': cells}

    completed = [pair for pair in packet['pairs'] if pair['state'] == 'completed']
    return {'schema_version': VERSION, 'science_version': SCIENCE_VERSION, 'read_only': True,
            'study_id': packet['study_id'], 'run_id': packet['run_id'], 'score_range': [low, high],
            'unit': 'kcal/mol', 'colour_note_zh': COLOUR_NOTE, 'scope_note_zh': SCOPE_NOTE,
            'review_note_zh': REVIEW_NOTE, 'summary': deepcopy(packet['summary']),
            'table': part(rows, columns),
            'heatmap': part(_selected(rows, 'compound_id', selected_compounds), _selected(columns, 'target_id', selected_targets)),
            'initial_focus': {'compound_ids': [cid for cid in cids if any(p['compound_id'] == cid for p in completed)],
                              'target_ids': [tid for tid in tids if any(p['target_id'] == tid for p in completed)]}}


def _drawing(view, *, full):
    """SVG和PNG共用布局，长标签换行且完整矩阵的NA行列不消失。"""
    part = view['table' if full else 'heatmap']
    labels = []
    for row in part['rows']:
        lines = _wrapped(row['label'])
        if row['name_zh'] and row['name_en'] != row['name_zh']:
            lines += _wrapped(row['name_en'])
        labels.append(lines)
    rh = max(58, max(len(lines) for lines in labels) * 16 + 18)
    left, top, cw = 350, 90, 76
    width, height = left + cw * len(part['columns']) + 120, top + rh * len(labels) + 100
    items = []

    def text(x, y, value, size=12, anchor='start', fill='#10253C'):
        """记录文字，保持两种格式完全一致。"""
        items.append(('text', x, y, str(value), size, anchor, fill))

    def rect(x, y, w, h, fill, dashed=False, title=''):
        """记录格子与NA虚线边框，SVG可悬停核对原值。"""
        items.append(('rect', x, y, w, h, fill, dashed, title))

    text(width / 2, 28, ('完整' if full else '焦点') + f"结合能热图 {len(labels)}×{len(part['columns'])}", 20, 'middle')
    text(width / 2, 50, '原评分与本轮补救合并展示；固定范围保留，结果须独立复核', 12, 'middle')
    for j, receptor in enumerate(part['columns']):
        text(left + (j + .5) * cw, 76, receptor['label'], 11, 'middle')
    for i, (row, lines) in enumerate(zip(part['rows'], labels)):
        first = top + i * rh + (rh - 16 * len(lines)) / 2 + 12
        for k, line in enumerate(lines):
            text(left - 12, first + 16 * k, line, 12 if k == 0 else 10, 'end')
        for j, cell in enumerate(part['cells'][i]):
            x, y = left + j * cw, top + i * rh
            title = f"{cell['compound_id']} × {cell['target_id']}：{cell['score_text']}；{cell['source_zh']}；{cell['quality']}；{cell['reason_zh']}"
            rect(x, y, cw - 1, rh - 1, cell['color'], cell['score'] is None, title)
            text(x + (cw - 1) / 2, y + rh / 2 + 4, cell['display_score'], 12, 'middle', cell['text_color'])
    low, high = view['score_range']
    plot_height = rh * len(labels)
    if low is not None:
        bx = left + cw * len(part['columns']) + 23
        for p in range(plot_height):
            rect(bx, top + p, 17, 1, _shade(high - (high - low) * p / max(1, plot_height - 1), low, high))
        text(bx + 8, top - 16, 'kcal/mol', 11, 'middle')
        for k in range(5):
            text(bx + 24, top + 4 + (plot_height - 7) * k / 4, f'{high - (high - low) * k / 4:.2f}', 10)
    bottom = top + plot_height
    text(18, bottom + 25, view['colour_note_zh'], 11)
    text(18, bottom + 47, '固定范围的全部NA及失败原因、来源类别与原始评分精度见完整CSV；同名条目按短编号区分。', 11)
    text(18, bottom + 69, '严格与探索沿用逐组合归档类别；探索评分不等同严格验证，评分不能直接证明药效。', 11)
    return {'width': width, 'height': height}, items


def heatmap_svg(view, *, full=True):
    """生成可编辑文字SVG，所有文字转义，NA以白底和虚线明确标注。"""
    geometry, items = _drawing(view, full=full)
    width, height = geometry['width'], geometry['height']
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>']
    for item in items:
        if item[0] == 'rect':
            _, x, y, w, h, fill, dashed, title = item
            outline = ' stroke="#8C969E" stroke-dasharray="4 4"' if dashed else ''
            pieces.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"{outline}><title>{escape(title)}</title></rect>')
        else:
            _, x, y, value, size, anchor, fill = item
            pieces.append(f'<text x="{x}" y="{y}" font-family="Microsoft YaHei,Arial,sans-serif" font-size="{size}" text-anchor="{anchor}" fill="{fill}">{escape(value)}</text>')
    return ''.join(pieces) + '</svg>'


def _png(view, path, *, full, font_path):
    """仅在科学子进程延迟加载Pillow绘制PNG，不向HTTP进程引入依赖。"""
    from PIL import Image, ImageDraw, ImageFont
    geometry, items = _drawing(view, full=full)
    scale = 2
    image = Image.new('RGB', (geometry['width'] * scale, geometry['height'] * scale), 'white')
    draw, fonts = ImageDraw.Draw(image), {}
    for item in items:
        if item[0] == 'rect':
            _, x, y, w, h, fill, dashed, _ = item
            box = tuple(round(value * scale) for value in (x, y, x + w, y + h))
            draw.rectangle(box, fill=fill)
            if dashed:
                for start in range(0, round(w * scale), 8 * scale):
                    for edge in (box[1], box[3]):
                        draw.line((box[0] + start, edge, min(box[0] + start + 4 * scale, box[2]), edge), fill='#8C969E', width=scale)
                for start in range(0, round(h * scale), 8 * scale):
                    for edge in (box[0], box[2]):
                        draw.line((edge, box[1] + start, edge, min(box[1] + start + 4 * scale, box[3])), fill='#8C969E', width=scale)
        else:
            _, x, y, value, size, anchor, fill = item
            if size not in fonts:
                fonts[size] = ImageFont.truetype(str(font_path), size * scale)
            draw.text((x * scale, y * scale), value, font=fonts[size], fill=fill,
                      anchor={'start': 'ls', 'middle': 'ms', 'end': 'rs'}[anchor])
    image.save(path, dpi=(192, 192))


def export(root, packet, folder, *, font_path=None):
    """在新目录生成完整及成功对象焦点PNG/SVG、原始精度CSV和展示事实包。"""
    view = build_view(packet)
    folder = Path(folder)
    planned = ['A06_完整结合能热图.png', 'A06_完整结合能热图.svg', 'A06_完整评分明细.csv', 'A06_补救展示.json']
    focus = view['initial_focus']
    if focus['compound_ids'] and focus['target_ids']:
        planned += ['A06_焦点结合能热图.png', 'A06_焦点结合能热图.svg']
    require(not any((folder / name).exists() for name in planned), '禁止覆盖已有补救图表，请使用独立导出目录')
    font = Path(font_path or Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc')
    require(font.is_file(), '请配置可用的中文绘图字体')
    folder.mkdir(parents=True, exist_ok=True)
    figures = []
    drawings = [('完整', 'full', view, True)]
    if focus['compound_ids'] and focus['target_ids']:
        focused = build_view(packet, selected_compounds=focus['compound_ids'], selected_targets=focus['target_ids'])
        drawings.append(('焦点', 'focus', focused, False))
    for label, role, drawing, full in drawings:
        png, svg = folder / f'A06_{label}结合能热图.png', folder / f'A06_{label}结合能热图.svg'
        svg.write_text(heatmap_svg(drawing, full=full), encoding='utf-8')
        _png(drawing, png, full=full, font_path=font)
        figures += [file_record(root, png, f'plot_a06_rescue_{role}_png'), file_record(root, svg, f'plot_a06_rescue_{role}_svg')]
    csv_path = folder / 'A06_完整评分明细.csv'
    fields = ['compound_id', 'compound_name', 'name_zh', 'name_en', 'target_id', 'symbol', 'state', 'state_zh',
              'score', 'quality', 'source_kind', 'source_zh', 'reason_zh']
    with csv_path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for compound, line in zip(view['table']['rows'], view['table']['cells']):
            for receptor, cell in zip(view['table']['columns'], line):
                row = {**compound, **receptor, **cell}
                row.update(compound_name=compound['label'], score=cell['score_text'])
                writer.writerow({key: row[key] for key in fields})
    json_path = folder / 'A06_补救展示.json'
    write_json(json_path, view)
    return figures, [file_record(root, csv_path, 'a06_rescue_matrix_csv'), file_record(root, json_path, 'a06_rescue_display_view')]
