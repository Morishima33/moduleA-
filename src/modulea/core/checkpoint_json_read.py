"""HTTP旧检查点文件只读批量核验；继承原单请求首尾完整SHA。"""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from types import FunctionType

from . import read_evidence as original
from .inherited_read_evidence import InheritedReadEvidence

VERSION='ModuleA.checkpoint_json_read.1'


class CheckpointReadEvidence(InheritedReadEvidence):
    """仅在原partial_recovery已验证的文件循环开始时批量读取，不预选恢复对象。"""
    def _partial_reader(self):
        """按本仓库实际函数对象识别，不以名称或任意调用方请求扩大白名单。"""
        if not hasattr(self,'partial_reader'):
            from .system_receptor_rescue_v2 import partial_recovery
            self.partial_reader=partial_recovery
            self.partial_wrappers={}
        return self.partial_reader

    def bind(self,function):
        """原函数code/defaults/closure保持，只给其私有JSON值包装文件列表的迭代。"""
        if not self._owned():return function
        if not isinstance(function,FunctionType) or function is not self._partial_reader():
            return super().bind(function)
        if function in self.partial_wrappers:return self.partial_wrappers[function]
        bound=super().bind(function)
        # 绑定共享模块namespace时可能递归遇到自身；继续采用已登记的同一包装器。
        if function in self.partial_wrappers:return self.partial_wrappers[function]
        if bound is function:return function
        @wraps(function)
        def read(*args,**kwargs):
            if not self._owned() or len(args)!=5 or kwargs:
                return function(*args,**kwargs)
            workflow,manifest,*_=args
            if (original.current_evidence(getattr(workflow,'root',None)) is not self
                or not isinstance(manifest,dict) or manifest.get('study_id')!=self.study_id):
                return function(*args,**kwargs)
            home=workflow.location(self.study_id)
            def checkpoint_json(path):
                """只包装本次不可变JSON副本；归属/历史链检查通过前不读取files内原件。"""
                value=self.read_json(path)
                if isinstance(value,dict) and isinstance(value.get('files'),list):
                    value['files']=_CheckpointFiles(value['files'],self,home)
                return value
            namespace=dict(bound.__globals__,read_json=checkpoint_json)
            clone=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
            clone.__kwdefaults__=bound.__kwdefaults__;clone.__annotations__=bound.__annotations__
            return clone(*args,**kwargs)
        self.partial_wrappers[function]=read;self.functions[function]=read
        return read


class _CheckpointFiles(list):
    """原循环开始时复用已有最多8线程全SHA；原逐件调用仍执行并复用同请求证明。"""
    def __init__(self,values,evidence,home):
        super().__init__(values)
        self.evidence=evidence;self.home=home

    def __iter__(self):
        if self.evidence._owned():
            # 原partial_recovery在这里之前已经核归属、参数、previous及成功不可覆盖。
            # 非匹配run被原continue跳过，不会迭代此列表，也不会核其无关files。
            self.evidence.verify_all(self.home,list.__iter__(self))
        return list.__iter__(self)


@contextmanager
def json_evidence_scope(data_root,study_id):
    """仅HTTP JSON使用；跨请求无证明复用，成功退出完整SHA后才允许发响应。"""
    root=Path(data_root).resolve();prior=original.current_evidence(root)
    if prior is not None and prior.study_id==study_id:
        yield prior
        return
    evidence=CheckpointReadEvidence(root,study_id,logical_root=Path(data_root).absolute())
    token=original._current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.active=False
        original._current.reset(token)
