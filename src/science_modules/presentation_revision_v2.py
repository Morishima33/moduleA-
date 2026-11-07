"""展示包二版固定导出键序；旧一版实现与已归档附件均保持，不改科学行序或数值。"""
from copy import deepcopy
from types import FunctionType
import json

from . import presentation_revision as original

VERSION='ModuleA.presentation_bundle.2'


def _json_bytes(value):
    """JSON对象键序与存储层一致，读回后再验仍对应同一原事实与完整精度。"""
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')


def _csv_bytes(rows):
    """仅稳定列名顺序；原行序、完整字段、NA及数值沿用冻结一版的导出规则。"""
    original.require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),'展示表不是记录列表')
    keys=sorted({key for row in rows for key in row})
    canonical=json.loads(_json_bytes(rows))
    return original._csv_bytes([{key:row.get(key) for key in keys} for row in canonical])


def _translation_audit(enrichment,lexicon):
    """仍按稳定ID、原英文、全部可见别名与出处严格核译；只固定审计行及表名顺序。"""
    rows=original._translation_audit(enrichment,lexicon)
    for row in rows:
        row['tables']=sorted(row['tables'])
    return sorted(rows,key=lambda row:row['ID'])


# 同一个独立全局环境中绑定所有相互调用，build调用v2验证器而非回落旧一版。
_namespace=dict(vars(original),VERSION=VERSION,_json_bytes=_json_bytes,
                _csv_bytes=_csv_bytes,_translation_audit=_translation_audit)
for _name in ('_checked_data','_figure_specs','_record','build_bundle','validate_bundle'):
    _function=getattr(original,_name)
    _bound=FunctionType(_function.__code__,_namespace,_name,_function.__defaults__,_function.__closure__)
    _bound.__kwdefaults__=deepcopy(_function.__kwdefaults__)
    _bound.__doc__=_function.__doc__
    globals()[_name]=_bound
    _namespace[_name]=_bound
