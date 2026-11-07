"""独立第三版准备检查点：复用原存储算法，旧会话及旧源码保持。"""
from types import FunctionType
from . import system_preparation_checkpoints as original

VERSION = 'A06.system_preparation_checkpoints.2'
PREPARATION = 'A06.system_preparation.3'
SESSIONS = 'analysis_plan_system_preparation_sessions_v2'
OBJECTS = 'analysis_plan_system_preparation_objects_v2'
PACKETS = 'analysis_plan_system_preparation_packets_v2'

# 每个函数只绑定本模块的版本与索引；不改共享模块全局变量。
_scope = dict(vars(original), VERSION=VERSION, PREPARATION=PREPARATION,
              SESSIONS=SESSIONS, OBJECTS=OBJECTS, PACKETS=PACKETS)
for _name, _value in vars(original).items():
    if isinstance(_value, FunctionType) and _value.__globals__ is vars(original):
        _scope[_name] = FunctionType(_value.__code__, _scope, _value.__name__,
                                    _value.__defaults__, _value.__closure__)
for _name, _value in _scope.items():
    if isinstance(_value, FunctionType) and _value.__globals__ is _scope:
        globals()[_name] = _value
