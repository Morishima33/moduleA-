"""第三版来源结果导出，沿用第二版文件排版。"""
from pathlib import Path
from types import FunctionType
from . import system_exports as original, system_exports_v2 as layout
from .system_exports_v2 import export, validate_files


def build_view(run, result, packet):
    """固定原范围、顺序、分数和NA；这里只声明独立导出排版版本。"""
    namespace = dict(vars(original),
                     SCORING=(*original.SCORING, 'A06.system_scoring.3'),
                     PREPARATION=(*original.PREPARATION, 'A06.system_qualification.3'))
    build = FunctionType(original.build_view.__code__, namespace, original.build_view.__name__)
    view = build(run, result, packet)
    view.update(schema_version=layout.VERSION, display_version=layout.VERSION)
    return layout.renderer()['validate_view'](view)


def implementation_files():
    """新排版和所有复用生成器共同归档，便于同请求精确恢复。"""
    return [Path(__file__), *layout.implementation_files()]


