"""报告二版复用原数量、筛选及评分事实；只更新可读名称与核译规则。"""
from types import FunctionType
from contracts import require
from . import plan_facts as original

VERSION = 'A07.plan_facts.2'
SCOPE_VERSION = 'A05.plan_automatic_scope.2'
BOUNDARY = original.BOUNDARY
GROUPS = original.GROUPS


def bilingual(row):
    """中文缺失只记录缺口，由交付检查阻断，图表不写未完成占位文字。"""
    english = original.english(row)
    chinese = row.get('description_zh') or ''
    return {'ID': row['ID'], 'english': english, 'chinese': chinese,
            'translation_status': 'checked' if chinese else 'pending',
            'label': english + (' / '+chinese if chinese else '')}


def automatic_enrichment(base, plan, source):
    """从原显著表派生相同范围，保留统计和ID；核译来源由本次归档快照决定。"""
    from science_modules.a05 import plan_display, plan_display_utf8
    display = plan_display_utf8 if base['summary'].get('protocol_version') == 'A05.plan_enrichment.2' else plan_display
    scope = dict(vars(original), bilingual=bilingual, check_source=display.check_source, SCOPE_VERSION=SCOPE_VERSION)
    calculate = FunctionType(original.automatic_enrichment.__code__, scope)
    value = calculate(base, plan, source)
    value['note_zh'] = '仅派生同批展示范围；原统计和BH保持，中文以归档核译快照为准，不伪造人工审批。'
    return value


# 数量和状态规则复用旧函数，仅新事实版本名独立；不改变原模块全局常量。
_scope = dict(vars(original), VERSION=VERSION)
docking = FunctionType(original.docking.__code__, _scope, 'docking', original.docking.__defaults__)
docking.__kwdefaults__ = dict(original.docking.__kwdefaults__ or {})
completion = FunctionType(original.completion.__code__, _scope, 'completion')
