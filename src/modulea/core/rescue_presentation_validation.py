"""独立补救展示按原评分、同批名称证据和原范围复核图CSV；只读且仅用标准库。"""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path

from contracts import fingerprint, require
from .bounded_evidence import verified_file
from .png_integrity import png_size
from .read_evidence import current_evidence


def validate_files(home, packet, names, allowed, files):
    """拒缺件和仅重登记新SHA的错误内容；PNG/SVG/CSV/JSON必须来自同一展示。"""
    from science_modules.a06 import system_rescue_presentation as render
    home = Path(home)
    evidence = current_evidence(home.parent.parent)
    view = render.build_view(packet, names, allowed_original_names=allowed)
    expected = {'a06_rescue_display_view', 'a06_rescue_matrix_csv', 'a06_rescue_name_evidence',
                'plot_a06_rescue_full_png', 'plot_a06_rescue_full_svg'}
    focus = view['initial_focus']
    if focus['compound_ids'] and focus['target_ids']:
        expected |= {'plot_a06_rescue_focus_png', 'plot_a06_rescue_focus_svg'}
    require(len(files) == len(expected) and {ref.get('role') for ref in files} == expected
            and len({ref['path'] for ref in files}) == len(files)
            and len({str(Path(ref['path']).parent) for ref in files}) == 1, '名称展示缺少完整同次图表或角色冲突')
    raw = {}
    for ref in files:
        path = evidence.reader.verify(home, ref) if evidence else verified_file(home, ref)
        data = path.read_bytes()
        require(len(data) == ref['bytes'] and sha256(data).hexdigest() == ref['sha256'], '名称图表读取期间原件变化')
        raw[ref['role']] = data
    require(fingerprint(json.loads(raw['a06_rescue_display_view'])) == fingerprint(view), '名称展示JSON与原评分或本批名称不同')
    expected_names = {'schema_version': 'ModuleA.rescue_presentation_names.1', 'study_id': packet['study_id'],
                      'run_id': packet['run_id'], 'names': names, 'allowed_original_name_ids': view['allowed_original_name_ids'],
                      'counts': view['name_counts']}
    require(fingerprint(json.loads(raw['a06_rescue_name_evidence'])) == fingerprint(expected_names), '名称证据或专名允许范围不同')
    rows = list(csv.DictReader(io.StringIO(raw['a06_rescue_matrix_csv'].decode('utf-8-sig'))))
    flat = [(compound, target, cell) for compound, line in zip(view['table']['rows'], view['table']['cells'])
            for target, cell in zip(view['table']['columns'], line)]
    fields = {'compound_id', 'compound_name', 'name_zh', 'name_en', 'name_scope', 'name_scope_note_zh',
              'target_id', 'symbol', 'state', 'state_zh', 'score', 'quality', 'source_kind', 'source_zh', 'reason_zh'}
    require(len(rows) == len(flat) and all(set(row) == fields for row in rows), '名称CSV缺少原完整矩阵或字段')
    for row, (compound, target, cell) in zip(rows, flat):
        wanted = {**compound, **target, **cell, 'compound_name': compound['label'], 'score': cell['score_text']}
        require(all(row[key] == ('' if wanted[key] is None else str(wanted[key])) for key in fields),
                '名称CSV的顺序、评分、身份范围或NA说明不同')
    views = [('full', view, True)]
    if 'plot_a06_rescue_focus_svg' in expected:
        focused = render.build_view(packet, names, allowed_original_names=allowed,
            selected_compounds=focus['compound_ids'], selected_targets=focus['target_ids'])
        views.append(('focus', focused, False))
    for role, selected, full in views:
        require(raw['plot_a06_rescue_' + role + '_svg'] == render.heatmap_svg(selected, full=full).encode('utf-8'),
                '名称SVG与同批矩阵、焦点或范围说明不同')
        geometry, _ = render._renderer(view['science_version'])['_drawing'](selected, full=full)
        require(png_size(raw['plot_a06_rescue_' + role + '_png']) == [geometry['width'] * 2, geometry['height'] * 2],
                '名称PNG尺寸与同批完整或焦点图不同')
    return view
