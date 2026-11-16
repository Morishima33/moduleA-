"""明确二版worker读取：纯核查范围首次/退出全SHA，缓存有界，科学与写入规则保持。"""
from collections import OrderedDict, deque
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from hashlib import sha256
from inspect import signature
import json
import marshal
from pathlib import Path
from weakref import WeakKeyDictionary

from contracts import fingerprint, require
import storage
from . import bounded_evidence as bounded
from . import read_evidence
from . import worker_io as original
from . import system_receptor_rescue as first
from . import system_receptor_rescue_v2 as second

VERSION = 'ModuleA.science_worker_io.2'
_MISSING = object()
_SOURCES = (first.source_binding, first._source_binding, second.source_binding)
_READS = (*_SOURCES, first.validate_request, second.validate_request,
          first.SystemReceptorRescueWorkflow._active, second.SystemReceptorRescueV2Workflow._active)
IMPLEMENTATIONS = (
    'src/modulea/core/worker_io.py', 'src/modulea/core/bounded_evidence.py',
    'src/modulea/core/rescue_recovery.py', 'src/modulea/tasks/rescue_worker_io.py',
    'tools/run_rescue_worker_io.py', 'src/modulea/core/scoped_worker_io.py',
    'src/modulea/tasks/scoped_rescue_worker.py', 'tools/run_scoped_rescue_worker.py',
    'src/modulea/tasks/manager.py', 'src/modulea/tasks/worker.py',
    'src/modulea/core/read_evidence.py', 'src/modulea/core/rescue_read_evidence.py',
    'src/modulea/core/read_archive.py', 'src/modulea/tasks/process_identity.py',
    'src/modulea/tasks/process_tree.py', 'src/modulea/tasks/compute_budget.py',
    'src/modulea/tasks/resource_runner.py', 'src/modulea/config.py', 'src/modulea/__main__.py',
    'src/modulea/core/checkpoint_read_phase.py',
)


class SourceEvidence(bounded.BoundedEvidence):
    """仅范围内缓存原绑定JSON值；不保存大型准备payload或跨请求证明。"""
    def __init__(self, *args, binding_bytes=2*1024*1024, document_bytes=16*1024*1024, **kwargs):
        kwargs.setdefault('cache_bytes', 64*1024*1024)
        super().__init__(*args, **kwargs)
        require(type(binding_bytes) is int and binding_bytes >= 0, '绑定缓存预算无效')
        require(type(document_bytes) is int and document_bytes >= 0, '单文档缓存预算无效')
        self.document_limit = document_bytes
        self.binding_limit = binding_bytes
        self.binding_cache = OrderedDict()
        self.binding_size = self.binding_peak = 0
        self.workflow_tokens = WeakKeyDictionary()
        self.next_workflow_token = 0
        self.stats.update(source_binding_hits=0, source_binding_stores=0, large_json_parses=0)

    def workflow_key(self, workflow):
        """弱身份令牌不保留临时Workflow，也不因Python复用id而混用实例。"""
        require(self._owned(), '工作流身份缓存范围已退出')
        if workflow not in self.workflow_tokens:
            self.next_workflow_token += 1
            self.workflow_tokens[workflow] = self.next_workflow_token
        return self.workflow_tokens[workflow]

    def read_json(self, path):
        """总JSON缓存有界，大型准备尝试不挤掉实际重复读取的上游结果。"""
        if not self._owned():
            return super().read_json(path)
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root):
            return super().read_json(path)
        key = self.by_path.get(resolved)
        if key is None:
            record = bounded.file_record(self.root, resolved, 'request_json')
            self._capture(self.root, record)
            key = self.by_path[resolved]
        if key[2] <= self.document_limit:
            return super().read_json(resolved)
        try:
            raw = resolved.read_bytes()
            require(len(raw) == key[2] and sha256(raw).hexdigest() == key[3], '大型JSON解析期间原件已改变')
            result = json.loads(raw)
        except (OSError, ValueError, UnicodeError) as error:
            from contracts import ContractError
            raise ContractError('数据文件缺失或损坏：'+resolved.name) from error
        self.stats['json_parses'] += 1
        self.stats['large_json_parses'] += 1
        return result

    def get_binding(self, key):
        """每次返回独立容器，调用方改动不能污染后续科学比较。"""
        require(self._owned(), '绑定缓存范围已退出或线程不同')
        if key not in self.binding_cache:
            return _MISSING
        self.binding_cache.move_to_end(key)
        self.stats['source_binding_hits'] += 1
        return marshal.loads(self.binding_cache[key])

    def store_binding(self, key, value):
        """按总字节预算淘汰，只保留小型实际绑定；大对象不进缓存。"""
        require(self._owned(), '绑定缓存范围已退出或线程不同')
        packed = marshal.dumps(value)
        if len(packed) > self.binding_limit:
            return
        if key in self.binding_cache:
            self.binding_size -= len(self.binding_cache.pop(key))
        while self.binding_cache and self.binding_size+len(packed) > self.binding_limit:
            _, old = self.binding_cache.popitem(last=False)
            self.binding_size -= len(old)
        self.binding_cache[key] = packed
        self.binding_size += len(packed)
        self.binding_peak = max(self.binding_peak, self.binding_size)
        self.stats['source_binding_stores'] += 1

    def close(self):
        """成功或异常退出均确定性释放，不等循环GC。"""
        self.binding_cache.clear()
        self.binding_size = 0
        self.workflow_tokens.clear()
        super().close()

    def bind(self, function):
        """嵌套旧读取适配也接入同一有界memo，不恢复原无上限事实缓存。"""
        if function in self.functions:
            return self.functions[function]
        bound = super().bind(function)
        if function not in _SOURCES or bound is function:
            return bound
        spec = signature(function); names = tuple(spec.parameters)
        @wraps(function)
        def fact(*args, **kwargs):
            if not self._owned():
                return function(*args, **kwargs)
            values = spec.bind(*args, **kwargs).arguments
            workflow = values[names[0]]
            if read_evidence.current_evidence(getattr(workflow, 'root', None)) is not self:
                return function(*args, **kwargs)
            key = (function, self.workflow_key(workflow), fingerprint({name: value for name, value in values.items() if name != names[0]}))
            result = self.get_binding(key)
            if result is _MISSING:
                result = bound(*args, **kwargs)
                self.store_binding(key, result)
            return result
        self.functions[function] = fact
        return fact


@contextmanager
def source_scope(data_root, study_id, *, binding_bytes=2*1024*1024,
                 cache_bytes=64*1024*1024, document_bytes=16*1024*1024):
    """只包围明确纯读取；退出前原manifest、全部原件及逻辑路径完整重核。"""
    root = Path(data_root).resolve()
    prior = read_evidence.current_evidence(root)
    if isinstance(prior, SourceEvidence) and prior.study_id == study_id:
        yield prior
        return
    evidence = SourceEvidence(root, study_id, logical_root=Path(data_root).absolute(), binding_bytes=binding_bytes,
                              cache_bytes=cache_bytes, document_bytes=document_bytes)
    token = read_evidence._current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.close()
        read_evidence._current.reset(token)


def scoped_verified_file(root, record):
    """当前二版范围内复用首次证明，外部调用仍逐次流式完整SHA。"""
    evidence = read_evidence.current_evidence()
    if isinstance(evidence, SourceEvidence) and evidence._home(root) is not None:
        return evidence.verified_file(root, record)
    return bounded.verified_file(root, record)


def scoped_read_json(path):
    """只读取本范围同数据根，JSON仍按原SHA核验，预算由明确二版范围固定。"""
    evidence = read_evidence.current_evidence()
    if isinstance(evidence, SourceEvidence) and Path(path).resolve().is_relative_to(evidence.root):
        return evidence.read_json(path)
    return storage.read_json(path)


class ScopedWorkerIO(original.WorkerIO):
    """只对白名单纯核查合并重复I/O；不改变Workflow继承、科学函数或写锁。"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.scope_wrappers = {}
        self.last_scopes = deque(maxlen=8)
        self.stats.update(source_scopes=0, source_scope_failures=0, source_binding_hits=0,
                          scope_first_sha_checks=0, scope_exit_sha_checks=0, checkpoint_read_phases=0)

    def project_code(self, function):
        """本适配器自身不再次代理，避免把私有范围管理递归绑定。"""
        return super().project_code(function) and Path(function.__code__.co_filename).resolve() not in (
            Path(__file__).resolve(), Path(__file__).with_name('checkpoint_read_phase.py').resolve())

    def value(self, value):
        """仅原函数对象路由；真正模块和全局函数不替换。"""
        if value is storage.verified_file or value is bounded.verified_file:
            return scoped_verified_file
        if value is storage.read_json:
            return scoped_read_json
        return super().value(value)

    def bind(self, function):
        """纯读取外层建立范围，source_binding只在同范围与完整参数下复用。"""
        if function is second.append_checkpoint:
            if function not in self.scope_wrappers:
                from .checkpoint_read_phase import bind_checkpoint
                self.scope_wrappers[function] = bind_checkpoint(self, function, super().bind)
            return self.scope_wrappers[function]
        if function not in _READS:
            return super().bind(function)
        if function in self.scope_wrappers:
            return self.scope_wrappers[function]
        spec = signature(function)
        names = tuple(spec.parameters)
        @wraps(function)
        def call(*args, **kwargs):
            values = spec.bind(*args, **kwargs).arguments
            workflow, document = values[names[0]], values[names[1]]
            sid = document['study_id'] if isinstance(document, dict) else document
            prior = read_evidence.current_evidence(workflow.root)
            owns = not (isinstance(prior, SourceEvidence) and prior.study_id == sid)
            evidence = None
            passed = False
            try:
                with source_scope(workflow.root, sid) as evidence:
                    key = None
                    if function in _SOURCES:
                        key = (function, evidence.workflow_key(workflow), fingerprint({name: value for name, value in values.items() if name != names[0]}))
                        saved = evidence.get_binding(key)
                        if saved is not _MISSING:
                            result = saved
                        else:
                            result = super(ScopedWorkerIO, self).bind(function)(*args, **kwargs)
                            evidence.store_binding(key, result)
                    else:
                        result = super(ScopedWorkerIO, self).bind(function)(*args, **kwargs)
                passed = True
                return result
            finally:
                if owns and evidence is not None:
                    self.stats['source_scopes'] += 1
                    self.stats['source_scope_failures'] += not passed
                    self.stats['source_binding_hits'] += evidence.stats['source_binding_hits']
                    self.stats['scope_first_sha_checks'] += evidence.stats['first_sha_checks']
                    self.stats['scope_exit_sha_checks'] += evidence.stats['exit_sha_checks']
                    self.last_scopes.append(dict(evidence.stats, passed=passed, binding_peak=evidence.binding_peak,
                                                 json_cache_peak=evidence.cache_peak))
        self.scope_wrappers[function] = call
        return call

    def wrap(self, workflow):
        """二版公开登记方法独立分派，不能误用旧版快照冒充新行为。"""
        if getattr(workflow, '_worker_io', None) is self:
            return workflow
        wrapper = type('ScopedWorkerIOWorkflow', (ScopedWorkerWorkflow, type(workflow)), {})
        value = object.__new__(wrapper); value.__dict__.update(workflow.__dict__)
        value._worker_io = self
        value.validators = {key: self.bind(fn) for key, fn in workflow.validators.items()}
        return value

    def read_checkpoint(self, workflow, sid, run_id, key, version, field):
        """本二版范围内将原严格reader的旧CP和目标历史附件一并捕获，范围外照旧。"""
        evidence = read_evidence.current_evidence(workflow.root)
        if isinstance(evidence, SourceEvidence) and evidence.study_id == sid:
            from .checkpoint_read_phase import read_checkpoint_in_scope
            return read_checkpoint_in_scope(self, original.WorkerIO.read_checkpoint,
                                           workflow, sid, run_id, key, version, field)
        return super().read_checkpoint(workflow, sid, run_id, key, version, field)

    def activate_registration(self, workflow, sid, reference):
        """只接受本明确二版登记，仍逐对象核原实现和全部归档字节。"""
        value = bounded.read_verified_json(workflow.location(sid), reference)
        self._validate_registration(workflow, sid, reference, value)
        previous = self.adapter_binding
        try:
            self.adapter_binding = sid, deepcopy(reference), deepcopy(value['implementation_sha256'])
            self.guard(workflow, sid)
        except Exception:
            self.adapter_binding = previous
            raise

    def _validate_registration(self, workflow, sid, reference, value):
        """登记须覆盖全部实现，并精确指向当前科学请求；不能以空快照放行。"""
        require(isinstance(value, dict) and value.get('schema_version') == VERSION,
                'worker I/O二版适配协议不同')
        manifest = workflow.load(sid)
        rid = value.get('run_id')
        require(value.get('study_id') == sid and manifest['current'].get('A06') == rid,
                'worker I/O二版研究或当前科学运行不同')
        run = workflow.run(manifest, rid)
        require(run['config'].get('version') == second.VERSION
                and value.get('request') == run['inputs']['rescue_request']
                and value.get('scientific_config_hash') == run['config_hash']
                and value.get('human_review_written') is False,
                'worker I/O二版请求、配置或人工标记不同')
        implementations = value.get('implementation_sha256')
        require(isinstance(implementations, dict) and set(implementations) == set(IMPLEMENTATIONS),
                'worker I/O二版实现清单不完整')
        files = value.get('files')
        folder = Path(reference['path']).parent
        require(folder.parent.as_posix() == f'runs/A06/{rid}/execution_adapters'
                and Path(reference['path']).name == 'adapter.json'
                and isinstance(files, list) and len(files) == len(IMPLEMENTATIONS),
                'worker I/O二版实现快照数量或目录不同')
        expected = {(folder/'code'/name).as_posix(): digest for name, digest in implementations.items()}
        require(all(isinstance(item, dict) and item.get('role') == 'worker_io_implementation'
                    and item.get('path') in expected and item.get('sha256') == expected[item['path']]
                    for item in files) and len({item['path'] for item in files}) == len(expected),
                'worker I/O二版实现快照缺失、重复或指纹不同')

    def guard(self, workflow, sid):
        """二版没有明确登记时禁止科学写入，不能用只读优化直接开始计算。"""
        require(self.adapter_binding is not None, 'I/O二版尚未明确登记，禁止执行或发表科学结果')
        study, reference, implementations = self.adapter_binding
        require(study == sid, 'worker I/O二版适配跨研究')
        value = bounded.read_verified_json(workflow.location(sid), reference)
        self._validate_registration(workflow, sid, reference, value)
        require(value['implementation_sha256'] == implementations, 'worker I/O二版登记实现已改变')
        super().guard(workflow, sid)

    def close(self):
        """释放额外私有绑定引用，不改原模块。"""
        self.scope_wrappers.clear()
        super().close()


class ScopedWorkerWorkflow(original.WorkerWorkflow):
    """本二版只能经显式登记进入生产，不升级原一版快照或科学运行。"""
    def execute_analysis_plan_receptor_rescue_v2(self, sid, body, *, tools, repair_packages, progress=None):
        """只接续已登记的同一运行和原请求，不能借二版I/O另开科学运行。"""
        adapter = self._worker_io
        adapter.guard(self, sid)
        _, reference, _ = adapter.adapter_binding
        record = bounded.read_verified_json(self.location(sid), reference)
        manifest = self.load(sid)
        require(manifest['current'].get('A06') == record['run_id'], 'I/O二版所绑定科学运行已改变')
        request = bounded.read_verified_json(self.location(sid), record['request'])
        require(body == request['request'], 'I/O二版只允许接续原明确请求，不可另开科学运行')
        return adapter.bind(second.execute)(self, sid, body, tools=tools,
                                            repair_packages=repair_packages, progress=progress)

    def register_worker_io(self, sid, run_id, body):
        """原来源资格通过后新增完整二版实现快照，保留旧适配、CP和人工意见。"""
        with storage.write_lock(self.root):
            manifest, _, run = self._worker_io.bind(second.validate_request)(self, sid, body)
            require(run and run['run_id'] == run_id and not manifest['runs'][run_id].get('result_file'),
                    'I/O二版仅用于明确指定的当前未完成二版科学运行')
            home = self.location(sid); code = Path(__file__).resolve().parents[3]
            require(all((code/name).is_file() for name in IMPLEMENTATIONS), 'I/O二版实现未完整接入，禁止登记')
            implementations = {name: sha256((code/name).read_bytes()).hexdigest() for name in IMPLEMENTATIONS}
            expected = {'schema_version': VERSION, 'study_id': sid, 'run_id': run_id,
                        'request': run['inputs']['rescue_request'], 'implementation_sha256': implementations,
                        'scientific_config_hash': run['config_hash'], 'human_review_written': False}
            for ref in manifest.get('worker_io_adaptations', []):
                old = storage.read_json(bounded.verified_file(home, ref))
                if old['run_id'] == run_id and old['schema_version'] == VERSION and old['implementation_sha256'] == implementations:
                    require(all(old.get(key) == value for key, value in expected.items()), 'I/O二版登记内容不同')
                    for item in old['files']: bounded.verified_file(home, item)
                    return ref
            folder = home/'runs/A06'/run_id/'execution_adapters'/storage.new_id('adapter')
            files = []
            for name, digest in implementations.items():
                raw = (code/name).read_bytes(); require(sha256(raw).hexdigest() == digest, '二版实现读取期间改变')
                target = folder/'code'/name; target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream: stream.write(raw)
                files.append(bounded.file_record(home, target, 'worker_io_implementation'))
            path = folder/'adapter.json'
            storage.write_json(path, dict(expected, files=files, created_at=storage.now()))
            ref = bounded.file_record(home, path, 'worker_io_adaptation')
            manifest.setdefault('worker_io_adaptations', []).append(ref)
            self.save(manifest)
            return ref
