"""HTTP独立有界JSON缓存：复用现有全SHA读取，结束立即释放，不改冻结worker。"""
from collections import OrderedDict
from contextlib import contextmanager
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace

from contracts import require
from . import read_evidence as original
from .bounded_evidence import BoundedEvidence
from .checkpoint_json_read import CheckpointReadEvidence
from .rescue_result_read import load_rescue_result, bound_batch

VERSION='ModuleA.http_bounded_read.1'
JSON_CACHE_BYTES=64*1024*1024


def _utf8_loads(raw):
    """HTTP沿原ReadEvidence显式UTF-8解码；不自动接受UTF-16/32或带BOM的JSON。"""
    return json.loads(raw.decode('utf-8'))


# 复用有界读取原code，仅给私有namespace替换解析入口；冻结模块globals保持原样。
_read_json=BoundedEvidence.read_json
_utf8_read_json=FunctionType(_read_json.__code__,dict(_read_json.__globals__,
    json=SimpleNamespace(loads=_utf8_loads)),_read_json.__name__,_read_json.__defaults__,_read_json.__closure__)


class HttpReadEvidence(CheckpointReadEvidence):
    """保留原HTTP白名单、继承与CP批读，只替换已经验证的内容缓存策略。"""
    def __init__(self,*args,cache_bytes=JSON_CACHE_BYTES,**kwargs):
        require(type(cache_bytes) is int and cache_bytes>=0,'HTTP读取缓存预算无效')
        super().__init__(*args,**kwargs)
        self.cache_limit=cache_bytes;self.cache=OrderedDict()
        self.cache_size=self.cache_peak=0
        self.stats.update(json_parses=0,json_cache_hits=0)

    def _allowed_functions(self):
        """共享只读加载器也加入本请求代理，保持原件首尾SHA，不扩冻结worker白名单。"""
        functions=super()._allowed_functions()
        functions.update((load_rescue_result, bound_batch))
        return functions

    # 原有界实现逐件核完整SHA，解析字节另与原登记比对；不长期保留JSON原文。
    _capture=BoundedEvidence._capture
    read_json=_utf8_read_json

    def close(self):
        """成功、业务错误和退出核验失败都清缓存；保留计数供外部自检。"""
        BoundedEvidence.close(self)
        for name in ('method_wrappers','partial_wrappers'):
            getattr(self,name,{}).clear()


@contextmanager
def json_evidence_scope(data_root,study_id,*,cache_bytes=JSON_CACHE_BYTES):
    """HTTP响应前原finish全SHA保持；独立请求不共享证明或内容。"""
    root=Path(data_root).resolve();prior=original.current_evidence(root)
    if prior is not None and prior.study_id==study_id:
        yield prior
        return
    evidence=HttpReadEvidence(root,study_id,logical_root=Path(data_root).absolute(),cache_bytes=cache_bytes)
    token=original._current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.close()
        original._current.reset(token)
