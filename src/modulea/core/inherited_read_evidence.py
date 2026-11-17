"""独立HTTP读取继承适配；复用原证据范围与完整SHA，不改冻结状态/科学实现。"""
from contextlib import contextmanager
import builtins
from functools import wraps
from pathlib import Path
from types import FunctionType,MethodType

from . import read_evidence as original
from .rescue_read_evidence import RescueReadEvidence

VERSION='ModuleA.inherited_json_read.1'


class InheritedReadEvidence(RescueReadEvidence):
    """继承原读取器；扩展仅限明确只读方法的委托，写入入口完全保持。"""
    def _active_methods(self):
        """只认本仓库明确五层类上的实际方法对象，不凭同名函数或任意类放行。"""
        if not hasattr(self,'method_owners'):
            from .native_execution import NativeWorkflow
            from .report_rescue_workflow import ReportRescueWorkflow
            from .system_receptor_rescue_v2 import SystemReceptorRescueV2Workflow
            from .system_receptor_rescue import SystemReceptorRescueWorkflow
            from .analysis_plans import AnalysisPlanWorkflow
            self.method_owners={owner.__dict__['_active']:owner for owner in (
                NativeWorkflow,ReportRescueWorkflow,SystemReceptorRescueV2Workflow,
                SystemReceptorRescueWorkflow,AnalysisPlanWorkflow)}
            self.method_wrappers={}
        return self.method_owners

    def _allowed_functions(self):
        """原只读白名单补全五层委托；不加入begin/finish/review或其他写方法。"""
        result=super()._allowed_functions()
        result.update(self._active_methods())
        return result

    def bind(self,function):
        """保留原code/defaults/closure，私有super只继续绑定已知_active委托。"""
        if not self._owned():return function
        if isinstance(function,MethodType):return super().bind(function)
        owners=self._active_methods()
        if not isinstance(function,FunctionType) or function not in owners:return super().bind(function)
        if function in self.method_wrappers:return self.method_wrappers[function]
        bound=super().bind(function)
        if bound is function:return function
        owner=owners[function]
        @wraps(function)
        def invoke(*args,**kwargs):
            receiver=args[0] if args else kwargs.get(function.__code__.co_varnames[0])
            root=original._object_root(receiver) if receiver is not None else None
            if not self._owned() or root is None or original.current_evidence(root) is not self:
                return function(*args,**kwargs)
            def local_super(*explicit):
                """无参super仍从原声明类与实际self开始；显式参数也沿Python原语义。"""
                value=builtins.super(*explicit) if explicit else builtins.super(owner,receiver)
                return _ReadSuper(value,self)
            namespace=dict(bound.__globals__,super=local_super)
            clone=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
            clone.__kwdefaults__=bound.__kwdefaults__;clone.__annotations__=bound.__annotations__
            return clone(*args,**kwargs)
        self.method_wrappers[function]=invoke;self.functions[function]=invoke
        return invoke


class _ReadSuper:
    """只给明确_active方法分派原只读克隆；其他属性完全沿原super对象。"""
    def __init__(self,value,evidence):self.value=value;self.evidence=evidence

    def __getattr__(self,name):
        value=getattr(self.value,name)
        if (name=='_active' and isinstance(value,MethodType)
            and value.__func__ in self.evidence._active_methods()):
            return self.evidence.bind(value)
        return value


@contextmanager
def json_evidence_scope(data_root,study_id):
    """与原范围同样在JSON发送前退出全SHA，既有同线程/根范围原样复用。"""
    root=Path(data_root).resolve();prior=original.current_evidence(root)
    if prior is not None and prior.study_id==study_id:
        yield prior
        return
    evidence=InheritedReadEvidence(root,study_id,logical_root=Path(data_root).absolute())
    token=original._current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.active=False
        original._current.reset(token)
