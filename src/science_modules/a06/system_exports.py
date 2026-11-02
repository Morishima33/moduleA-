"""系统评分与全NA准备的同源导出适配；复用旧图表/Excel排版，不重算科学结果。"""
from copy import deepcopy
import math
from pathlib import Path
from types import FunctionType

from contracts import require
from . import automatic_exports as legacy
from . import matrix_palette

VERSION = 'A06.system_exports.1'
SCORING = ('A06.system_scoring.1', 'A06.system_scoring.2')
PREPARATION = ('A06.system_preparation.1', 'A06.system_preparation.2', 'A06.system_qualification.1', 'A06.system_qualification.2')


def renderer():
    """独立命名空间绑定新展示版本；旧自动展示协议、函数和全局状态不变。"""
    context = dict(vars(legacy), VERSION=VERSION)
    for name in ('validate_view', '_drawing', 'heatmap_svg', 'export'):
        original = getattr(legacy, name)
        value = FunctionType(original.__code__, context, original.__name__, original.__defaults__, original.__closure__)
        value.__kwdefaults__ = deepcopy(original.__kwdefaults__); context[name] = value
    return context


def build_view(run, result, packet):
    """保留固定对象顺序、原始浮点数、NA/失败及原因；未执行评分的ready不能冒充NA。"""
    version = run['config'].get('version'); scoring = version in SCORING
    require(version in SCORING + PREPARATION and result['run_id'] == run['run_id']
            and result['study_id'] == run['study_id'] and result['summary']['input_key'] == packet['input_key'], '系统导出来源版本或固定范围不同')
    rows = [{'compound_id': row['compound_id'], 'name_en': row.get('name_en') or row.get('name') or row['compound_id'],
             'name_zh': row.get('name_zh') or '', 'name': row.get('name') or row['compound_id'], 'name_evidence': []}
            for row in packet['compounds']]
    columns = [{'target_id': row['target_id'], 'symbol': row.get('symbol') or row['target_id'],
                'candidate_grade': row.get('candidate_grade') or row.get('grade') or '', 'quality_zh': row.get('quality') or ''}
               for row in packet['receptors']]
    require(rows and columns and len({r['compound_id'] for r in rows}) == len(rows)
            and len({r['target_id'] for r in columns}) == len(columns), '系统导出对象为空或身份重复')
    pairs = result['tables']['plan_scoring_pairs' if scoring else 'planned_pairs']
    expected = [(c['compound_id'], r['target_id']) for c in rows for r in columns]
    require(len(pairs) == len(expected) and [(r['compound_id'], r['target_id']) for r in pairs] == expected,
            '系统导出必须为本批原顺序完整唯一矩阵')
    for pair in pairs:
        require(pair['state'] in (('completed', 'failed', 'NA') if scoring else ('NA',)), '尚有未执行评分的可用组合，不能冒充准备NA导出')
        valid = pair['state'] == 'completed'
        require((valid and type(pair['score']) in (int, float) and math.isfinite(pair['score']))
                or (not valid and pair['score'] is None and bool(pair['reason_zh'])), '导出原评分非法或缺失原因')
    values = [r['score'] for r in pairs if r['state'] == 'completed']; low, high = (min(values), max(values)) if values else (None, None)
    lookup = {(r['compound_id'], r['target_id']): r for r in pairs}
    def part(cs, rs):
        """完整矩阵与重点图共用原值和完整同批色标，不改变科学范围。"""
        cells = []
        for c in cs:
            line = []
            for r in rs:
                source = lookup[(c['compound_id'], r['target_id'])]; score = source['score']
                shade = matrix_palette.color(score, low, high, matrix_palette.RED_BLUE) if score is not None else '#FFFFFF'
                line.append({'compound_id': c['compound_id'], 'target_id': r['target_id'], 'state': source['state'],
                    'score': score, 'quality': source.get('quality') or '', 'reason_zh': source['reason_zh'],
                    'color': shade, 'text_color': matrix_palette.text_color(shade),
                    'display_score': f'{score:.2f}' if score is not None else 'NA',
                    'threshold_mark': '**' if score is not None and score <= -8 else ''})
            cells.append(line)
        return {'rows': deepcopy(cs), 'columns': deepcopy(rs), 'cells': cells}
    view = {'schema_version': VERSION, 'display_version': VERSION, 'ready': True, 'study_id': run['study_id'],
        'run_id': run['run_id'], 'packet_id': packet['input_key'], 'science_version': version,
        'palette': dict(deepcopy(matrix_palette.RED_BLUE), na_color='#FFFFFF'), 'score_range': [low, high],
        'table': part(rows, columns), 'heatmap': part(rows[:8], columns[:8]), 'summary': deepcopy(result['summary']),
        'threshold_note_zh': '原始Vina评分≤−8 kcal/mol附**，不代表统计显著性；单元格显示两位小数，原始数值未舍入。',
        'scope_note_zh': f"本批{len(rows)}成分×{len(columns)}受体；{run['module_id']}运行{run['run_id']}。A/B为候选梯队，NA与失败保留，不直接证明药效；导出不签署人工复核。"}
    return renderer()['validate_view'](view)


def implementation_files():
    """固定导出适配和复用排版实现，不将旧科学运行配置原地扩展。"""
    return [Path(__file__), Path(legacy.__file__), Path(matrix_palette.__file__)]


def export(view, folder):
    """后台复用既有PNG/SVG/CSV/Excel生成器，工作簿文本按原字符串保存，不执行公式。"""
    from openpyxl import load_workbook
    files = renderer()['export'](view, folder)
    # 科学名称/原因属于文本，不应被Excel按等号开头解析成公式。
    book = load_workbook(files['xlsx'])
    for sheet in book:
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str) and cell.data_type == 'f': cell.data_type = 's'
        sheet.sheet_view.showGridLines = False
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = 'landscape'; sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1; sheet.page_setup.fitToHeight = 0
        sheet.print_options.horizontalCentered = True
    book.save(files['xlsx']); book.close()
    validate_files(view, files)
    return files


def validate_files(view, files):
    """从实际Excel/CSV回读完整原值、顺序和NA；检查标签文本、数值精度及显示标记。"""
    import csv
    from openpyxl import load_workbook
    expected = [dict(c) | r | cell for c, line in zip(view['table']['rows'], view['table']['cells'])
                for r, cell in zip(view['table']['columns'], line)]
    with Path(files['csv']).open(encoding='utf-8-sig', newline='') as stream: actual = list(csv.DictReader(stream))
    require(len(actual) == len(expected), '导出CSV漏组合')
    for row, source in zip(actual, expected):
        require(all(row[key] == str(source[key]) for key in ('compound_id', 'target_id', 'state', 'reason_zh'))
                and (float(row['score']) == source['score'] if source['score'] is not None else row['score'] == ''), '导出CSV与原组合或原始评分不同')
    book = load_workbook(files['xlsx'], data_only=False); matrix = book['完整评分矩阵']; detail = book['原始评分与异常']
    require(matrix.max_column == len(view['table']['columns']) + 2 and detail.max_row == len(expected) + 1, 'Excel矩阵或明细范围不完整')
    for i, (row, line) in enumerate(zip(view['table']['rows'], view['table']['cells']), 2):
        require((matrix.cell(i, 1).value or '') == row['name_zh'] and matrix.cell(i, 2).value == row['name_en'], 'Excel成分标签不同')
        for j, source in enumerate(line, 3):
            cell = matrix.cell(i, j); require(cell.value == (source['score'] if source['score'] is not None else 'NA'), 'Excel评分值或NA被改变')
            require(cell.number_format == ('0.00"**"' if source['threshold_mark'] else '0.00'), 'Excel原始阈值标记不同')
    require(not any(cell.data_type == 'f' for sheet in book for row in sheet for cell in row), '原名称或原因不能作为Excel公式执行')
    book.close()
    return True
