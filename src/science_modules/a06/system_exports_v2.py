"""系统同批导出第二版：只修复Excel列宽与说明裁切，第一版实现和原始数值保持。"""
from copy import deepcopy
import math
from pathlib import Path
from types import FunctionType

from . import system_exports as original

VERSION = 'A06.system_exports.2'


def renderer():
    """独立显示命名空间，不修改第一版或旧自动流程的全局状态。"""
    context = original.renderer()
    context['VERSION'] = VERSION
    return context


def build_view(run, result, packet):
    """固定原范围、顺序、分数和NA；这里只声明独立导出排版版本。"""
    view = original.build_view(run, result, packet)
    view.update(schema_version=VERSION, display_version=VERSION)
    return renderer()['validate_view'](view)


def implementation_files():
    """新排版和所有复用生成器共同归档，便于同请求精确恢复。"""
    return [Path(__file__), *original.implementation_files()]


def text_units(value):
    """按中文字符较宽估算换行，仅用于排版，不处理科学数值。"""
    return sum(1.8 if ord(c) > 255 else 1 for c in str(value or ''))


def export(view, folder):
    """复用原六文件生成器，再调整新Excel的可读性；不回写任何旧文件。"""
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    namespace = dict(vars(original), renderer=renderer)
    producer = FunctionType(original.export.__code__, namespace, original.export.__name__, original.export.__defaults__)
    producer.__kwdefaults__ = deepcopy(original.export.__kwdefaults__)
    files = producer(view, folder)
    book = load_workbook(files['xlsx']); matrix = book['完整评分矩阵']; detail = book['原始评分与异常']
    for sheet in book:
        sheet.freeze_panes = 'C2' if sheet is matrix else 'D2'
        sheet.print_title_rows = '1:1'
        for row in sheet:
            for cell in row:
                cell.font = Font(name='Microsoft YaHei', size=10, color=cell.font.color, bold=cell.row == 1)
                cell.alignment = Alignment(vertical='center', horizontal='right' if isinstance(cell.value, (int, float)) else 'left', wrap_text=True)
        sheet.row_dimensions[1].height = 34
    matrix.column_dimensions['A'].width = 28
    matrix.column_dimensions['B'].width = 52
    for index in range(3, matrix.max_column + 1):
        matrix.column_dimensions[get_column_letter(index)].width = max(16, min(30, text_units(matrix.cell(1,index).value) + 3))
    for index in range(2, len(view['table']['rows']) + 2):
        needed=max(text_units(matrix.cell(index,j).value)/matrix.column_dimensions[get_column_letter(j)].width for j in (1,2))
        matrix.row_dimensions[index].height = max(26, math.ceil(needed) * 16 + 8)
    # 说明只跨本表原宽度合并；科学表头和数据格始终保持独立。
    width = sum(matrix.column_dimensions[get_column_letter(j)].width for j in range(1,matrix.max_column+1))
    for index in range(len(view['table']['rows']) + 2, matrix.max_row + 1):
        units = text_units(matrix.cell(index,1).value)
        matrix.merge_cells(start_row=index,start_column=1,end_row=index,end_column=matrix.max_column)
        matrix.row_dimensions[index].height = max(32, math.ceil(units / max(1,width-5)) * 18 + 10)
    widths=[48,28,52,22,18,22,20,18,20,22,18,64]
    for index, width in enumerate(widths,1):detail.column_dimensions[get_column_letter(index)].width=width
    for row in detail.iter_rows(min_row=2):
        needed=max(text_units(cell.value)/widths[cell.column-1] for cell in row)
        detail.row_dimensions[row[0].row].height=max(30,math.ceil(needed)*17+8)
    book.save(files['xlsx']);book.close()
    original.validate_files(view,files)
    return files


def validate_files(view, files):
    """沿用第一版实际Excel/CSV读回，排版不得改变原数值或范围。"""
    return original.validate_files(view, files)
