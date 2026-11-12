"""受体补救展示2：按本轮集合区分沿用评分与新增评分，冻结展示1保持原字节。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType

from contracts import require, safe_id
from . import matrix_palette
from . import system_rescue_display as original

SCIENCE_VERSION = 'A06.system_rescue.2'
VERSION = 'A06.system_rescue.display.2'


def renderer():
    """私有命名空间复用冻结几何与导出器，不替换原模块任何函数或常量。"""
    namespace = dict(vars(original), SCIENCE_VERSION=SCIENCE_VERSION, VERSION=VERSION)
    for name in ('build_view', '_drawing', 'heatmap_svg', '_png', 'export'):
        source = getattr(original, name)
        clone = FunctionType(source.__code__, namespace, source.__name__, source.__defaults__, source.__closure__)
        clone.__kwdefaults__ = deepcopy(source.__kwdefaults__)
        namespace[name] = clone
    namespace['base_build_view'] = namespace['build_view']
    namespace['build_view'] = build_view
    return namespace


def _round_keys(packet):
    """只检查展示集合完整性；代次依据由科学校验器核实，不按source_kind猜测。"""
    lookup = {(row['compound_id'], row['target_id']): row for row in packet['pairs']}
    sets = []
    for field in ('reused_pair_keys', 'new_pair_keys'):
        rows = packet.get(field)
        require(isinstance(rows, list) and all(isinstance(row, list) and len(row) == 2
                and all(isinstance(value, str) and value for value in row) for row in rows), '补救展示代次集合格式错误')
        keys = {tuple(row) for row in rows}
        require(len(keys) == len(rows) and keys <= set(lookup), '补救展示代次集合重复或包含未知组合')
        sets.append(keys)
    reused, new = sets
    require(not reused & new, '补救展示的本轮与沿用集合重叠')
    require(all(lookup[key]['state'] == 'completed' for key in reused), '沿用集合只能包含已核验成功评分')
    require(all(lookup[key]['state'] in ('completed', 'failed') for key in new), '本轮集合不能把未评分NA记作实际执行')
    require({key for key, row in lookup.items() if row['state'] == 'completed'} <= reused | new,
            '有效评分缺少唯一的本轮或沿用代次')
    return reused, new


def build_view(packet, *, selected_compounds=None, selected_targets=None):
    """继承完整顺序、原值和配色，仅据本轮集合附加展示来源，不回写原行。"""
    require(packet.get('schema_version') == SCIENCE_VERSION, '不支持的补救展示2科学协议')
    reused, new = _round_keys(packet)
    view = renderer()['base_build_view'](packet, selected_compounds=selected_compounds, selected_targets=selected_targets)
    for matrix in (view['table'], view['heatmap']):
        for line in matrix['cells']:
            for cell in line:
                key = (cell['compound_id'], cell['target_id'])
                if key in reused:
                    cell['source_zh'] = '沿用已核验评分'
                elif key in new:
                    cell['source_zh'] = '本轮新增评分' if cell['state'] == 'completed' else '本轮实际计算（未获评分）'
                else:
                    cell['source_zh'] = '未评分（NA）' if cell['state'] == 'NA' else '既有未通过记录'
    return view


def heatmap_svg(view, *, full=True):
    """本版SVG使用私有几何，格子提示与CSV均采用相同本轮来源文字。"""
    require(view.get('schema_version') == VERSION and view.get('science_version') == SCIENCE_VERSION,
            '补救展示2图件协议错误')
    return renderer()['heatmap_svg'](view, full=full)


def export(root, packet, folder, *, font_path=None):
    """每次导出使用本运行display下独立尝试目录，失败残件不覆盖或伪装为成功。"""
    require(packet.get('schema_version') == SCIENCE_VERSION, '补救展示2导出科学协议错误')
    root, folder = Path(root).resolve(), Path(folder).resolve()
    run_id = packet['run_id']
    require(isinstance(run_id, str) and run_id and '/' not in run_id and '\\' not in run_id
            and run_id not in ('.', '..'), '补救展示2运行身份错误')
    expected = root / 'runs/A06' / run_id / 'rescue/display'
    safe_id(folder.name, 'display')
    require(folder.parent == expected.resolve() and folder.is_relative_to(root), '补救展示2导出必须使用本运行独立尝试目录')
    return renderer()['export'](root, packet, folder, font_path=font_path)


def implementation_files():
    """声明本版及实际复用的冻结显示依赖，供科学运行单独归档核对。"""
    return [Path(__file__), Path(original.__file__), Path(matrix_palette.__file__)]
