"""二版HTTP读取适配；复用既有证据范围，冻结运行绑定文件保持原字节。"""
from contextlib import contextmanager
from functools import wraps
import importlib
import marshal
from pathlib import Path
from types import FunctionType, ModuleType

from contracts import fingerprint
from . import read_evidence as original


# 仅扩充明确的只读入口，不把execute、append、register或科学任务加入读取代理。
READ_ONLY = {
    'modulea.api.rescue_evidence': {
        'read', 'focus', 'load_bundle', 'checked_bytes', '_execution', '_artifacts',
    },
    'modulea.api.receptor_rescue_v2': {'info'},
    'modulea.core.system_receptor_rescue_v2': {
        'info', 'source_binding', 'partial_recovery', '_read_request',
        'SystemReceptorRescueV2Workflow._active',
    },
    'modulea.core.receptor_source_packages': {
        '_same', '_bytes', '_json', '_refs', '_identity', '_validate',
        'read_record', 'for_baseline', 'url_mapping',
    },
}
FACTS = {
    ('modulea.core.system_receptor_rescue_v2', 'source_binding'),
    ('modulea.core.system_receptor_rescue', '_source_binding'),
}


class RescueReadEvidence(original.ReadEvidence):
    """仅当前JSON请求扩充白名单；原SHA、路径、登记及线程保护全部沿用。"""

    def _allowed_functions(self):
        """按实际模块属性取函数对象，避免仅凭函数名称代理未知来源。"""
        functions = super()._allowed_functions()
        for module_name, names in READ_ONLY.items():
            module = importlib.import_module(module_name)
            for name in names:
                value = module
                for part in name.split('.'):
                    value = getattr(value, part)
                if isinstance(value, FunctionType):
                    functions.add(value)
        return functions

    def _value(self, value):
        """局部导入和模块引用只换请求私有外观，真实模块globals始终保持。"""
        if isinstance(value, ModuleType) and value.__name__ in READ_ONLY:
            if value not in self.modules:
                self.modules[value] = original._BoundModule(value, self)
            return self.modules[value]
        return super()._value(value)

    def bind(self, function):
        """相同工作流、完整manifest和绑定参数只重建一次，返回隔离容器。"""
        if function in self.functions:
            return self.functions[function]
        bound = super().bind(function)
        identity = (getattr(function, '__module__', None), getattr(function, '__name__', None))
        if bound is function or identity not in FACTS:
            return bound

        @wraps(function)
        def fact(*args, **kwargs):
            """跨根、跨线程、退出作用域或非常规调用均回到原严格读取。"""
            if not self._owned() or len(args) != 4 or kwargs:
                return function(*args, **kwargs)
            workflow, manifest, *binding = args
            if original.current_evidence(getattr(workflow, 'root', None)) is not self:
                return function(*args, **kwargs)
            key = function, id(workflow), fingerprint(manifest), fingerprint(binding)
            if key not in self.preparation_records:
                self.preparation_records[key] = marshal.dumps(bound(*args))
            return marshal.loads(self.preparation_records[key])

        self.functions[function] = fact
        return fact


@contextmanager
def json_evidence_scope(data_root, study_id):
    """JSON发送前退出并完整复验全部原件；不用于下载、写入或任务执行。"""
    root = Path(data_root).resolve()
    prior = original.current_evidence(root)
    if prior is not None and prior.study_id == study_id:
        yield prior
        return
    evidence = RescueReadEvidence(root, study_id, logical_root=Path(data_root).absolute())
    token = original._current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.active = False
        original._current.reset(token)
