"""独立救援名称展示修订：复用原几何、原评分，名称依据由外层归档核验。"""
from copy import deepcopy
import csv
import os
from pathlib import Path
import re
from types import FunctionType

from contracts import require, safe_id
from storage import file_record, write_json
from modulea.core.rescue_presentation_names import chinese_name
from . import system_rescue_display as original
from . import system_rescue_display_v2 as second

VERSION = 'A06.system_rescue.display.3'
SCOPES = {
    'prepared_identity_translation': '中文名按本批已准备身份核对，不改变评分或结构。',
    'source_term_translation_only': '仅翻译原来源术语，不是结构身份确认；本批原NA和未评分状态保持。',
    'original_proper_name': '仅保留经明确允许的原来源专名，不计为已核中文译名；结构身份未核实，本批未评分。',
}


def _name_rows(packet, names, allowed_original_names):
    """检查精确原名和准备身份；此函数不代替公开Workflow核验证据文件及用户决定。"""
    fixed = packet['source_fixed']['compounds']
    ids = [row['compound_id'] for row in fixed]
    require(isinstance(names, list) and [row['compound_id'] for row in names] == ids,
            '名称修订必须覆盖同批全部稳定对象并保持原顺序')
    prepared = {row['compound_id']: row for row in packet['compounds']}
    allowed = set(allowed_original_names or ())
    require(allowed <= set(ids), '原专名允许范围包含未知对象')
    rows = []
    for source, item in zip(fixed, names):
        cid = source['compound_id']
        en = source.get('name_en') or source.get('name') or cid
        require(item.get('source_name') == en and item.get('scope') in SCOPES,
                '名称修订原文或范围不同')
        evidence = item.get('evidence')
        require(isinstance(evidence, list) and evidence and all(isinstance(ref, dict)
                and isinstance(ref.get('path'), str) and ref['path']
                and type(ref.get('bytes')) is int and ref['bytes'] > 0
                and isinstance(ref.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', ref['sha256'])
                for ref in evidence) and isinstance(item.get('translation_basis'), str)
                and item['translation_basis'].strip(), '名称修订缺少证据引用或核译依据')
        identity = item.get('identity', {})
        scope = item['scope']
        if scope == 'prepared_identity_translation':
            number = prepared[cid].get('cid')
            require(prepared[cid].get('state') == 'ready' and type(number) is int and number > 0
                    and identity == {'scheme': 'PubChem', 'id': str(number)},
                    '名称修订CID与本批已准备身份不同')
        else:
            require(prepared[cid].get('state') == 'NA' and all(row['state'] == 'NA' and row['score'] is None
                    for row in packet['pairs'] if row['compound_id'] == cid),
                    '原术语或原专名说明只能用于本批未准备、未评分对象')
            require(identity.get('scheme') == 'HERB' and isinstance(identity.get('id'), str)
                    and re.fullmatch(r'HBIN\d+', identity['id']), '原术语缺少明确来源稳定编号')
        zh = chinese_name(item.get('display_name_zh'))
        if scope == 'original_proper_name':
            require(cid in allowed and not item.get('display_name_zh'), '原专名未明确允许或冒充中文核译')
        else:
            require(zh, '名称修订缺少可核中文或包含占位文字')
        rows.append({'compound_id': cid, 'name_en': en, 'name_zh': zh, 'name': zh or en,
                     'name_scope': scope, 'name_scope_note_zh': SCOPES[scope]})
    original._label_rows(rows, 'compound_id', 'name')
    for row in rows:
        if row['name_scope'] == 'source_term_translation_only':
            row['label'] += '〔仅来源术语译名〕'
        elif row['name_scope'] == 'original_proper_name':
            row['label'] += '〔原来源专名〕'
    return rows


def build_view(packet, names, *, allowed_original_names=None, selected_compounds=None, selected_targets=None):
    """从原科学包建立新展示，再按稳定ID加双语标签，不替换source_fixed或原评分。"""
    version = packet.get('schema_version')
    require(version in (original.SCIENCE_VERSION, second.SCIENCE_VERSION), '名称修订不支持该科学协议')
    builder = second.build_view if version == second.SCIENCE_VERSION else original.build_view
    view = builder(packet, selected_compounds=selected_compounds, selected_targets=selected_targets)
    rows = _name_rows(packet, names, allowed_original_names)
    lookup = {row['compound_id']: row for row in rows}
    for matrix in (view['table'], view['heatmap']):
        matrix['rows'] = [deepcopy(lookup[row['compound_id']]) for row in matrix['rows']]
    view['schema_version'] = VERSION
    view['name_records'] = deepcopy(names)
    view['allowed_original_name_ids'] = sorted(allowed_original_names or ())
    view['name_counts'] = {'chinese': sum(bool(row['name_zh']) for row in rows),
                           'source_term_only': sum(row['name_scope'] == 'source_term_translation_only' for row in rows),
                           'original_proper_name': sum(row['name_scope'] == 'original_proper_name' for row in rows)}
    view['scope_note_zh'] += ' 名称修订只改变展示；原来源术语译名和保留专名均不代表结构身份核实。'
    return view


def _renderer(science_version):
    """只为本次调用复制冻结几何函数的命名空间，不修改原模块globals或版本。"""
    require(science_version in (original.SCIENCE_VERSION, second.SCIENCE_VERSION), '名称修订科学版本错误')
    namespace = dict(vars(original), VERSION=VERSION, SCIENCE_VERSION=science_version)
    for name in ('_drawing', 'heatmap_svg', '_png'):
        source = getattr(original, name)
        clone = FunctionType(source.__code__, namespace, source.__name__, source.__defaults__, source.__closure__)
        clone.__kwdefaults__ = deepcopy(source.__kwdefaults__)
        namespace[name] = clone
    base_drawing = namespace['_drawing']
    def scoped_drawing(view, *, full):
        """在原画布下追加范围说明，使脱离CSV的独立PNG/SVG也不误称身份已核。"""
        geometry, items = base_drawing(view, full=full)
        scopes = {row['name_scope'] for row in view['table' if full else 'heatmap']['rows']}
        notes = [SCOPES[key] for key in ('source_term_translation_only', 'original_proper_name') if key in scopes]
        lines = [line for note in notes for line in original._wrapped(note, max(24, (geometry['width'] - 36) // 6))]
        for index, line in enumerate(lines):
            items.append(('text', 18, geometry['height'] + 18 + index * 20, line, 11, 'start', '#28323C'))
        if lines:
            geometry['height'] += len(lines) * 20 + 10
        return geometry, items
    namespace['_drawing'] = scoped_drawing
    return namespace


def heatmap_svg(view, *, full=True):
    """SVG保持原布局，逐行明确术语译名／原专名范围。"""
    require(view.get('schema_version') == VERSION, '名称展示协议错误')
    return _renderer(view['science_version'])['heatmap_svg'](view, full=full)


def export(root, packet, names, folder, *, font_path=None, allowed_original_names=None):
    """在本运行独立修订目录追加图CSV和名称证据，不覆盖科学结果中的历史附件。"""
    root, folder = Path(root).resolve(), Path(folder).resolve()
    safe_id(packet['run_id'], 'run')
    safe_id(folder.name, 'rescueview')
    require(folder.parent == (root / 'runs/A06' / packet['run_id'] / 'rescue/presentations').resolve()
            and folder.is_relative_to(root), '名称修订导出目录不属于本运行')
    view = build_view(packet, names, allowed_original_names=allowed_original_names)
    focus = view['initial_focus']
    drawings = [('完整', 'full', view, True)]
    if focus['compound_ids'] and focus['target_ids']:
        selected = build_view(packet, names, allowed_original_names=allowed_original_names,
                              selected_compounds=focus['compound_ids'], selected_targets=focus['target_ids'])
        drawings.append(('焦点', 'focus', selected, False))
    planned = ['A06_完整评分明细.csv', 'A06_补救展示.json', 'A06_名称证据.json']
    planned += [f'A06_{label}结合能热图.{extension}' for label, _, _, _ in drawings for extension in ('png', 'svg')]
    require(not any((folder / name).exists() for name in planned), '禁止覆盖已有名称展示修订附件')
    font = Path(font_path or Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc')
    require(font.is_file(), '请配置可用的中文绘图字体')
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir(exist_ok=False)
    except FileExistsError:
        require(False, '名称修订目录已存在，禁止并发覆盖，请使用独立修订目录')
    figures = []
    for label, role, drawing, full in drawings:
        png, svg = folder / f'A06_{label}结合能热图.png', folder / f'A06_{label}结合能热图.svg'
        svg.write_text(heatmap_svg(drawing, full=full), encoding='utf-8')
        _renderer(drawing['science_version'])['_png'](drawing, png, full=full, font_path=font)
        figures += [file_record(root, png, f'plot_a06_rescue_{role}_png'), file_record(root, svg, f'plot_a06_rescue_{role}_svg')]
    csv_path = folder / 'A06_完整评分明细.csv'
    fields = ['compound_id', 'compound_name', 'name_zh', 'name_en', 'name_scope', 'name_scope_note_zh',
              'target_id', 'symbol', 'state', 'state_zh', 'score', 'quality', 'source_kind', 'source_zh', 'reason_zh']
    with csv_path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for compound, line in zip(view['table']['rows'], view['table']['cells']):
            for receptor, cell in zip(view['table']['columns'], line):
                row = {**compound, **receptor, **cell, 'compound_name': compound['label'], 'score': cell['score_text']}
                writer.writerow({key: row[key] for key in fields})
    view_path, names_path = folder / 'A06_补救展示.json', folder / 'A06_名称证据.json'
    write_json(view_path, view)
    write_json(names_path, {'schema_version': 'ModuleA.rescue_presentation_names.1',
               'study_id': packet['study_id'], 'run_id': packet['run_id'], 'names': deepcopy(names),
               'allowed_original_name_ids': view['allowed_original_name_ids'], 'counts': view['name_counts']})
    return figures, [file_record(root, csv_path, 'a06_rescue_matrix_csv'),
                     file_record(root, view_path, 'a06_rescue_display_view'),
                     file_record(root, names_path, 'a06_rescue_name_evidence')]
