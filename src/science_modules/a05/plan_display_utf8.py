"""A05显式二版展示：消费Unicode统计协议，复用原分类、范围和绘图规则。"""
from types import FunctionType
from contracts import require
from . import plan_display as original

VERSION='A05.plan_display.2'
SOURCE_VERSION='A05.plan_display_source.2'
GROUPS=original.GROUPS
screening=original.screening
LEXICON=original.LEXICON
_namespace=dict(vars(original),VERSION=VERSION,SOURCE_VERSION=SOURCE_VERSION)


def significant(base):
    """仅识别明确第二版统计；第一版展示函数、状态和完整统计不修改。"""
    require(base.get('module_id')=='A05' and base.get('summary',{}).get('protocol_version')=='A05.plan_enrichment.2',
        '第二版展示仅消费本批Unicode统计协议')
    return {group:base['tables'][group.lower()+'_significant'] for group in GROUPS}


_namespace['significant']=significant
for _name in ('make_source','check_source','decision_values','build'):
    _function=getattr(original,_name)
    globals()[_name]=FunctionType(_function.__code__,_namespace,_function.__name__,_function.__defaults__,_function.__closure__)
    globals()[_name].__kwdefaults__=dict(_function.__kwdefaults__ or {})
    _namespace[_name]=globals()[_name]
